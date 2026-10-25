"""Downstream tests (spec 032): the repositories that depend on this library, whose own test
workflows shipmill starts on a pull request and reads back as checks. This module holds the
[downstream] section of .github/shipmill.toml (D-4) and `downstream start`, which writes one
check per downstream on the pull request's head and dispatches each downstream's workflow
with a token minted for the App and limited to that downstream's repository, and `downstream
collect`, which finds each run start dispatched by its shipmill-id and concludes its check.

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

from shipmill.app import (
    Access,
    Answer,
    Api,
    Lacks,
    NotInstalled,
    Permission,
    Signer,
    Token,
    app_slug,
    check_key,
    default_key,
    installation,
    jwt,
    mint,
)
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
RUNNING = "running"  # a required check's title until collect concludes it
REPORT_RUNNING = "report-only: running"  # a report-only check is completed from the start: its title says it waits
_SHA = re.compile(r"[0-9a-f]{40}")
OLD_CALLER_FIX = "shipmill init --downstream --force"  # rewrites a caller written before the sha input


@dataclass(frozen=True, slots=True)
class CommitSha:
    """A full commit SHA as GitHub writes it: 40 lowercase hexadecimal characters, nothing else"""

    value: str

    def __post_init__(self) -> None:
        if not _SHA.fullmatch(self.value):
            raise ReleaseError(f"a commit SHA is 40 lowercase hexadecimal characters, got {self.value!r}")

    def __str__(self) -> str:
        return self.value


class HeadMoved(Exception):
    """A dispatched start named a head SHA the pull request no longer has: exit 1, nothing written.
    Not a ReleaseError, whose exit is 2: the run is refused, the setup is fine"""


def moved(pr: int, current: str, named: CommitSha) -> str:
    """The line a dispatched start prints when the head moved after the person read it"""
    return f"the head of #{pr} is {current}, not {named}; read the new commits and start again with -f sha={current}"


def dispatched_sha(text: str | None) -> CommitSha:
    """--sha of a workflow_dispatch start: the head SHA the person read; missing or malformed is
    a caller written before the sha input, or a bad dispatch"""
    if text is None or not _SHA.fullmatch(text):
        got = "no --sha" if text is None else f"--sha {text!r}"
        raise ReleaseError(
            f"a workflow_dispatch start names the head SHA the person read with --sha, the 40 lowercase "
            f"hexadecimal characters of the workflow's sha input; got {got}. Dispatch it with "
            f"-f sha=<head SHA>, and rewrite a caller without the sha input with `{OLD_CALLER_FIX}`"
        )
    return CommitSha(text)


def check_name(name: str) -> str:
    return f"downstream: {name}"


def shipmill_id(library: str, pr: int, sha: str, name: str) -> str:
    """The id a downstream run's run-name carries, so collect finds the run the dispatch started"""
    return f"{library}#{pr}@{sha}/{name}"


def external_id(sid: str, dispatched: dt.datetime) -> str:
    """A check's external_id: the shipmill-id and the dispatch time, so the state lives on the
    forge (N-2). The time is taken just before the dispatch, so no run it started is older"""
    return f"{sid} {dispatched.astimezone(dt.UTC).isoformat(timespec='seconds')}"


def parse_external_id(value: str, name: str) -> tuple[str, dt.datetime]:
    """external_id's inverse: the shipmill-id and the dispatch time start recorded on a check"""
    sid, _, when = value.rpartition(" ")
    try:
        dispatched = dt.datetime.fromisoformat(when)
    except ValueError:
        dispatched = None
    if not sid or dispatched is None or dispatched.tzinfo is None:
        raise ReleaseError(
            f"the check {check_name(name)} has external_id {value!r}, not the shipmill-id and dispatch time "
            "`downstream start` writes; rerun start"
        )
    return sid, dispatched


