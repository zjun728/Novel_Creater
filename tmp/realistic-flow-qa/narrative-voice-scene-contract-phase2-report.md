# NarrativeVoiceContract + SceneExecutionContract Phase 2.0 Report

Status: implementation, deterministic verification, offline model validation, and fresh read-only review complete.

Evidence closure update:
- Product audit found the previous report summary did not match the current `narrative-voice-phase2-model-validation.json`.
- Added deterministic evidence contract `tmp/test_narrative_voice_phase2_evidence_contract.mjs` to prevent stale report/JSON mismatch and evaluator pass/issue semantic ambiguity.
- Current model QA summary below is copied from the current JSON fields.
- Follow-up review found the first evidence contract used unqualified `qualityScore=...` and `passedEvaluator=...` substring checks. The matcher now requires label-qualified `oldPrompt.*` and `newPrompt.*` tokens and includes in-memory stale-report assertions for newPrompt score/pass changes.

Scope guard:
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run the formal chapter generation/finalization chain.
- Did not write real DB data or execute migrations/cleanup.
- Did not restore LongformBrowser, run #98 canary/rerun, or run #99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not implement Phase 3 provider adapters or connect new model providers to the production chain.

## Changed Files

Phase 2.0 files changed or added:
- `frontend/src/utils/narrativeVoiceContract.js`
- `frontend/src/utils/sceneExecutionContract.js`
- `frontend/src/utils/literaryQualityEvaluator.js`
- `frontend/src/utils/contextPackV2.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/prompts/chapterDraftPrompt.js`
- `tmp/test_narrative_voice_scene_contract_phase2.mjs`
- `tmp/test_narrative_voice_phase2_evidence_contract.mjs`
- `tmp/run_narrative_voice_phase2_model_validation.mjs`
- `tmp/realistic-flow-qa/narrative-voice-phase2-model-validation.json`
- `tmp/realistic-flow-qa/narrative-voice-scene-contract-phase2-report.md`

## Prompt/Style Dry Audit

| Path / rule source | Risk found | Phase 2.0 handling |
| --- | --- | --- |
| `frontend/src/prompts/chapterDraftPrompt.js` / `formatAiTraceRulesForGeneration()` | Creative system prompt injected a thick anti-AI-trace checklist, pushing the model toward compliance/report mode. | Removed the thick checklist from creative system prompt. AI trace rules remain available for audit/repair paths, not as creative identity. |
| `frontend/src/prompts/chapter.js` / `## 写作质量方向` | Long quality checklist contained good advice but encouraged rule-by-rule execution and summary-style self-checking. | Replaced with short `## 戏剧执行底线` focused on pressure, dialogue conflict, emotional turn, action consequence, embodied detail, information release, and stop point. |
| `frontend/src/data/writingStyleStandards.js` / `short-drama-reversal` and project style notes | Phrases like “节奏快、场景短、少描述多动作、对话简洁” can be misread as action流水账 and under-described scenes. | `NarrativeVoiceContract v2` normalizes these into balanced constraints: short scenes still need emotional turns; less explanation still needs facial/voice/environment cues; action must carry intention/relationship change; concise dialogue needs conflict/subtext. |
| `ContextPack v2` narrative voice v1 | Reserved schema existed but was thin and did not transform risky style shorthand into executable dramatic profile. | Added v2 schema/lint/sanitize and compatibility export for old `lintNarrativeVoiceContract`. |
| Saved beat plan / guard snapshot mixed context risk | Scene writing may accidentally treat plan/guard material as creative facts if prompt builders accept broad context. | Scene card only reads trusted current-stage creative/stateAuthority inputs. `guardSnapshot` and saved beat plan are not copied into prompt-facing SceneExecutionCard. |
| Repair/audit prompts | Some prompts intentionally contain checklists. | Left unchanged for this phase unless used as creative draft prompt. They remain evaluation/repair tools, not primary scene generation instructions. |

## NarrativeVoiceContract v2

Schema highlights:
- `schemaVersion: narrative-voice-contract-v2`
- `scope: expression_only`
- `dialogue.conflictAndSubtext`
- `emotion.mustTurn`
- `embodiment.facialVoiceEnvironment`
- `action.mustCarryIntentionAndRelationshipChange`
- `interiority.shortAndInterrupted`
- `sourceRiskTransform` records whether risky shorthand was normalized.

