"""Strict normalized JSON adapter for author-supplied public snapshots."""

from __future__ import annotations

import json

from pydantic import ValidationError

from backend.domain.market import MarketSnapshot
from backend.domain.market_sources import MarketSourceFailure


MAX_MANUAL_SNAPSHOT_BYTES = 256 * 1024


class ManualSnapshotAdapter:
    adapter_version = "manual-snapshot-v1"

    def parse(self, payload: object) -> MarketSnapshot:
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
            return MarketSnapshot.model_validate(values)
        except ValidationError:
            raise MarketSourceFailure("MARKET_MANUAL_SNAPSHOT_INVALID") from None
