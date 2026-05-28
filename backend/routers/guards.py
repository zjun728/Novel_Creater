from fastapi import HTTPException

from database import fetchone


async def _count(sql: str, args: tuple) -> int:
    row = await fetchone(sql, args)
    return int((row or {}).get("c") or 0)


async def project_has_chapter_content(pid: str) -> bool:
    written_chapters = await _count(
        """
        SELECT COUNT(*) AS c FROM chapters
        WHERE project_id=%s
          AND (COALESCE(word_count, 0) > 0 OR final_version_id IS NOT NULL OR COALESCE(summary, '') <> '' OR status IN ('final', 'reviewing'))
        """,
        (pid,),
    )
    chapter_versions = await _count(
        "SELECT COUNT(*) AS c FROM chapter_versions WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    temp_drafts = await _count(
        "SELECT COUNT(*) AS c FROM temp_drafts WHERE project_id=%s AND COALESCE(content, '') <> ''",
        (pid,),
    )
    return written_chapters > 0 or chapter_versions > 0 or temp_drafts > 0


async def ensure_project_without_chapter_content(pid: str, action: str = "修改核心规划") -> None:
    if await project_has_chapter_content(pid):
        raise HTTPException(
            409,
            f"项目已有正文内容，不能{action}。如需调整，请通过纠偏任务、章节修订或后续软过渡处理。",
        )
