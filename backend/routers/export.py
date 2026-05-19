"""Full project import/export."""
from fastapi import APIRouter, HTTPException
from database import fetchall, execute
from .helpers import convert_rows, to_snake
import uuid
import time
import json

router = APIRouter(tags=["export"])

MODEL_ID_KEYS = [
    "writingModelId",
    "brainstormModelId",
    "outlineModelId",
    "auditModelId",
    "summaryModelId",
    "extractionModelId",
    "marketModelId",
    "polishModelId",
]


@router.post("/export/full")
async def export_full(projectId: str = "", includeApiKeys: bool = False):
    providers = convert_rows(await fetchall("SELECT * FROM provider_profiles"))
    if not includeApiKeys:
        for provider in providers:
            provider["apiKey"] = ""

    result = {
        "version": "1.0",
        "exportedAt": int(time.time() * 1000),
        "providers": providers,
        "projects": []
    }

    if projectId:
        project_rows = await fetchall("SELECT * FROM projects WHERE id=%s", (projectId,))
    else:
        project_rows = await fetchall("SELECT * FROM projects ORDER BY created_at")

    for proj in project_rows:
        pid = proj["id"]
        result["projects"].append({
            "project": _convert_one(proj),
            "chapters": _convert(await fetchall("SELECT * FROM chapters WHERE project_id=%s", (pid,))),
            "chapterVersions": _convert(await fetchall("SELECT * FROM chapter_versions WHERE project_id=%s", (pid,))),
            "creativeSeeds": _convert(await fetchall("SELECT * FROM creative_seeds WHERE project_id=%s", (pid,))),
            "bible": _convert(await fetchall("SELECT * FROM creative_bible WHERE project_id=%s", (pid,)))[:1],
            "characters": _convert(await fetchall("SELECT * FROM characters WHERE project_id=%s", (pid,))),
            "plotThreads": _convert(await fetchall("SELECT * FROM plot_threads WHERE project_id=%s", (pid,))),
            "outlines": _convert(await fetchall("SELECT * FROM rolling_outlines WHERE project_id=%s", (pid,)))[:1],
            "projectVolumes": _convert(await fetchall("SELECT * FROM project_volumes WHERE project_id=%s", (pid,))),
            "projectAuditReports": _convert(await fetchall("SELECT * FROM project_audit_reports WHERE project_id=%s", (pid,))),
            "correctionTasks": _convert(await fetchall("SELECT * FROM correction_tasks WHERE project_id=%s", (pid,))),
            "canonFacts": _convert(await fetchall("SELECT * FROM canon_facts WHERE project_id=%s", (pid,))),
            "possibilityCards": _convert(await fetchall("SELECT * FROM possibility_cards WHERE project_id=%s", (pid,))),
            "marketItems": _convert(await fetchall("SELECT * FROM market_items WHERE project_id=%s", (pid,))),
            "marketChatMessages": _convert(await fetchall("SELECT * FROM market_chat_messages WHERE project_id=%s", (pid,))),
            "marketDirectionReports": _convert(await fetchall("SELECT * FROM market_direction_reports WHERE project_id=%s", (pid,))),
            "settingEntities": _convert(await fetchall("SELECT * FROM setting_entities WHERE project_id=%s", (pid,))),
            "settingRelations": _convert(await fetchall("SELECT * FROM setting_relations WHERE project_id=%s", (pid,))),
            "settingChangeEvents": _convert(await fetchall("SELECT * FROM setting_change_events WHERE project_id=%s", (pid,))),
            "tempDrafts": _convert(await fetchall("SELECT * FROM temp_drafts WHERE project_id=%s", (pid,))),
            "bindings": _convert(await fetchall("SELECT * FROM task_model_bindings WHERE project_id=%s", (pid,))),
        })

    return result


