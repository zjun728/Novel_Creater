# M2 Artifact and Legacy Gate Boundary Design

**Status:** Approved design, 2026-07-17
**Scope:** M2 repository artifact scanning, effective legacy-shadow scanning, their
unit tests, and the corresponding M2E verification commands only

## Problem

The approved M2 implementation baseline is
`bc0919a2f8464a552c979a9601258fb148d98cac`. It is the clean commit that contains
the implementation index and all five approved plans before implementation
began. The later `b9b19e8` commit is a normative correction to the 10-style/64-card
counts; it does not replace the frozen diff baseline.

The current artifact scanner correctly fails closed, but it treats every file
added after the baseline as a public artifact. This produces false findings for:

- the required `backend/requirements-m2.lock.txt` dependency lock;
- long Python, JavaScript, test, and verification source files;
- synthetic sentinel and DSN definitions that runtime leak observers must know;
- approved specification and implementation-plan source.

The current raw legacy-name command has a separate category error: it searches
the textual diff and therefore reports negative tests and protective rejection
rules as if they were active shadow-QA dependencies.

Changing the baseline to a later implementation commit would hide roughly 144
M2-added files from review and is forbidden. Deleting or obfuscating protective
test strings merely to make a grep pass is also forbidden.

## Goals

1. Keep the exact approved baseline and scan every M2-added file at its current
   HEAD content.
2. Reject raw novel/corpus files and unreviewed evidence without confusing
   implementation definitions with published artifacts.
3. Scan the complete effective HEAD execution surface for retired shadow-QA
   names while allowing only exact protective rule definitions.
4. Keep both gates deterministic, local, fail-closed, and free of product DB,
   service, browser, Provider, or network activity.
5. Emit bounded path/reason findings without echoing file content, secrets,
   DSNs, or absolute private paths.

## Non-goals

- This is not a general source-code secret scanner. Provider response redaction,
  runtime sentinel observers, and API/public DTO tests remain the secret-egress
  authorities.
- This change does not alter product routes, database schemas, AI prompts,
  browser goals, assets, corpus data, or Provider behavior.
- It does not restore `phase-e`, `e.23`, `applyAdapter`, `providerAdapter`, or any
  historical compatibility path.
- It does not make evidence or asset review automatic; human L4 review remains
  a separate checkpoint.

## Selected architecture

Two small gates retain separate responsibilities:

1. `scan-m2-artifacts.mjs` classifies baseline-added files by repository role and
   applies artifact rules appropriate to that role.
2. A dedicated effective-legacy gate scans the committed HEAD path/content
   inventory for retired shadow-QA references.

Neither gate reads the dirty worktree as release evidence. Git supplies the
changed-file or HEAD inventory, and file contents are read from the committed
HEAD snapshot. Pure scanning functions continue to accept injected inventories
and readers for unit tests.

## Artifact role classification

Classification order is fixed. A file cannot escape an earlier rule through a
later role.

### 1. Raw corpus extensions

- `.epub` and `.mobi`, case-insensitive, are forbidden anywhere.
- `.txt`, case-insensitive, is forbidden anywhere except the exact dependency
  lock path `backend/requirements-m2.lock.txt`.
- The exception is exact, not suffix-, basename-, or directory-based.

The runtime browser corpus remains repository-external and temporary, so it is
not an exception to the repository gate.

### 2. Reviewed writing assets

Only these exact files are reviewed large-content assets:

- `backend/assets/writer-core-v1.1.0/manifest.json`
- `backend/assets/writer-core-v1.1.0/style_templates.json`
- `backend/assets/writer-core-v1.1.0/experience_cards.json`

They may exceed prose heuristics, but remain subject to per-file/aggregate size
limits and private sentinel/DSN/path checks. No directory-wide asset exception
is allowed.

### 3. Implementation definitions

Implementation definitions may be long and may deliberately define synthetic
sentinels. They are therefore not evaluated as public evidence by the prose or
synthetic-sentinel rules. They remain subject to normalized repository paths,
readability, per-file size, and aggregate size checks.

The closed definition roles are:

- files under `backend/`, `frontend/`, `scripts/`, and `tools/` with one of the
  exact case-insensitive source suffixes `.py`, `.pyi`, `.js`, `.mjs`, `.cjs`,
  `.ts`, `.tsx`, `.vue`, `.css`, `.scss`, `.html`, `.sql`, `.toml`, `.ini`,
  `.cfg`, `.yaml`, or `.yml`;
- the exact source-fixture path
  `tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json`;
- approved design and plan Markdown under `docs/superpowers/specs/` and
  `docs/superpowers/plans/`;