class Status(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Conclusion(StrEnum):
    """A check run's conclusion, as GitHub accepts and reports it"""

    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    STALE = "stale"


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
class Written:
    """A check as GitHub holds it on a commit: its id and what it says"""

    id: int
    check: Check


def parse_check(found: Any) -> Written:
    """A check run from GitHub's API; anything else is refused"""
    if not isinstance(found, dict) or not isinstance(found.get("id"), int) or not isinstance(found.get("name"), str):
        raise ReleaseError("GitHub's answer has a check run without an id or a name")
    name = str(found["name"])

    def text(value: object, what: str) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ReleaseError(f"GitHub's check run {name} has a {what} that isn't a string")
        return value

    output = found.get("output")
    if output is not None and not isinstance(output, dict):
        raise ReleaseError(f"GitHub's check run {name} has an output that isn't an object")
    shown = output or {}
    try:
        status = Status(str(found.get("status")))
        raw = found.get("conclusion")
        conclusion = None if raw is None else Conclusion(str(raw))
    except ValueError:
        raise ReleaseError(
            f"GitHub's check run {name} has status {found.get('status')!r} and conclusion {found.get('conclusion')!r}"
        ) from None
    check = Check(
        name,
        status,
        conclusion,
        text(shown.get("title"), "title"),
        text(shown.get("summary"), "summary"),
        text(found.get("external_id"), "external_id"),
        text(found.get("details_url"), "details_url"),
    )
    return Written(int(found["id"]), check)


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

    def read_check(self, sha: str, name: str) -> Written | None:
        """The check find_check names, as GitHub holds it; None when there is none"""
        ...

    def create_check(self, sha: str, check: Check) -> int: ...

    def update_check(self, check_id: int, check: Check) -> None: ...

    def dispatch_collect(self, ref: str, pr: int, sha: str) -> None:
        """Start the library's WORKFLOW on ref with pr, sha=sha, and collect=sha"""
        ...


class GhFailed(ReleaseError):
    """A gh call that exited non-zero; status is the HTTP status gh named, None when it named none"""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


_HTTP = re.compile(r"\bHTTP (\d{3})\b")  # gh api says "(HTTP 404)", gh secret list "HTTP 403:"


def _run_gh(gh: str, root: Path, args: tuple[str, ...], stdin: str | None) -> str:
    """gh's stdout; a failure is a GhFailed quoting its first arguments and stderr, which is
    only ever gh's or GitHub's message"""
    proc = subprocess.run([gh, *args], capture_output=True, text=True, encoding="utf-8", cwd=root, input=stdin)
    if proc.returncode != 0:
        status = _HTTP.search(proc.stderr)
        raise GhFailed(
            f"gh {' '.join(args[:4])} failed: {proc.stderr.strip()[:500]}", None if status is None else int(status[1])
        )
    return proc.stdout


class GhLibrary:
    """Library through the gh CLI, authenticated by GH_TOKEN in Actions; {owner}/{repo} is the
    checkout's origin. A body goes on stdin, never in argv"""

    def __init__(self, root: Path, gh: str = "gh") -> None:
        self.root = root
        self.gh = gh

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        return _run_gh(self.gh, self.root, args, stdin)

    def _json(self, *args: str, stdin: str | None = None) -> Any:
        out = self._gh(*args, stdin=stdin)
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            raise ReleaseError(f"gh {' '.join(args[:4])} printed no JSON") from None

    def pull(self, number: int) -> Pull:
        return parse_pull(self._json("api", f"repos/{{owner}}/{{repo}}/pulls/{number}"), number)

    def _newest(self, sha: str, name: str) -> dict[str, Any] | None:
        """The newest check run with the name this workflow's App wrote on the commit"""
        found = self._json(
            "api", "-X", "GET", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
            "-f", f"check_name={name}", "-f", "filter=all", "-f", "per_page=100",
        )  # fmt: skip
        runs = found.get("check_runs") if isinstance(found, dict) else None
        if not isinstance(runs, list):
            raise ReleaseError(f"gh api printed no check_runs for {sha}")
        ours: list[dict[str, Any]] = []
        for run in runs:
            app = run.get("app") if isinstance(run, dict) else None
            if not isinstance(app, dict) or not isinstance(run.get("id"), int):
                raise ReleaseError(f"gh api printed a check run without an id or an app for {sha}")
            if run.get("name") == name and app.get("slug") == CHECKS_APP:
                ours.append(run)
        return max(ours, key=lambda run: int(run["id"])) if ours else None

    def find_check(self, sha: str, name: str) -> int | None:
        newest = self._newest(sha, name)
        return None if newest is None else int(newest["id"])

    def read_check(self, sha: str, name: str) -> Written | None:
        newest = self._newest(sha, name)
        return None if newest is None else parse_check(newest)

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
        try:
            self._gh(
                "workflow", "run", WORKFLOW, "--ref", ref, "-f", f"pr={pr}", "-f", f"sha={sha}", "-f", f"collect={sha}"
            )  # fmt: skip
        except GhFailed as exc:
            if exc.status == 422:  # a caller written before the sha input refuses it as unexpected
                raise ReleaseError(
                    f"{exc}; a {WORKFLOW} without the sha input is rewritten with `{OLD_CALLER_FIX}`"
                ) from None
            raise


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
    pinned: CommitSha | None = None,
) -> list[str]:
    """Spec 032, `downstream start`: a check per downstream on the pull request's head, each
    downstream's workflow dispatched, then collect dispatched on the library's default branch.
    actor is the person or bot who started a workflow_dispatch run, None on pull_request_target.
    pinned is the head SHA that person read, which a workflow_dispatch start needs: when the
    head is another, start writes, mints, and dispatches nothing and raises HeadMoved (exit 1).
    origin is the checkout's GitHub repository when it is known. The lines it returns say what
    it did; a ReleaseError is exit 2"""
    if actor is not None and pinned is None:
        dispatched_sha(None)  # raises: a person's start names the head it is for
    if actor is None and pinned is not None:
        raise ReleaseError("--sha pins a workflow_dispatch start, which names its --actor; omit it otherwise")
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
    if pinned is not None and pinned.value != sha:  # before any check, token, or dispatch (S-032-18)
        raise HeadMoved(moved(pr, sha, pinned))
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
            running = Check(check_name(d.name), Status.COMPLETED, Conclusion.NEUTRAL, REPORT_RUNNING, summary)
        else:
            running = Check(check_name(d.name), Status.IN_PROGRESS, None, RUNNING, summary)
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
    command = f"gh workflow run {WORKFLOW} -f pr={pull.number} -f sha={pull.head_sha}"
    summary = (
        f"The head of this pull request, {pull.head_sha}, is in {where}, not {pull.repo}. A downstream's "
        "workflow would run it with the downstream's secrets on its runners, so it runs only once a "
        f"maintainer has read the change at this commit and starts it for that commit; the run refuses "
        f"any other head:\n\n```\n{command}\n```"
    )
    page = f"{SERVER}/{pull.repo}/actions/workflows/{WORKFLOW}"  # GitHub asks action_required for a details URL
    lines = []
    for d in config.downstreams:
        _write(library, pull.head_sha, _ended(d, Conclusion.ACTION_REQUIRED, FORK_TITLE, summary, page, mark=False))
        lines.append(f"{check_name(d.name)}: waits for a person: {command}")
    return lines