@router.post("/import/full")
async def import_full(data: dict):
    provider_id_map = {}
    imported_projects = 0

    try:
        for provider in data.get("providers", []):
            old_provider_id = provider.get("id", "")
            new_provider_id = str(uuid.uuid4())
            if old_provider_id:
                provider_id_map[old_provider_id] = new_provider_id
            provider["id"] = new_provider_id
            provider["apiKey"] = provider.get("apiKey") or ""
            await _insert("provider_profiles", provider)

        for proj_data in data.get("projects", []):
            proj = proj_data.get("project", {})
            old_project_id = proj.get("id", "")
            new_project_id = str(uuid.uuid4())
            id_map = {old_project_id: new_project_id} if old_project_id else {}
            setting_entity_id_map = {}
            pending_final_versions = []

            proj["id"] = new_project_id
            await _insert("projects", proj)

            for chapter in proj_data.get("chapters", []):
                old_chapter_id = chapter.get("id", "")
                old_final_version_id = _get_key(chapter, "finalVersionId")
                new_chapter_id = str(uuid.uuid4())
                if old_chapter_id:
                    id_map[old_chapter_id] = new_chapter_id

                chapter["id"] = new_chapter_id
                _put_key(chapter, "projectId", new_project_id)
                _put_key(chapter, "finalVersionId", None)
                if old_final_version_id:
                    pending_final_versions.append((new_chapter_id, old_final_version_id))
                await _insert("chapters", chapter)

            for version in proj_data.get("chapterVersions", []):
                old_version_id = version.get("id", "")
                new_version_id = str(uuid.uuid4())
                if old_version_id:
                    id_map[old_version_id] = new_version_id

                version["id"] = new_version_id
                _put_key(version, "projectId", new_project_id)
                old_chapter_id = _get_key(version, "chapterId")
                if old_chapter_id in id_map:
                    _put_key(version, "chapterId", id_map[old_chapter_id])

                old_model_id = _get_key(version, "sourceModelId")
                if old_model_id in provider_id_map:
                    _put_key(version, "sourceModelId", provider_id_map[old_model_id])
                await _insert("chapter_versions", version)

            for new_chapter_id, old_final_version_id in pending_final_versions:
                new_final_version_id = id_map.get(old_final_version_id)
                if new_final_version_id:
                    await execute(
                        "UPDATE chapters SET final_version_id=%s WHERE id=%s",
                        (new_final_version_id, new_chapter_id),
                    )

            for seed in proj_data.get("creativeSeeds", []):
                seed["id"] = str(uuid.uuid4())
                _put_key(seed, "projectId", new_project_id)
                await _insert("creative_seeds", seed)

            for bible in (proj_data.get("bible") or []):
                bible["id"] = str(uuid.uuid4())
                _put_key(bible, "projectId", new_project_id)
                await _insert("creative_bible", bible)

            for character in proj_data.get("characters", []):
                character["id"] = str(uuid.uuid4())
                _put_key(character, "projectId", new_project_id)
                await _insert("characters", character)

            for thread in proj_data.get("plotThreads", []):
                thread["id"] = str(uuid.uuid4())
                _put_key(thread, "projectId", new_project_id)
                await _insert("plot_threads", thread)

            for outline in (proj_data.get("outlines") or []):
                outline["id"] = str(uuid.uuid4())
                _put_key(outline, "projectId", new_project_id)
                await _insert("rolling_outlines", outline)

            for volume in proj_data.get("projectVolumes", []):
                volume["id"] = str(uuid.uuid4())
                _put_key(volume, "projectId", new_project_id)
                await _insert("project_volumes", volume)

            for report in proj_data.get("projectAuditReports", []):
                report["id"] = str(uuid.uuid4())
                _put_key(report, "projectId", new_project_id)
                await _insert("project_audit_reports", report)

            for task in proj_data.get("correctionTasks", []):
                task["id"] = str(uuid.uuid4())
                _put_key(task, "projectId", new_project_id)
                await _insert("correction_tasks", task)

            for fact in proj_data.get("canonFacts", []):
                fact["id"] = str(uuid.uuid4())
                _put_key(fact, "projectId", new_project_id)
                await _insert("canon_facts", fact)

            for card in proj_data.get("possibilityCards", []):
                card["id"] = str(uuid.uuid4())
                _put_key(card, "projectId", new_project_id)
                await _insert("possibility_cards", card)

            for item in proj_data.get("marketItems", []):
                item["id"] = str(uuid.uuid4())
                _put_key(item, "projectId", new_project_id)
                await _insert("market_items", item)

            for chat_message in proj_data.get("marketChatMessages", []):
                chat_message["id"] = str(uuid.uuid4())
                _put_key(chat_message, "projectId", new_project_id)
                await _insert("market_chat_messages", chat_message)

            for report in proj_data.get("marketDirectionReports", []):
                report["id"] = str(uuid.uuid4())
                _put_key(report, "projectId", new_project_id)
                await _insert("market_direction_reports", report)

            for entity in proj_data.get("settingEntities", []):
                old_entity_id = entity.get("id", "")
                new_entity_id = str(uuid.uuid4())
                if old_entity_id:
                    setting_entity_id_map[old_entity_id] = new_entity_id
                entity["id"] = new_entity_id
                _put_key(entity, "projectId", new_project_id)
                await _insert("setting_entities", entity)

            for relation in proj_data.get("settingRelations", []):
                relation["id"] = str(uuid.uuid4())
                _put_key(relation, "projectId", new_project_id)
                old_source_id = _get_key(relation, "sourceEntityId")
                old_target_id = _get_key(relation, "targetEntityId")
                if old_source_id in setting_entity_id_map:
                    _put_key(relation, "sourceEntityId", setting_entity_id_map[old_source_id])
                if old_target_id in setting_entity_id_map:
                    _put_key(relation, "targetEntityId", setting_entity_id_map[old_target_id])
                await _insert("setting_relations", relation)

            for event in proj_data.get("settingChangeEvents", []):
                event["id"] = str(uuid.uuid4())
                _put_key(event, "projectId", new_project_id)
                old_entity_id = _get_key(event, "entityId")
                if old_entity_id in setting_entity_id_map:
                    _put_key(event, "entityId", setting_entity_id_map[old_entity_id])
                await _insert("setting_change_events", event)

            for draft in proj_data.get("tempDrafts", []):
                chapter_num = _get_key(draft, "chapterNum") or 0
                draft["id"] = f"{new_project_id}_{chapter_num}"
                _put_key(draft, "projectId", new_project_id)
                await _insert("temp_drafts", draft)

            for binding in proj_data.get("bindings", []):
                binding["id"] = str(uuid.uuid4())
                _put_key(binding, "projectId", new_project_id)
                for key in MODEL_ID_KEYS:
                    old_model_id = _get_key(binding, key)
                    if old_model_id in provider_id_map:
                        _put_key(binding, key, provider_id_map[old_model_id])
                await _insert("task_model_bindings", binding)

            imported_projects += 1
    except Exception as exc:
        raise HTTPException(400, f"导入失败: {exc}") from exc

    return {"ok": True, "importedProjects": imported_projects}


def _convert(rows):
    return convert_rows(rows) if rows else []


def _convert_one(row):
    return _convert([row])[0] if row else None


def _get_key(row, camel_key):
    return row.get(camel_key, row.get(to_snake(camel_key)))


def _put_key(row, camel_key, value):
    row.pop(to_snake(camel_key), None)
    row[camel_key] = value


async def _insert(table, data):
    values = {}
    for key, value in data.items():
        values[to_snake(key)] = json.dumps(value) if isinstance(value, (dict, list)) else value

    cols = list(values.keys())
    vals = list(values.values())
    placeholders = ",".join(["%s"] * len(cols))
    await execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)
