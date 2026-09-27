"""Author-facing continuity queries, each pinned to one read-only snapshot."""

import hashlib
import json


class ContinuityReadError(ValueError):
    pass


def decoded(value):
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            raise ContinuityReadError("invalid_content") from None
    return value


def evidence_excerpt(prose, evidence):
    if not isinstance(prose, str) or not isinstance(evidence, dict):
        return None
    start, end = evidence.get("startScalar"), evidence.get("endScalar")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prose):
        return None
    excerpt = prose[start:end]
    if hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != evidence.get("excerptHash"):
        return None
    return excerpt


def entity_value(row):
    return {"id": row["id"], "name": row["canonical_name"], "type": row["entity_type"]}


class ContinuityReader:
    def __init__(self, repository, connection_factory):
        self.repository = repository
        self.connection_factory = connection_factory

    async def future_design(self, project_id, *, revision=None, entity_id=None):
        async with self.connection_factory() as session:
            revision = await self._revision(session, project_id, revision)
            if entity_id is not None:
                entity = await self.repository.entity(session, project_id, entity_id, revision)
                if entity is None:
                    raise ContinuityReadError("entity_missing")
            row = await self.repository.future_design(session, project_id)
            def design(prefix):
                if row is None or row.get(f"{prefix}_id") is None:
                    return None
                content = decoded(row[f"{prefix}_content"])
                if not isinstance(content, dict):
                    raise ContinuityReadError("invalid_content")
                return {"id": row[f"{prefix}_id"], "revision": row[f"{prefix}_revision"],
                        "contentHash": row[f"{prefix}_hash"], "content": content}
            planning = design("planning")
            plots = planning["content"].get("plots", []) if planning else []
            linked_plots = [plot for plot in plots if entity_id is not None
                            and plot.get("lifecycle") == "active"
                            and isinstance(plot.get("characterDesign"), dict)
                            and plot["characterDesign"].get("entityId") == entity_id]
            return {"projectId": project_id, "revision": revision, "association": "explicit",
                    "entityId": entity_id, "linkedPlots": linked_plots,
                    "bible": design("bible"), "planning": planning}

    async def _revision(self, session, project_id, expected):
        head = await self.repository.head(session, project_id)
        if head is None:
            raise ContinuityReadError("project_missing")
        revision = head["canon_revision_number"]
        if revision != head["projection_revision_number"]:
            raise ContinuityReadError("projection_out_of_sync")
        if expected is not None and expected != revision:
            raise ContinuityReadError("snapshot_changed")
        return revision

    @staticmethod
    def _page(project_id, revision, rows, offset, limit):
        return {"projectId": project_id, "revision": revision, "items": rows[:limit],
                "nextOffset": offset + limit if len(rows) > limit else None}

    @staticmethod
    def _bounds(offset, limit):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 50:
            raise ContinuityReadError("invalid_request")

    async def entities(self, project_id, *, offset=0, limit=30, query="", entity_type=None, revision=None):
        self._bounds(offset, limit)
        if entity_type not in {None, "person", "organization", "place", "item"} or len(query) > 100:
            raise ContinuityReadError("invalid_request")
        async with self.connection_factory() as session:
            revision = await self._revision(session, project_id, revision)
            rows = await self.repository.entities(session, project_id, revision, offset=offset,
                                                   limit=limit + 1, query=query.strip(), entity_type=entity_type)
            return self._page(project_id, revision, [entity_value(row) for row in rows], offset, limit)

    async def records(self, project_id, *, kind, entity_id=None, offset=0, limit=30, revision=None,
                      field_path=None, global_only=False):
        self._bounds(offset, limit)
        if kind not in {"facts", "state", "memory", "arcs", "clues", "progress"}:
            raise ContinuityReadError("invalid_request")
        if (type(global_only) is not bool or (global_only and entity_id is not None)
                or (kind != "facts" and (field_path is not None or global_only))
                or (field_path is not None and (
                    not isinstance(field_path, str) or not field_path.strip() or len(field_path) > 200
                    or not (entity_id or global_only)))):
            raise ContinuityReadError("invalid_request")
        async with self.connection_factory() as session:
            revision = await self._revision(session, project_id, revision)
            entity = None
            if entity_id:
                row = await self.repository.entity(session, project_id, entity_id, revision)
                if row is None:
                    raise ContinuityReadError("entity_missing")
                entity = entity_value(row)
            history_filters = {}
            if field_path is not None:
                history_filters["field_path"] = field_path
            if global_only:
                history_filters["global_only"] = True
            rows = await self.repository.records(session, project_id, revision, kind=kind,
                                                  entity_id=entity_id, offset=offset, limit=limit + 1,
                                                  **history_filters)
            items = [{"id": row["id"], "entityId": row["entity_id"], "entityName": row["canonical_name"],
                      "field": row["field_path"], "value": decoded(row["payload_json"]),
                      "sourceEventId": row["source_event_id"], "sourceChapter": row["source_chapter"],
                      "formedChapter": row.get("formed_chapter", row["source_chapter"] if kind in {"facts", "memory"} else None),
                      "targetTitle": row.get("target_title"),
                      "isClaim": row["fact_kind"] == "claim"} for row in rows]
            return {**self._page(project_id, revision, items, offset, limit), "entity": entity, "kind": kind}

    async def evidence(self, project_id, event_id):
        async with self.connection_factory() as session:
            revision = await self._revision(session, project_id, None)
            row = await self.repository.evidence(session, project_id, event_id, revision)
            if row is None:
                raise ContinuityReadError("evidence_missing")
            excerpt = evidence_excerpt(row["content"], decoded(row["evidence_json"]))
            return {"projectId": project_id, "eventId": event_id, "chapterNumber": row["chapter_num"],
                    "excerpt": excerpt, "verified": excerpt is not None}
