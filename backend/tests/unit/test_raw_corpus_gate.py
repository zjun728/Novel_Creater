from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from backend.scripts.verify_raw_corpus_gate import (
    RawCorpusGateError,
    approved_commit_from_environment,
    main,
    verify_raw_corpus_gate,
)


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return result.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repository(
    tmp_path: Path, *, baseline_raw: str | None = None
) -> tuple[Path, str]:
    repository = tmp_path / "gate-repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Corpus Gate Test")
    _git(repository, "config", "user.email", "corpus-gate@example.invalid")
    _write(repository / ".gitignore", "ignored/\n")
    paths = [".gitignore"]
    if baseline_raw is not None:
        _write(repository / baseline_raw, "baseline non-corpus note\n")
        paths.append(baseline_raw)
    _git(repository, "add", *paths)
    _git(repository, "commit", "-q", "-m", "approved plan")
    approved = _git(repository, "rev-parse", "HEAD")
    _write(repository / "backend/requirements.txt", "fastapi>=0.100\n")
    _write(
        repository / "backend/requirements-m2.lock.txt",
        "fastapi==0.115.0\npydantic==2.13.4\n",
    )
    _git(repository, "add", "backend/requirements.txt", "backend/requirements-m2.lock.txt")
    _git(repository, "commit", "-q", "-m", "dependency manifests")
    return repository, approved


def test_gate_requires_explicit_approved_commit_environment():
    with pytest.raises(RawCorpusGateError, match="APPROVED_M2_PLAN_COMMIT"):
        approved_commit_from_environment({})
    assert approved_commit_from_environment({
        "APPROVED_M2_PLAN_COMMIT": "a" * 40
    }) == "a" * 40


def test_gate_cli_fails_closed_before_git_when_environment_is_missing(
    tmp_path, capsys
):
    assert main(["--repository", str(tmp_path)], environment={}) == 2
    assert "APPROVED_M2_PLAN_COMMIT" in capsys.readouterr().err


def test_gate_allows_only_the_two_exact_dependency_manifest_hits(tmp_path):
    repository, approved = _repository(tmp_path)

    report = verify_raw_corpus_gate(repository, approved)

    assert report.approved_commit == approved
    assert report.original_hits == 2
    assert report.raw_novel_candidates == 0
    assert report.dependency_manifests == 2


@pytest.mark.parametrize(
    ("kind", "relative_path"),
    (
        ("committed", "novels/third.txt"),
        ("committed", "novels/third.epub"),
        ("untracked", "loose manuscript.TXT"),
        ("untracked", "loose manuscript [草稿] $&'(),;=@#%.txt"),
        ("untracked", "loose.mobi"),
        ("working", "tracked-notes.txt"),
        ("committed", "docs/requirements.txt"),
    ),
)
def test_gate_fails_closed_for_every_other_raw_extension(
    tmp_path, kind, relative_path
):
    repository, approved = _repository(
        tmp_path,
        baseline_raw=relative_path if kind == "working" else None,
    )
    target = repository / relative_path
    if kind == "working":
        _write(target, "changed manuscript sentinel\n")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic raw book bytes")
        if kind == "committed":
            _git(repository, "add", relative_path)
            _git(repository, "commit", "-q", "-m", "unexpected raw file")

    with pytest.raises(RawCorpusGateError, match="raw corpus candidate"):
        verify_raw_corpus_gate(repository, approved)


@pytest.mark.parametrize(
    "polluted",
    (
        "Once upon a synthetic chapter, prose continued here.\n",
        "../private/novel.txt\n",
        "https://private.example/full-book.txt\n",
        "# Chapter one: synthetic prose hidden as a comment.\nfastapi==0.115.0\n",
    ),
)
def test_gate_rejects_novel_or_path_content_hidden_in_allowed_manifest(
    tmp_path, polluted
):
    repository, approved = _repository(tmp_path)
    _write(repository / "backend/requirements.txt", polluted)
    _git(repository, "add", "backend/requirements.txt")
    _git(repository, "commit", "-q", "-m", "polluted dependency manifest")

    with pytest.raises(RawCorpusGateError, match="dependency manifest"):
        verify_raw_corpus_gate(repository, approved)


def test_gate_rejects_uncommitted_pollution_in_allowed_manifest(tmp_path):
    repository, approved = _repository(tmp_path)
    _write(
        repository / "backend/requirements.txt",
        "# Synthetic full-book text hidden in a comment.\nfastapi>=0.100\n",
    )

    with pytest.raises(RawCorpusGateError, match="dependency manifest"):
        verify_raw_corpus_gate(repository, approved)


def test_gate_rejects_staged_pollution_hidden_by_a_clean_working_copy(tmp_path):
    repository, approved = _repository(tmp_path)
    manifest = repository / "backend/requirements.txt"
    clean = manifest.read_text(encoding="utf-8")
    _write(
        manifest,
        "# Synthetic full-book text staged in the index.\nfastapi>=0.100\n",
    )
    _git(repository, "add", "backend/requirements.txt")
    _write(manifest, clean)

    with pytest.raises(RawCorpusGateError, match="dependency manifest"):
        verify_raw_corpus_gate(repository, approved)


def test_gate_rejects_a_raw_file_staged_then_deleted_from_worktree(tmp_path):
    repository, approved = _repository(tmp_path)
    staged_only = repository / "staged-only.txt"
    staged_only.write_text("Synthetic staged manuscript.\n", encoding="utf-8")
    _git(repository, "add", "staged-only.txt")
    staged_only.unlink()

    with pytest.raises(RawCorpusGateError, match="raw corpus candidate"):
        verify_raw_corpus_gate(repository, approved)