Lint/sanitize behavior:
- Blocks fact/stage/guard override fields such as `factOverrides`, `stateAuthority`, `stageBoundary`, `creativeStageContract`, `worldRules`, `guardSnapshot`, `futureRoadmap`.
- Warns/rejects documentary/rule tone inputs like historical-document/report/rule-instruction style when they appear as contract content.
- Sanitizer drops forbidden fact/stage/guard fields and only keeps expression-facing voice controls.
- Backward compatibility: `contextPackV2.lintNarrativeVoiceContract()` still returns string issues for Phase 1 callers/tests; v2 module exports structured issues.

## SceneExecutionCard Boundary

`SceneExecutionCard` is prompt-facing, but only current-stage-facing:
- Inputs: chapter goal, current stage writable facts, creative stage contract, trusted stateAuthority facts, safe creative restrictions.
- Outputs: scene objective, conflict pair, emotional turn, dialogue task, physical pressure, facial/voice cues, environmental pressure, allowed facts, stop point, safe forbidden summary.
- Exclusions: no `guardSnapshot`, no future roadmap, no saved old beat plan, no failed/candidate authority.
- Guard-only wording is generic: deterministic guard owns future/forbidden checks; the creative card does not expose the future secret or roadmap content.

## No-model Literary Quality Evaluator

Added `frontend/src/utils/literaryQualityEvaluator.js`.

Deterministic checks include:
- Documentary/rule/report tone.
- Summary tone replacing visible scene.
- Dialogue ratio and direct conflict/subtext.
- Emotional turn signal.
- Face/voice cues.
- Environmental pressure.
- Short interiority.
- Action expression.
- Repeated action templates such as 握拳/指节发白/沉默.
- Prompt-level unbalanced “少描述/多动作/对话简洁” shorthand without counterweights.
- Regex count semantics are covered by fixture: one documentary cue does not become two hits, while repeated summary markers are counted.

Fixture coverage in `tmp/test_narrative_voice_scene_contract_phase2.mjs`:
- Risky style shorthand is transformed into healthier dramatic constraints.
- Voice lint rejects/sanitizes facts/stage/world/guard override fields.
- SceneExecutionCard includes trusted final/current-stage facts and stop point.
- SceneExecutionCard and draft prompt do not expose guard-only future roadmap or saved old beat plan.
- Draft system prompt no longer includes the thick AI-trace generation checklist.
- Bad documentary/summary/action-template text fails.
- A compact dramatic scene with dialogue conflict, emotional turn, face/voice/environment/action signals passes.
- Direct SceneExecutionCard candidate/failed/missing-provenance/unknown/degraded fact inputs are filtered out of `allowedFacts`.
- Prompt-facing SceneExecutionCard text does not mention `guardSnapshot`, `guard-only`, `roadmap`, or future-roadmap implementation terms.

## Offline Model-assisted Validation

Preferred model requested by policy: `联通云-DeepSeek-V4-Flash`.

Actual model used: `DeepSeek fallback / deepseek-v4-pro`.

Reason for fallback:
- Current thread exposed `DEEPSEEK_API_KEY` and model names, but did not expose an unmasked usable `联通云-DeepSeek-V4-Flash` baseURL/API key pair.
- No app/backend/provider DB state was read or started to recover credentials.

Parameters:
- `temperature: 0.7`
- `top_p: 0.9`
- `max_tokens: 900`

Validation design:
- Old prompt input represented the previous risk shape: thick AI-trace/quality checklist, unbalanced “节奏快/场景短促/少描述多动作/对话简洁”, and an intentionally wrong creative-context inclusion of guardSnapshot future roadmap.
- New prompt input used Phase 2 SceneExecutionCard + NarrativeVoiceContract; guardSnapshot remained outside creative prompt.

Current result summary from `tmp/realistic-flow-qa/narrative-voice-phase2-model-validation.json`:
- oldPrompt.qualityScore=100
- oldPrompt.passedEvaluator=true
- oldPrompt.blockingIssueCodes=none
- oldPrompt.warningIssueCodes=missing_short_interiority
- oldPrompt.leakedFutureSecret=false
- newPrompt.qualityScore=100
- newPrompt.passedEvaluator=true
- newPrompt.blockingIssueCodes=none
- newPrompt.warningIssueCodes=none
- newPrompt.leakedFutureSecret=false
- newPromptQualityAtLeastOld=true
- newPromptAvoidedFutureSecret=true
- newPromptPassedEvaluator=true
- oldPromptPassedEvaluator=true
- newPromptHasNoBlockingIssues=true

