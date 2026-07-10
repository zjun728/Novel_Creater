from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[3]
APPLY = ROOT / "backend" / "migrations" / "20260710_control_plane_draft_write_batches.sql"
ROLLBACK = ROOT / "backend" / "migrations" / "20260710_control_plane_draft_write_batches_rollback.sql"


class DraftWriteMigrationTest(unittest.TestCase):
    def test_apply_creates_only_the_control_ledger_with_exact_binary_identity(self):
        sql = APPLY.read_text(encoding="utf-8")
        lowered = sql.lower()
        self.assertEqual(len(re.findall(r"\bcreate\s+table\s+draft_write_batches\b", lowered)), 1)
        self.assertEqual(len(re.findall(r"\bcreate\s+table\b", lowered)), 1)
        self.assertIn("id char(36) not null", lowered)
        self.assertIn("project_id char(36) not null", lowered)
        self.assertIn("idempotency_key varbinary(120) not null", lowered)
        self.assertIn("manifest_sha256 char(64) character set ascii collate ascii_bin not null", lowered)
        self.assertIn("result_json json default null", lowered)
        self.assertIn("created_at bigint not null", lowered)
        self.assertIn("committed_at bigint default null", lowered)
        self.assertRegex(
            lowered,
            r"unique\s+key\s+uniq_draft_write_batches_project_key\s*\(\s*project_id\s*,\s*idempotency_key\s*\)",
        )
        for forbidden in ["if not exists", "create database", "use ", "alter table"]:
            self.assertNotIn(forbidden, lowered)

    def test_rollback_drops_exactly_the_control_ledger(self):
        normalized = " ".join(ROLLBACK.read_text(encoding="utf-8").split())
        self.assertEqual(normalized, "DROP TABLE draft_write_batches;")

    def test_product_startup_files_do_not_mention_the_ledger_or_router(self):
        for relative in ["backend/schema.sql", "backend/database.py", "backend/main.py"]:
            with self.subTest(relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("draft_write_batches", text)
                self.assertNotIn("control_plane_draft_writes", text)


if __name__ == "__main__":
    unittest.main()
