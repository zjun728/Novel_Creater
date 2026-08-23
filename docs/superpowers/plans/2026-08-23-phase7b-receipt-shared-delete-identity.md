# Phase 7B Receipt Shared-Delete Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Windows readiness receipt publication by reopening owned temporary paths with a delete-compatible, read-attributes-only handle.

**Architecture:** Add one private Win32 path-identity helper beside the existing receipt owner check. The helper opens the path with the minimum access and all compatible share flags, returns the existing backup module's identity value, and always closes its handle; only the `_OwnedFileLease` branch uses it.

**Tech Stack:** Python 3.12, ctypes Win32 API, pytest, existing Phase 7B receipt ownership primitives.

---

## File map

- Modify `backend/scripts/prepare_product_database.py` — add the Win32 shared-delete identity reopen and use it for receipt leases.
- Modify `backend/tests/unit/test_prepare_product_database_command.py` — assert the exact access/share/open contract and handle cleanup.

### Task 1: Prove the regression

**Files:**
- Modify: `backend/tests/unit/test_prepare_product_database_command.py`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Add the failing test**

Add a test that creates an `_OwnedFileLease`, injects a fake `CreateFileW`,
identity reader, and closer, then calls `_same_receipt_owner()`:

```python
def test_receipt_owner_reopens_delete_capable_path_with_shared_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.services.product_database_backup as backup_module

    path = tmp_path / "owned.tmp"
    path.write_bytes(b"")
    expected = backup_module._OwnedFileIdentity(1, 2, 3)
    lease = backup_module._OwnedFileLease(expected, 51, delete_through_handle=True)
    calls: list[object] = []

    class Creator:
        def __call__(self, *args: object) -> int:
            calls.append(("open", args))
            return 71

    monkeypatch.setattr(
        backup_module, "_kernel32", lambda: SimpleNamespace(CreateFileW=Creator())
    )
    monkeypatch.setattr(
        backup_module,
        "_identity_from_handle",
        lambda handle: calls.append(("identity", handle)) or expected,
    )
    monkeypatch.setattr(
        backup_module,
        "_close_windows_handle",
        lambda handle: calls.append(("close", handle)),
    )

    assert command_module._same_receipt_owner(path, lease) is True
    assert calls == [
        ("open", (str(path), 0x00000080, 0x00000007, None, 3, 0x00200000, None)),
        ("identity", 71),
        ("close", 71),
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py::test_receipt_owner_reopens_delete_capable_path_with_shared_delete -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-receipt-shared-delete-red
```

Expected: the assertion fails because current `_same_receipt_owner()` uses
`os.open()` and the fake Win32 calls are absent.

### Task 2: Implement the minimal helper

**Files:**
- Modify: `backend/scripts/prepare_product_database.py`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Add the helper**

Add beside `_same_receipt_owner()`:

```python
def _receipt_identity_from_path(path: Path) -> object:
    import ctypes
    from ctypes import wintypes
    from backend.services import product_database_backup as backup_safety

    creator = backup_safety._kernel32().CreateFileW
    creator.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    creator.restype = wintypes.HANDLE
    opened = creator(
        str(path),
        0x00000080,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x00200000,
        None,
    )
    if opened == ctypes.c_void_p(-1).value:
        raise OSError
    handle = int(opened)
    try:
        return backup_safety._identity_from_handle(handle)
    finally:
        backup_safety._close_windows_handle(handle)
```

- [ ] **Step 2: Use it only for receipt leases**

Replace the `_OwnedFileLease` branch's `os.open()` block with:

```python
if type(identity) is _OwnedFileLease:
    try:
        return _receipt_identity_from_path(path) == identity.identity
    except OSError:
        return False
```

Leave the tuple branch unchanged.

- [ ] **Step 3: Verify GREEN**

Run the RED command again. Expected: `1 passed`.

- [ ] **Step 4: Run the complete command tests**

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-receipt-shared-delete-command
```

Expected: zero failures and warnings.

### Task 3: Verify and deliver

**Files:**
- Test only: existing Phase 7B files

- [ ] **Step 1: Run the focused Phase 7B gate**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_run_phase7b_browser_command.py backend/tests/unit/test_prepare_product_database_command.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-receipt-shared-delete-focused
```

Expected: zero failures and warnings.

- [ ] **Step 2: Run static checks**

```powershell
python -m py_compile backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --check
```

- [ ] **Step 3: Commit and push**

Stage only the two implementation files, commit with
`fix: reopen phase7b receipts with shared delete`, and push `main` after verifying
the tracked tree and index are clean.

- [ ] **Step 4: Run the real disposable receipt gate**

Use one exact absent-only synthetic receipt target in the approved backup
directory, call the production publisher, remove the published target in
`finally`, and require `publication=pass`, `cleanup=pass`, and zero residue. Do
not access MySQL, Provider services, or Stage A/B.
