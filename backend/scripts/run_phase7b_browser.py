"""Own and finalize the standalone Phase 7B browser sandbox."""

from __future__ import annotations

import os
import sys

from backend.domain.json_contracts import canonical_json
from backend.scripts.prepare_product_database import (
    _BROWSER_NODE_COMMAND,
    _BROWSER_SMOKE_PREFIX,
    _BROWSER_SMOKE_TIMEOUT_SECONDS,
    REPOSITORY_ROOT,
    _default_browser_smoke_runner,
    _open_browser_root_lease,
    run_owned_phase7b_browser,
)


_FAILURE_LINE = "phase7b browser smoke failed"


def _run() -> dict[str, object]:
    return run_owned_phase7b_browser(
        node_command=_BROWSER_NODE_COMMAND,
        cwd=REPOSITORY_ROOT,
        environment=dict(os.environ),
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
    except BaseException:
        print(_FAILURE_LINE, file=sys.stderr)
        return 1
    print(_BROWSER_SMOKE_PREFIX + canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
