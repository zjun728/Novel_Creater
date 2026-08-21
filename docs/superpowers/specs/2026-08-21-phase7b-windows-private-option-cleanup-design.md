# Phase 7B Windows Private Option Cleanup Design

## Goal

Correct the Windows-only lifecycle defect that lets the Phase 7B MySQL option
file be written and scrubbed but prevents its deletion. Prove the fix with a
real Windows ACL regression test and then use only a disposable
`novel_creator_phase7b_restore_<32 lowercase hex>` database to diagnose the remaining
restore boundary. A real Stage A retry remains a separate approval gate.

## Observed failure and root cause

The approved Stage A attempt published a logical SQL backup, returned the fixed
public failure message, created no `novel_creator_v113`, left no restore database,
and did not publish a readiness receipt. Its option file was scrubbed to zero
bytes but remained on disk.

The residue has one non-inherited ACE granting the current user only `(R,W)`.
`backend.services.product_database_backup` currently imports
`restrict_windows_acl` from `backend.scripts.configure_local_mysql`; that helper
intentionally grants only `(R,W)`. The later owner-bound cleanup opens the file
with Windows `DELETE` access (`0x00010000`), which that ACL denies. The cleanup
contract and the selected ACL therefore contradict each other.

The published backup does not prove that restore succeeded. Because the CLI
sanitizes internal exceptions and no readiness receipt exists, the primary
restore failure must be diagnosed independently rather than inferred from the
option-file cleanup failure.

## Chosen approach

Use the existing shared private-files boundary in
`backend.security.private_files` for Phase 7B backup resources. It grants only
the current process SID full control, removes inheritance and unrelated grants,
and verifies the exact resulting ACL. Full control supplies the required delete
right without making the file accessible to another account.

Keep `configure_local_mysql.restrict_windows_acl` unchanged. Local configuration
publishing has a different lifecycle and changing its established `(R,W)`
contract would expand the repair beyond the failing Phase 7B boundary.

Add a small Phase 7B adapter that applies and verifies private permissions with
the correct file/directory type. Continue injecting the ACL callback into unit
boundaries so failure ordering, sanitization, and race tests remain deterministic.
Do not add a delete fallback, privilege elevation, broad ACL, retry loop, or
path-based deletion that bypasses the existing owner identity checks.

## Data and control flow

1. The approved external backup directory is validated as external, existing,
   non-reparse, and identity-stable.
2. The Phase 7B ACL adapter applies an owner-only full-control directory ACL and
   verifies it.
3. The temporary option file is created with the existing owner lease.
4. The adapter applies and verifies an owner-only full-control file ACL before
   credentials are written.
5. Existing code writes, flushes, and exposes the option path to explicit MySQL
   8.4 clients.
6. On every exit path, existing code scrubs through the owner handle, closes the
   non-share-delete lease, reopens with `DELETE`, verifies the same file identity,
   marks deletion, and closes the deletion handle.
7. The logical backup remains published if a later restore or cleanup operation
   fails.

## Failure handling and safety boundaries

- ACL application or verification fails closed before credentials are written.
- Cleanup retains the existing primary-error-first ordering and fixed public
  error strings. Secrets, private paths, SQL data, and raw OS errors remain
  excluded from public output.
- The product databases `novel_creator` and `novel_creator_v113` are not written
  during repair verification.
- The published SQL backup is preserved and is not considered restore-proven
  until a controlled restore succeeds.
- The existing zero-byte option-file residue is not deleted as part of the code
  patch. Any remediation of that exact external artifact is a separately audited
  cleanup action.
- No Provider call, market refresh, configuration cutover, Stage B action, or
  legacy deletion is in scope.

## Test and diagnostic design

### RED regression

Add a Windows-only test that uses the production ACL callback with
`private_mysql_option_file`. While inside the context it verifies the option file
is private and usable; after normal exit it requires that the directory contain
no option file. Against the current `(R,W)` ACL, the test must fail at cleanup and
leave only a zero-byte owned file, reproducing the real symptom.

Keep existing injected-callback tests unchanged. Add a focused adapter test that
requires the correct `is_directory` value for both directory and file resources.

### GREEN and regression gates

After the minimal ACL dependency change:

- rerun the new Windows regression and the complete product-database-backup unit
  file with warnings treated as errors;
- run the prepare-command and readiness-service focused tests;
- run compilation and `git diff --check`;
- run the existing Phase 7B lifecycle focused gate if the focused tests pass.

### Disposable restore diagnosis

Run one controlled restore diagnostic using the already published backup and an
exact run-owned `novel_creator_phase7b_restore_<32 lowercase hex>` database. The diagnostic
must:

- use the approved MySQL 8.4 client pair and configured `127.0.0.1:3307`
  authority without exposing credentials;
- create no product database and never select a pre-existing test database;
- record the fixed stage boundary and safe client result;
- clean only its exact run-owned test database in `finally`;
- prove created equals cleaned and remaining owned databases equal zero.

If the disposable restore succeeds, the prior primary failure lies after the raw
restore invocation and investigation continues at inventory comparison. If it
fails, stop at the exact fixed restore stage and diagnose that boundary without
running a second restore automatically.

## Completion criteria

- The real Windows option-file lifecycle leaves zero residue on normal and
  exceptional exits.
- Existing ownership, identity, scrub, error-precedence, and secret-sanitization
  tests remain green.
- The disposable diagnostic reports one bounded outcome and zero owned database
  residue.
- Git contains only the reviewed repair, tests, and planning documentation.
- No real Stage A retry occurs; the next real execution requires a new explicit
  approval of its exact command and current external resources.
