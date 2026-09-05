# Finalization Preflight A Implementation Plan

> Execute with the subagent-driven-development skill for bounded independent work and independent review. User approved A on 2026-09-05; B remains excluded.

**Goal:** Prevent author confirmation of planning patches which atomic finalization must reject, without weakening commit guards or changing confirmed-review recovery.

**Architecture:** Reuse a shared pure protected-outline identity function. The repository places the sorted protected ID set in planning context, which is already hashed into the frozen finalization manifest. Validate raw model output before converting protected patches into existing non-authoritative suggestions, then revalidate. Correct and confirm reject protected patches and dry-run the exact pure Planning transformation used by commit. The frontend permits removal of unconfirmed future patches and explains the suggestion boundary.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, existing MySQL repository, Vue/Node tests; external providers remain fake.

## Task 1 — Frozen protected planning authority

- [x] Add regression tests in `backend/tests/unit/test_finalization_service.py` and `test_finalization_repository.py`: current/history protection, context drift, missing legacy context and corrupt/missing pinned outlines.
- [x] Run focused tests and observe failures before production edits.
- [x] Create `backend/domain/finalization_planning.py` with shared protected-ID parsing, bounded conversion and target validation; preserve existing commit rejection behavior through its wrapper.
- [x] Extend `backend/repositories/finalization.py` preparation context with authoritative sorted protected IDs; make pinned history lookup fail closed on a missing joined outline rather than silently dropping it.
- [x] Bind the set through existing planning-context hashing; reject missing/malformed protection context for new prepare/confirm without rewriting old records. Existing unconfirmed cancel remains available.

## Task 2 — Preparation, correction and confirmation

- [x] Add RED cases for protected patch demotion, valid future patches, invalid identity/evidence, suggestion overflow and injected protected corrections/legacy confirmations.
- [x] In `backend/services/finalization.py`: validate raw ChangeSet, convert protected patches, revalidate and publish; apply protected-target validation on correct and confirm. No conversion after author confirmation.
- [x] Preserve facts, progress events, IDs and evidence; bound suggestion length/count with existing strict domain models. Fail closed on overflow.
- [x] Add a stable public preflight conflict classification and Chinese recovery message for unsupported old/unexecutable reviews; retain existing confirmation/cancellation restrictions.

## Task 3 — Author correction controls

- [x] In `frontend/src/components/writer/FinalizationPanel.vue`, add removal of individual planning patches only while editable; removing a patch must mark local changes and require save before confirmation.
- [x] Show that non-authoritative suggestions do not update planning. Never enable editing or cancellation of confirmed reviews.
- [x] Add behavioral tests using existing finalization component/controller harness, then implement and run focused Node tests.

## Task 4 — Verification and review

- [x] Run affected backend/service/repository/API/commit tests and frontend tests; run focused disposable MySQL finalization tests with existing isolation guards.
- [x] Perform independent spec review, address concrete findings, then independent quality review.
- [x] At final scope run full unit suites and production build once; no real Provider/product-data writes. Preserve main document edits and the separate recommendation worktree.
- [x] Record evidence and A-only completion; commit only this feature's explicit files locally. No merge/push without deciding the final integration scope; no B implementation.

Representative commands (worktree root):

```powershell
D:/Software/Python/Python312/python.exe -m pytest backend/tests/unit/test_finalization_service.py backend/tests/unit/test_finalization_repository.py backend/tests/unit/test_finalization_commit.py backend/tests/unit/test_finalization_checks.py backend/tests/api/test_finalization_routes.py -q
npm --prefix frontend run test:unit
npm --prefix frontend run build
git diff --check
```

The formal Phase 5 browser fixture CLI also installs/clears the explicit runtime configuration, following the existing Phase 8A fixture pattern. This repairs its pre-existing startup incompatibility so the A UI gate can run; it does not change product runtime behavior.
