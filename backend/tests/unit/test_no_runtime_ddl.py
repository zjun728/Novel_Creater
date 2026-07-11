from pathlib import Path

from backend import database


def test_database_module_has_no_runtime_schema_mutator():
    assert not hasattr(database, "ensure_schema")


def test_database_module_contains_no_create_or_alter_statements():
    source = Path(database.__file__).read_text(encoding="utf-8").upper()
    assert "CREATE TABLE" not in source
    assert "ALTER TABLE" not in source