Evaluator pass semantics:
- `passedEvaluator=true` means `qualityScore >= 70` and `blockingIssueCodes` is empty.
- `warningIssueCodes` may be present while `passedEvaluator=true`; this is now explicit in JSON via `passRule`.

Conclusion for this sample:
- This run does not prove every old prompt leaks future roadmap.
- Both old and new outputs passed the deterministic evaluator in this sample.
- The new Scene Card prompt did not leak the future secret, matched the old prompt score, and had fewer evaluator issues (`none` vs warning-only `missing_short_interiority`).
- Therefore the current evidence supports “architecture usable and current sample not weaker than old prompt”; it should not be reported as broad statistical proof of quality superiority.

## Verification

Commands run:
- `node tmp\test_narrative_voice_scene_contract_phase2.mjs`
  - Result: passed.
- `node tmp\test_narrative_voice_phase2_evidence_contract.mjs`
  - Result: passed.
- `node tmp\test_context_pack_v2_phase1_contract.mjs`
  - Result: passed.
- `node tmp\test_state_provenance_phase1_2_contract.mjs`
  - Result: passed.
- `node tmp\test_quality_chain_contract.mjs`
  - Result: passed.
- `node tmp\test_quality_first_generation_contract.mjs`
  - Result: passed.
- `node tmp\test_prompt_boundary_modules.mjs`
  - Result: passed.
- `node tmp\test_writer_store_prompt_boundaries.mjs`
  - Result: passed.
- `node tmp\test_writing_style_standards_contract.mjs`
  - Result: passed.
- `node tmp\test_ai_trace_review_prompt.mjs`
  - Result: passed.
- `node tmp\test_audit_ai_trace_contract.mjs`
  - Result: passed.
- `npm --prefix frontend run build`
  - Result: passed.
  - Note: Vite emitted an existing dynamic/static import chunking warning for `writerStore.js`; build completed successfully.
- `node tmp\run_narrative_voice_phase2_model_validation.mjs`
  - Result: completed with DeepSeek fallback and wrote QA summary JSON.

## Fresh Review

Review subthread: `019f2e55-1593-7061-983b-df5daaf764fc`.
Evidence-closure review subthread: `019f2e65-44f6-7d30-ab93-1d8d09c76cd5`.

Result:
- Initial review Critical: none.
- Initial review Important: three findings, all fixed before final handoff.
- Evidence-closure review Critical: none.
- Evidence-closure review Important: one test-hardening finding, fixed before final handoff.
- Evidence-closure follow-up review: no Critical/Important remaining; reviewer confirmed current report matches JSON.

Fixes applied:
- `literaryQualityEvaluator.countMatches()` now forces global regex matching so metric counts reflect occurrences, not capture-array length. Added fixtures for single documentary cue and repeated summary markers.
- Prompt-facing SceneExecutionCard text no longer mentions `guardSnapshot`, `guard-only`, `roadmap`, or future-roadmap implementation terms.
- SceneExecutionCard fact normalization now filters failed/candidate/unfinalized/pending/tainted/quarantined/unknown/degraded sources and no longer treats missing-status object facts as trusted. Plain strings are only accepted from `creativeStageContract.allowedFacts`, which is already the current-stage creative contract.
- Evidence matcher now verifies label-qualified `oldPrompt.qualityScore`, `newPrompt.qualityScore`, `oldPrompt.passedEvaluator`, and `newPrompt.passedEvaluator`, and asserts in-memory stale report mutations are rejected.

## Remaining Risks / Phase 2+ Entry

- The literary evaluator is heuristic and should remain a gate/diagnostic, not a substitute for human/editorial judgment.
- SceneExecutionCard currently derives scene pressure with conservative defaults; future Phase 2 work can make richer scene-card extraction from trustworthy chapter plans without admitting guard-only data.
- Offline model validation was a small sample, not broad A/B benchmarking.
- Full Phase 2 writing engine integration, SceneExecutionContract orchestration across multi-scene chapters, and Phase 3 provider work remain intentionally out of scope.
