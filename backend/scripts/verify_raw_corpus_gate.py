"""Fail-closed Git gate preventing raw corpus files from entering the tree."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping


APPROVED_COMMIT_ENV = "APPROVED_M2_PLAN_COMMIT"
_COMMIT = re.compile(r"[0-9a-fA-F]{40}\Z")
_DEPENDENCY = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9][A-Za-z0-9._,-]*\])?"
    r"(?:(?:===|==|~=|!=|<=|>=|<|>)"
    r"[A-Za-z0-9][A-Za-z0-9.*+!_,<>=~^-]*)?\Z"
)
_ALLOWED_MANIFESTS = frozenset({
    "backend/requirements.txt",
    "backend/requirements-m2.lock.txt",
})
_RAW_PATHSPECS = (
    ":(icase,glob)**/*.txt",
    ":(icase,glob)**/*.epub",
    ":(icase,glob)**/*.mobi",
)


class RawCorpusGateError(RuntimeError):
    """A stable gate precondition or raw-file invariant failed."""


@dataclass(frozen=True, slots=True)
class RawCorpusGateReport:
    approved_commit: str
    original_hits: int
    dependency_manifests: int
    raw_novel_candidates: int


def approved_commit_from_environment(
    environment: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if environment is None else environment
    value = source.get(APPROVED_COMMIT_ENV)
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise RawCorpusGateError(
            f"{APPROVED_COMMIT_ENV} is required as an exact commit hash"
        )
    return value.lower()


def _git(repository: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise RawCorpusGateError("git executable is unavailable") from exc
    if result.returncode != 0:
        raise RawCorpusGateError("git raw corpus inspection failed")
    return result.stdout


def _nul_paths(raw: bytes) -> tuple[str, ...]:
    if not raw:
        return ()
    fields = raw.split(b"\0")
    if fields[-1] != b"":
        raise RawCorpusGateError("git returned a non-NUL-safe path list")
    try:
        paths = tuple(
            field.decode("utf-8", errors="strict").replace("\\", "/")
            for field in fields[:-1]
        )
    except UnicodeDecodeError as exc:
        raise RawCorpusGateError("git returned an unsafe path encoding") from exc
    if any(not path or path.startswith("/") or "\x00" in path for path in paths):
        raise RawCorpusGateError("git returned an unsafe repository path")
    return paths


def _changed_paths(repository: Path, *git_args: str) -> tuple[str, ...]:
    return _nul_paths(_git(
        repository, *git_args, "--", *_RAW_PATHSPECS
    ))


def _validate_dependency_document(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RawCorpusGateError(
            "fixed dependency manifest is not valid UTF-8"
        ) from exc
    dependency_count = 0
    for source_line in text.splitlines():
        line = source_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            raise RawCorpusGateError(
                "fixed dependency manifest comments are not permitted"
            )
        dependency_count += 1
        if _DEPENDENCY.fullmatch(line) is None:
            raise RawCorpusGateError(
                "fixed dependency manifest contains non-dependency content"
            )
    if dependency_count == 0:
        raise RawCorpusGateError("fixed dependency manifest contains no dependencies")


def _validate_manifest_versions(repository: Path) -> None:
    for relative_path in sorted(_ALLOWED_MANIFESTS):
        committed = _git(repository, "show", f"HEAD:{relative_path}")
        _validate_dependency_document(committed)
        staged = _git(repository, "show", f":{relative_path}")
        _validate_dependency_document(staged)
        try:
            working = (repository / Path(relative_path)).read_bytes()
        except OSError as exc:
            raise RawCorpusGateError(
                "fixed dependency manifest is absent from the working tree"
            ) from exc
        _validate_dependency_document(working)


def verify_raw_corpus_gate(
    repository_root: Path | str,
    approved_commit: str,
) -> RawCorpusGateReport:
    if not isinstance(approved_commit, str) or _COMMIT.fullmatch(
        approved_commit
    ) is None:
        raise RawCorpusGateError("approved plan commit must be an exact commit hash")
    repository = Path(repository_root)
    if not repository.is_dir():
        raise RawCorpusGateError("repository root is unavailable")
    _git(repository, "cat-file", "-e", f"{approved_commit}^{{commit}}")

    committed = _changed_paths(
        repository, "diff", "--name-only", "-z", f"{approved_commit}...HEAD"
    )
    staged = _changed_paths(
        repository, "diff", "--cached", "--name-only", "-z", "HEAD"
    )
    working = _changed_paths(
        repository, "diff", "--name-only", "-z", "HEAD"
    )
    untracked = _changed_paths(
        repository, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if set(committed) != _ALLOWED_MANIFESTS or len(committed) != len(
        _ALLOWED_MANIFESTS
    ):
        candidates = set(committed) - _ALLOWED_MANIFESTS
        if candidates:
            raise RawCorpusGateError("raw corpus candidate detected in committed diff")
        raise RawCorpusGateError(
            "approved baseline must resolve to both fixed dependency manifests"
        )
    raw_candidates = (
        set(committed) | set(staged) | set(working) | set(untracked)
    ) - _ALLOWED_MANIFESTS
    if raw_candidates:
        raise RawCorpusGateError("raw corpus candidate detected in repository state")
    _validate_manifest_versions(repository)
    return RawCorpusGateReport(
        approved_commit=approved_commit.lower(),
        original_hits=len(committed),
        dependency_manifests=len(_ALLOWED_MANIFESTS),
        raw_novel_candidates=0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    return parser


def main(argv=None, *, environment=None) -> int:
    args = _parser().parse_args(argv)
    try:
        approved = approved_commit_from_environment(environment)
        report = verify_raw_corpus_gate(args.repository, approved)
    except RawCorpusGateError as exc:
        print(f"raw_corpus_gate=failed reason={exc}", file=sys.stderr)
        return 2
    print(
        "raw_corpus_gate=passed "
        f"approved_commit={report.approved_commit} "
        f"original_hits={report.original_hits} "
        f"dependency_manifests={report.dependency_manifests} "
        f"raw_novel_candidates={report.raw_novel_candidates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "RawCorpusGateError", "RawCorpusGateReport",
    "approved_commit_from_environment", "main", "verify_raw_corpus_gate",
)
