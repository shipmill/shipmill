"""Land a release commit that passed CI: put it where its lane keeps releases, tag it, bring
a stable release made off main back into main, and publish it. A lane with after_publish
then waits for its publish runs and PyPI before it starts the workflows that move the
release's references (D-50)"""

import base64
import datetime as dt
import re
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from shipmill import fragments
from shipmill.app import LAND_PERMISSIONS, Api, AuthFailure, Signer, mint
from shipmill.environments import deployed_from
from shipmill.errors import ReleaseError
from shipmill.github import Forbidden, GitHub, OpenMilestone, close_milestone_args, set_milestone_args
from shipmill.gitrepo import Git
from shipmill.plugin import PYPI_PROJECT, Fetch
from shipmill.policy import Lane, Policy, VersionFiles
from shipmill.stamp import notes, stamp, sync
from shipmill.version import PATTERN, Version

WORK_PREFIX = "shipmill/"  # the branch a release commit waits on while CI runs
# A branch named the prefix itself blocks every work branch: git can't hold both
# refs/heads/X and refs/heads/X/...
BLOCKING_BRANCH = WORK_PREFIX.rstrip("/")
_SYNC_ATTEMPTS = 5
_TAG_RETRY_WAITS = (2, 5, 10, 0)  # seconds after each failed attempt; the last is not waited


def work_branch(version: Version) -> str:
    return f"{WORK_PREFIX}{version.tag}"


def blocked(work: str) -> str:
    """The problem and the fix when origin's BLOCKING_BRANCH stands in the way of a work branch"""
    return f"origin has a branch '{BLOCKING_BRANCH}', which blocks the work branch {work}; delete or rename it"


# GITHUB_WORKFLOW_REF: owner/repo/.github/workflows/<file>@<ref>; in a reusable workflow it
# names the caller, the release workflow whose runs share the work branch
_WORKFLOW_REF = re.compile(r"^[^/@]+/[^/@]+/\.github/workflows/(?P<file>[^/@]+\.ya?ml)@\S+$")


@dataclass(frozen=True, slots=True)
class ActionsRun:
    """The GitHub Actions run prepare runs in: its release workflow's file and its id"""

    workflow: str
    id: int

    @classmethod
    def parse(cls, ref: str, run_id: str) -> ActionsRun | None:
        """From GITHUB_WORKFLOW_REF and GITHUB_RUN_ID, which GitHub sets in every job; None
        when both are empty, outside Actions"""
        if not ref and not run_id:
            return None
        found = _WORKFLOW_REF.match(ref)
        if found is None or not run_id.isdigit():
            raise ReleaseError(
                f"GITHUB_WORKFLOW_REF={ref!r} and GITHUB_RUN_ID={run_id!r} name no workflow run:"
                " expected owner/repo/.github/workflows/<file>@<ref> and a number"
            )
        return cls(found["file"], int(run_id))


class Stop(StrEnum):
    """Why prepare left a work branch it found on origin alone"""

    OWNED = "owned"  # another queued or in-progress run of the release workflow may own it
    FORBIDDEN = "forbidden"  # the token can't list the workflow's runs: no actions: read
    OUTSIDE = "outside"  # not in an Actions run, so no run to compare with


@dataclass(frozen=True, slots=True)
class Prepared:
    changed: tuple[str, ...]
    sha: str  # empty unless committed
    pushed: bool  # the work branch was pushed; False when it was on origin and prepare stopped
    found: str = ""  # the work branch's commit prepare found on origin, else empty
    stop: Stop | None = None  # why prepare stopped at the branch it found; None when it pushed

    @property
    def recovered(self) -> bool:
        """Whether prepare deleted an orphaned work branch before pushing its own"""
        return self.pushed and bool(self.found)


