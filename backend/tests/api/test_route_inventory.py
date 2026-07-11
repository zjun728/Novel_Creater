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


def test_main_registers_only_m1_product_routes():
    paths = {
        route.path
        for route in main.app.routes
        if route.path.startswith("/api/")
    }
    assert "/api/health" in paths
    assert "/api/projects" in paths
    assert "/api/providers" in paths
    assert "/api/projects/{pid}/seeds" in paths
    assert "/api/projects/{project_id}/writer-core/state" in paths
    banned_fragments = (
        "/chapters",
        "/novel",
        "/market",
        "/experience-cards",
        "/export",
        "/volumes",
        "/story-blocks",
        "/correction",
        "/project-state",
        "/ai/",
    )
    assert not {
        path
        for path in paths
        if any(fragment in path for fragment in banned_fragments)
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