NO_RUN_WITHIN = dt.timedelta(minutes=2)  # a dispatched run shows within this, or its run-name lacks the id
POLL_SECONDS = 30
RUN_NAME_RULE = "its run-name must contain inputs.shipmill-id"
# what collect needs on a downstream: read its workflow runs and their jobs, never write
READ_PERMISSIONS = (
    Permission("actions", "Actions", Access.READ),
    Permission("metadata", "Metadata", Access.READ),
)
_JOB_NAME = 100  # characters of a job's name a summary shows
_UNSAFE = re.compile(r"[`\x00-\x1f\x7f]+")  # a job's name is the downstream's text: no code span break, no newline


class RunConclusion(StrEnum):
    """A workflow run's or a job's conclusion, as GitHub reports it"""

    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    STALE = "stale"
    STARTUP_FAILURE = "startup_failure"

    @property
    def failed(self) -> bool:
        """A job that failed; a run passes only on success"""
        return self not in {RunConclusion.SUCCESS, RunConclusion.NEUTRAL, RunConclusion.SKIPPED}


@dataclass(frozen=True, slots=True)
class Run:
    """A downstream workflow run as collect reads it: its id, its page, and its conclusion,
    never its run-name beyond the shipmill-id nor its logs"""

    id: int
    url: str
    conclusion: RunConclusion | None  # None until it completes


