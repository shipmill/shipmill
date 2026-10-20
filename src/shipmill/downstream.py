"""Downstream tests (spec 032): the repositories that depend on this library, whose own test
workflows shipmill starts on a pull request and reads back as checks. This module holds the
[downstream] section of .github/shipmill.toml (D-4) and `downstream start`, which writes one
check per downstream on the pull request's head and dispatches each downstream's workflow
with a token minted for the App and limited to that downstream's repository.

It never reads, checks out, or runs the pull request's code: it reads the pull request's
head SHA and repository through the API, and a fork's head is dispatched only when a person
starts the run (D-16, D-37)."""

import datetime as dt
import json
import re
import subprocess
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from shipmill.app import Access, Api, Lacks, NotInstalled, Permission, Signer, app_slug, check_key, jwt, mint
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


WORKFLOW = "downstream.yml"  # the library's caller of the reusable workflow; collect is dispatched on it
CHECKS_APP = "github-actions"  # the App a workflow's GITHUB_TOKEN writes checks as
SERVER = "https://github.com"
# what the App needs on a downstream: start its workflow, and read which branch is its default
DISPATCH_PERMISSIONS = (
    Permission("actions", "Actions", Access.WRITE),
    Permission("metadata", "Metadata", Access.READ),
)
FORK_TITLE = "a fork's pull request runs downstream tests only by hand"
_SHA = re.compile(r"[0-9a-f]{40}")


def check_name(name: str) -> str:
    return f"downstream: {name}"


def shipmill_id(library: str, pr: int, sha: str, name: str) -> str:
    """The id a downstream run's run-name carries, so collect finds the run the dispatch started"""
    return f"{library}#{pr}@{sha}/{name}"


def external_id(sid: str, dispatched: dt.datetime) -> str:
    """A check's external_id: the shipmill-id and the dispatch time, so the state lives on the
    forge (N-2). The time is taken just before the dispatch, so no run it started is older"""
    return f"{sid} {dispatched.astimezone(dt.UTC).isoformat(timespec='seconds')}"


