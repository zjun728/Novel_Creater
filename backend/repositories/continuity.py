"""Bounded reads over existing Canon and projection authorities."""


class ContinuityRepository:
    async def state_history_reference(self, session, project_id, entity_id, field_path, revision):
        """Last state source for one exact key, using the existing projection rule.

        The second row detects an invalid tie; this is not a facts/history page
        (which also contains claims), nor a read from the current projection head.
        """
        return await session.fetchall(
            """SELECT event.id,event.project_id,event.entity_id,event.field_path,
                      event.revision_number,event.event_order,event.fact_kind,
                      event.confirmation_status,event.value_json AS payload_json
                 FROM canon_events event
                WHERE event.project_id=%s
                  AND CAST(event.entity_id AS BINARY)=CAST(%s AS BINARY)
                  AND CAST(event.field_path AS BINARY)=CAST(%s AS BINARY)
                  AND event.revision_number<=%s
                  AND event.confirmation_status='confirmed' AND event.fact_kind<>'claim'
                ORDER BY event.revision_number DESC, event.event_order DESC, event.id LIMIT 2""",
            (project_id, entity_id, field_path, revision),
        )

    async def future_design(self, session, project_id):
        """Read confirmed designs only when their full upstream basis is current."""
        return await session.fetchone(
            """SELECT bible.id AS bible_id, bible.revision AS bible_revision,
                      bible.content_hash AS bible_hash, bible.content_json AS bible_content,
                      planning.id AS planning_id, planning.revision AS planning_revision,
                      planning.content_hash AS planning_hash, planning.content_json AS planning_content
                 FROM project_selected_seeds selected
                 JOIN project_contract_heads contracts ON contracts.project_id=selected.project_id
                 JOIN creation_contracts creation ON creation.project_id=contracts.project_id
                  AND creation.id=contracts.creation_contract_id AND creation.revision=contracts.revision
                  AND creation.content_hash=contracts.creation_hash
                  AND creation.selection_revision=selected.selection_revision
                  AND creation.seed_id=selected.seed_id AND creation.seed_revision_id=selected.seed_revision_id
                  AND creation.seed_hash=selected.seed_hash
                 JOIN style_contracts style ON style.project_id=contracts.project_id
                  AND style.id=contracts.style_contract_id AND style.revision=contracts.revision
                  AND style.content_hash=contracts.style_hash AND style.creation_contract_id=creation.id
                 JOIN project_bible_heads bible_head ON bible_head.project_id=selected.project_id
                 JOIN creation_bible_revisions bible ON bible.project_id=bible_head.project_id
                  AND bible.id=bible_head.bible_revision_id AND bible.revision=bible_head.revision
                  AND bible.content_hash=bible_head.content_hash
                  AND bible.selection_revision=selected.selection_revision
                  AND bible.seed_id=selected.seed_id AND bible.seed_revision_id=selected.seed_revision_id
                  AND bible.seed_hash=selected.seed_hash AND bible.contract_revision=contracts.revision
                  AND bible.creation_contract_id=contracts.creation_contract_id
                  AND bible.creation_hash=contracts.creation_hash
                  AND bible.style_contract_id=contracts.style_contract_id AND bible.style_hash=contracts.style_hash
                 LEFT JOIN project_planning_heads planning_head ON planning_head.project_id=selected.project_id
                 LEFT JOIN planning_revisions planning ON planning.project_id=planning_head.project_id
                  AND planning.id=planning_head.planning_revision_id AND planning.revision=planning_head.revision
                  AND planning.content_hash=planning_head.content_hash
                  AND planning.selection_revision=bible.selection_revision
                  AND planning.seed_id=bible.seed_id AND planning.seed_revision_id=bible.seed_revision_id
                  AND planning.seed_hash=bible.seed_hash AND planning.contract_revision=bible.contract_revision
                  AND planning.creation_contract_id=bible.creation_contract_id AND planning.creation_hash=bible.creation_hash
                  AND planning.style_contract_id=bible.style_contract_id AND planning.style_hash=bible.style_hash
                  AND planning.bible_revision=bible.revision AND planning.bible_revision_id=bible.id
                  AND planning.bible_hash=bible.content_hash
                WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def head(self, session, project_id):
        return await session.fetchone(
            "SELECT canon_revision_number, projection_revision_number FROM projection_heads WHERE project_id=%s",
            (project_id,),
        )

    async def entity(self, session, project_id, entity_id, revision):
        return await session.fetchone(
            """SELECT id, canonical_name, entity_type FROM canon_entities
               WHERE project_id=%s AND id=%s AND created_revision<=%s""",
            (project_id, entity_id, revision),
        )

    async def entities(self, session, project_id, revision, *, offset, limit, query, entity_type):
        conditions = ["project_id=%s", "created_revision<=%s"]
        args = [project_id, revision]
        if query:
            conditions.append("LOCATE(%s, canonical_name)>0")
            args.append(query)
        if entity_type:
            conditions.append("entity_type=%s")
            args.append(entity_type)
        return await session.fetchall(
            f"""SELECT id, canonical_name, entity_type FROM canon_entities
                WHERE {' AND '.join(conditions)} ORDER BY canonical_name, id LIMIT %s OFFSET %s""",
            (*args, limit, offset),
        )

    async def records(self, session, project_id, revision, *, kind, entity_id, offset, limit,
                      field_path=None, global_only=False):
        # All identifiers below are closed server-owned constants, never user SQL.
        if kind in {"facts", "memory"}:
            # memory_views is the confirmed event history. JSON_TABLE pages its
            # event references without shipping an unbounded entity history.
            memory_join = """JOIN memory_views memory ON memory.project_id=event.project_id
                AND memory.revision_number=%s AND memory.entity_id <=> event.entity_id
                JOIN JSON_TABLE(memory.payload_json, '$[*]' COLUMNS
                    (event_id VARCHAR(100) PATH '$.eventId')) item ON CAST(item.event_id AS BINARY)=CAST(event.id AS BINARY)""" if kind == "memory" else ""
            args = [revision] if kind == "memory" else []
            conditions = ["event.project_id=%s", "event.revision_number<=%s", "event.confirmation_status='confirmed'"]
            args.extend((project_id, revision))
            if entity_id:
                conditions.append("event.entity_id=%s")
                args.append(entity_id)
            if global_only:
                conditions.append("event.entity_id IS NULL")
            if field_path is not None:
                conditions.append("CAST(event.field_path AS BINARY)=CAST(%s AS BINARY)")
                args.append(field_path)
            return await session.fetchall(
                f"""SELECT event.id, event.entity_id, entity.canonical_name,
                      event.field_path, event.value_json AS payload_json, event.id AS source_event_id,
                      event.fact_kind, final.chapter_num AS source_chapter,
                      final.chapter_num AS formed_chapter
                   FROM canon_events event {memory_join}
                   LEFT JOIN canon_entities entity ON entity.project_id=event.project_id AND entity.id=event.entity_id
                   LEFT JOIN final_chapters final ON final.project_id=event.project_id AND final.canon_revision=event.revision_number
                   WHERE {' AND '.join(conditions)}
                   ORDER BY event.revision_number DESC, event.event_order DESC, event.id LIMIT %s OFFSET %s""",
                (*args, limit, offset),
            )
        table, field = {
            "state": ("current_state_projections", "field_path"),
            "arcs": ("arc_projections", "arc_key"),
            "clues": ("plot_thread_projections", "field_path"),
            "progress": ("plot_thread_projections", "field_path"),
        }[kind]
        conditions = ["projection.project_id=%s", "projection.revision_number=%s"]
        args = [project_id, revision]
        if kind in {"clues", "progress"}:
            operator = "LIKE" if kind == "progress" else "NOT LIKE"
            conditions.append(f"projection.field_path {operator} %s")
            args.append("plot.progress.%")
        if entity_id:
            conditions.append("projection.entity_id=%s")
            args.append(entity_id)
        target_title = "NULL"
        if kind == "progress":
            cases = []
            for target_type, path, label in (
                ("story_block", "$.storyBlocks[*]", "title"),
                ("stage", "$.storyBlocks[*].stages[*]", "title"),
                ("scene_task", "$.storyBlocks[*].stages[*].sceneTasks[*]", "task"),
            ):
                cases.append(f"""WHEN '{target_type}' THEN
                    (SELECT node.title FROM JSON_TABLE(planning.content_json, '{path}'
                      COLUMNS (node_id VARCHAR(100) PATH '$.id', title VARCHAR(4000) PATH '$.{label}')) node
                     WHERE CAST(node.node_id AS BINARY)=CAST(JSON_UNQUOTE(JSON_EXTRACT(projection.payload_json, '$.targetId')) AS BINARY)
                     LIMIT 1)""")
            target_title = "CASE JSON_UNQUOTE(JSON_EXTRACT(projection.payload_json, '$.targetType')) " + " ".join(cases) + " END"
        return await session.fetchall(
            f"""SELECT projection.id, projection.entity_id, entity.canonical_name,
                    projection.{field} AS field_path, projection.payload_json,
                    {target_title} AS target_title,
                    source.id AS source_event_id, source.fact_kind, final.chapter_num AS source_chapter,
                    formed_final.chapter_num AS formed_chapter
                FROM {table} projection
                LEFT JOIN canon_entities entity ON entity.project_id=projection.project_id AND entity.id=projection.entity_id
                LEFT JOIN canon_events source ON source.id=(
                    SELECT event.id FROM canon_events event
                    WHERE event.project_id=projection.project_id AND event.entity_id <=> projection.entity_id
                      AND CAST(event.field_path AS BINARY)=CAST(projection.{field} AS BINARY) AND event.revision_number<=projection.revision_number
                      AND event.confirmation_status='confirmed' AND event.fact_kind<>'claim'
                    ORDER BY event.revision_number DESC, event.event_order DESC LIMIT 1)
                LEFT JOIN final_chapters final ON final.project_id=source.project_id AND final.canon_revision=source.revision_number
                LEFT JOIN canon_events formed ON formed.id=(
                    SELECT event.id FROM canon_events event
                    WHERE event.project_id=projection.project_id AND event.entity_id <=> projection.entity_id
                      AND CAST(event.field_path AS BINARY)=CAST(projection.{field} AS BINARY) AND event.revision_number<=projection.revision_number
                      AND event.confirmation_status='confirmed' AND event.fact_kind<>'claim'
                    ORDER BY event.revision_number ASC, event.event_order ASC LIMIT 1)
                LEFT JOIN final_chapters formed_final ON formed_final.project_id=formed.project_id
                  AND formed_final.canon_revision=formed.revision_number
                LEFT JOIN planning_revisions planning ON planning.project_id=final.project_id
                  AND planning.id=final.planning_revision_id AND planning.content_hash=final.planning_hash
                WHERE {' AND '.join(conditions)}
                ORDER BY projection.entity_id, projection.{field}, projection.id LIMIT %s OFFSET %s""",
            (*args, limit, offset),
        )

    async def evidence(self, session, project_id, event_id, revision):
        return await session.fetchone(
            """SELECT event.evidence_json, final.chapter_num, final.content
               FROM canon_events event
               LEFT JOIN final_chapters final ON final.project_id=event.project_id
                 AND final.canon_revision=event.revision_number
               WHERE event.project_id=%s AND event.id=%s AND event.revision_number<=%s
                 AND event.confirmation_status='confirmed'""",
            (project_id, event_id, revision),
        )