def prepare(
    git: Git,
    policy: Policy,
    lane: Lane,
    version: Version,
    base: str,
    today: dt.date,
    merges: tuple[str, ...] = (),
    prs: tuple[int, ...] = (),
    commit: bool = False,
    push: bool = False,
    github: GitHub | None = None,
    run: ActionsRun | None = None,
) -> Prepared:
    """Check out base, stamp it as version, and optionally commit and push the work branch.
    A work branch already on origin is deleted first when no other queued or in-progress run
    of the release workflow could own it (D-18); otherwise prepare stops without pushing"""
    if git.dirty():
        raise ReleaseError("the checkout has uncommitted changes; prepare stamps a clean checkout")
    git.run("checkout", "-q", "--detach", base)
    changed = tuple(stamp(git, policy, lane, version, today, merges))
    if not commit:
        return Prepared(changed, "", False)
    git.run("add", "-A")
    subject = f"Release {version}"
    if prs:
        subject += f" (hotfix: {', '.join(f'#{p}' for p in prs)})"
    git.run("commit", "-q", "-m", subject)
    sha = git.sha()
    if not push:
        return Prepared(changed, sha, False)
    work = work_branch(version)
    found = git.remote_branch(work)
    if found is not None:
        if (stop := _held(github, run)) is not None:
            return Prepared(changed, sha, False, found, stop)
        # the lease deletes the branch only while it is still the commit no run owns
        if error := git.push(f"--force-with-lease=refs/heads/{work}:{found}", f":refs/heads/{work}"):
            raise ReleaseError(f"deleting the orphaned {work} at {found[:12]} was rejected: {error}")
    elif git.remote_branch(BLOCKING_BRANCH) is not None:
        raise ReleaseError(blocked(work))
    if error := git.push(f"{sha}:refs/heads/{work}"):
        raise ReleaseError(f"pushing {work} was rejected: {error}")
    return Prepared(changed, sha, True, found or "")


def _held(github: GitHub | None, run: ActionsRun | None) -> Stop | None:
    """Why the work branch on origin may still be in use, or None when it is orphaned: no
    other run of the release workflow is queued or in progress. Any such run counts, since
    one whose CI still runs on the branch must never lose it"""
    if github is None or run is None:
        return Stop.OUTSIDE
    try:
        active = github.active_runs(run.workflow)
    except Forbidden:
        return Stop.FORBIDDEN
    return Stop.OWNED if any(r.id != run.id for r in active) else None