class Status(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Conclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class Check:
    """A check run as written: its conclusion is None while it is in progress"""

    name: str
    status: Status
    conclusion: Conclusion | None
    title: str
    summary: str
    external_id: str = ""
    details_url: str = ""

    def payload(self) -> dict[str, object]:
        """The body of GitHub's create and update calls, without the head SHA"""
        body: dict[str, object] = {
            "name": self.name,
            "status": str(self.status),
            "output": {"title": self.title, "summary": self.summary},
        }
        if self.conclusion is not None:
            body["conclusion"] = str(self.conclusion)
        if self.external_id:
            body["external_id"] = self.external_id
        if self.details_url:
            body["details_url"] = self.details_url
        return body


@dataclass(frozen=True, slots=True)
class Pull:
    """The pull request as start reads it: never its code"""

    number: int
    head_sha: str  # the full 40-character SHA
    head_repo: str | None  # owner/name; None when the fork was deleted
    repo: str  # the library's owner/name, the pull request's base
    default_branch: str  # the library's

    @property
    def fork(self) -> bool:
        return self.head_repo is None or self.head_repo.lower() != self.repo.lower()


def parse_pull(found: Any, number: int) -> Pull:
    """GitHub's `GET /repos/<repo>/pulls/<N>` answer; anything else is refused"""

    def refuse(what: str) -> ReleaseError:
        return ReleaseError(f"GitHub's answer for pull request #{number} has {what}")

    if not isinstance(found, dict) or found.get("number") != number:
        raise refuse("no matching number")
    head, base = found.get("head"), found.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise refuse("no head or base")
    sha = head.get("sha")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise refuse("no full head SHA")
    head_repo = head.get("repo")  # null once the fork is deleted
    if head_repo is not None and (not isinstance(head_repo, dict) or not isinstance(head_repo.get("full_name"), str)):
        raise refuse("a head repository without a full_name")
    base_repo = base.get("repo")
    if (
        not isinstance(base_repo, dict)
        or not isinstance(base_repo.get("full_name"), str)
        or not isinstance(base_repo.get("default_branch"), str)
        or not base_repo["default_branch"]
    ):
        raise refuse("a base repository without a full_name or a default_branch")
    return Pull(
        number,
        sha,
        None if head_repo is None else str(head_repo["full_name"]),
        str(base_repo["full_name"]),
        str(base_repo["default_branch"]),
    )


class Library(Protocol):
    """The library's repository, as the reusable workflow's GITHUB_TOKEN reaches it"""

    def pull(self, number: int) -> Pull: ...

    def find_check(self, sha: str, name: str) -> int | None:
        """The id of the check with the name that this workflow's App wrote on the commit, the
        newest when there are several; None when there is none"""
        ...

    def create_check(self, sha: str, check: Check) -> int: ...

    def update_check(self, check_id: int, check: Check) -> None: ...

    def dispatch_collect(self, ref: str, pr: int, sha: str) -> None:
        """Start the library's WORKFLOW on ref with pr and collect=sha"""
        ...


class GhLibrary:
    """Library through the gh CLI, authenticated by GH_TOKEN in Actions; {owner}/{repo} is the
    checkout's origin. A body goes on stdin, never in argv"""

    def __init__(self, root: Path, gh: str = "gh") -> None:
        self.root = root
        self.gh = gh

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        proc = subprocess.run(
            [self.gh, *args], capture_output=True, text=True, encoding="utf-8", cwd=self.root, input=stdin
        )
        if proc.returncode != 0:
            raise ReleaseError(f"gh {' '.join(args[:4])} failed: {proc.stderr.strip()[:500]}")
        return proc.stdout

    def _json(self, *args: str, stdin: str | None = None) -> Any:
        out = self._gh(*args, stdin=stdin)
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            raise ReleaseError(f"gh {' '.join(args[:4])} printed no JSON") from None

    def pull(self, number: int) -> Pull:
        return parse_pull(self._json("api", f"repos/{{owner}}/{{repo}}/pulls/{number}"), number)

    def find_check(self, sha: str, name: str) -> int | None:
        found = self._json(
            "api", "-X", "GET", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
            "-f", f"check_name={name}", "-f", "filter=all", "-f", "per_page=100",
        )  # fmt: skip
        runs = found.get("check_runs") if isinstance(found, dict) else None
        if not isinstance(runs, list):
            raise ReleaseError(f"gh api printed no check_runs for {sha}")
        ids = []
        for run in runs:
            app = run.get("app") if isinstance(run, dict) else None
            if not isinstance(app, dict) or not isinstance(run.get("id"), int):
                raise ReleaseError(f"gh api printed a check run without an id or an app for {sha}")
            if run.get("name") == name and app.get("slug") == CHECKS_APP:
                ids.append(int(run["id"]))
        return max(ids) if ids else None

    def create_check(self, sha: str, check: Check) -> int:
        body = {**check.payload(), "head_sha": sha}
        found = self._json(
            "api", "-X", "POST", "repos/{owner}/{repo}/check-runs", "--input", "-", stdin=json.dumps(body)
        )
        if not isinstance(found, dict) or not isinstance(found.get("id"), int):
            raise ReleaseError(f"gh api printed no id for the check {check.name}")
        return int(found["id"])

    def update_check(self, check_id: int, check: Check) -> None:
        self._json(
            "api", "-X", "PATCH", f"repos/{{owner}}/{{repo}}/check-runs/{check_id}", "--input", "-",
            stdin=json.dumps(check.payload()),
        )  # fmt: skip

    def dispatch_collect(self, ref: str, pr: int, sha: str) -> None:
        self._gh("workflow", "run", WORKFLOW, "--ref", ref, "-f", f"pr={pr}", "-f", f"collect={sha}")


@dataclass(frozen=True, slots=True)
class Refusal:
    """A dispatch GitHub refused: its HTTP status and what fixes it"""

    status: int
    fix: str


class Dispatcher(Protocol):
    def dispatch(self, downstream: Downstream, inputs: Mapping[str, str]) -> Refusal | None:
        """Start the downstream's workflow on its ref with the inputs; a Refusal when GitHub
        refuses it for the App's installation or the workflow, None once it is started"""
        ...


def not_installed(app_id: int, repo: str) -> str:
    return f"the App {app_id} is not installed on {repo}, or lacks Actions: read and write"


def no_workflow(d: Downstream, ref: str) -> str:
    return f"{d.workflow} doesn't exist on {ref} in {d.repo}, or has no workflow_dispatch trigger"


class AppDispatcher:
    """Dispatches as the App: each downstream gets its own token, minted for app_id and limited
    to that downstream's repository and to DISPATCH_PERMISSIONS (D-14). A token is never
    printed, stored, or quoted in a message"""

    def __init__(self, app_id: int, key: Path, signer: Signer, api: Api, clock: Callable[[], dt.datetime]) -> None:
        self.app_id = app_id
        self.key = key
        self.signer = signer
        self.api = api
        self.clock = clock

    def dispatch(self, downstream: Downstream, inputs: Mapping[str, str]) -> Refusal | None:
        d = downstream
        try:
            token = mint(self.app_id, d.repo, self.key, self.clock(), self.signer, self.api, DISPATCH_PERMISSIONS)
        except NotInstalled:
            return Refusal(404, not_installed(self.app_id, d.repo))
        except Lacks:
            return Refusal(403, not_installed(self.app_id, d.repo))
        ref = d.ref
        if ref is None:
            path = f"/repos/{d.repo}"
            answer = self.api.get(path, token.value)
            if answer.status in {403, 404}:
                return Refusal(answer.status, not_installed(self.app_id, d.repo))
            ref = _default_branch(answer.status, answer.body, path)
        path = f"/repos/{d.repo}/actions/workflows/{urllib.parse.quote(d.workflow)}/dispatches"
        answer = self.api.post(path, token.value, {"ref": ref, "inputs": dict(inputs)})
        if answer.status == 204:
            return None
        if answer.status == 403:
            return Refusal(403, not_installed(self.app_id, d.repo))
        if answer.status in {404, 422}:  # 422: the workflow has no workflow_dispatch trigger, or other inputs
            return Refusal(answer.status, no_workflow(d, ref))
        raise ReleaseError(f"POST {path} answered {answer.status}: {answer.body.strip()[:300]}")


def _default_branch(status: int, body: str, path: str) -> str:
    if status != 200:
        raise ReleaseError(f"GET {path} answered {status}: {body.strip()[:300]}")
    try:
        found = json.loads(body)
    except json.JSONDecodeError:
        raise ReleaseError(f"GET {path} answered without JSON") from None
    branch = found.get("default_branch") if isinstance(found, dict) else None
    if not isinstance(branch, str) or not branch:
        raise ReleaseError(f"GET {path} gave no default_branch")
    return branch


KeyCheck = Callable[[], str | None]


def key_problem(app_id: int, key: Path, signer: Signer, api: Api, clock: Callable[[], dt.datetime]) -> KeyCheck:
    """What is wrong with the App's key, or None: missing or readable by others, empty, not a
    private key openssl signs with, or not App app_id's (GitHub refuses its JWT). The key's
    bytes are never read; openssl signs with its path"""

    def problem() -> str | None:
        try:
            check_key(key)
            if key.stat().st_size == 0:
                return f"the App private key {key} is empty; set SHIPMILL_DOWNSTREAM_KEY to App {app_id}'s key"
            app_slug(app_id, jwt(app_id, key, clock(), signer), api)
        except ReleaseError as exc:
            return str(exc)
        return None

    return problem


def _ref_text(d: Downstream) -> str:
    return d.ref if d.ref is not None else "its default branch"


def _ended(
    d: Downstream, conclusion: Conclusion, title: str, summary: str, details_url: str = "", mark: bool = True
) -> Check:
    """A completed check: a report-only downstream's is neutral, its title marked so unless
    mark is False"""
    if d.report_only:
        shown = f"report-only: {title}" if mark else title
        return Check(check_name(d.name), Status.COMPLETED, Conclusion.NEUTRAL, shown, summary, details_url=details_url)
    return Check(check_name(d.name), Status.COMPLETED, conclusion, title, summary, details_url=details_url)


def _write(library: Library, sha: str, check: Check) -> int:
    """Update the check this workflow already wrote on the commit with that name, else create
    it, so a rerun never adds a second"""
    found = library.find_check(sha, check.name)
    if found is None:
        return library.create_check(sha, check)
    library.update_check(found, check)
    return found


def start(
    config: DownstreamConfig,
    library: Library,
    dispatcher: Dispatcher,
    key: KeyCheck,
    pr: int,
    actor: str | None,
    origin: str | None,
    clock: Callable[[], dt.datetime],
) -> list[str]:
    """Spec 032, `downstream start`: a check per downstream on the pull request's head, each
    downstream's workflow dispatched, then collect dispatched on the library's default branch.
    actor is the person or bot who started a workflow_dispatch run, None on pull_request_target.
    origin is the checkout's GitHub repository when it is known. The lines it returns say what
    it did; a ReleaseError is exit 2"""
    for d in config.downstreams:
        if origin is not None and d.repo.lower() == origin.lower():
            raise ReleaseError(
                f"[downstream.{d.name}] names {d.repo}, this library's own repository; "
                "a downstream is another repository that depends on it"
            )
    pull = library.pull(pr)
    sha = pull.head_sha
    if pull.fork and actor is not None and actor.endswith("[bot]"):
        raise ReleaseError(f"a fork's downstream run is started by a person, not {actor}")
    if pull.fork and actor is None:
        return _hold_fork(config, library, pull)
    problem = key()
    if problem is not None:
        for d in config.downstreams:
            summary = f"Testing {pull.repo} at {sha}: shipmill couldn't start {d.workflow} in {d.repo}: {problem}"
            _write(library, sha, _ended(d, Conclusion.FAILURE, "couldn't start: the App's key", summary))
        raise ReleaseError(problem)
    lines = []
    started = 0
    for d in config.downstreams:
        sid = shipmill_id(pull.repo, pr, sha, d.name)
        summary = (
            f"Testing {pull.repo} at {sha} with {d.workflow} in {d.repo} on {_ref_text(d)}, "
            f"for up to {d.timeout_minutes} minutes.\n\nshipmill-id: `{sid}`"
        )
        if d.report_only:
            summary += "\n\nThis downstream is report-only: its result never holds the merge."
            running = Check(check_name(d.name), Status.COMPLETED, Conclusion.NEUTRAL, "report-only: running", summary)
        else:
            running = Check(check_name(d.name), Status.IN_PROGRESS, None, "running", summary)
        when = clock()
        check_id = _write(library, sha, replace(running, external_id=external_id(sid, when)))
        inputs = {"library-repo": pull.repo, "library-ref": sha, "shipmill-id": sid}
        try:
            refusal = dispatcher.dispatch(d, inputs)
        except ReleaseError as exc:  # recorded on the check before the exit 2
            failed = f"Testing {pull.repo} at {sha}: shipmill couldn't start {d.workflow} in {d.repo}: {exc}"
            library.update_check(check_id, _ended(d, Conclusion.FAILURE, "couldn't start", failed))
            if started:  # the runs already started still get a collector, or their checks never end
                library.dispatch_collect(pull.default_branch, pr, sha)
            raise
        if refusal is None:
            started += 1
            lines.append(f"{check_name(d.name)}: started {d.workflow} in {d.repo} on {_ref_text(d)} ({sid})")
            continue
        refused = (
            f"Testing {pull.repo} at {sha}: GitHub answered {refusal.status} to the dispatch of {d.workflow} "
            f"in {d.repo}.\n\nFix: {refusal.fix}."
        )
        library.update_check(check_id, _ended(d, Conclusion.FAILURE, f"couldn't start: {refusal.status}", refused))
        lines.append(f"{check_name(d.name)}: couldn't start, {refusal.status}: {refusal.fix}")
    if started:
        library.dispatch_collect(pull.default_branch, pr, sha)
        lines.append(f"started {WORKFLOW} on {pull.default_branch} to collect the results for {sha}")
    return lines


def _hold_fork(config: DownstreamConfig, library: Library, pull: Pull) -> list[str]:
    """A fork's head is code no maintainer has read: no dispatch until a person starts one"""
    where = pull.head_repo if pull.head_repo is not None else "a deleted fork"
    command = f"gh workflow run {WORKFLOW} -f pr={pull.number}"
    summary = (
        f"The head of this pull request, {pull.head_sha}, is in {where}, not {pull.repo}. A downstream's "
        "workflow would run it with the downstream's secrets on its runners, so it runs only once a "
        f"maintainer has read the change and starts it:\n\n```\n{command}\n```"
    )
    page = f"{SERVER}/{pull.repo}/actions/workflows/{WORKFLOW}"  # GitHub asks action_required for a details URL
    lines = []
    for d in config.downstreams:
        _write(library, pull.head_sha, _ended(d, Conclusion.ACTION_REQUIRED, FORK_TITLE, summary, page, mark=False))
        lines.append(f"{check_name(d.name)}: waits for a person: {command}")
    return lines
