from pathlib import Path

from backend import main


DELETED_ROUTERS = (
    "ai_proxy.py",
    "chapters.py",
    "control_plane_draft_writes.py",
    "novel.py",
    "experience_cards.py",
    "settings_library.py",
    "story_blocks.py",
    "volumes.py",
    "correction_tasks.py",
    "project_state.py",
    "provenance_support.py",
    "export.py",
    "market.py",
)

APPROVED_FORMAL_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/projects"),
    ("GET", "/api/projects/archived"),
    ("POST", "/api/projects"),
    ("GET", "/api/projects/{project_id}"),
    ("GET", "/api/projects/{project_id}/preparation"),
    ("PUT", "/api/projects/{project_id}"),
    ("POST", "/api/projects/{project_id}/archive"),
    ("POST", "/api/projects/{project_id}/restore"),
    ("DELETE", "/api/projects/{project_id}"),
    ("GET", "/api/providers"),
    ("POST", "/api/providers"),
    ("PUT", "/api/providers/{provider_id}"),
    ("DELETE", "/api/providers/{provider_id}"),
    ("POST", "/api/providers/{provider_id}/test-connection"),
    ("POST", "/api/providers/{provider_id}/clear-api-key"),
    ("GET", "/api/settings/application"),
    ("PUT", "/api/settings/application/default-model"),
    ("GET", "/api/settings/application/diagnostics"),
    ("GET", "/api/projects/{pid}/bindings"),
    ("GET", "/api/projects/{pid}/bindings/status"),
    ("PUT", "/api/projects/{pid}/bindings"),
    ("GET", "/api/projects/{pid}/seeds"),
    ("POST", "/api/projects/{pid}/seeds"),
    ("POST", "/api/projects/{pid}/seed-inspiration"),
    ("PUT", "/api/projects/{pid}/seeds/{seed_id}"),
    ("DELETE", "/api/projects/{pid}/seeds/{seed_id}"),
    ("POST", "/api/projects/{pid}/seeds/{seed_id}/archive"),
    ("POST", "/api/projects/{pid}/seeds/{seed_id}/restore"),
    ("GET", "/api/projects/{pid}/selected-seed"),
    ("PUT", "/api/projects/{pid}/selected-seed"),
    ("POST", "/api/projects/{pid}/story-engine-batches"),
    ("POST", "/api/projects/{pid}/story-engine-batches/manual"),
    ("GET", "/api/projects/{pid}/story-engine-batches/recoverable"),
    ("GET", "/api/projects/{pid}/story-engine-batches/{batch_id}"),
    ("POST", "/api/projects/{pid}/story-engine-batches/{batch_id}/reconcile"),
    ("POST", "/api/projects/{pid}/style-trials"),
    ("GET", "/api/projects/{pid}/contract-draft"),
    ("PUT", "/api/projects/{pid}/contract-draft"),
    ("POST", "/api/projects/{pid}/contracts/preview"),
    ("POST", "/api/projects/{pid}/contracts/{source_revision}/clone"),
    ("POST", "/api/projects/{pid}/contracts/confirm"),
    ("GET", "/api/projects/{pid}/contracts/head"),
    ("GET", "/api/projects/{pid}/contracts/history"),
    ("GET", "/api/projects/{pid}/bible/head"),
    ("GET", "/api/projects/{pid}/bible/draft"),
    ("PUT", "/api/projects/{pid}/bible/draft"),
    ("POST", "/api/projects/{pid}/bible/draft/clone"),
    ("POST", "/api/projects/{pid}/bible/confirm"),
    ("POST", "/api/projects/{pid}/bible/generate"),
    ("GET", "/api/projects/{pid}/bible/generation-attempts/{attemptId}"),
    ("GET", "/api/projects/{pid}/bible/history"),
    ("GET", "/api/projects/{pid}/bible/history/{revision}"),
    ("GET", "/api/projects/{pid}/planning"),
    ("GET", "/api/projects/{pid}/planning/history"),
    ("POST", "/api/projects/{pid}/planning/drafts"),
    ("PUT", "/api/projects/{pid}/planning/drafts/{draft_id}"),
    ("POST", "/api/projects/{pid}/planning/drafts/{draft_id}/confirm"),
    ("POST", "/api/projects/{pid}/planning/drafts/{draft_id}/generate"),
    ("GET", "/api/projects/{pid}/planning/operations/{operation_id}"),
    (
        "GET",
        "/api/projects/{pid}/planning/operations/"
        "by-idempotency-key/{idempotency_key}",
    ),
    ("GET", "/api/projects/{pid}/chapter-outlines/current"),
    (
        "GET",
        "/api/projects/{pid}/chapter-outlines/operations/"
        "by-key/{idempotency_key}",
    ),
    (
        "GET",
        "/api/projects/{pid}/chapter-outlines/operations/{operation_id}",
    ),
    (
        "GET",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}",
    ),
    (
        "GET",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}/history",
    ),
    (
        "POST",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}/drafts",
    ),
    (
        "PUT",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
        "{draft_id}",
    ),
    (
        "POST",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
        "{draft_id}/generate",
    ),
    (
        "POST",
        "/api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/"
        "{draft_id}/confirm",
    ),
    ("GET", "/api/projects/{pid}/chapter-sessions/{chapter_number}"),
    ("POST", "/api/projects/{pid}/chapter-sessions/{chapter_number}"),
    ("PUT", "/api/projects/{pid}/chapter-sessions/{session_id}/working-draft"),
    ("POST", "/api/projects/{pid}/chapter-sessions/{session_id}/candidates"),
    ("POST", "/api/projects/{pid}/chapter-sessions/{session_id}/draft-operations"),
    ("GET", "/api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}"),
    ("GET", "/api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/events"),
    ("GET", "/api/assets/style-templates"),
    ("GET", "/api/assets/style-templates/{revision_id}"),
    ("GET", "/api/assets/experience-cards"),
    ("GET", "/api/assets/experience-cards/{revision_id}"),
    ("GET", "/api/assets/inventory"),
    ("POST", "/api/projects/{pid}/asset-recommendations"),
    ("GET", "/api/corpus/discovery"),
    ("POST", "/api/corpus/imports"),
    ("GET", "/api/corpus/imports/{import_id}"),
    ("GET", "/api/corpus/sources"),
    ("GET", "/api/corpus/sources/{source_id}"),
    ("DELETE", "/api/corpus/sources/{source_id}"),
    ("GET", "/api/corpus/sources/{source_id}/versions"),
    ("POST", "/api/corpus/sources/{source_id}/archive"),
    ("POST", "/api/corpus/sources/{source_id}/restore"),
    ("GET", "/api/corpus/sources/{source_id}/chapters"),
    ("GET", "/api/corpus/chapters/{chapter_id}/fragments"),
    ("GET", "/api/market-sources"),
    ("GET", "/api/market-sources/{source_id}"),
    ("GET", "/api/market-sources/{source_id}/snapshots"),
    ("GET", "/api/market-sources/{source_id}/snapshots/{snapshot_id}"),
    ("POST", "/api/market-sources/{source_id}/manual-import"),
    ("POST", "/api/market-sources/{source_id}/refresh"),
    ("PUT", "/api/market-sources/{source_id}/schedule"),
    ("POST", "/api/projects/{project_id}/market-analyses"),
    ("GET", "/api/projects/{project_id}/market-analyses/{analysis_id}"),
    ("GET", "/api/projects/{project_id}/writer-core/state"),
    ("GET", "/api/projects/{project_id}/canon/head"),
    ("GET", "/api/projects/{project_id}/canon/revisions"),
    ("GET", "/api/projects/{project_id}/canon/entities"),
    ("GET", "/api/projects/{project_id}/canon/entities/{entity_id}"),
    ("GET", "/api/projects/{project_id}/canon/events"),
    ("GET", "/api/projects/{project_id}/canon/aliases/resolve"),
    ("GET", "/api/projects/{project_id}/projections/head"),
    ("GET", "/api/projects/{project_id}/projections/current-state"),
    ("GET", "/api/projects/{project_id}/projections/memories"),
    ("GET", "/api/projects/{project_id}/projections/arcs"),
    ("GET", "/api/projects/{project_id}/projections/plot-threads"),
}

