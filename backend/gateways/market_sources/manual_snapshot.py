"""Strict normalized JSON adapter for author-supplied public snapshots."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from backend.domain.market import MarketSnapshot
from backend.domain.market_sources import MarketSourceFailure


MAX_MANUAL_SNAPSHOT_BYTES = 256 * 1024
_WORK_URL_RULES = {
    "qidian_public_rank": (
        "https",
        "www.qidian.com",
        re.compile(r"/book/[1-9][0-9]*/"),
    ),
    "qq_reading_public_rank": (
        "https",
        "book.qq.com",
        re.compile(r"/book-detail/[1-9][0-9]*"),
    ),
}


def _work_url_is_canonical(url: str, adapter_key: str) -> bool:
    rule = _WORK_URL_RULES.get(adapter_key)
    if rule is None:
        return False
    scheme, netloc, path_pattern = rule
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return bool(
        parsed.scheme == scheme
        and parsed.netloc == netloc
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and path_pattern.fullmatch(parsed.path)
    )


class ManualSnapshotAdapter:
    adapter_version = "manual-snapshot-v1"

    def parse(
        self,
        payload: object,
        *,
        adapter_key: str | None = None,
    ) -> MarketSnapshot:
        values = payload
        if isinstance(payload, bytes):
            if len(payload) > MAX_MANUAL_SNAPSHOT_BYTES:
                raise MarketSourceFailure("MARKET_BODY_TOO_LARGE")
            try:
                values = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
        elif isinstance(payload, str):
            encoded = payload.encode("utf-8")
            if len(encoded) > MAX_MANUAL_SNAPSHOT_BYTES:
                raise MarketSourceFailure("MARKET_BODY_TOO_LARGE")
            try:
                values = json.loads(payload)
            except json.JSONDecodeError:
                raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
        else:
            try:
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError):
                raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
            if len(encoded) > MAX_MANUAL_SNAPSHOT_BYTES:
                raise MarketSourceFailure("MARKET_BODY_TOO_LARGE")
        try:
            snapshot = MarketSnapshot.model_validate(values)
        except ValidationError:
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
        if adapter_key is not None and any(
            not _work_url_is_canonical(entry.work_url, adapter_key)
            for entry in snapshot.entries
        ):
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID")
        return snapshot