class Runs(Protocol):
    """The downstream repositories' workflow runs, as the App reads them"""

    def find(self, downstream: Downstream, sid: str, since: dt.datetime) -> Run | Refusal | None:
        """The newest workflow_dispatch run of the downstream's workflow created at or after
        since whose run-name carries sid; None while there is none; a Refusal when GitHub
        refuses the read for the App's installation or the workflow"""
        ...

    def failed_jobs(self, downstream: Downstream, run: Run) -> tuple[str, ...]:
        """The names of the run's failed jobs, made safe to show"""
        ...


def _object(answer: Answer, path: str) -> dict[str, Any]:
    if answer.status != 200:
        raise ReleaseError(f"GET {path} answered {answer.status}: {answer.body.strip()[:300]}")
    try:
        found = json.loads(answer.body)
    except json.JSONDecodeError:
        raise ReleaseError(f"GET {path} answered without JSON") from None
    if not isinstance(found, dict):
        raise ReleaseError(f"GET {path} answered with JSON that is not an object")
    return found


def _instant(value: object, path: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            found = dt.datetime.fromisoformat(value)
        except ValueError:
            found = None
        if found is not None and found.tzinfo is not None:
            return found
    raise ReleaseError(f"GET {path} gave a run with created_at {value!r}, not a time with an offset")


def _conclusion(value: object, path: str) -> RunConclusion:
    try:
        return RunConclusion(str(value))
    except ValueError:
        raise ReleaseError(f"GET {path} gave the conclusion {value!r}, which shipmill doesn't know") from None


def job_name(name: str) -> str:
    """A job's name as a summary shows it: one line, no backtick, at most _JOB_NAME characters"""
    shown = " ".join(_UNSAFE.sub(" ", name).split())
    return shown if len(shown) <= _JOB_NAME else shown[: _JOB_NAME - 1] + "…"


class AppRuns:
    """Reads the downstream runs as the App: a token per downstream repository, minted for
    app_id, limited to that repository and to READ_PERMISSIONS, and minted again before it
    expires. A token is never printed, stored, or quoted in a message"""

    def __init__(self, app_id: int, key: Path, signer: Signer, api: Api, clock: Callable[[], dt.datetime]) -> None:
        self.app_id = app_id
        self.key = key
        self.signer = signer
        self.api = api
        self.clock = clock
        self._tokens: dict[str, Token] = {}

    def _token(self, repo: str) -> Token | Refusal:
        now = self.clock()
        held = self._tokens.get(repo)
        if held is not None and held.reusable(repo, self.app_id, now):
            return held
        try:
            token = mint(self.app_id, repo, self.key, now, self.signer, self.api, READ_PERMISSIONS)
        except NotInstalled:
            return Refusal(404, not_installed(self.app_id, repo))
        except Lacks:
            return Refusal(403, not_installed(self.app_id, repo))
        self._tokens[repo] = token
        return token

    def find(self, downstream: Downstream, sid: str, since: dt.datetime) -> Run | Refusal | None:
        d = downstream
        token = self._token(d.repo)
        if isinstance(token, Refusal):
            return token
        created = since.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = urllib.parse.urlencode({"event": "workflow_dispatch", "created": f">={created}", "per_page": "100"})
        path = f"/repos/{d.repo}/actions/workflows/{urllib.parse.quote(d.workflow)}/runs?{query}"
        answer = self.api.get(path, token.value)
        if answer.status == 403:
            return Refusal(403, not_installed(self.app_id, d.repo))
        if answer.status == 404:
            return Refusal(404, no_workflow(d, _ref_text(d)))
        runs = _object(answer, path).get("workflow_runs")
        if not isinstance(runs, list):
            raise ReleaseError(f"GET {path} gave no workflow_runs")
        # not the id of a downstream named longer, nor of a library whose owner's name ends with this one's
        carries = re.compile(r"(?<![A-Za-z0-9-])" + re.escape(sid) + r"(?![a-z0-9-])")
        matched: list[dict[str, Any]] = []
        for run in runs:
            if not isinstance(run, dict) or not isinstance(run.get("id"), int):
                raise ReleaseError(f"GET {path} gave a run without an id")
            title = run.get("display_title")
            if not isinstance(title, str):
                raise ReleaseError(f"GET {path} gave run {run['id']} without a display_title")
            if carries.search(title) and _instant(run.get("created_at"), path) >= since:
                matched.append(run)
        if not matched:
            return None
        newest = max(matched, key=lambda run: int(run["id"]))
        run_id = int(newest["id"])
        status = newest.get("status")
        if not isinstance(status, str):
            raise ReleaseError(f"GET {path} gave run {run_id} without a status")
        conclusion = _conclusion(newest.get("conclusion"), path) if status == "completed" else None
        return Run(run_id, f"{SERVER}/{d.repo}/actions/runs/{run_id}", conclusion)

    def failed_jobs(self, downstream: Downstream, run: Run) -> tuple[str, ...]:
        d = downstream
        token = self._token(d.repo)
        if isinstance(token, Refusal):
            raise ReleaseError(f"shipmill can't read the jobs of {run.url}: {token.fix}")
        path = f"/repos/{d.repo}/actions/runs/{run.id}/jobs?filter=latest&per_page=100"
        jobs = _object(self.api.get(path, token.value), path).get("jobs")
        if not isinstance(jobs, list):
            raise ReleaseError(f"GET {path} gave no jobs")
        failed = []
        for job in jobs:
            if not isinstance(job, dict) or not isinstance(job.get("name"), str):
                raise ReleaseError(f"GET {path} gave a job without a name")
            raw = job.get("conclusion")
            if raw is not None and _conclusion(raw, path).failed:
                failed.append(job_name(str(job["name"])))
        return tuple(failed)


@dataclass(frozen=True, slots=True)
class _Watch:
    """A check collect waits on: as it last wrote it, and what start recorded in it"""

    downstream: Downstream
    check_id: int
    check: Check
    sid: str
    dispatched: dt.datetime


def waiting(check: Check) -> bool:
    """A check without a result yet: a required one still in progress, or a report-only one,
    completed from the start, still titled running"""
    return check.status is not Status.COMPLETED or check.title == REPORT_RUNNING


def _result(library: str, sha: str, d: Downstream, run: Run, jobs: tuple[str, ...], how: str) -> str:
    """S-032-10: the SHA tested, the run's link, and its failed jobs' names; no line of its logs"""
    lines = [f"Tested {library} at {sha} with {d.workflow} in {d.repo}{how}.", "", f"Downstream run: {run.url}", ""]
    if jobs:
        lines += ["Failed jobs:", *(f"- `{name}`" for name in jobs)]
    else:
        lines.append("Failed jobs: none")
    lines += ["", f"The run's logs stay in {d.repo}; this check copies none of them."]
    return "\n".join(lines)


def _conclude(library: Library, w: _Watch, check: Check) -> str:
    """Write the check's result, once: collect stops watching it"""
    library.update_check(w.check_id, replace(check, external_id=w.check.external_id))
    return f"{check.name}: {check.title}"


def _look(library: Library, runs: Runs, repo: str, sha: str, w: _Watch, now: dt.datetime) -> _Watch | str:
    """One look at a check's downstream run: the watch while it waits, else the line saying
    how its check was concluded"""
    d = w.downstream
    found = runs.find(d, w.sid, w.dispatched)
    if isinstance(found, Refusal):
        refused = (
            f"Testing {repo} at {sha}: GitHub answered {found.status} to reading the runs of {d.workflow} "
            f"in {d.repo}.\n\nFix: {found.fix}."
        )
        return _conclude(library, w, _ended(d, Conclusion.FAILURE, f"couldn't read: {found.status}", refused))
    if found is None:
        if now - w.dispatched < NO_RUN_WITHIN:
            return w
        missing = (
            f"Testing {repo} at {sha}: no run of {d.workflow} in {d.repo} has {w.sid} in its run-name within "
            f"2 minutes of the dispatch; {RUN_NAME_RULE}."
        )
        return _conclude(library, w, _ended(d, Conclusion.FAILURE, "couldn't start: no run", missing))
    if w.check.details_url != found.url:
        linked = replace(
            w.check,
            details_url=found.url,
            summary=f"Testing {repo} at {sha} with {d.workflow} in {d.repo}.\n\nDownstream run: {found.url}",
        )
        library.update_check(w.check_id, linked)
        w = replace(w, check=linked)
    if found.conclusion is RunConclusion.SUCCESS:
        summary = _result(repo, sha, d, found, runs.failed_jobs(d, found), "")
        return _conclude(library, w, _ended(d, Conclusion.SUCCESS, "passed", summary, found.url))
    if found.conclusion is not None:
        summary = _result(repo, sha, d, found, runs.failed_jobs(d, found), "")
        return _conclude(library, w, _ended(d, Conclusion.FAILURE, f"failed: {found.conclusion}", summary, found.url))
    if now - w.dispatched < dt.timedelta(minutes=d.timeout_minutes):
        return w
    how = f"; the run didn't complete within {d.timeout_minutes} minutes of the dispatch and is left running"
    summary = _result(repo, sha, d, found, runs.failed_jobs(d, found), how)
    title = f"timed out after {d.timeout_minutes} minutes"
    return _conclude(library, w, _ended(d, Conclusion.TIMED_OUT, title, summary, found.url))


def collect(
    config: DownstreamConfig,
    library: Library,
    runs: Runs,
    pr: int,
    sha: str,
    clock: Callable[[], dt.datetime],
    sleep: Callable[[float], None],
) -> list[str]:
    """Spec 032, `downstream collect`: each `downstream: <name>` check on sha still without a
    result is linked to the downstream run start dispatched, found by its shipmill-id, and
    concluded once that run completes, its timeout passes, or no run shows within 2 minutes.
    It looks every POLL_SECONDS. The lines it returns say what it did; a ReleaseError is exit 2"""
    if not _SHA.fullmatch(sha):
        raise ReleaseError(f"--head is the full 40-character head SHA, got {sha!r}")
    pull = library.pull(pr)
    lines = []
    watching = []
    for d in config.downstreams:
        name = check_name(d.name)
        written = library.read_check(sha, name)
        if written is None:
            lines.append(f"{name}: no check on {sha}; nothing to collect")
            continue
        if not waiting(written.check):
            lines.append(f"{name}: already concluded: {written.check.title}")
            continue
        sid, dispatched = parse_external_id(written.check.external_id, d.name)
        expected = shipmill_id(pull.repo, pr, sha, d.name)
        if sid != expected:
            raise ReleaseError(f"the check {name} on {sha} records the shipmill-id {sid}, not {expected}; rerun start")
        watching.append(_Watch(d, written.id, written.check, sid, dispatched))
    while watching:
        now = clock()
        still = []
        for w in watching:
            looked = _look(library, runs, pull.repo, sha, w, now)
            if isinstance(looked, str):
                lines.append(looked)
            else:
                still.append(looked)
        watching = still
        if watching:
            sleep(POLL_SECONDS)
    return lines


SECRET = "SHIPMILL_DOWNSTREAM_KEY"  # the library's repository secret holding the App's private key
INPUTS = ("library-repo", "library-ref", "shipmill-id")  # what a downstream's workflow_dispatch declares


class Unreadable(ReleaseError):
    """The maintainer's login can't read a downstream repository"""


@dataclass(frozen=True, slots=True)
class Found:
    """A downstream's workflow file as doctor read it: the ref read, and its text, None when
    the file isn't on that ref"""

    ref: str
    text: str | None


class Reader(Protocol):
    """What doctor reads through the maintainer's own gh"""

    def secrets(self) -> frozenset[str]:
        """The names of the library's repository secrets; never their values"""
        ...

    def workflow(self, downstream: Downstream) -> Found:
        """The downstream's workflow file on its ref, or its default branch; Unreadable when
        the login can't read the repository"""
        ...


class GhReader:
    """Reader through the maintainer's gh; {owner}/{repo} is the checkout's origin"""

    def __init__(self, root: Path, gh: str = "gh") -> None:
        self.root = root
        self.gh = gh

    def secrets(self) -> frozenset[str]:
        out = _run_gh(self.gh, self.root, ("secret", "list", "--app", "actions", "--json", "name"), None)
        try:
            found = json.loads(out)
        except json.JSONDecodeError:
            raise ReleaseError("gh secret list printed no JSON") from None
        if not isinstance(found, list) or not all(
            isinstance(s, dict) and isinstance(s.get("name"), str) for s in found
        ):
            raise ReleaseError("gh secret list printed something other than a list of names")
        return frozenset(str(s["name"]) for s in found)

    def workflow(self, downstream: Downstream) -> Found:
        d = downstream
        try:
            meta = _run_gh(self.gh, self.root, ("api", f"repos/{d.repo}"), None)
        except GhFailed as exc:
            if exc.status in {403, 404}:
                raise Unreadable(f"your gh login can't read {d.repo}") from None
            raise
        ref = d.ref if d.ref is not None else _default_branch(200, meta, f"/repos/{d.repo}")
        path = f"repos/{d.repo}/contents/.github/workflows/{urllib.parse.quote(d.workflow)}"
        query = urllib.parse.urlencode({"ref": ref})
        try:
            text = _run_gh(
                self.gh, self.root, ("api", "-H", "Accept: application/vnd.github.raw", f"{path}?{query}"), None
            )
        except GhFailed as exc:
            if exc.status == 404:
                return Found(ref, None)
            raise
        return Found(ref, text)


Installed = Callable[[str], None]  # raises NotInstalled or Lacks when the App can't start a run on the repo


def app_on_host(
    key: Path | None, home: Path, signer: Signer, api: Api, clock: Callable[[], dt.datetime]
) -> Callable[[int], Installed | None]:
    """doctor's look at the App on each downstream: given [downstream] app_id, a check of its
    installation on a repo, or None when the key isn't on the host (no key passed and none at
    the default path app.py names). The check asks for DISPATCH_PERMISSIONS, which cover the
    reads collect makes; the key's bytes are never read. A key passed that isn't a file only
    its owner can read raises ReleaseError at once, never a WARN per downstream"""

    def probe(app_id: int) -> Installed | None:
        path = key if key is not None else default_key(app_id, home)
        if key is None and not path.exists():
            return None
        if key is not None:
            check_key(key)

        def installed(repo: str) -> None:
            installation(app_id, repo, jwt(app_id, check_key(path), clock(), signer), api, DISPATCH_PERMISSIONS)

        return installed

    return probe
