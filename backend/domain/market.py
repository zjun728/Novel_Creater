"""Strict normalized public market snapshot values."""

from __future__ import annotations

import math
import re
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_MARKET_ENTRIES = 100
_METRIC_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _public_http_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("URL must be a string")
    value = value.strip()
    if not value or len(value) > 2_048:
        raise ValueError("URL is blank or too long")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be a public HTTP(S) URL")
    return value


class _MarketModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class MarketEntry(_MarketModel):
    """One exact public rank fact."""

    rank: int = Field(gt=0, le=MAX_MARKET_ENTRIES)
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=160)
    work_url: str = Field(alias="workURL", min_length=1, max_length=2_048)
    public_metrics: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        alias="publicMetrics",
    )

    @field_validator("work_url")
    @classmethod
    def validate_work_url(cls, value: str) -> str:
        return _public_http_url(value)

    @field_validator("public_metrics")
    @classmethod
    def validate_public_metrics(
        cls,
        value: dict[str, str | int | float | bool],
    ) -> dict[str, str | int | float | bool]:
        if len(value) > 32:
            raise ValueError("public metrics are unbounded")
        normalized: dict[str, str | int | float | bool] = {}
        for key, item in value.items():
            if _METRIC_KEY.fullmatch(key) is None:
                raise ValueError("public metric key is invalid")
            if isinstance(item, str):
                item = item.strip()
                if not item or len(item) > 200:
                    raise ValueError("public metric text is invalid")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("public metric number is invalid")
            normalized[key] = item
        return normalized


class MarketSnapshot(_MarketModel):
    """One complete, immutable normalized ranking capture."""

    platform: str = Field(min_length=1, max_length=120)
    ranking_name: str = Field(alias="rankingName", min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=160)
    captured_at: int = Field(alias="capturedAt", gt=0)
    source_url: str = Field(alias="sourceURL", min_length=1, max_length=2_048)
    entries: tuple[MarketEntry, ...] = Field(
        min_length=1,
        max_length=MAX_MARKET_ENTRIES,
    )

    @field_validator("entries", mode="before")
    @classmethod
    def freeze_entries(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _public_http_url(value)

    @model_validator(mode="after")
    def reject_duplicate_ranks(self) -> Self:
        ranks = tuple(entry.rank for entry in self.entries)
        if len(ranks) != len(set(ranks)):
            raise ValueError("snapshot ranks must be unique")
        return self


def snapshot_content_value(snapshot: MarketSnapshot) -> dict[str, object]:
    """Return the timestamp-free content identity used for immutable reuse."""

    return {
        "platform": snapshot.platform,
        "rankingName": snapshot.ranking_name,
        "category": snapshot.category,
        "sourceURL": snapshot.source_url,
        "entries": [
            entry.model_dump(mode="json", by_alias=True)
            for entry in snapshot.entries
        ],
    }
