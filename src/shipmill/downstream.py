"""Downstream tests (spec 032): the repositories that depend on this library, whose own test
workflows shipmill starts on a pull request and reads back as checks. This module holds the
[downstream] section of .github/shipmill.toml (D-4)"""

import re
from dataclasses import dataclass

from shipmill.config import Table
from shipmill.errors import ReleaseError

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,38}")  # it becomes a check's name, "downstream: <name>"
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")  # the characters GitHub allows in an owner or a repo name
_SCALARS = ("app_id", "timeout_minutes")
_TIMEOUT = 30  # minutes, the default
_MAX_TIMEOUT = 300


@dataclass(frozen=True, slots=True)
class Downstream:
    """One [downstream.<name>] table"""

    name: str  # the check's name is "downstream: <name>"
    repo: str  # owner/name
    workflow: str  # a file in the downstream's .github/workflows
    ref: str | None  # the downstream's branch to run on; None: its default branch
    report_only: bool  # report the result, never hold the merge
    timeout_minutes: int  # how long its run may take, counted from the dispatch


@dataclass(frozen=True, slots=True)
class DownstreamConfig:
    """[downstream]: the App that starts the downstream workflows and the downstreams, in the
    order the config declares them"""

    app_id: int
    timeout_minutes: int
    downstreams: tuple[Downstream, ...]

    @classmethod
    def parse(cls, t: Table) -> DownstreamConfig:
        Table({k: v for k, v in t.raw.items() if not isinstance(v, dict)}, t.where).allow(*_SCALARS)
        timeout = t.integer("timeout_minutes", default=_TIMEOUT, low=1, high=_MAX_TIMEOUT) or _TIMEOUT
        app_id = t.integer("app_id", default=None, low=1, high=None)
        names = [k for k, v in t.raw.items() if isinstance(v, dict)]
        if not names:
            raise ReleaseError(f"{t.where} names no downstream repository")
        if app_id is None:
            raise ReleaseError(f"{t.where}: app_id is required")
        downstreams = tuple(_downstream(name, t.table(name), timeout) for name in names)
        seen: dict[tuple[str, str], str] = {}
        for d in downstreams:
            key = (d.repo, d.workflow)
            if key in seen:
                raise ReleaseError(
                    f"{t.where}: [{seen[key]}] and [{d.name}] both name {d.workflow} in {d.repo}; keep one"
                )
            seen[key] = d.name
        return cls(app_id, timeout, downstreams)


def _downstream(name: str, t: Table, section_timeout: int) -> Downstream:
    if not _NAME.fullmatch(name):
        raise ReleaseError(
            f"{t.where}: a downstream's name matches [a-z0-9][a-z0-9-]{{0,38}}, since it becomes a check's name"
        )
    t.allow("repo", "workflow", "ref", "report_only", "timeout_minutes")
    repo = t.string("repo")
    owner, slash, rest = repo.partition("/")
    if not slash or any(p in {".", ".."} or not _SEGMENT.fullmatch(p) for p in (owner, rest)):
        raise ReleaseError(f"{t.where}: repo is owner/name, such as example-org/consumer-app; got {repo!r}")
    workflow = t.string("workflow")
    if "/" in workflow or not workflow.endswith((".yml", ".yaml")):
        raise ReleaseError(f"{t.where}: workflow names a file in the downstream's .github/workflows, got {workflow!r}")
    ref = t.string("ref") if "ref" in t.raw else None
    if ref is not None and not ref.strip():
        raise ReleaseError(f"{t.where}: ref must be a branch name; omit it for the downstream's default branch")
    timeout = t.integer("timeout_minutes", default=section_timeout, low=1, high=_MAX_TIMEOUT) or section_timeout
    return Downstream(name, repo, workflow, ref, t.boolean("report_only", default=False), timeout)
