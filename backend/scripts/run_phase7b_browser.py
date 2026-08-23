"""Own and finalize the standalone Phase 7B browser sandbox."""

from __future__ import annotations

import os
import sys

from backend.domain.json_contracts import canonical_json
from backend.domain.product_database_readiness import LEGACY_DATABASE, NEW_DATABASE
from backend.scripts.configure_local_mysql import LOCAL_CONFIG_PATH
from backend.scripts.cutover_product_database import read_local_document
from backend.scripts.prepare_product_database import (
    _BROWSER_NODE_COMMAND,
    _BROWSER_SMOKE_EXPECTED,
    _BROWSER_SMOKE_PREFIX,
    _BROWSER_SMOKE_TIMEOUT_SECONDS,
    REPOSITORY_ROOT,
    _default_browser_smoke_runner,
    _is_exact_browser_record,
    _open_browser_root_lease,
    run_owned_phase7b_browser,
)


_FAILURE_LINE = "phase7b browser smoke failed"
_MYSQL_KEYS = (
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
)


def _run() -> dict[str, object]:
    environment = dict(os.environ)
    configured_database = read_local_document(LOCAL_CONFIG_PATH).get("MYSQL_DB")
    if configured_database == LEGACY_DATABASE:
        environment["MYSQL_DB"] = NEW_DATABASE
    elif configured_database == NEW_DATABASE:
        for name in _MYSQL_KEYS:
            environment.pop(name, None)
    else:
        raise ValueError
    environment["MARKET_SCHEDULER_ENABLED"] = "false"
    return run_owned_phase7b_browser(
        node_command=_BROWSER_NODE_COMMAND,
        cwd=REPOSITORY_ROOT,
        environment=environment,
        timeout_seconds=_BROWSER_SMOKE_TIMEOUT_SECONDS,
        runner=_default_browser_smoke_runner,
        root_factory=_open_browser_root_lease,
    )


def main() -> int:
    if len(sys.argv) != 1:
        print(_FAILURE_LINE, file=sys.stderr)
        return 1
    try:
        summary = _run()
        if not _is_exact_browser_record(summary, _BROWSER_SMOKE_EXPECTED):
            raise ValueError
    except BaseException:
        print(_FAILURE_LINE, file=sys.stderr)
        return 1
    print(_BROWSER_SMOKE_PREFIX + canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
