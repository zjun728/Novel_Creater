from pathlib import Path

from backend import main


DELETED_ROUTERS = (
    "chapters.py",
    "novel.py",
    "settings_library.py",
    "story_blocks.py",
    "volumes.py",
    "correction_tasks.py",
    "project_state.py",
    "provenance_support.py",
    "export.py",
)

APPROVED_M2_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    ("GET", "/api/projects/{pid}"),
    ("GET", "/api/projects/{pid}/content-state"),
    ("PUT", "/api/projects/{pid}"),
    ("DELETE", "/api/projects/{pid}"),
    ("GET", "/api/providers"),
    ("POST", "/api/providers"),
    ("PUT", "/api/providers/{provider_id}"),
    ("DELETE", "/api/providers/{provider_id}"),
    ("GET", "/api/projects/{pid}/bindings"),
    ("GET", "/api/projects/{pid}/bindings/status"),
    ("PUT", "/api/projects/{pid}/bindings"),
    ("GET", "/api/projects/{pid}/seeds"),
    ("POST", "/api/projects/{pid}/seeds"),
    ("PUT", "/api/projects/{pid}/seeds/{seed_id}"),
    ("DELETE", "/api/projects/{pid}/seeds/{seed_id}"),
    ("GET", "/api/projects/{pid}/selected-seed"),
    ("PUT", "/api/projects/{pid}/selected-seed"),
    ("POST", "/api/projects/{pid}/story-engine-batches"),
    ("POST", "/api/projects/{pid}/story-engine-batches/manual"),
    ("GET", "/api/projects/{pid}/story-engine-batches/recoverable"),
    ("GET", "/api/projects/{pid}/story-engine-batches/{batch_id}"),
    ("POST", "/api/projects/{pid}/story-engine-batches/{batch_id}/reconcile"),
    ("GET", "/api/projects/{pid}/contract-draft"),
    ("PUT", "/api/projects/{pid}/contract-draft"),
    ("POST", "/api/projects/{pid}/contracts/preview"),
    ("POST", "/api/projects/{pid}/contracts/clone"),
    ("POST", "/api/projects/{pid}/contracts/confirm"),
    ("GET", "/api/projects/{pid}/contracts/head"),
    ("GET", "/api/projects/{pid}/contracts/history"),
    ("GET", "/api/assets/style-templates"),
    ("GET", "/api/assets/style-templates/{revision_id}"),
    ("GET", "/api/assets/experience-cards"),
    ("GET", "/api/assets/experience-cards/{revision_id}"),
    ("GET", "/api/projects/{pid}/asset-recommendations"),
    ("GET", "/api/corpus/discovery"),
    ("POST", "/api/corpus/imports"),
    ("GET", "/api/corpus/imports/{import_id}"),
    ("GET", "/api/corpus/sources"),
    ("GET", "/api/corpus/sources/{source_id}"),
    ("GET", "/api/corpus/sources/{source_id}/chapters"),
    ("GET", "/api/corpus/chapters/{chapter_id}/fragments"),
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
    "/api/market",
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


def _api_methods_and_paths():
    return {
        (method, route.path)
        for route in main.app.routes
        if route.path.startswith("/api/")
        for method in route.methods
    }


def test_main_registers_exact_frozen_m2_route_inventory():
    assert _api_methods_and_paths() == APPROVED_M2_ROUTES


def test_forbidden_legacy_route_prefixes_remain_absent():
    paths = {path for _, path in _api_methods_and_paths()}
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
