"""The migration mutates only a fixture-owned schema via the existing logical adapter."""
import pytest
from backend.scripts import upgrade_product_database_v116 as upgrade
from backend.scripts.upgrade_product_database_v115 import v115_statements
from backend.services.product_database_inventory import inventory_database
from backend.tests.integration.test_product_database_readiness_mysql import _LogicalDatabaseSession

pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]

async def test_incremental_upgrade_preserves_all_previous_tables(empty_disposable_mysql):
    db = empty_disposable_mysql
    for statement in v115_statements(): await db.session.execute(statement)
    await db.session.execute('INSERT INTO schema_metadata VALUES (1,%s,%s,1)', (upgrade.V115_SCHEMA_VERSION,upgrade.V115_MANIFEST_HASH))
    await db.session.execute("INSERT INTO projects (id,title,genre,description,target_words,target_chapters,status,created_at,updated_at) VALUES ('91000000-0000-0000-0000-000000000001','Author project','fantasy','preserve',120000,10,'drafting',1,1)")
    original = await db.session.fetchone("SELECT * FROM projects WHERE id='91000000-0000-0000-0000-000000000001'")
    session = _LogicalDatabaseSession(db.session, db.database_name, upgrade.PRODUCT_DATABASE)
    before = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    result = await upgrade.upgrade_v115_to_v116(session,database=upgrade.PRODUCT_DATABASE,confirm_database=upgrade.PRODUCT_DATABASE,now_ms=2)
    after = await inventory_database(session, upgrade.PRODUCT_DATABASE)
    assert result.added_tables == 1
    assert after.structural_fingerprint == upgrade.V116_STRUCTURAL_FINGERPRINT
    assert after.row_counts == tuple(sorted((*before.row_counts, ('review_finding_decisions',0))))
    assert await db.session.fetchone("SELECT * FROM projects WHERE id='91000000-0000-0000-0000-000000000001'") == original