- the exact repository metadata path `.gitattributes`; and
- the exact M2 dependency lock exception above.

`backend/assets/`, `docs/development/`, any path containing a normalized segment
named `evidence`, `output`, or `artifacts`, and unknown paths take precedence over
source extensions. They are never implementation definitions merely because
their filename resembles code.

### 4. Evidence and unknown artifacts

`docs/development/`, paths containing the exact `evidence`, `output`, or
`artifacts` segment, unreviewed assets, and every unclassified textual file use
the strict artifact policy. The policy rejects:

- the closed synthetic sentinel values and DSN/root patterns represented by the
  scanner;
- credential-bearing DSNs and private absolute-root sentinels;
- oversized individual or aggregate content; and
- large source-like prose outside the three reviewed asset files.

Unknown roles fail into this strict policy; they are never implicitly trusted.

## Artifact CLI contract

The CLI continues to require an explicit `--base` and verifies that it resolves
to a commit. Formal M2 acceptance supplies the exact full hash of `bc0919a`.

The Git inventory remains baseline-added files (`--diff-filter=A`) because this
gate's approved contract is baseline-new artifact prevention. Each path is read
from `HEAD:<path>` rather than the mutable worktree. Invalid revisions, Git
errors, missing HEAD entries, invalid paths, unreadable content, or invalid sizes
return usage/infrastructure status 2. Findings return 1; a clean scan returns 0.

Output contains only normalized repository path and stable reason code/text. It
does not print matched content.

## Effective legacy-shadow gate

The legacy gate scans all tracked files in committed HEAD under:

- `backend/`
- `frontend/`
- `scripts/`
- `tools/`
- root `package.json`

The exact path patterns `backend/tests/**`, `frontend/tests/**`,
`scripts/tests/**`, and `tools/**/tests/**` are excluded. Formal executable
browser code under `frontend/e2e/`, backend scripts, root runners, and executable
QA tools remain included.

Both normalized path names and content are checked case-insensitively for:

- `phase-e`
- `e.23`
- `applyAdapter`
- `providerAdapter`

The gate permits only exact, line-bounded protective definitions already needed
to reject those names:

- the effective legacy scanner's own closed pattern definitions;
- the control-plane gateway's two normalized deny-list entries.

The allowance is path plus exact syntactic form, not a whole-file exclusion. Any
second occurrence, changed context, import, call, identifier, command, script,
or filename remains a finding. This prevents a protective file from hiding an
active legacy dependency.

The gate inventories and reads committed HEAD through Git, uses no shell string
evaluation, and emits only path plus stable reason. Git/inventory/read errors
return 2, findings return 1, and a clean scan returns 0.

## Testing contract

Artifact tests must prove:

1. the exact requirements lock is accepted while any other `.txt` and all
   `.epub`/`.mobi` variants are rejected;
2. legitimate long source, tests, specifications, and synthetic sentinel
   definitions are accepted as implementation definitions;
3. the same sentinel, DSN, private root, or long prose in evidence/unknown paths
   is rejected without echoing content;
4. only the three exact reviewed asset JSON files may contain large prose;
5. unreviewed `backend/assets` files remain strict even with a source-like
   extension;
6. path normalization, size limits, missing base, invalid base, and Git/read
   failures remain fail-closed; and
7. the real CLI passes from the exact `bc0919a` baseline.

Legacy-gate tests must prove:

1. negative tests in the four exact excluded test path patterns do not create
   findings;
2. the two exact protective definition locations are accepted;
3. a second forbidden occurrence in any allowlisted file is rejected;
4. forbidden identifiers, imports, commands, paths, and package scripts in every
   effective execution root are rejected;
5. formal `frontend/e2e` and executable `tools` files are included;
6. Git/inventory/read failures are non-zero and content is never echoed; and
7. the real committed HEAD scan is clean.

Focused RED tests precede implementation. After GREEN, run all script tests,
the exact artifact CLI, the exact effective legacy CLI, frontend build, backend
compile, isolated `.venv-m2` dependency/runtime checks, and the complete
`npm run test:milestone2` aggregate with `PYTHON` bound to the worktree venv.

## Documentation and release boundary

Implementation updates the M2E and formal-test-isolation plans so they invoke the
two official gates rather than the raw diff/grep command. The frozen baseline is
recorded by full hash; `b9b19e8` remains recorded separately as the normative
10-style/64-card plan amendment.

Passing these gates grants repository-artifact and effective-legacy readiness
only. It does not grant product DB, L4 human quality, L5 Provider, chapter-writing,
or Product Ready status.
