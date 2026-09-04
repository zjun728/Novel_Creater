"""Strict normalized JSON adapter for author-supplied public snapshots."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from backend.domain.market import MarketSnapshot, _public_http_url
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
    "fanqie_manual_snapshot": (
        "https",
        "fanqienovel.com",
        re.compile(r"/page/[1-9][0-9]*"),
    ),
    "fanqie_public_rank": (
        "https",
        "fanqienovel.com",
        re.compile(r"/page/[1-9][0-9]*"),
    ),
    "qimao_manual_snapshot": (
        "https",
        "www.qimao.com",
        re.compile(r"/shuku/[1-9][0-9]*(?:-[1-9][0-9]*)?/"),
    ),
    "qimao_public_rank": (
        "https",
        "www.qimao.com",
        re.compile(r"/shuku/[1-9][0-9]*/"),
    ),
    "shuqi_manual_snapshot": (
        "https",
        "www.shuqi.com",
        re.compile(r"/book/[1-9][0-9]*\.html"),
    ),
    "17k_public_rank": (
        "https",
        "www.17k.com",
        re.compile(r"/book/[1-9][0-9]*\.html"),
    ),
    "hongxiu_public_rank": (
        "https",
        "www.hongxiu.com",
        re.compile(r"/book/[1-9][0-9]*\.html"),
    ),
    "zongheng_public_rank": (
        "https",
        "www.zongheng.com",
        re.compile(r"/detail/[1-9][0-9]*"),
    ),
    "jjwxc_public_rank": (
        "https",
        "www.jjwxc.net",
        re.compile(r"/onebook\.php"),
    ),
    "heiyan_public_rank": (
        "https",
        "www.heiyan.com",
        re.compile(r"/book/[1-9][0-9]*"),
    ),
    "readnovel_public_rank": (
        "https",
        "www.readnovel.com",
        re.compile(r"/book/[1-9][0-9]*"),
    ),
    "xxsy_public_rank": (
        "https",
        "www.xxsy.net",
        re.compile(r"/book/[1-9][0-9]*"),
    ),
}
_QUERY_RULES = {
    "jjwxc_public_rank": re.compile(r"novelid=[1-9][0-9]*"),
}


def work_url_is_canonical(url: str, adapter_key: str) -> bool:
    rule = _WORK_URL_RULES.get(adapter_key)
    if rule is None:
        return False
    scheme, netloc, path_pattern = rule
    try:
        url = _public_http_url(url)
        parsed = urlsplit(url)
    except ValueError:
        return False
    query_pattern = _QUERY_RULES.get(adapter_key)
    query_valid = bool(
        query_pattern.fullmatch(parsed.query)
        if query_pattern is not None
        else not parsed.query
    )
    return bool(
        parsed.scheme == scheme
        and parsed.netloc == netloc
        and parsed.username is None
        and parsed.password is None
        and query_valid
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
            not work_url_is_canonical(entry.work_url, adapter_key)
            for entry in snapshot.entries
        ):
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID")
        return snapshot
