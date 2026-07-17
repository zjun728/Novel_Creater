# M2 Reset Seed Mapping Design

- Date: 2026-07-17
- Status: Approved in product-control conversation; pending written-spec review
- Baseline: `main@f48d699`
- Scope: one-time `writer-core-v1.0.0` to `writer-core-v1.1.0` product reset

## 1. Problem

The guarded M2 product reset correctly recognizes the exact 34-table M1
manifest, but its seed mapper validates M1 rows directly as the current
nine-field `SeedPayload`. The committed M1 product database does not have that
shape:

- `creative_seeds.premise_json` contains the exact thirteen-field M1 premise;
- the authoritative seed title remains in `creative_seeds.title`;
- the M1 `content_hash` covers the canonical envelope
  `{"title": title, "premise": premise}`;
- the selected seed row has `status='selected'`, while the other two rows have
  `status='candidate'`.

Consequently, the formal read-only product dry-run fails before it can emit a
reset receipt. This is a defect in the one-time reset boundary, not a reason to
add legacy support to the product runtime.

## 2. Goals and non-goals

The change must:

1. accept only the exact, hash-valid M1 seed representation already produced by
   the approved M1 reset;
2. convert it deterministically into the single current nine-field
   `SeedPayload`;
3. preserve the three seed identities, their titles, their eight still-current
   story fields, and their creation timestamps;
4. make `project_selected_seeds` the only selected-seed fact in M2;
5. leave the current M2 readback/no-op path strict to the nine-field schema;
6. keep dry-run read-only and keep destructive execution behind the existing
   host, port, database, confirmation, authority, lock, and manifest gates.

The change must not:

- modify the product database before the later explicit execute confirmation;
- add legacy parsing to normal project, seed, contract, Writer, or Provider
  runtime services;
- preserve the five retired M1 seed fields in M2;
- infer or synthesize missing seed content;
- relax source manifest, project, seed, Provider, binding, Canon, projection,
  or empty-derived-table checks;
- call a Provider/model or generate story content.

## 3. Closed M1 source contract

The M1 mapper accepts a JSON object with exactly these thirteen keys:

1. `genre`
2. `logline`
3. `protagonist`
4. `desire`
5. `coreConflict`
6. `worldPressure`
7. `openingHook`
8. `emotionalPromise`
9. `differentiation`
10. `styleTarget`
11. `source`
12. `riskNotes`
13. `endingAnchor`

Every value must be text and every field retained by M2 must satisfy the
current `SeedPayload` validation after mapping. Unknown keys, missing keys,
invalid JSON, non-object JSON, non-text values, and invalid destination values
fail closed.

Before conversion, the mapper recomputes the historical M1 hash from the
canonical envelope:

```json
{"title":"<creative_seeds.title>","premise":{...exact M1 premise...}}
```

The recomputed hash must equal `creative_seeds.content_hash`. This preserves the
integrity guarantee of the original M1 seed even though M2 will use a different
canonical document and hash.

The M1 status set is also closed:

- `典镇山河` must be `selected`;
- `永乐长明` and `文渊山海` must be `candidate`;
- the existing `project_selected_seeds` row must independently select
  `典镇山河`.

Any disagreement fails dry-run before DDL.

## 4. Deterministic M2 mapping

The M2 payload is constructed from one authoritative title column and eight
retained premise fields:

| M2 field | M1 source |
| --- | --- |
| `title` | `creative_seeds.title` |
| `genre` | `premise_json.genre` |
| `logline` | `premise_json.logline` |
| `protagonist` | `premise_json.protagonist` |
| `desire` | `premise_json.desire` |
| `coreConflict` | `premise_json.coreConflict` |
| `worldPressure` | `premise_json.worldPressure` |
| `openingHook` | `premise_json.openingHook` |
| `differentiation` | `premise_json.differentiation` |

These five M1 fields are validated as part of the exact source object and then
discarded:

- `emotionalPromise`
- `styleTarget`
- `source`
- `riskNotes`
- `endingAnchor`

The mapped payload is validated by the current strict `SeedPayload`, serialized
with `canonical_json`, and assigned a new M2 `canonical_hash`.

All three M2 `creative_seeds` identities use `status='candidate'`. Selection is
represented only by the revisioned `project_selected_seeds` row for
`典镇山河`. This removes the M1 duplicate status representation instead of
carrying it forward.

## 5. Code boundary

The one-time reset script will have two explicit paths:

- an M1 mapper that validates the thirteen-field premise, historical envelope
  hash, and M1 status contract before producing the current payload;
- an M2 readback mapper that accepts only the current nine-field payload and
  current seed status.

The M2 no-op/readback path must not call the M1 mapper. Shared identity and
timestamp validation may be factored into a small private helper, but source
shape and hash rules remain separate and obvious.

No other backend router, service, repository, schema, frontend file, or API
contract changes.

## 6. Failure behavior and secrecy

All validation failures occur during dry-run or before destructive DDL. The CLI
continues to return its generic failure banner; focused tests may inspect typed
internal exceptions.

The public dry-run/execute receipt remains unchanged and excludes:

- premise text and retired-field values;
- Provider API keys and Base URLs;
- DSNs, passwords, notes, and thinking configuration;
- absolute local paths.

The mapper must not log raw seed JSON.

## 7. Verification

TDD adds focused coverage for:

1. a real-shape thirteen-field M1 seed with a valid historical envelope hash
   maps to the exact nine-field M2 payload and new hash;
2. the selected M1 seed is accepted only for `典镇山河` and maps to a
   `candidate` M2 identity;
3. missing, extra, non-object, non-text, oversized, or empty retained fields
   fail closed;
4. a mismatched historical hash fails closed;
5. wrong M1 status combinations fail closed;
6. the M2 readback path still accepts only strict nine-field payloads and
   rejects legacy thirteen-field input;
7. receipts still exclude all secret and raw-content sentinels;
8. focused reset unit tests, real disposable-MySQL reset integration, the
   repository test gate, and `git diff --check` pass.

After code review, the formal product reset dry-run is rerun against
`127.0.0.1:3307/novel_creator`. Only a successful allowlisted dry-run receipt
may be presented for the separate destructive execute confirmation.

## 8. Rollout and rollback

The code change is merged before any product data write. The product database
remains untouched while tests, reviews, and dry-run execute.

If the later destructive reset is not explicitly approved, work stops with the
M1 database unchanged. If approved, the existing guarded reset lifecycle owns
the DDL, transaction, verification, cleanup, and partial-state reporting. No
new rollback mechanism is introduced by this mapping fix.
