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


def test_seed_and_canon_paths_have_no_write_methods():
    relevant = [
        route
        for route in main.app.routes
        if "/seeds" in route.path
        or "/canon/" in route.path
        or "/projections/" in route.path
    ]
    assert relevant
    assert all(route.methods <= {"GET", "HEAD"} for route in relevant)


def test_incompatible_router_files_are_physically_absent():
    router_dir = Path(main.__file__).with_name("routers")
    assert not [name for name in DELETED_ROUTERS if (router_dir / name).exists()]
