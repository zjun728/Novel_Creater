# Phase 7B Receipt Shared-Delete Identity Design

## Goal

Allow readiness receipt publication to verify an owned Windows temporary file
while its delete-capable owner handle remains open.

## Root cause

The production probe proved that the lease identity and live descriptor identity
match before and after ACL restriction, while reopening the path fails even
before ACL restriction. `_same_receipt_owner()` currently uses `os.open()` for
the reopen. The existing owner handle requests `DELETE`; the CRT reopen does not
share delete access, so Windows rejects it as a sharing conflict.

## Design

Add one private helper beside `_same_receipt_owner()`. It opens the exact path
with Win32 `CreateFileW`, requests only `FILE_READ_ATTRIBUTES`, and supplies
`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`. It uses
`OPEN_EXISTING` and `FILE_FLAG_OPEN_REPARSE_POINT`, reads the existing
`_OwnedFileIdentity`, and always closes the Win32 handle.

The `_OwnedFileLease` branch of `_same_receipt_owner()` compares this identity
with the lease identity. The tuple/POSIX branch remains unchanged. Open,
identity, or close failures continue to return `False`; no error details become
public.

## Boundaries

- No change to receipt content, ACL, hardlink, absent-only publication, cleanup,
  database lifecycle, Stage B, Provider behavior, or retry policy.
- Do not close the owner handle before verification or request `DELETE` on the
  verification handle.
- Add focused unit coverage for the exact Win32 access/share/flag contract and
  handle cleanup, then rerun the existing Phase 7B command gates.
