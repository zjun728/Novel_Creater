"""Versioned source registry and evidence policy contracts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.domain.json_contracts import canonical_hash
from backend.http_errors import PublicDomainError


PACKAGE_VERSION = "market-sources-v1.0.0"
MAX_SOURCE_MANIFEST_BYTES = 64 * 1024
MAX_SOURCE_FILE_BYTES = 256 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_CONFIG_KEYS = {"platform", "rankingName", "category"}


_FAILURE_MESSAGES = {
    "MARKET_POLICY_MISSING": "Market source policy is unavailable",
    "MARKET_POLICY_NOT_VERIFIED": "Automatic refresh is not publicly verified",
    "MARKET_POLICY_EXPIRED": "Market source policy evidence is stale",
    "MARKET_POLICY_HASH_INVALID": "Market source policy integrity check failed",
    "MARKET_SOURCE_NOT_FOUND": "Market source was not found",
    "MARKET_SOURCE_CONFLICT": "Market source state changed; refresh and retry",
    "MARKET_SOURCE_ADAPTER_UNAVAILABLE": "Market source adapter is unavailable",
    "MARKET_REDIRECT_REJECTED": "Market source redirect was rejected",
    "MARKET_URL_NOT_ALLOWED": "Market source URL is outside the approved boundary",
    "MARKET_BODY_TOO_LARGE": "Market source response exceeds the maximum size",
    "MARKET_HTTP_FAILED": "Market source request failed",
    "MARKET_TRANSPORT_FAILED": "Market source transport failed",
    "MARKET_INTERSTITIAL_REJECTED": "Market source requires interactive access",
    "MARKET_HTML_UNKNOWN": "Market source format is not recognized",
    "MARKET_PAGE_INCOMPLETE": "Market source page is incomplete",
    "MARKET_SNAPSHOT_INVALID": "Market source returned an invalid snapshot",
    "MARKET_SNAPSHOT_IDENTITY_MISMATCH": "Market snapshot identity does not match its source",
    "MARKET_MANUAL_SNAPSHOT_INVALID": "Manual market snapshot is invalid",
    "MARKET_REFRESH_COMMAND_INVALID": "Market refresh command is invalid",
    "MARKET_REFRESH_COOLDOWN": "Market source refresh is in cooldown",
    "MARKET_REFRESH_IN_PROGRESS": "Market source refresh is already in progress",
    "MARKET_REFRESH_LEASE_EXPIRED": "Market source refresh lease expired",
    "MARKET_REFRESH_FAILED": "Market source refresh could not be completed",
}


class MarketSourceFailure(PublicDomainError):
    """A fixed, non-sensitive public source failure."""

    status_code = 422

    def __init__(self, code: str) -> None:
        if code not in _FAILURE_MESSAGES:
            raise TypeError("MarketSourceFailure requires a fixed public code")
        self.code = code
        self.message = _FAILURE_MESSAGES[code]
        super().__init__()


class MarketSourceNotFound(MarketSourceFailure):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("MARKET_SOURCE_NOT_FOUND")


class MarketSourceConflict(MarketSourceFailure):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("MARKET_SOURCE_CONFLICT")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class SourcePolicy(_FrozenModel):
    status: Literal["verified_public", "manual_only", "disabled"]
    checked_at: int = Field(alias="checkedAt", gt=0)
    evidence_url: str = Field(alias="evidenceURL", min_length=1, max_length=2_048)
    evidence_hash: str = Field(alias="evidenceHash", pattern=_SHA256.pattern)
    allowed_origins: tuple[str, ...] = Field(
        alias="allowedOrigins",
        min_length=1,
        max_length=8,
    )
    path_prefixes: tuple[str, ...] = Field(
        alias="pathPrefixes",
        min_length=1,
        max_length=8,
    )
    request_interval_seconds: int = Field(
        alias="requestIntervalSeconds",
        ge=60,
        le=31_536_000,
    )
    policy_version: str = Field(
        alias="policyVersion",
        min_length=1,
        max_length=120,
    )
    enabled: bool = False

    @field_validator("allowed_origins", "path_prefixes", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from urllib.parse import urlsplit

        for origin in value:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
            ):
                raise ValueError("allowed origin is invalid")
        if len(value) != len(set(value)):
            raise ValueError("allowed origins must be unique")
        return value

    @field_validator("path_prefixes")
    @classmethod
    def validate_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not prefix.startswith("/") or len(prefix) > 512 for prefix in value):
            raise ValueError("path prefix is invalid")
        if len(value) != len(set(value)):
            raise ValueError("path prefixes must be unique")
        return value

    @field_validator("request_interval_seconds")
    @classmethod
    def require_whole_minutes(cls, value: int) -> int:
        if value % 60:
            raise ValueError("request interval must use whole minutes")
        return value

    @field_validator("evidence_url")
    @classmethod
    def validate_evidence_url(cls, value: str) -> str:
        from backend.domain.market import _public_http_url

        return _public_http_url(value)

    @model_validator(mode="after")
    def enabled_requires_verified_public(self):
        if self.enabled and self.status != "verified_public":
            raise ValueError("only a verified public policy can be enabled")
        return self


class MarketSourceDefinition(_FrozenModel):
    stable_key: str = Field(alias="stableKey", min_length=1, max_length=160)
    adapter_key: Literal["qidian_public_rank", "qq_reading_public_rank"] = Field(
        alias="adapterKey"
    )
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    public_config: dict[str, str] = Field(alias="publicConfig")
    policy: SourcePolicy
    policy_hash: str = Field(alias="policyHash", pattern=_SHA256.pattern)

    @field_validator("public_config")
    @classmethod
    def validate_public_config(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _PUBLIC_CONFIG_KEYS:
            raise ValueError("public source configuration has unsupported fields")
        if any(
            not isinstance(item, str) or not item.strip() or len(item) > 160
            for item in value.values()
        ):
            raise ValueError("public source configuration is invalid")
        return {key: item.strip() for key, item in value.items()}

    def policy_content_hash(self) -> str:
        return canonical_hash(self.policy)


class SourceFile(_FrozenModel):
    path: str = Field(min_length=1, max_length=2_048)
    sha256: str = Field(pattern=_SHA256.pattern)

    @field_validator("path")
    @classmethod
    def safe_relative_json_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(value)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or windows.root
            or ".." in posix.parts
            or posix.suffix.lower() != ".json"
        ):
            raise ValueError("source child path is invalid")
        return normalized


class MarketSourceManifest(_FrozenModel):
    package_version: Literal["market-sources-v1.0.0"]
    sources_file: SourceFile


class MarketSourcePackage(_FrozenModel):
    manifest: MarketSourceManifest
    sources: tuple[MarketSourceDefinition, ...] = Field(
        min_length=1,
        max_length=16,
    )

    @field_validator("sources", mode="before")
    @classmethod
    def freeze_sources(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @property
    def package_version(self) -> str:
        return self.manifest.package_version


class MarketSourcePackageError(ValueError):
    _MESSAGES = {
        "MARKET_SOURCE_MANIFEST_IO": "market source manifest could not be read",
        "MARKET_SOURCE_MANIFEST_TOO_LARGE": "market source manifest is too large",
        "MARKET_SOURCE_MANIFEST_INVALID": "market source manifest is invalid",
        "MARKET_SOURCE_FILE_IO": "market source file could not be read",
        "MARKET_SOURCE_FILE_TOO_LARGE": "market source file is too large",
        "MARKET_SOURCE_FILE_HASH_INVALID": "market source file hash is invalid",
        "MARKET_SOURCE_PACKAGE_INVALID": "market source package is invalid",
    }

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            raise TypeError("MarketSourcePackageError requires a fixed code")
        self.code = code
        self.safe_message = self._MESSAGES[code]
        super().__init__(f"{code}: {self.safe_message}")


def _read_bounded(path: Path, limit: int, *, prefix: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError:
        raise MarketSourcePackageError(f"{prefix}_IO") from None
    if size > limit:
        raise MarketSourcePackageError(f"{prefix}_TOO_LARGE")
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        raise MarketSourcePackageError(f"{prefix}_IO") from None
    if len(raw) > limit:
        raise MarketSourcePackageError(f"{prefix}_TOO_LARGE")
    return raw


def _json(raw: bytes, *, code: str) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MarketSourcePackageError(code) from None


def load_market_source_package(manifest_path: Path) -> MarketSourcePackage:
    """Load one bounded, hash-bound built-in source package."""

    path = Path(manifest_path)
    manifest_raw = _read_bounded(
        path,
        MAX_SOURCE_MANIFEST_BYTES,
        prefix="MARKET_SOURCE_MANIFEST",
    )
    try:
        manifest = MarketSourceManifest.model_validate(
            _json(manifest_raw, code="MARKET_SOURCE_MANIFEST_INVALID")
        )
    except ValidationError:
        raise MarketSourcePackageError("MARKET_SOURCE_MANIFEST_INVALID") from None

    root = path.parent.resolve()
    child_path = (root / manifest.sources_file.path).resolve()
    if root not in child_path.parents:
        raise MarketSourcePackageError("MARKET_SOURCE_MANIFEST_INVALID")
    child_raw = _read_bounded(
        child_path,
        MAX_SOURCE_FILE_BYTES,
        prefix="MARKET_SOURCE_FILE",
    )
    if sha256(child_raw).hexdigest() != manifest.sources_file.sha256:
        raise MarketSourcePackageError("MARKET_SOURCE_FILE_HASH_INVALID")
    values = _json(child_raw, code="MARKET_SOURCE_PACKAGE_INVALID")
    try:
        package = MarketSourcePackage.model_validate(
            {"manifest": manifest.model_dump(mode="json"), "sources": values}
        )
    except ValidationError:
        raise MarketSourcePackageError("MARKET_SOURCE_PACKAGE_INVALID") from None
    stable_keys = tuple(source.stable_key for source in package.sources)
    if len(stable_keys) != len(set(stable_keys)):
        raise MarketSourcePackageError("MARKET_SOURCE_PACKAGE_INVALID")
    if any(
        source.policy_hash != source.policy_content_hash()
        for source in package.sources
    ):
        raise MarketSourcePackageError("MARKET_SOURCE_PACKAGE_INVALID")
    return package
