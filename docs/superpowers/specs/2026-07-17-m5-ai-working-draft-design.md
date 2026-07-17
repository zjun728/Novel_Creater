# M5 AI WorkingDraft Design

## Goal

M5 opens the first real AI writing path for Writer Core V1: generate chapter prose into the current `WorkingDraft` through the backend provider boundary, while keeping author control intact.

## Scope

M5 adds one operation: generate or regenerate the current chapter working draft. It does not finalize a chapter, does not write Canon, does not create `DraftCandidate` automatically, and does not call any browser-side provider adapter.

The browser sends only chapter-session identifiers, the current `WorkingDraft` revision, and optional author instruction text. Provider keys, base URLs, model selection, and outbound calls stay in the backend.

## Product flow

1. Author enters `ChapterWriterView`.
2. If a chapter session exists, the author can click `AI 生成工作稿`.
3. The frontend sends:
   - `expectedWorkingDraftRevision`
   - optional `authorInstruction`
4. Backend locks the project/session/draft, checks CAS revision, builds the chapter-writing context, resolves the `writing` task binding, calls an OpenAI-compatible provider through a backend gateway, and saves returned prose into `WorkingDraft` revision `+1`.
5. The updated workspace returns to the frontend and the editor displays the new draft.
6. Candidate count remains unchanged until the author explicitly clicks `保存为候选`.

## Backend design

Add a generation service beside `ChapterSessionService`, not inside routers or frontend code:

- `backend/services/chapter_draft_generation.py`
  - owns command validation, locking, prompt/context assembly, provider-bound generation, CAS write, and safe errors.
- `backend/gateways/chapter_draft_provider.py`
  - OpenAI-compatible outbound gateway with injectable fake transport for tests.
- `backend/prompts/chapter_draft.py`
  - deterministic prompt assembly from planning snapshot, current working draft, contract/planning facts, and optional author instruction.

Generation uses the existing `project_model_binding_*` formal binding tables and the `writing` task key. It must not use legacy `task_model_bindings`, browser `frontend/src/api/ai/*`, or old `WriterView`.

## API design

Add:

`POST /api/projects/{pid}/chapter-sessions/{session_id}/generate-working-draft`

Request body:

```json
{
  "expectedWorkingDraftRevision": 1,
  "authorInstruction": "这一章更有市井感，对话多一点"
}
```

Response: same public workspace shape as M4 chapter-session endpoints.

Errors:

- `422 ChapterSessionRequestInvalid`: invalid body.
- `404 ChapterSessionNotFound`: project/session missing.
- `409 ChapterSessionConflict`: session status invalid or working draft revision drift.
- `422 ChapterSessionPreconditionFailed`: missing active planning, binding, provider, or empty provider result.
- `502 ChapterDraftGenerationFailed`: provider/transport/response failure. Response must not echo raw provider body, API key, base URL, or DSN.

## Frontend design

Extend `chapterSessions` API client and `chapterSessionStore` with one command:

`generateWorkingDraft(projectId, sessionId, { expectedWorkingDraftRevision, authorInstruction })`

`ChapterWriterView` adds:

- author instruction input
- `AI 生成工作稿` button
- loading/error display

Generation updates `WorkingDraft` only. It must not call `saveCandidate`, must not infer readiness, and must not import or use `frontend/src/api/ai/*`.

## Testing design

RED/GREEN tests must cover:

- backend service writes provider output into `WorkingDraft` revision `+1`;
- backend service does not create candidates;
- stale working draft revision returns conflict before provider call;
- provider failure/empty output does not mutate draft;
- API route rejects unknown fields and maps safe public errors;
- frontend API client strips `apiKey/baseURL/debug` fields;
- store generation uses current working draft revision and does not create candidate;
- route/static tests prove M5 UI does not import old `WriterView`, browser provider adapter, `chatCompletion`, or finalization.

Live provider calls are not part of unit readiness. Live acceptance is manual browser testing with the configured `writing` binding (`联通云 / deepseek-v4-flash`).
