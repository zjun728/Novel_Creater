# Lean Test Gate Policy Design

## Goal

Reduce repeated test time by changing gate frequency and scope, without deleting tests,
changing product behavior, or building another test orchestration system.

## Decision

Keep the current test commands and `scripts/run-tests.mjs` unchanged. Development plans and
reviews will use four evidence levels:

1. **Focused:** Run explicitly named tests during RED/GREEN/refactor and diagnosis.
2. **Slice:** Run affected unit/API tests, affected disposable-MySQL tests only when database
   behavior changed, a build when production frontend code changed, and a narrow browser
   scenario only when a critical visible flow changed.
3. **Phase:** After every slice is accepted and code has stopped changing, run `npm test`,
   `npm run test:integration`, `npm run build`, the Phase's formal fake-provider browser gate,
   and the owned-resource residue audit once.
4. **Release:** At a release candidate, repeat the Phase matrix and add the applicable
   product-shell, packaging, backup/import, security, and explicitly authorized environment
   checks.

## Review evidence reuse

- The implementer records one fresh slice result after focused RED/GREEN work.
- Specification and quality reviews reuse that result when they request no code change and
  identify no missing test class.
- A code change invalidates the affected evidence and requires the affected tests again.
- The controller runs the full Phase gate once at Phase close.
- Failed tests are diagnosed; unchanged failing commands are not blindly rerun.

## Boundaries

- Keep every existing test and existing npm command.
- Do not add a generic focused-test CLI, impact detector, selector manifest, or gate engine.
- Do not automatically run a real provider, live website, or product database.
- Do not weaken Canon, immutable-baseline, transaction, secret, process, port, temporary-file,
  or disposable-database coverage.
- Do not rewrite historical acceptance records; they continue to describe evidence that was
  actually collected.

## Documentation changes

- Add one concise authoritative policy under `docs/testing/`.
- Reference it from `CURRENT_PROJECT_STATE.md`.
- Future implementation plans must list exact focused and slice commands. They must reserve
  full regression for Phase or release acceptance unless a concrete cross-cutting risk is
  documented.

## Acceptance criteria

- No production or test-dispatcher code changes.
- Existing test commands retain their meanings.
- The authoritative policy clearly distinguishes focused, slice, Phase, and release evidence.
- Review evidence reuse is explicit and invalidation rules are unambiguous.
- Full disposable-MySQL and formal browser gates remain mandatory at Phase acceptance.
- The change can be reverted by reverting documentation only.