WORKFLOW_BOT = "github-actions[bot]"  # who the workflow token pushes as
_EXTRAHEADER = "http.https://github.com/.extraheader"  # where actions/checkout persists the workflow token
# GitHub's refusal of a push by a branch's rules: GH013 for a ruleset, GH006's "Protected
# branch update failed" for classic protection
_RULES_REFUSE = re.compile(r"GH013|protected branch", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AppPush:
    """Spec 054: the App's installation token, limited to the repository with contents and
    workflows write, that pushes the protected branches (the release commit to the default
    branch, a hotfix to release/X.Y, the sync commit); repr leaves the token out"""

    token: str = field(repr=False)
    app_id: int

    @property
    def identity(self) -> str:
        return f"the App {self.app_id}"

    def config(self) -> tuple[tuple[str, str], ...]:
        """git's settings for a push as the App: the checkout's persisted header, the workflow
        token's, is cleared (an empty value resets the list) and the App's sent instead; they
        reach git through its environment, never its arguments (S-054-7)"""
        basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode("ascii")
        return ((_EXTRAHEADER, ""), (_EXTRAHEADER, f"AUTHORIZATION: basic {basic}"))


def mint_land(app_id: int, repo: str, key: Path, now: dt.datetime, signer: Signer, api: Api) -> AppPush:
    """S-054-5: one installation token limited to repo with LAND_PERMISSIONS, minted before
    land's first push. A missing key, an App not installed on repo, or an installation without
    those permissions fails naming the problem and its fix: land never falls back to the
    workflow token (D-14)"""
    try:
        token = mint(app_id, repo, key, now, signer, api, LAND_PERMISSIONS)
    except AuthFailure as exc:
        raise ReleaseError(
            f"land can't push as the App {app_id}, so it pushed nothing: {exc.problem}; fix: {exc.fix}"
        ) from None
    return AppPush(token.value, app_id)


def _branch_config(app: AppPush | None) -> tuple[tuple[str, str], ...]:
    """The push settings of a protected branch: the App's under spec 054, else none, so the
    push is the one land made before it (S-054-2)"""
    return () if app is None else app.config()


def _refused(what: str, branch: str, error: str, app: AppPush | None) -> ReleaseError:
    """A refused push of a protected branch: git's error, plus the fix when GitHub's branch
    rules refused it (S-054-9); any other refusal reads as before"""
    said = f"{what} was rejected: {error}"
    if _RULES_REFUSE.search(error):
        identity = WORKFLOW_BOT if app is None else app.identity
        said += (
            f"; {branch}'s rules refuse {identity}: run shipmill doctor, and see Protected default branch"
            " in docs/release-lanes.md"
        )
    return ReleaseError(said)


@dataclass(frozen=True, slots=True)
class Rollover:
    """What land did to the milestone titled a stable release, under close_milestone (spec
    068): the Release run's summary line, empty when it read or wrote none worth saying; and
    when a read or write failed, the problem with the command that does the write, else empty.
    A failure comes after the tag and the publish, so the release stands"""

    said: str = ""
    failed: str = ""


@dataclass(frozen=True, slots=True)
class Landed:
    tag: str
    placed: str  # where the release commit went: main, release/X.Y, or the tag alone
    synced: bool  # a sync commit brought the release into main
    published: tuple[str, ...]
    milestone: Rollover = Rollover()


def land(
    git: Git,
    policy: Policy,
    github: GitHub,
    lane: Lane,
    version: Version,
    sha: str,
    base: str,
    today: dt.date,
    retry_waits: tuple[int, ...] = _TAG_RETRY_WAITS,
    waiting: Waiting | None = None,
    app: AppPush | None = None,
) -> Landed:
    """Land the release commit sha as version. A lane with after_publish starts those
    workflows only once each dispatch run succeeded and, under version_files = 'pyproject',
    PyPI serves the version (D-50); waiting is how land waits, needed for such a lane. With
    app, the release commit's push to its branch and the sync commit's go as the App, while
    the tag keeps the workflow token (spec 054)"""
    branched = _branch_config(app)
    rule = policy.rule(lane)
    work = work_branch(version)
    git.fetch(f"+refs/heads/{work}:refs/remotes/origin/{work}")
    if git.sha(f"origin/{work}") != sha:
        raise ReleaseError(f"{work_branch(version)} is not at {sha[:12]}: another run replaced it")
    if git.remote_tag(version.tag):
        raise ReleaseError(f"{version.tag} exists on origin already")
    if git.first_parent(sha) != base:
        raise ReleaseError(f"{sha[:12]} is not a release commit on {base[:12]}")

    placed = "tag only"
    on_main = False
    if lane is Lane.STABLE and git.remote_branch(policy.branch) == base:
        if error := git.push(f"{sha}:refs/heads/{policy.branch}", config=branched):
            raise _refused(f"pushing {sha[:12]} to {policy.branch}", policy.branch, error, app)
        placed, on_main = policy.branch, True
    elif lane is Lane.HOTFIX:
        branch = f"release/{version.series}"
        current = git.remote_branch(branch)
        if current is not None and current != base:
            raise ReleaseError(f"{branch} moved to {current[:12]} since the hotfix was planned on {base[:12]}")
        if error := git.push(f"{sha}:refs/heads/{branch}", config=branched):
            raise _refused(f"pushing {sha[:12]} to {branch}", branch, error, app)
        placed = branch

    message = policy.tag_message.format(name=policy.name, version=version)
    git.run("tag", "-a", version.tag, "-m", message, sha)
    _push_tag(git, version, sha, retry_waits)

    released = git.show(sha, policy.changelog)
    if released is None:
        raise ReleaseError(f"no {policy.changelog} in {sha[:12]}")
    synced = False
    if lane in (Lane.STABLE, Lane.HOTFIX) and not on_main:
        newest = all(t.version <= version for t in git.tags() if t.version.is_stable)
        _sync_main(git, policy, version, released, today, newest, app)
        synced = True

    stable = [t.version for t in git.tags() if t.version.is_stable and t.version < version]
    since = max(stable) if stable else None
    published = []
    if rule.github_release:
        title = policy.release_title.format(name=policy.name, version=version)
        pending = fragments.entries(fragments.at_revision(git, policy, sha)) if not version.is_stable else []
        github.create_release(version.tag, title, notes(policy, released, version, since, pending), lane.is_pre)
        published.append("github-release")
    started: list[tuple[str, str | None]] = []
    for workflow in rule.dispatch:
        started.append((workflow, github.dispatch(workflow, policy.branch, version.tag)))
        published.append(workflow)
    for env in deployed_from(policy.environments, lane):
        # on the tag, so the deployment GitHub records names it as its ref: operate reads it there
        github.dispatch(env.workflow, version.tag, version.tag, env.inputs)
        published.append(f"{env.workflow}@{env.name}")
    if rule.after_publish:
        if waiting is None:
            raise ReleaseError(f"{lane} sets after_publish, and land was given no way to wait for the publish")
        held = _Held.of(policy, rule.after_publish, version, waiting.clock() + waiting.timeout)
        for workflow, url in started:
            _await_run(github, workflow, url, waiting, held)
        if (project := _pypi_project(git, policy, sha)) is not None:
            _await_pypi(project, version, waiting, held)
        for workflow in rule.after_publish:
            github.dispatch(workflow, policy.branch, version.tag)
            published.append(workflow)
    # last, after the publish and the references it moves (D-50): a milestone that fails leaves
    # the release as it stands (S-068-6); a pre-release closes nothing (S-068-5)
    rollover = roll_milestone(github, version) if rule.close_milestone and version.is_stable else Rollover()
    return Landed(version.tag, placed, synced, tuple(published), rollover)


_WRITER = "shipmill gh"  # the command a failed milestone write names: as the App where it is set (D-14)


def _command(args: tuple[str, ...]) -> str:
    return " ".join((_WRITER, *args))


def roll_milestone(github: GitHub, version: Version) -> Rollover:
    """Spec 068, D-95: close the open milestone titled the stable version, first moving its
    open issues to the open milestone titled the lowest stable version above it. With open
    issues and no such milestone it writes nothing, and spec 022's overtaken rename applies
    (S-022-10); with no open milestone titled the version it reads nothing more. Closed issues
    stay where they are. A read or a write that fails is returned, never raised"""
    title = str(version)
    try:
        found = github.open_milestones()
    except ReleaseError as exc:
        return Rollover(
            failed=f"milestone {title}: reading the open milestones failed, so it was left as it is: {exc};"
            " `shipmill milestones` names the milestone's fix once it reads"
        )
    own = next((m for m in found if m.title == title), None)
    if own is None:
        return Rollover()
    close = _command(close_milestone_args(own.number))
    if own.open_issues == 0:
        return _close(github, own, close, ())
    later = _next_milestone(found, version)
    if later is None:
        return Rollover(
            f"milestone {title} left open: it has open issues, and no open milestone is titled a stable version"
            " above it (spec 022 renames it once overtaken)"
        )
    try:
        listed = github.milestone_issues(title)
    except ReleaseError as exc:
        return Rollover(
            failed=f"milestone {title}: reading its issues failed, so none moved to {later.title} and it stays"
            f" open: {exc}; for each open issue N of {title} run"
            f" {_WRITER} api -X PATCH repos/{{owner}}/{{repo}}/issues/N -F milestone={later.number}, then {close}"
        )
    moved: list[int] = []
    for issue in listed.open:
        try:
            github.set_milestone(issue.number, later.number)
        except ReleaseError as exc:
            move = _command(set_milestone_args(issue.number, later.number))
            return Rollover(
                _moved(title, moved, later, closed=False),
                f"milestone {title}: moving #{issue.number} to {later.title} failed, so {title} stays open: {exc};"
                f" run {move}, the same for each open issue left in {title}, then {close}",
            )
        moved.append(issue.number)
    return _close(github, own, close, tuple(moved), later)


def _next_milestone(found: list[OpenMilestone], version: Version) -> OpenMilestone | None:
    """The open milestone titled the lowest stable version above version, as str of the
    version spells it; a title that is no stable version is ignored"""
    above: list[tuple[Version, OpenMilestone]] = []
    for m in found:
        if not PATTERN.fullmatch(m.title):
            continue
        titled = Version.parse(m.title)
        if titled.is_stable and str(titled) == m.title and titled > version:
            above.append((titled, m))
    return min(above, key=lambda pair: pair[0])[1] if above else None


def _moved(title: str, moved: Sequence[int], later: OpenMilestone | None, closed: bool) -> str:
    """`milestone X closed`, with `; #12, #14 moved to Y` when issues moved"""
    said = f"milestone {title} closed" if closed else f"milestone {title} left open"
    if moved and later is not None:
        said += f"; {', '.join(f'#{n}' for n in moved)} moved to {later.title}"
    return said


def _close(
    github: GitHub, own: OpenMilestone, close: str, moved: tuple[int, ...], later: OpenMilestone | None = None
) -> Rollover:
    try:
        github.close_milestone(own.number)
    except ReleaseError as exc:
        return Rollover(
            _moved(own.title, moved, later, closed=False) if moved else "",
            f"milestone {own.title}: closing it failed: {exc}; run {close}",
        )
    return Rollover(_moved(own.title, moved, later, closed=True))


PUBLISH_TIMEOUT = 30 * 60.0  # seconds land waits for the publish runs and PyPI, together (D-50)
PUBLISH_POLL = 15.0  # seconds between two reads of a run or of PyPI
_RUN_URL = re.compile(r"/actions/runs/(?P<id>\d+)$")


@dataclass(frozen=True, slots=True)
class Waiting:
    """How land waits for a release's publish before it starts the lane's after_publish
    workflows (D-50): PyPI's HTTP status for a URL (ReleaseError when no answer comes back), a
    monotonic clock, and a sleep, so a test waits without sleeping"""

    pypi: Fetch
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    timeout: float = PUBLISH_TIMEOUT
    poll: float = PUBLISH_POLL


@dataclass(frozen=True, slots=True)
class _Held:
    """One wait for a publish: when it gives up, and what a failed wait leaves undone, for its
    error: the after_publish workflows and the commands that start them by hand"""

    deadline: float  # on Waiting's clock
    workflows: tuple[str, ...]
    fix: str

    @classmethod
    def of(cls, policy: Policy, workflows: tuple[str, ...], version: Version, deadline: float) -> _Held:
        runs = "; ".join(f"gh workflow run {w} --ref {policy.branch} -f tag={version.tag}" for w in workflows)
        return cls(deadline, workflows, f"once {version.tag} is published, run {runs}")

    def say(self, problem: str) -> ReleaseError:
        names = ", ".join(self.workflows)
        return ReleaseError(
            f"{problem}; {names} not started, so the references stay on the previous release: {self.fix}"
        )


def _await_run(github: GitHub, workflow: str, url: str | None, waiting: Waiting, held: _Held) -> None:
    """Wait for the run land started to succeed; the run is the one GitHub named when it was
    dispatched, never the newest of its workflow"""
    found = _RUN_URL.search(url or "")
    if found is None:
        raise held.say(f"dispatching {workflow} named no run ({url!r}), so land can't wait for it")
    run = int(found["id"])
    while not (state := github.run_state(run)).done:
        if waiting.clock() >= held.deadline:
            raise held.say(f"{workflow} run {url} is still {state.status} after {waiting.timeout:.0f}s")
        waiting.sleep(waiting.poll)
    if state.conclusion != "success":
        raise held.say(f"{workflow} run {url} ended {state.conclusion or 'without a conclusion'}")


def _pypi_project(git: Git, policy: Policy, sha: str) -> str | None:
    """The project PyPI serves the release as: pyproject.toml's [project] name at the release
    commit, under version_files = 'pyproject'; None otherwise, when land waits on no index"""
    if policy.version_files is not VersionFiles.PYPROJECT:
        return None
    text = git.show(sha, "pyproject.toml")
    if text is None:
        raise ReleaseError(f"no pyproject.toml in {sha[:12]}, which version_files = 'pyproject' needs")
    name = tomllib.loads(text).get("project", {}).get("name")
    if not isinstance(name, str) or not name:
        raise ReleaseError(f"pyproject.toml in {sha[:12]} has no [project] name")
    return name


def _await_pypi(project: str, version: Version, waiting: Waiting, held: _Held) -> None:
    """Wait for PyPI to serve the project at the version: 200 for its release JSON"""
    url = PYPI_PROJECT.format(name=project, version=version)
    while True:
        try:
            status = waiting.pypi(url)
        except ReleaseError as exc:
            answer = f"no answer ({exc})"
        else:
            if status == 200:
                return
            answer = f"HTTP {status}"
        if waiting.clock() >= held.deadline:
            raise held.say(f"PyPI still answers {answer} for {url} after {waiting.timeout:.0f}s")
        waiting.sleep(waiting.poll)


def _push_tag(git: Git, version: Version, sha: str, retry_waits: tuple[int, ...]) -> None:
    """Push the release tag. A rejection is retried: by then the release commit is on its
    branch, so a tag that never arrives leaves a release no later run can finish"""
    errors = []
    for wait in retry_waits:
        if not (error := git.push(f"refs/tags/{version.tag}")):
            return
        errors.append(error)
        if git.remote_tag(version.tag):
            git.fetch(f"+refs/tags/{version.tag}:refs/tags/{version.tag}")
            if git.sha(version.tag) == sha:
                return  # the push landed although git reported an error
            raise ReleaseError(f"{version.tag} appeared on origin at another commit: {error}")
        time.sleep(wait)
    raise ReleaseError(f"pushing tag {version.tag} was rejected {len(errors)} times: {errors[-1]}")


def _sync_main(
    git: Git, policy: Policy, version: Version, released: str, today: dt.date, newest: bool, app: AppPush | None = None
) -> None:
    """Commit the release's CHANGELOG section (and version, when newest) onto main, retrying
    when a merge lands on main between the fetch and the push; a push the branch's rules
    refuse fails at once, since no retry passes them (S-054-9)"""
    for _ in range(_SYNC_ATTEMPTS):
        git.fetch(f"+refs/heads/{policy.branch}:refs/remotes/origin/{policy.branch}")
        git.run("checkout", "-q", "--detach", f"origin/{policy.branch}")
        sync(git, policy, version, released, today, newest)
        git.run("add", "-A")
        git.run("commit", "-q", "-m", f"Sync {version} into {policy.branch}")
        if not (error := git.push(f"HEAD:refs/heads/{policy.branch}", config=_branch_config(app))):
            return
        if _RULES_REFUSE.search(error):
            raise _refused(f"pushing the sync of {version} to {policy.branch}", policy.branch, error, app)
    raise ReleaseError(f"{policy.branch} kept moving: the sync of {version} failed {_SYNC_ATTEMPTS} times")


def cleanup(git: Git, version: Version) -> bool:
    """Delete the release commit's work branch; whether there was one"""
    if git.remote_branch(work_branch(version)) is None:
        return False
    if error := git.push(f":refs/heads/{work_branch(version)}"):
        raise ReleaseError(f"deleting {work_branch(version)} was rejected: {error}")
    return True
