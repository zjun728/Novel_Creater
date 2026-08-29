from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

import backend.domain.novel_downloads as downloads
from backend.domain.novel_downloads import (
    DownloadFormat,
    DownloadScope,
    FinalizedChapterSnapshot,
    NovelDownloadIntegrityError,
    NovelDownloadScopeNotFoundError,
    NovelDownloadSelector,
    NovelDownloadSnapshot,
    render_novel_download,
    safe_attachment_names,
    select_chapters,
)


def _chapter(
    chapter_number: int,
    *,
    volume_id: str = "volume-1",
    volume_order: int = 1,
    volume_title: str = "卷名",
    chapter_title: str | None = None,
    content: str = "正文",
) -> FinalizedChapterSnapshot:
    return FinalizedChapterSnapshot(
        chapter_number=chapter_number,
        chapter_title=chapter_title or f"章名{chapter_number}",
        volume_id=volume_id,
        volume_order=volume_order,
        volume_title=volume_title,
        content=content,
        content_hash=sha256(content.encode("utf-8")).hexdigest(),
    )


def _snapshot(*chapters: FinalizedChapterSnapshot) -> NovelDownloadSnapshot:
    return NovelDownloadSnapshot(book_title="书名", chapters=chapters)


def _selector(
    scope: DownloadScope,
    format: DownloadFormat = DownloadFormat.TXT,
    **kwargs: object,
) -> NovelDownloadSelector:
    return NovelDownloadSelector(scope=scope, format=format, **kwargs)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "scope": DownloadScope.BOOK,
                "format": DownloadFormat.TXT,
                "volume_id": "volume-1",
            },
            "book scope must not include volume_id or chapter_number",
        ),
        (
            {
                "scope": DownloadScope.BOOK,
                "format": DownloadFormat.TXT,
                "chapter_number": 1,
            },
            "book scope must not include volume_id or chapter_number",
        ),
        (
            {
                "scope": DownloadScope.VOLUME,
                "format": DownloadFormat.TXT,
            },
            "volume scope requires volume_id only",
        ),
        (
            {
                "scope": DownloadScope.VOLUME,
                "format": DownloadFormat.TXT,
                "volume_id": "volume-1",
                "chapter_number": 1,
            },
            "volume scope requires volume_id only",
        ),
        (
            {
                "scope": DownloadScope.CHAPTER,
                "format": DownloadFormat.TXT,
            },
            "chapter scope requires a positive chapter_number only",
        ),
        (
            {
                "scope": DownloadScope.CHAPTER,
                "format": DownloadFormat.TXT,
                "chapter_number": 0,
            },
            "chapter scope requires a positive chapter_number only",
        ),
        (
            {
                "scope": DownloadScope.CHAPTER,
                "format": DownloadFormat.TXT,
                "chapter_number": 1,
                "volume_id": "volume-1",
            },
            "chapter scope requires a positive chapter_number only",
        ),
    ],
)
def test_selector_enforces_exact_scope_fields(
    payload: dict[str, object], message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        NovelDownloadSelector.model_validate(payload)


def test_selector_is_strict_frozen_and_closed_to_txt_or_markdown() -> None:
    selector = _selector(DownloadScope.BOOK)

    with pytest.raises(ValidationError):
        NovelDownloadSelector.model_validate({
            "scope": DownloadScope.BOOK,
            "format": "pdf",
        })
    with pytest.raises(ValidationError):
        NovelDownloadSelector.model_validate({
            "scope": DownloadScope.BOOK,
            "format": DownloadFormat.TXT,
            "unexpected": True,
        })
    with pytest.raises(ValidationError):
        selector.scope = DownloadScope.VOLUME


def test_select_chapters_filters_book_volume_and_chapter_in_global_order() -> None:
    snapshot = _snapshot(
        _chapter(3, volume_id="volume-2", volume_order=2, volume_title="第二卷"),
        _chapter(1, volume_id="volume-1"),
        _chapter(2, volume_id="volume-1"),
    )

    assert [chapter.chapter_number for chapter in select_chapters(
        snapshot, _selector(DownloadScope.BOOK),
    )] == [1, 2, 3]
    assert [chapter.chapter_number for chapter in select_chapters(
        snapshot, _selector(DownloadScope.VOLUME, volume_id="volume-1"),
    )] == [1, 2]
    assert [chapter.chapter_number for chapter in select_chapters(
        snapshot, _selector(DownloadScope.CHAPTER, chapter_number=2),
    )] == [2]


@pytest.mark.parametrize(
    "selector",
    [
        _selector(DownloadScope.BOOK),
        _selector(DownloadScope.VOLUME, volume_id="missing-volume"),
        _selector(DownloadScope.CHAPTER, chapter_number=99),
    ],
)
def test_select_chapters_reports_a_missing_scope_with_the_exact_domain_outcome(
    selector: NovelDownloadSelector,
) -> None:
    with pytest.raises(
        NovelDownloadScopeNotFoundError,
        match="^requested download scope has no finalized chapters$",
    ):
        select_chapters(_snapshot(), selector)


def test_render_txt_is_exact_utf8_without_bom_and_normalizes_only_line_endings() -> None:
    snapshot = _snapshot(_chapter(
        1,
        chapter_title="章名",
        content="# 正文\r\n第二行\r第三行\n\n",
    ))

    rendered = render_novel_download(snapshot, _selector(DownloadScope.BOOK))

    assert rendered == (
        "书名\n\n===== 第 1 卷 · 卷名 =====\n\n"
        "----- 第 1 章 · 章名 -----\n\n# 正文\n第二行\n第三行\n"
    ).encode("utf-8")
    assert not rendered.startswith(b"\xef\xbb\xbf")


def test_render_markdown_uses_heading_levels_and_flattens_escaped_titles() -> None:
    snapshot = NovelDownloadSnapshot(
        book_title="书\n名 #标题",
        chapters=(_chapter(
            1,
            volume_title="卷\r名 #卷",
            chapter_title="章\r\n名 #章",
        ),),
    )

    assert render_novel_download(
        snapshot, _selector(DownloadScope.BOOK, DownloadFormat.MARKDOWN),
    ) == (
        "# 书 名 \\#标题\n\n## 第 1 卷 · 卷 名 \\#卷\n\n"
        "### 第 1 章 · 章 名 \\#章\n\n正文\n"
    ).encode("utf-8")


def test_render_markdown_escapes_titles_as_inline_literals() -> None:
    snapshot = NovelDownloadSnapshot(
        book_title="书\\名 [链接](url) `代码` *强调* _下划线_ <标签>",
        chapters=(_chapter(1),),
    )

    assert render_novel_download(
        snapshot, _selector(DownloadScope.BOOK, DownloadFormat.MARKDOWN),
    ) == (
        "# 书\\\\名 \\[链接\\]\\(url\\) \\`代码\\` \\*强调\\* "
        "\\_下划线\\_ \\<标签\\>\n\n## 第 1 卷 · 卷名\n\n"
        "### 第 1 章 · 章名1\n\n正文\n"
    ).encode("utf-8")


def test_snapshot_rejects_different_volumes_with_the_same_volume_order() -> None:
    with pytest.raises(
        ValueError,
        match="finalized chapter volume order is inconsistent",
    ):
        _snapshot(
            _chapter(1, volume_id="volume-1", volume_order=1, volume_title="第一卷"),
            _chapter(2, volume_id="volume-2", volume_order=1, volume_title="第二卷"),
        )


@pytest.mark.parametrize(
    "operation",
    [
        lambda snapshot: select_chapters(snapshot, _selector(DownloadScope.BOOK)),
        lambda snapshot: render_novel_download(snapshot, _selector(DownloadScope.BOOK)),
    ],
)
def test_selection_and_render_fail_closed_for_model_copy_volume_order_collision(
    operation,
) -> None:
    snapshot = _snapshot(
        _chapter(1, volume_id="volume-1", volume_order=1, volume_title="第一卷"),
        _chapter(2, volume_id="volume-2", volume_order=2, volume_title="第二卷"),
    )
    corrupted = snapshot.model_copy(update={
        "chapters": (
            snapshot.chapters[0],
            snapshot.chapters[1].model_copy(update={"volume_order": 1}),
        ),
    })

    with pytest.raises(
        NovelDownloadIntegrityError,
        match="^finalized chapter volume order is inconsistent$",
    ):
        operation(corrupted)


def test_render_fails_closed_when_any_final_prose_hash_does_not_match() -> None:
    chapter = _chapter(1)
    snapshot = _snapshot(chapter.model_copy(update={"content_hash": "0" * 64}))

    with pytest.raises(
        NovelDownloadIntegrityError,
        match="^final prose hash does not match chapter 1$",
    ):
        render_novel_download(snapshot, _selector(DownloadScope.BOOK))


def test_selection_verifies_only_the_selected_final_prose_scope() -> None:
    chapter_1 = _chapter(1, content="第一章正文")
    chapter_3 = _chapter(3, content="第三章正文").model_copy(
        update={"content_hash": "0" * 64},
    )
    snapshot = _snapshot(chapter_1, chapter_3)
    chapter_1_selector = _selector(DownloadScope.CHAPTER, chapter_number=1)

    assert select_chapters(snapshot, chapter_1_selector) == (chapter_1,)
    assert b"\xe7\xac\xac\xe4\xb8\x80\xe7\xab\xa0\xe6\xad\xa3\xe6\x96\x87" in render_novel_download(
        snapshot,
        chapter_1_selector,
    )
    with pytest.raises(
        NovelDownloadIntegrityError,
        match="^final prose hash does not match chapter 3$",
    ):
        select_chapters(
            snapshot,
            _selector(DownloadScope.CHAPTER, chapter_number=3),
        )
    with pytest.raises(NovelDownloadIntegrityError):
        select_chapters(snapshot, _selector(DownloadScope.BOOK))


def test_snapshot_rejects_a_volume_split_into_non_contiguous_chapter_runs() -> None:
    with pytest.raises(
        ValueError,
        match="finalized chapter volume run is inconsistent",
    ):
        _snapshot(
            _chapter(1, volume_id="volume-1", volume_order=1, volume_title="第一卷"),
            _chapter(2, volume_id="volume-2", volume_order=2, volume_title="第二卷"),
            _chapter(3, volume_id="volume-1", volume_order=1, volume_title="第一卷"),
        )


def test_render_rejects_at_the_small_cap_before_normalizing_later_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ProseThatMustNotBeRendered(str):
        def replace(self, *args: object, **kwargs: object) -> str:
            raise AssertionError("prose should not be normalized after cap failure")

    content = _ProseThatMustNotBeRendered("正文")
    chapter = _chapter(1).model_copy(update={
        "content": content,
        "content_hash": sha256(content.encode("utf-8")).hexdigest(),
    })
    monkeypatch.setattr(downloads, "MAX_DOWNLOAD_BYTES", len("书名".encode("utf-8")))

    with pytest.raises(
        downloads.NovelDownloadTooLargeError,
        match="^rendered download exceeds 128 MiB$",
    ):
        render_novel_download(_snapshot(chapter), _selector(DownloadScope.BOOK))


def test_render_fails_closed_when_the_fixed_128_mib_cap_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert downloads.MAX_DOWNLOAD_BYTES == 128 * 1024 * 1024
    monkeypatch.setattr(downloads, "MAX_DOWNLOAD_BYTES", 1)

    with pytest.raises(
        downloads.NovelDownloadTooLargeError,
        match="^rendered download exceeds 128 MiB$",
    ):
        render_novel_download(_snapshot(_chapter(1)), _selector(DownloadScope.BOOK))


def test_safe_attachment_names_never_returns_a_path_or_control_characters() -> None:
    names = safe_attachment_names("目录/名\\\x00\r\n", DownloadFormat.TXT)

    assert names.ascii_filename == "novel-download.txt"
    assert names.unicode_filename == "目录名.txt"
    assert all(character not in names.unicode_filename for character in "/\\\x00\r\n")
