from __future__ import annotations

import json
from typing import Any

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.project_lifecycle import lock_active_project


class PlanningRepository:
    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_contract_head(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_contract_heads WHERE project_id=%s",
            (project_id,),
        )

    async def read_creation_contract(self, session, creation_contract_id: str):
        return await session.fetchone(
            "SELECT * FROM creation_contracts WHERE id=%s",
            (creation_contract_id,),
        )

    async def read_bible_head(self, session, project_id: str):
        return await session.fetchone(
            """SELECT head.revision,head.bible_revision_id,head.content_hash,
                      bible.selection_revision,bible.contract_revision,
                      bible.contract_hash
               FROM project_bible_heads head
               LEFT JOIN creation_bible_revisions bible
                 ON bible.project_id=head.project_id
                AND bible.id=head.bible_revision_id
               WHERE head.project_id=%s""",
            (project_id,),
        )

    async def read_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id,selected.seed_revision_id,
                      selected.seed_hash,selected.selection_revision,
                      revision.payload_json
               FROM project_selected_seeds selected
               JOIN creative_seed_revisions revision
                 ON revision.project_id=selected.project_id
                AND revision.id=selected.seed_revision_id
               WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def read_current_plan(self, session, project_id: str):
        volume = await session.fetchone(
            """SELECT volume.*
               FROM volume_plans volume
               JOIN project_selected_seeds selected
                 ON selected.project_id=volume.project_id
                AND selected.selection_revision=volume.selection_revision
               JOIN project_contract_heads contract_head
                 ON contract_head.project_id=volume.project_id
                AND contract_head.revision=volume.contract_revision
                AND contract_head.creation_hash=volume.contract_hash
               JOIN creation_contracts current_contract
                 ON current_contract.project_id=contract_head.project_id
                AND current_contract.id=contract_head.creation_contract_id
                AND current_contract.selection_revision=volume.selection_revision
                AND current_contract.revision=volume.contract_revision
                AND current_contract.content_hash=volume.contract_hash
               JOIN project_bible_heads bible_head
                 ON bible_head.project_id=volume.project_id
                AND bible_head.revision=volume.bible_revision
                AND bible_head.content_hash=volume.bible_hash
               JOIN creation_bible_revisions current_bible
                 ON current_bible.project_id=bible_head.project_id
                AND current_bible.id=bible_head.bible_revision_id
                AND current_bible.selection_revision=volume.selection_revision
                AND current_bible.contract_revision=volume.contract_revision
                AND current_bible.contract_hash=volume.contract_hash
                AND current_bible.revision=volume.bible_revision
                AND current_bible.content_hash=volume.bible_hash
               WHERE volume.project_id=%s AND volume.status='active'
               ORDER BY volume.volume_num LIMIT 1""",
            (project_id,),
        )
        if volume is None:
            return None
        block = await session.fetchone(
            """SELECT * FROM story_blocks
               WHERE project_id=%s AND volume_plan_id=%s AND status='active'
               ORDER BY block_num LIMIT 1""",
            (project_id, volume["id"]),
        )
        if block is None:
            return None
        stages = await session.fetchall(
            """SELECT * FROM story_stages
               WHERE project_id=%s AND story_block_id=%s
                 AND status IN ('pending','in_progress','completed')
               ORDER BY stage_order""",
            (project_id, block["id"]),
        )
        stage_ids = tuple(stage["id"] for stage in stages)
        tasks = []
        if stage_ids:
            placeholders = ",".join(["%s"] * len(stage_ids))
            tasks = await session.fetchall(
                f"""SELECT * FROM scene_tasks
                    WHERE project_id=%s AND story_stage_id IN ({placeholders})
                      AND status IN ('pending','in_progress','completed')
                    ORDER BY FIELD(story_stage_id,{placeholders}), task_order""",
                (project_id, *stage_ids, *stage_ids),
            )
        bundle = {
            "volume": self._volume(volume),
            "block": self._block(block),
            "stages": tuple(self._stage(row) for row in stages),
            "scene_tasks": tuple(self._task(row) for row in tasks),
        }
        bundle.update({
            "selection_revision": int(volume["selection_revision"]),
            "contract_revision": int(volume["contract_revision"]),
            "contract_hash": volume["contract_hash"],
            "bible_revision": int(volume["bible_revision"]),
            "bible_hash": volume["bible_hash"],
            "manifest_hash": volume["manifest_hash"],
        })
        return bundle

    async def insert_initial_plan(self, session, bundle: dict[str, Any]) -> bool:
        volume = bundle["volume"]
        block = bundle["block"]
        if await session.execute(
            """INSERT INTO volume_plans
               (id,project_id,selection_revision,contract_revision,contract_hash,
                bible_revision,bible_hash,manifest_hash,volume_num,title,
                direction_json,revision,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                volume["id"], volume["project_id"],
                volume["selection_revision"], volume["contract_revision"],
                volume["contract_hash"], volume["bible_revision"],
                volume["bible_hash"], volume["manifest_hash"],
                volume["volume_num"], volume["title"],
                canonical_json(volume["payload"]),
                volume["revision"], volume["status"],
                volume["created_at"], volume["updated_at"],
            ),
        ) != 1:
            return False
        if await session.execute(
            """INSERT INTO story_blocks
               (id,project_id,volume_plan_id,block_num,title,goal_json,revision,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                block["id"], block["project_id"], block["volume_plan_id"],
                block["block_num"], block["title"], canonical_json(block["payload"]),
                block["revision"], block["status"],
                block["created_at"], block["updated_at"],
            ),
        ) != 1:
            return False
        for stage in bundle["stages"]:
            if await session.execute(
                """INSERT INTO story_stages
                   (id,project_id,story_block_id,stage_order,title,plan_json,revision,status,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    stage["id"], stage["project_id"], stage["story_block_id"],
                    stage["stage_order"], stage["title"], canonical_json(stage["payload"]),
                    stage["revision"], stage["status"],
                    stage["created_at"], stage["updated_at"],
                ),
            ) != 1:
                return False
        for task in bundle["scene_tasks"]:
            if await session.execute(
                """INSERT INTO scene_tasks
                   (id,project_id,story_stage_id,task_order,task_json,revision,status,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    task["id"], task["project_id"], task["story_stage_id"],
                    task["task_order"], canonical_json(task["payload"]),
                    task["revision"], task["status"],
                    task["created_at"], task["updated_at"],
                ),
            ) != 1:
                return False
        return True

    def _contract_revision(self, head) -> int:
        return int((head or {}).get("revision") or 0)

    def _json(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        return {}

    def _volume(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "selection_revision": row["selection_revision"],
            "contract_revision": row["contract_revision"],
            "contract_hash": row["contract_hash"],
            "bible_revision": row["bible_revision"],
            "bible_hash": row["bible_hash"],
            "manifest_hash": row["manifest_hash"],
            "volume_num": row["volume_num"], "title": row["title"],
            "payload": self._json(row["direction_json"]),
            "revision": row["revision"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _block(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "volume_plan_id": row["volume_plan_id"],
            "block_num": row["block_num"], "title": row["title"],
            "payload": self._json(row["goal_json"]),
            "revision": row["revision"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _stage(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "story_block_id": row["story_block_id"],
            "stage_order": row["stage_order"], "title": row["title"],
            "payload": self._json(row["plan_json"]),
            "revision": row["revision"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _task(self, row):
        return {
            "id": row["id"], "project_id": row["project_id"],
            "story_stage_id": row["story_stage_id"],
            "task_order": row["task_order"],
            "payload": self._json(row["task_json"]),
            "revision": row["revision"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
