# Phase 8A Manuscript Productization Acceptance

**Accepted:** 2026-08-29
**Feature branch:** `codex/manuscript-productization`
**Accepted code HEAD:** `5fb4d2d637af5cd810ea0cdaf68398daeee77e29`
**Baseline:** `b2ee1b54e337ef400e79ea438cf91daf8f9ff7c9`

## Outcome

The approved “作品稿件” vertical slice is accepted. Authors can discover the
manuscript from the project shell and overview, browse finalized chapters by
volume and chapter, read finalized prose in the product, switch to the pinned
author-facing outline, navigate between actual finalized neighbors, download
approved scopes, return to the current creative action, and move from a newly
finalized writer chapter into its verified reader route.

Historical finalized chapters remain read-only manuscript routes. They are not
reopened through the current-authority writer route. Internal Canon/Projection
payloads, hashes, UUIDs, SQL details, field paths, and raw exceptions are not
rendered in the author reading flow.

This acceptance covers the manuscript slice only. It does not claim completion
of later seed → contract → bible → planning transition productization, real
Provider quality, finalized-chapter editing or version history, search,
annotation, or the complete long-form creation product.

## Accepted scope and viewport

The final user-approved browser target is headed wide-screen Chromium at
`1440×900`, browser zoom `100%`. The user explicitly removed mobile portrait
and `200%` zoom from this acceptance scope. The formal runner therefore reports
one wide-screen point rather than the superseded multi-viewport matrix.

At the accepted point, the application had no horizontal overflow, used the
full desktop navigation, preserved keyboard and reduced-motion assertions, and
captured a visible non-zero Windows Chrome window without a headless flag.

## Delivered commit boundaries

The slice starts from the approved design and implementation plan:

- `652b2ce78d9dee838d33d38675f783ccb9df65d7` — define the manuscript productization slice.
- `481d61ce3195f5e35ec05e92d67bd02501c0eb86` — plan the manuscript productization implementation.
- `96f7882a2b911e76823c615a69446d447e74ed9d` — isolate finalized download integrity scope.
- `bea88016f249102c0b6f9e43e68d8feb3c2031b7` — define the manuscript read domain.
- `74a483ba02f8012d8dd1dfb4cabc83cfaad9d63f` — read pinned manuscript records.
- `5f2db6f5a7c78c68b0a01e0694a5afb53daff050` — expose finalized manuscript reading.
- `8ebc56e394d55a67e1e190a2f754fe08127b6011` — coordinate manuscript frontend state.
- `4a4304eee84dfa55d553da326f2f96adbaeda823` — add the manuscript directory product flow.
- `b2dd8ec1f82f84cb7301dd9c4272268720ff1a7b` — read finalized chapters in the product.
- `83c388f9ac69b8c3b824f7b036a30d25b074a4db` — close the finalized manuscript author loop.
- `eb33ea25c68c36cad091ef2ecab8a1320979153c` — make manuscript reading accessible.
- `92f0768332336d0d3642353500de06d159144499` — add the Phase 8A browser workflow.
- `0eb12a9ae888268e314fca9c1bb906d99bb6f111` — run Phase 8A in headed Chromium.

Task 11 added and hardened the strict product read-only verifier and safe browser
diagnostics through these exact commits:

- `a932c515559fd88ebb5b125e7c94aba5d9ccfe23`
- `b1a24b20297586b094cced83895699bbcac330b8`
- `b1d117fe6f78e24e5be51eae22f0256b51157cd1`
- `4162bc9f231fcfb4f25906a1d1a7fe96e741e267`
- `08089882ac124782b3e12c65e74944e87f212aac`
- `b68d1da73b17b9408d9a631e9e3511627b56e4d0`
- `f13b3f547f5e9251034d64f025f5aad257c2ce25`
- `c3b35dd5aeadf817ed990f1ce0e3f63fddb56fb4`
- `8a48f794103f09d22a0d39e93b3d5cae0b30cb9b`
- `693fb8347c2f5862bdcaca259a412061f6005479`
- `2e8b7906b2ef86a2587c060949fd711761592b07`
- `5fb4d2d637af5cd810ea0cdaf68398daeee77e29`

## Fresh verification results

The final focused set on accepted HEAD completed as follows:

- Backend manuscript/download/API/verifier focus: `329 passed`.
- Focused disposable MySQL: `9 passed`; `created=9`, `cleaned=9`, `remaining=0`.
- Frontend manuscript/product-shell focus: `168 passed`.
- Production frontend build: Vite `8.0.13`; `2,994` modules transformed.
- Formal headed Phase 8A browser: `1/1 wide-screen point passed`.

The formal browser ledger reported:

- Provider requests: `0`.
- Live website access: `0`.
- Unexpected console errors: `0`.
- Page errors: `0`.
- Request failures: `0`.
- Four known console events, each exactly linked to the four intentional corrupt
  fixture `GET 500` responses.
- Owned child processes, ports, temporary paths, downloads, and disposable
  schemas after cleanup: `0`.

Risk-related full gates:

- Final `npm test` on accepted HEAD:
  - Python: `5,427 passed`, `9 skipped`.
  - Node formal suites: `450 passed`.
  - Frontend: `910 passed`.
- `npm run test:integration`: `400 passed`, `7 skipped`;
  disposable MySQL `created=398`, `cleaned=398`, `remaining=0`.
  Later changes were confined to the standalone smoke verifier, its unit tests,
  and browser diagnostic classification; final focused MySQL was rerun on the
  accepted HEAD.
- Final `npm --prefix frontend run test:unit`: `910 passed`.
- Final `npm run build`: Vite `8.0.13`; `2,994` modules transformed.
- `git diff --check`: clean.

## Product database read-only smoke

The approved product project was checked with the production manuscript and
preparation services through enforced read-only transactions:

```text
python -m backend.scripts.verify_manuscript_product_smoke --project-id 474d110f-977c-4c82-bec4-464f30ec5a16
```

The fixed safe receipt was:

```json
{"chapterCheckCount":3,"finalChapterCount":3,"pinnedCheckCount":3,"projectId":"474d110f-977c-4c82-bec4-464f30ec5a16","status":"passed"}
```

The verifier called the production directory reader, chapter readers for
chapters 1–3, and project preparation service. It validated the three approved
chapter titles internally, three pinned author-outline projections, and current
authority chapter 4. It printed no title, prose, outline payload, hash, DSN,
SQL, database identity, or raw exception.

The independent headed product UI review used only `GET` requests and confirmed:

- Directory chapter count: `3`.
- Non-empty readable finalized prose: `3/3`; content was not copied or logged.
- Valid pinned outline views: `3/3`; outline payloads were not copied or logged.
- Chapter 1 direct link: passed.
- Current action: “准备第 4 章小纲”, with the safe planning/story-block target;
  the action was inspected but not activated.
- Provider attempts: `0`.
- External page requests: `0`.
- Forbidden methods and writes: `0`.
- Downloads: `0`.
- Console errors, page errors, failed responses, and request failures: `0`.

Chromium background probes were separated from Provider accounting and blocked
by the run-owned deny proxy (`HTTP=1`, `CONNECT=39`). Browser, context, backend,
Vite, deny proxy, ports, profiles, temporary paths, and downloads were all zero
after cleanup. The private product configuration hash was unchanged.

No write, generation, finalization, archive, restore, download mutation,
fixture, direct SQL write, Provider endpoint, or external website was invoked.

## First-cause and remediation history

- A focused backend run first encountered an inaccessible stale system pytest
  directory. A workspace-owned `--basetemp` was used, verified, and removed;
  the complete focused set then passed.
- One intermittent Phase 8A request failure lacked safe classification.
  Closed method, stage, route-template, and failure-type diagnostics were added
  without adding an allowlist or converting any failure to success.
- Independent review found a marker could copy lowercase untrusted evidence.
  Markers were changed to anchored field allowlists, bounded values, canonical
  reserialization, and fixed fallbacks. Download options received its own fixed
  route template; timeout classification was corrected.
- Independent review found cold-import failure classification could emit a raw
  traceback. Classification now fails closed to a fixed receipt.
- The product CLI initially lacked the application runtime-configuration
  lifecycle. It now owns `load → install → verify → close → clear`, cleans only
  resources it installed, preserves control-flow exceptions, and leaves an
  existing owner untouched.
- The verifier had also required a current chapter-4 outline even though the
  frozen plan requires current authority chapter 4 plus pinned outlines for
  finalized chapters 1–3. The extra condition was removed. The product correctly
  presents “准备第 4 章小纲” as its next author action.
- Independent product-browser attempts exposed three temporary-review-runner
  issues: duplicated Vite config loading, an incomplete loopback proxy bypass,
  and use of DPR as a browser-zoom proxy. The runner was corrected with one Vue
  plugin, a bare loopback bypass, and a CSS/CDP zoom-1 gate. Provider accounting
  was separated from blocked Chromium background probes. None was a product-code
  defect, and the final stable-HEAD review passed.

## Independent reviews

- Verifier specification review: Ready `Yes`; Blocking/Major/Minor `0/0/0`.
- Verifier quality review after runtime-ownership remediation: Ready `Yes`;
  Critical/Major/Minor `0/0/0`.
- Safe Phase 8A diagnostic review after marker remediation: Ready `Yes`;
  Critical/Major/Minor `0/0/0`.
- Final independent headed product-flow review: Ready `Yes`;
  Blocking/Major/Minor `0/0/0`.

Every Blocking or Major finding was resolved by the original implementation
owner and independently re-reviewed before the final focused gates.

## Repository and cleanup boundary

Before this record was committed:

- The feature worktree was clean at code HEAD `5fb4d2d`.
- No task-owned process or `.codex-test-artifacts` path remained.
- No product prose, outline payload, database dump, screenshot, browser download,
  secret, or temporary artifact was staged.
- The user-owned repository-root `.review-worktrees/` path was not modified,
  removed, or staged.