FORBIDDEN_LEGACY_PREFIXES = (
    "/api/ai/",
    "/api/market/",
    "/api/experience-cards",
    "/api/planning",
    "/api/drafts",
    "/api/writer",
    "/api/Writer",
    "/api/finalization",
    "/api/chapters",
    "/api/novel",
    "/api/export",
    "/api/volumes",
    "/api/story-blocks",
    "/api/correction",
    "/api/project-state",
)

FORBIDDEN_LEGACY_PATHS = {
    "/api/market",
}


def _api_methods_and_paths():
    return {
        (method, route.path)
        for route in main.app.routes
        if route.path.startswith("/api/")
        for method in route.methods
    }


def test_main_registers_exact_formal_route_inventory():
    assert _api_methods_and_paths() == APPROVED_FORMAL_ROUTES


def test_forbidden_legacy_route_prefixes_remain_absent():
    paths = {path for _, path in _api_methods_and_paths()}
    assert paths.isdisjoint(FORBIDDEN_LEGACY_PATHS)
    assert not {
        path
        for path in paths
        if path.startswith(FORBIDDEN_LEGACY_PREFIXES)
    }


def test_only_approved_seed_paths_write_and_canon_remains_read_only():
    seed_routes = [
        route
        for route in main.app.routes
        if "/seeds" in route.path or "/selected-seed" in route.path
    ]
    seed_methods = {}
    for route in seed_routes:
        seed_methods.setdefault(route.path, set()).update(route.methods)
    assert seed_methods == {
        "/api/projects/{pid}/seeds": {"GET", "POST"},
        "/api/projects/{pid}/seeds/{seed_id}": {"PUT", "DELETE"},
        "/api/projects/{pid}/seeds/{seed_id}/archive": {"POST"},
        "/api/projects/{pid}/seeds/{seed_id}/restore": {"POST"},
        "/api/projects/{pid}/selected-seed": {"GET", "PUT"},
    }

    canon_routes = [
        route
        for route in main.app.routes
        if "/canon/" in route.path or "/projections/" in route.path
    ]
    assert canon_routes
    assert all(route.methods <= {"GET", "HEAD"} for route in canon_routes)


def test_incompatible_router_files_are_physically_absent():
    router_dir = Path(main.__file__).with_name("routers")
    assert not [name for name in DELETED_ROUTERS if (router_dir / name).exists()]
