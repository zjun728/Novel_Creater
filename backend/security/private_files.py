"""Fail-closed private filesystem permissions shared by package boundaries."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess


_WINDOWS_ACL_TIMEOUT_SECONDS = 5
PRIVATE_PERMISSIONS_ERROR = "private file permissions are unavailable"


class PrivateFilePermissionsError(Exception):
    """Permissions could not be made private and verified."""


def _is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _windows_current_process_sid() -> str:
    import ctypes
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError("process token unavailable")
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if required.value == 0:
            raise OSError("process token unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required, ctypes.byref(required)):
            raise OSError("process token unavailable")
        sid_text = ctypes.c_wchar_p()
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        if not advapi32.ConvertSidToStringSidW(token_user.user.sid, ctypes.byref(sid_text)):
            raise OSError("process SID unavailable")
        try:
            value = sid_text.value
            if value is None or re.fullmatch(r"S-[0-9]+(?:-[0-9]+)+", value) is None:
                raise OSError("process SID unavailable")
            return value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _windows_private_acl_is_valid(path: Path, sid: str, *, is_directory: bool) -> bool:
    import ctypes
    from ctypes import wintypes

    class AclSizeInformation(ctypes.Structure):
        _fields_ = (("ace_count", wintypes.DWORD), ("acl_bytes_in_use", wintypes.DWORD), ("acl_bytes_free", wintypes.DWORD))

    class AceHeader(ctypes.Structure):
        _fields_ = (("ace_type", wintypes.BYTE), ("ace_flags", wintypes.BYTE), ("ace_size", wintypes.WORD))

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = (("header", AceHeader), ("mask", wintypes.DWORD), ("sid_start", wintypes.DWORD))

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = (wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD))
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int)
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    expected_sid = ctypes.c_void_p()
    try:
        if advapi32.GetNamedSecurityInfoW(os.fspath(path), 1, 0x00000004, None, None, ctypes.byref(dacl), None, ctypes.byref(security_descriptor)) != 0 or not dacl.value:
            return False
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(security_descriptor, ctypes.byref(control), ctypes.byref(revision)) or not control.value & 0x1000:
            return False
        acl_information = AclSizeInformation()
        if not advapi32.GetAclInformation(dacl, ctypes.byref(acl_information), ctypes.sizeof(acl_information), 2) or acl_information.ace_count != 1:
            return False
        if not advapi32.ConvertStringSidToSidW(sid, ctypes.byref(expected_sid)):
            return False
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            return False
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(AccessAllowedAce)).contents
        expected_flags = 0x03 if is_directory else 0
        if ace.header.ace_type != 0 or ace.header.ace_flags & 0x10 or ace.header.ace_flags != expected_flags or ace.mask != 0x001F01FF:
            return False
        ace_sid = ctypes.c_void_p(ace_pointer.value + AccessAllowedAce.sid_start.offset)
        return bool(advapi32.EqualSid(ace_sid, expected_sid))
    finally:
        if expected_sid.value:
            kernel32.LocalFree(expected_sid)
        if security_descriptor.value:
            kernel32.LocalFree(security_descriptor)


def apply_private_permissions(path: Path, *, is_directory: bool) -> None:
    """Apply and verify an owner-only ACL/mode; never expose OS failure details."""

    try:
        if os.name == "nt":
            sid = _windows_current_process_sid()
            inheritance = "(OI)(CI)" if is_directory else ""
            result = subprocess.run(
                ["icacls", os.fspath(path), "/inheritance:r", "/remove:g", f"*{sid}", "*S-1-5-18", "*S-1-5-32-544", "*S-1-3-4", "/grant:r", f"*{sid}:{inheritance}F"],
                check=False, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=_WINDOWS_ACL_TIMEOUT_SECONDS,
            )
            if result.returncode != 0 or not _windows_private_acl_is_valid(path, sid, is_directory=is_directory):
                raise PrivateFilePermissionsError(PRIVATE_PERMISSIONS_ERROR)
            return
        expected_mode = 0o700 if is_directory else 0o600
        os.chmod(path, expected_mode)
        metadata = path.lstat()
        expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
        if not expected_type(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != expected_mode or _is_link(path):
            raise PrivateFilePermissionsError(PRIVATE_PERMISSIONS_ERROR)
    except PrivateFilePermissionsError:
        raise
    except Exception:
        raise PrivateFilePermissionsError(PRIVATE_PERMISSIONS_ERROR) from None
