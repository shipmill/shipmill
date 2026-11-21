"""shipmill operate: watch each environment in [environments] and move releases along.

Each run reads what runs where from GitHub's deployments, checks each environment's health
URL, records the result as a deployment status (the health history: no state lives outside
GitHub, D-6), and then:

- promotes: an environment with `from` gets the tag its source has run healthily for
  `bake_minutes`, counted from the source deployment's success, every check since passing
- catches a missed deploy: an environment with `lane` that is behind its lane's newest tag
  (land's dispatch failed, say) gets that tag

Either deploy follows the environment's deploy autonomy under the hold: act dispatches its
workflow, propose opens or updates one issue that `--approve <env>` acts on, observe only
reports. A proposal closes once the environment runs its tag or a later one, whoever
deployed it. shipmill deploys a tag to an environment at most once: a deployment of that tag
there, in any state, means it was tried, and so does a run of the environment's workflow on
the tag (still queued, or failed before its deploy job made a deployment).

Health: a GET of `health` answering 2xx within 10 s. When the body is a JSON object with a
string `version`, it must name the deployed release (`1.2.0` or `v1.2.0`), so a stale
instance answering 200 doesn't count as healthy. Statuses are written only when the state
changes: `in_progress` while baking, `success` once baked (or at once when nothing is
promoted from the environment). A failed check writes `failure`, which restarts the bake,
once per check until `[operate] rollback_after` of them stand in a row: those statuses are
the count of failed checks, so a failing stretch writes at most that many.

Rollback and incidents: at `rollback_after` failed checks in a row, operate opens one issue
labelled `[operate] incident_label` per environment and bad tag (found again by a hidden
line holding the environment, the tags, and its state), and rolls the environment back to
the previous tag that reached success there, under the rollback autonomy and the hold: act
starts the environment's workflow on that tag; propose (or act under a hold, D-8) has the
incident say so, and `--approve-rollback <env>` does it once; observe only says so. A
rollback is the one deploy exempt from deploying a tag at most once: its tag ran there
before by definition. It is still started once: a deployment of it after the bad one, or a
run of the workflow on it since the checks began failing, means it was. Later runs comment
on the incident instead of opening another: when the environment is healthy again, and
when the rollback's tag fails its checks too, where shipmill stops rather than guess a
second time. The planner holds the blocker lanes while an incident is open.

Compare (spec 084): an environment that declares probes has its current deployment's answers
compared once with the previous release's, at its first passing check, each probe a GET of
the address the deploy job's `environment: url` recorded. Every counted probe the same writes
a `shipmill compare:` success status, which is not part of the health history. A difference
is explained by a `Changes answers:` line in the body of a pull request merged between the
two tags, which also writes success; an unexplained one opens the incident at once (its
hidden line holding `cause=compare`), rolls back as a failed health check does, writes a
`failure` compare status, and keeps the deployment from promotion and from being a rollback's
target. A compare incident reads healthy again only once another tag passes its check."""

import datetime as dt
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from shipmill.autonomy import HOLD_LABEL, Autonomy, EnvironmentName, Hold, Stage
from shipmill.doctor import OPERATE_CALLER
from shipmill.environments import Environment, Pointer
from shipmill.environments import Probe as DeclaredProbe
from shipmill.errors import ReleaseError
from shipmill.github import Deployment, DeploymentState, DeploymentStatus, GitHub, Issue, WorkflowRun, address
from shipmill.gitrepo import Git, Tag
from shipmill.policy import Lane, Policy
from shipmill.propose import find_proposal, upsert
from shipmill.version import PATTERN, TAG_PREFIX, Version

HEALTH_TIMEOUT = 10.0  # seconds
MISSED_GRACE = dt.timedelta(minutes=30)  # land dispatches right after tagging; give that deploy time to show
STATUS_PREFIX = "shipmill health"  # starts the description of every health status shipmill writes
COMPARE_PREFIX = "shipmill compare:"  # starts a compare status's (spec 084), which is not a health status
BODY_LIMIT = 64 * 1024  # bytes of a health answer read
PROBE_BODY_LIMIT = 1024 * 1024  # bytes of a probe's answer read
_DESCRIPTION_LIMIT = 140  # GitHub's limit on a status description
_EXCERPT_LIMIT = 300  # characters of a failing health body an incident quotes
_POINTERS_SHOWN = 10  # differing JSON pointers a compare incident names per probe
_POINTER_LIMIT = 120  # characters of one pointer it shows
_SHA = re.compile(r"[0-9a-f]{40}")


# -- health ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: str
    seconds: float  # from the request to the end of the body


class Unreachable(Exception):
    """The health URL gave no HTTP answer: refused, timed out, or a broken response"""


class Http(Protocol):
    def get(self, url: str, timeout: float, limit: int = BODY_LIMIT) -> HttpResponse:
        """GET the URL with no body, cookie, or credential, reading up to limit bytes of the
        answer; raises Unreachable when no HTTP answer comes back"""
        ...


class UrllibHttp:
    def get(self, url: str, timeout: float, limit: int = BODY_LIMIT) -> HttpResponse:
        request = urllib.request.Request(url, headers={"User-Agent": "shipmill-operate"})
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                body = answer.read(limit)
                status = int(answer.status)
        except urllib.error.HTTPError as exc:  # 4xx and 5xx: an answer, not a broken connection
            try:
                body = exc.read(limit) if exc.fp is not None else b""
            except OSError, http.client.HTTPException:  # the status is the answer; its body is a bonus
                body = b""
            return HttpResponse(exc.code, body.decode(errors="replace"), time.monotonic() - start)
        except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSErrors
            raise Unreachable(str(getattr(exc, "reason", exc))) from exc
        return HttpResponse(status, body.decode(errors="replace"), time.monotonic() - start)


@dataclass(frozen=True, slots=True)
class Probe:
    healthy: bool
    detail: str
    excerpt: str = ""  # the start of the body, on one line, for an incident to quote


_REDACTED = "[redacted]"
_SECRET_VALUE = re.compile(  # the value after a key that names a secret: "password": "x", token=x
    r"""(?i)(["']?[\w-]*(?:passw|pwd|secret|token|api[_-]?key|auth|cookie|session|credential)[\w-]*["']?"""
    r"""\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;&}]+)"""
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[^\s\"',;}]+")
_URL_USER = re.compile(r"(\w+://)[^/\s@]+@")  # credentials in a URL the body names
_OPAQUE = re.compile(r"(?<![\w+/=.-])(?=[\w+/=.-]*\d)(?=[\w+/=.-]*[A-Za-z])[\w+/=.-]{32,}")  # a key or hash


def _redacted(match: re.Match[str]) -> str:
    value = match[2]
    quote = value[0] if value[0] in "\"'" else ""
    return f"{match[1]}{quote}{_REDACTED}{quote}"


def excerpt(body: str) -> str:
    """The start of a health body on one line, capped, with no backticks to break a code span
    and nothing that looks like a secret: a secret key's value, a bearer token, a URL's
    credentials, or a long opaque string (an incident is an issue anyone with read sees)"""
    flat = " ".join(body.split()).replace("`", "'")
    flat = _SECRET_VALUE.sub(_redacted, flat)
    flat = _BEARER.sub(lambda m: f"{m[1]} {_REDACTED}", flat)
    flat = _URL_USER.sub(lambda m: f"{m[1]}{_REDACTED}@", flat)
    flat = _OPAQUE.sub(_REDACTED, flat)
    return flat if len(flat) <= _EXCERPT_LIMIT else flat[: _EXCERPT_LIMIT - 3] + "..."


def shown_url(url: str) -> str:
    """The health URL as an incident shows it: no user, password, query, or fragment, which
    may carry a token"""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return f"{parts.scheme}://{host}{f':{parts.port}' if parts.port else ''}{parts.path}"


def probe(http: Http, url: str, deployed: Version) -> Probe:
    try:
        answer = http.get(url, HEALTH_TIMEOUT)
    except Unreachable as exc:
        return Probe(False, f"unreachable: {exc}")
    quoted = excerpt(answer.body)
    if not 200 <= answer.status < 300:
        return Probe(False, f"HTTP {answer.status}", quoted)
    if answer.seconds > HEALTH_TIMEOUT:
        return Probe(False, f"answered in {answer.seconds:.1f} s, over {HEALTH_TIMEOUT:.0f} s", quoted)
    named = named_version(answer.body)
    if named is not None and named not in (str(deployed), deployed.tag):
        return Probe(False, f"answers version {named}, but {deployed.tag} is deployed", quoted)
    return Probe(True, f"HTTP {answer.status}" + (f", version {named}" if named else ""), quoted)


def named_version(body: str) -> str | None:
    """The version a health body names: a JSON object's top-level string `version`; any
    other body names none"""
    try:
        found = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(found, dict) and isinstance(found.get("version"), str):
        return str(found["version"])
    return None


# -- what runs where -------------------------------------------------------------------------


def tag_of(deployment: Deployment, tags: Sequence[Tag]) -> Version | None:
    """The release a deployment runs: its ref when that is a release tag (shipmill dispatches
    deploys on the tag), else the newest release tag on its ref when the ref is a sha"""
    ref = deployment.ref.removeprefix("refs/tags/")
    if ref.startswith(TAG_PREFIX) and PATTERN.fullmatch(ref[len(TAG_PREFIX) :]):
        return Version.of_tag(ref)
    if _SHA.fullmatch(ref):
        on = [t.version for t in tags if t.commit == ref]
        return max(on) if on else None
    return None


def _ours(status: DeploymentStatus) -> bool:
    """A health status shipmill wrote"""
    return status.description.startswith(STATUS_PREFIX)


def _compared(status: DeploymentStatus) -> bool:
    """A compare status shipmill wrote: not part of the health history"""
    return status.description.startswith(COMPARE_PREFIX)


def _differed(statuses: Sequence[DeploymentStatus]) -> bool:
    """Whether a deployment carries a failure compare status: its answers differ from the
    previous release's, unexplained, so it is neither promoted nor rolled back to (spec 084)"""
    return any(_compared(s) and s.state is DeploymentState.FAILURE for s in statuses)


@dataclass(frozen=True, slots=True)
class Observed:
    """One environment as this run found it"""

    env: Environment
    deployments: tuple[Deployment, ...]  # newest first
    current: Deployment | None  # the newest deployment that reached success
    statuses: tuple[DeploymentStatus, ...]  # the current deployment's, oldest first
    tag: Version | None
    probe: Probe | None  # None: no health URL, or nothing to check
    bake_start: dt.datetime | None  # when the current healthy stretch began
    failing_since: dt.datetime | None  # when the current run of failed checks began
    failed_checks: int  # failed checks in a row, this run's included; 0 while healthy or unchecked

    def healthy_for(self, now: dt.datetime) -> dt.timedelta | None:
        """How long the current deployment has been healthy; None while it isn't. Without a
        health URL, the time since it succeeded"""
        if self.bake_start is None or (self.probe is not None and not self.probe.healthy):
            return None
        return now - self.bake_start

    def tried(self, tag: Version) -> Deployment | None:
        """The newest deployment of the tag here, in any state"""
        hits = [d for d in self.deployments if d.ref.removeprefix("refs/tags/") == tag.tag]
        return hits[0] if hits else None


def observe(github: GitHub, http: Http, env: Environment, tags: Sequence[Tag], now: dt.datetime) -> Observed:
    deployments = tuple(github.deployments(env.name))
    for deployment in deployments:
        statuses = tuple(github.deployment_statuses(deployment.id))
        succeeded = [s for s in statuses if s.state is DeploymentState.SUCCESS]
        if succeeded:
            break
    else:
        return Observed(env, deployments, None, (), None, None, None, None, 0)
    tag = tag_of(deployment, tags)
    checked = probe(http, env.health, tag) if env.health and tag is not None else None
    ours = [s for s in statuses if _ours(s)]
    failures = [s for s in ours if s.state is DeploymentState.FAILURE]
    bake_start: dt.datetime | None = succeeded[0].created_at
    if failures:  # a failed check restarts the bake: it counts from the first passing one after
        recovered = [s for s in ours if s.id > failures[-1].id]
        bake_start = recovered[0].created_at if recovered else now
    failing_since = None
    failed_checks = 0
    if checked is not None and not checked.healthy:
        bake_start = None
        # each failed check writes a failure status (up to rollback_after): the ones that end
        # the history are the checks failed in a row before this one, the first of them its start
        trailing = 0
        health = [s for s in statuses if not _compared(s)]
        for status in reversed(health):
            if not (_ours(status) and status.state is DeploymentState.FAILURE):
                break
            trailing += 1
        failing_since = health[-trailing].created_at if trailing else now
        failed_checks = trailing + 1
    return Observed(env, deployments, deployment, statuses, tag, checked, bake_start, failing_since, failed_checks)


# -- rollback and incidents ------------------------------------------------------------------


class IncidentState(StrEnum):
    FAILING = "failing"  # no rollback made: none to make, or rollback autonomy is observe
    PROPOSED = "proposed"  # a rollback waits on --approve-rollback
    ROLLED_BACK = "rolled-back"  # shipmill started the rollback
    STOPPED = "stopped"  # the rollback's tag fails its checks too: no second rollback
    HEALTHY = "healthy"  # healthy again, on the bad tag or the rollback's


class Cause(StrEnum):
    """What opened an incident: its hidden line's optional `cause=`"""

    HEALTH = "health"  # failed health checks: a line without cause= reads as one, as lines before spec 084
    COMPARE = "compare"  # answers that differ from the previous release's (spec 084)


_INCIDENT = re.compile(
    r"<!-- shipmill:incident env=(?P<env>\S+) tag=(?P<tag>\S+) to=(?P<to>\S+) state=(?P<state>\S+)"
    r"(?: cause=(?P<cause>\S+))? -->"
)


def incident_line(env: str, tag: Version, to: Version | None, state: IncidentState, cause: Cause = Cause.HEALTH) -> str:
    """The hidden line that finds an environment's incident again, and keeps its state; a
    health incident's carries no cause, as before spec 084"""
    tail = "" if cause is Cause.HEALTH else f" cause={cause}"
    return f"<!-- shipmill:incident env={env} tag={tag.tag} to={to.tag if to else '-'} state={state}{tail} -->"


@dataclass(frozen=True, slots=True)
class Incident:
    """An incident issue shipmill opened: the environment, its bad tag, the rollback's tag"""

    issue: Issue
    env: str
    tag: Version
    to: Version | None
    state: IncidentState
    cause: Cause = Cause.HEALTH

    @classmethod
    def read(cls, issue: Issue) -> Incident | None:
        """None for an issue with the label that shipmill didn't open"""
        found = _INCIDENT.search(issue.body)
        if found is None:
            return None
        try:
            state = IncidentState(found["state"])
        except ValueError:
            raise ReleaseError(f"incident #{issue.number} has an unknown state {found['state']!r}") from None
        try:
            cause = Cause(found["cause"] or Cause.HEALTH)
        except ValueError:
            raise ReleaseError(f"incident #{issue.number} has an unknown cause {found['cause']!r}") from None
        to = None if found["to"] == "-" else Version.of_tag(found["to"])
        return cls(issue, found["env"], Version.of_tag(found["tag"]), to, state, cause)

    @property
    def number(self) -> int:
        return self.issue.number

    def moved(self, state: IncidentState, to: Version | None, cause: Cause | None = None) -> str:
        """The issue's body with its hidden line in the new state; its cause kept unless given"""
        line = incident_line(self.env, self.tag, to, state, self.cause if cause is None else cause)
        return _INCIDENT.sub(lambda _: line, self.issue.body, count=1)


def incidents(policy: Policy, github: GitHub) -> list[Incident]:
    """The incidents shipmill opened, open and closed, newest first"""
    found = (Incident.read(i) for i in github.labelled_issues(policy.operate.incident_label))
    return [i for i in found if i is not None]


def incident_title(env: str, tag: Version) -> str:
    return f"Incident: {env} fails its health checks on {tag.tag}"


@dataclass(frozen=True, slots=True)
class Previous:
    """The release before the current one in an environment: its tag and its statuses"""

    tag: Version
    statuses: tuple[DeploymentStatus, ...]  # oldest first


def _earlier(github: GitHub, seen: Observed, tags: Sequence[Tag]) -> Iterator[Previous]:
    """The deployments before the current one that reached success there, on another tag,
    newest first"""
    assert seen.current is not None and seen.tag is not None  # only a checked deployment has one
    for deployment in seen.deployments:
        tag = tag_of(deployment, tags)
        if deployment.id >= seen.current.id or tag is None or tag == seen.tag:
            continue
        statuses = github.deployment_statuses(deployment.id)
        if any(s.state is DeploymentState.SUCCESS for s in statuses):
            yield Previous(tag, tuple(sorted(statuses, key=lambda s: s.id)))


def _previous(github: GitHub, seen: Observed, tags: Sequence[Tag]) -> Previous | None:
    """The newest deployment before the current one that reached success there, on another
    tag, whose last health check (if shipmill wrote one) didn't fail and whose answers didn't
    differ from the release before it (spec 084)"""
    for found in _earlier(github, seen, tags):
        ours = [s for s in found.statuses if _ours(s)]
        if ours and ours[-1].state is DeploymentState.FAILURE:
            continue
        if _differed(found.statuses):
            continue
        return found
    return None


def _last_good(github: GitHub, seen: Observed, tags: Sequence[Tag]) -> Version | None:
    """The tag a rollback deploys: the previous release's"""
    found = _previous(github, seen, tags)
    return found.tag if found is not None else None


def _rolled_back(github: GitHub, seen: Observed, to: Version) -> str | None:
    """How the rollback to the tag shows it was started: a deployment of it after the bad
    one, or a run of the workflow on it since the checks began failing (still queued, say)"""
    assert seen.current is not None
    newer = [d for d in seen.deployments if d.id > seen.current.id and d.ref.removeprefix("refs/tags/") == to.tag]
    if newer:
        return f"deployment {newer[0].id}"
    started = _started(github, seen.env, to, seen.failing_since or seen.current.created_at)
    return f"run {started.id}, {started.status}" if started is not None else None


def _approve_rollback_how(env: str, cause: str) -> tuple[str, ...]:
    command = f"gh workflow run {OPERATE_CALLER.name} -f approve-rollback={env} -f dry-run=false"
    if cause.startswith(f"held by {HOLD_LABEL}"):
        how = f"Close the open `{HOLD_LABEL}` issues first; then approve the rollback:"
    else:
        how = "To roll back, approve it:"
    return (how, "", "```", command, "```")


@dataclass(frozen=True, slots=True)
class Rollback:
    """What this run did about rolling an environment back"""

    to: Version | None
    state: IncidentState
    text: str  # a sentence for the incident and the summary
    how: tuple[str, ...] = ()  # the approve lines, for a proposed rollback


def _rollback(
    policy: Policy, github: GitHub, seen: Observed, tags: Sequence[Tag], hold: Hold, dry_run: bool
) -> Rollback:
    to = _last_good(github, seen, tags)
    if to is None:
        return Rollback(None, IncidentState.FAILING, "no rollback: no earlier tag reached success here")
    stage = Stage.rollback()
    level = policy.autonomy.effective(stage, hold)
    env = seen.env
    if level is Autonomy.ACT:
        # a rollback deploys a tag that ran here before, so the at-most-once rule for deploys
        # doesn't apply to it; started once is still the rule
        if (started := _rolled_back(github, seen, to)) is not None:
            return Rollback(to, IncidentState.ROLLED_BACK, f"rollback to {to.tag} started already ({started})")
        if dry_run:
            return Rollback(to, IncidentState.ROLLED_BACK, f"would roll back: start {env.workflow} with {to.tag}")
        url = github.dispatch(env.workflow, to.tag, to.tag, env.inputs)
        run = f": {url}" if url else ""
        return Rollback(to, IncidentState.ROLLED_BACK, f"rolled back: started {env.workflow} with {to.tag}{run}")
    cause = policy.autonomy.cause(stage, hold)
    if level is Autonomy.PROPOSE:
        how = _approve_rollback_how(env.name, cause)
        return Rollback(to, IncidentState.PROPOSED, f"would roll back to {to.tag}, but {cause}", how)
    return Rollback(to, IncidentState.FAILING, f"would roll back to {to.tag}, but {cause}")


def incident_body(policy: Policy, seen: Observed, rollback: Rollback, now: dt.datetime) -> str:
    assert seen.tag is not None and seen.probe is not None and seen.env.health is not None
    env = seen.env.name
    since = seen.failing_since or now
    lanes = ", ".join(str(lane) for lane in Lane if lane in policy.blocker_lanes)
    lines = [
        incident_line(env, seen.tag, rollback.to, rollback.state),
        f"**{env}** failed {seen.failed_checks} health checks in a row on **{seen.tag.tag}**, since"
        f" {since:%Y-%m-%d %H:%M} UTC.",
        "",
        f"- Health check: `{shown_url(seen.env.health)}`",
        f"- Last check: {seen.probe.detail}",
    ]
    if seen.probe.excerpt:
        lines.append(f"- Body: `{seen.probe.excerpt}`")
    lines += ["", f"**Rollback**: {rollback.text}."]
    if rollback.how:
        lines += ["", *rollback.how]
    lines += [
        "",
        f"While this issue is open, the {lanes} lanes don't release: the `{policy.operate.incident_label}`"
        " label holds them like the blocker label. Close it once resolved, by hand or with a hotfix pull"
        f" request's \"Fixes #N\". shipmill comments here when {env} is healthy again, and doesn't roll back"
        " a second time if the rollback fails its checks too.",
    ]
    return "\n".join(lines) + "\n"


def _compare_ended(seen: Observed, known: Sequence[Incident]) -> Incident | None:
    """The environment's open compare incident that the current tag, not its bad one, ends"""
    ended = [
        i
        for i in known
        if i.env == seen.env.name
        and i.cause is Cause.COMPARE
        and i.tag != seen.tag
        and not i.issue.closed
        and i.state is not IncidentState.HEALTHY
    ]
    return ended[0] if ended else None


def _healthy_again(github: GitHub, seen: Observed, incident: Incident, detail: str, dry_run: bool) -> str:
    """Comment that the environment is healthy again and mark the incident so"""
    assert seen.tag is not None
    if not dry_run:
        github.comment_issue(incident.number, f"{seen.env.name} is healthy again on {seen.tag.tag} ({detail}).")
        healthy = incident.moved(IncidentState.HEALTHY, incident.to)
        github.update_issue(incident.number, incident.issue.title, healthy)
    return f"{'would ' if dry_run else ''}comment on incident #{incident.number}: healthy again"


def _incident(
    policy: Policy,
    github: GitHub,
    seen: Observed,
    tags: Sequence[Tag],
    known: Sequence[Incident],
    hold: Hold,
    now: dt.datetime,
    dry_run: bool,
) -> str | None:
    """Open, comment on, or roll back for this environment's incident; what it did"""
    if seen.current is None or seen.tag is None:
        return None
    if seen.env.health is None:
        # no health check: no health incident, but a compare incident still ends once another
        # tag's deployment reached success, the signal the compare itself waits for here (#1451)
        ended = _compare_ended(seen, known)
        if ended is None:
            return None
        detail = f"its deployment reached success; {seen.env.name} has no health check"
        return _healthy_again(github, seen, ended, detail, dry_run)
    if seen.probe is None:
        return None
    env = seen.env.name
    # an incident closed before the current stretch of failed checks began is history: the
    # person closed that failure, not this one, which opens another
    since = seen.failing_since
    mine = [
        i
        for i in known
        if i.env == env
        and seen.tag in (i.tag, i.to)
        and not (since is not None and i.issue.closed_at is not None and i.issue.closed_at < since)
    ]
    incident = mine[0] if mine else None
    would = "would " if dry_run else ""
    if seen.probe.healthy:
        if incident is not None and incident.cause is Cause.COMPARE and incident.tag == seen.tag:
            return None  # its answers differ: passing the health check on the bad tag doesn't end it
        if incident is None or incident.issue.closed or incident.state is IncidentState.HEALTHY:
            # a compare incident ends once the environment runs another tag that passes
            incident = _compare_ended(seen, known)
            if incident is None:
                return None
        return _healthy_again(github, seen, incident, seen.probe.detail, dry_run)
    if seen.failed_checks < policy.operate.rollback_after:
        return None
    if incident is not None and incident.issue.closed:
        return (
            f"incident #{incident.number} for {incident.tag.tag} was closed while it failed; shipmill opens"
            " another only if it fails again after recovering"
        )
    if incident is None:
        rollback = _rollback(policy, github, seen, tags, hold, dry_run)
        if dry_run:
            return f"would open an incident; {rollback.text}"
        fix = f"grant `issues: write` to the job that calls operate.yml in {OPERATE_CALLER}"
        try:
            number = github.create_issue(
                incident_title(env, seen.tag),
                incident_body(policy, seen, rollback, now),
                (policy.operate.incident_label,),
            )
        except ReleaseError as exc:
            raise ReleaseError(f"{exc}; if GitHub refused it (403): {fix}") from exc
        return f"opened incident #{number}; {rollback.text}"
    if incident.tag == seen.tag:
        if incident.state is not IncidentState.HEALTHY:
            return f"incident #{incident.number} open ({incident.state})"
        rollback = _rollback(policy, github, seen, tags, hold, dry_run)
        if not dry_run:
            text = [f"{env} fails its health checks again on {seen.tag.tag} ({seen.probe.detail}).", ""]
            text += [f"**Rollback**: {rollback.text}.", *(("", *rollback.how) if rollback.how else ())]
            github.comment_issue(incident.number, "\n".join(text))
            moved = incident.moved(rollback.state, rollback.to)
            github.update_issue(incident.number, incident.issue.title, moved)
        return f"{would}comment on incident #{incident.number}: failing again; {rollback.text}"
    # the environment runs the rollback's tag, and that fails its checks too
    if incident.state is IncidentState.STOPPED:
        return f"incident #{incident.number}: the rollback to {seen.tag.tag} fails too; waiting for a person"
    if not dry_run:
        stop = (
            f"{seen.tag.tag}, the rollback, fails its health checks too ({seen.probe.detail}). shipmill doesn't"
            f" roll {env} back a second time: a second automatic guess is worse than waiting for a person."
        )
        github.comment_issue(incident.number, stop)
        stopped = incident.moved(IncidentState.STOPPED, incident.to)
        github.update_issue(incident.number, incident.issue.title, stopped)
    return (
        f"{would}comment on incident #{incident.number}: the rollback to {seen.tag.tag} fails too; no second rollback"
    )


# -- compare (spec 084) ----------------------------------------------------------------------


class Verdict(StrEnum):
    """What one probe found, comparing the new release's answer with the previous one's"""

    SAME = "same"
    DIFFERENT = "different"
    UNSTABLE = "unstable"  # the previous release's own answers differ beyond what the compare removes
    UNCHECKED = "unchecked"  # the previous release gave no HTTP answer


type JsonPath = tuple[str, ...]  # a JSON pointer's segments, unescaped
_NOT_JSON = object()
_GONE = object()  # an array element removed from both sides, so the indices after it still line up
_MAX_DEPTH = 64  # nesting deeper than this is compared as text


def _json(body: str) -> object:
    """The body's JSON value, or _NOT_JSON"""
    try:
        value: object = json.loads(body)
    except ValueError, RecursionError:  # JSONDecodeError, or an integer past Python's digit limit
        return _NOT_JSON
    level = [value]
    for _ in range(_MAX_DEPTH):
        level = [v for x in level for v in (x.values() if isinstance(x, dict) else x if isinstance(x, list) else ())]
        if not level:
            return value
    return _NOT_JSON


def _differing(
    a: object, b: object, at: JsonPath, found: set[JsonPath], lengths: dict[JsonPath, tuple[int, int]] | None = None
) -> None:
    """Add each pointer at which two JSON values differ: a key one side lacks, an array whose
    length differs (its two lengths into lengths), or a scalar of another type or value"""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            if key in a and key in b:
                _differing(a[key], b[key], (*at, key), found, lengths)
            else:
                found.add((*at, key))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _differing(x, y, (*at, str(i)), found, lengths)
    elif type(a) is not type(b) or a != b:
        found.add(at)
        if lengths is not None and isinstance(a, list) and isinstance(b, list):
            lengths[at] = (len(a), len(b))


def _strip(value: object, ignore: Sequence[Pointer], noise: set[JsonPath], at: JsonPath) -> object:
    """The value without what an ignore pointer or a noise pointer names"""

    def gone(path: JsonPath) -> bool:
        return path in noise or any(p.matches(path) for p in ignore)

    if isinstance(value, dict):
        return {k: _strip(v, ignore, noise, (*at, k)) for k, v in value.items() if not gone((*at, k))}
    if isinstance(value, list):
        return [_GONE if gone((*at, str(i))) else _strip(v, ignore, noise, (*at, str(i))) for i, v in enumerate(value)]
    return value


@dataclass(frozen=True, slots=True)
class Difference:
    """How a probe's new answer differs from the previous release's, in what a public incident
    may show: the HTTP statuses, the pointers, an array's lengths, a fixed note; never a value"""

    before: int  # the previous release's HTTP status
    after: int | None  # the new release's; None: no HTTP answer
    pointers: tuple[JsonPath, ...] = ()  # where two JSON answers differ, sorted
    lengths: tuple[tuple[JsonPath, int, int], ...] = ()  # an array's length on each side, by pointer
    note: str = ""  # shipmill's own words for a difference no pointer names


def _verdict(
    previous: Sequence[HttpResponse], new: HttpResponse | None, ignore: Sequence[Pointer]
) -> tuple[Verdict, Difference | None]:
    """The new release's answer against the previous release's, the first of them the one
    compared with, the others telling the previous release's own noise; how it differs, when
    it does"""
    reference = previous[0]
    if any(p.status != reference.status for p in previous):
        return Verdict.UNSTABLE, None
    if new is None:
        return Verdict.DIFFERENT, Difference(reference.status, None, note="no HTTP answer")
    if new.status != reference.status:
        return Verdict.DIFFERENT, Difference(reference.status, new.status)
    parsed = [_json(p.body) for p in previous]
    if all(v is not _NOT_JSON for v in parsed):
        noise: set[JsonPath] = set()
        for other in parsed[1:]:
            _differing(parsed[0], other, (), noise)
        if () in noise:  # the whole answer changes by itself
            return Verdict.UNSTABLE, None
        theirs = _json(new.body)
        if theirs is _NOT_JSON:
            return Verdict.DIFFERENT, Difference(reference.status, new.status, note="the answer is no longer JSON")
        found: set[JsonPath] = set()
        lengths: dict[JsonPath, tuple[int, int]] = {}
        _differing(_strip(parsed[0], ignore, noise, ()), _strip(theirs, ignore, noise, ()), (), found, lengths)
        if not found:
            return Verdict.SAME, None
        pointers = tuple(sorted(found))
        sized = tuple((p, *lengths[p]) for p in pointers if p in lengths)
        return Verdict.DIFFERENT, Difference(reference.status, new.status, pointers, sized)
    if any(p.body != reference.body for p in previous):
        return Verdict.UNSTABLE, None
    if new.body == reference.body:
        return Verdict.SAME, None
    return Verdict.DIFFERENT, Difference(reference.status, new.status, note="the text differs")


def _send(http: Http, url: str) -> HttpResponse | None:
    """A probe's GET: None when no HTTP answer comes back"""
    try:
        return http.get(url, HEALTH_TIMEOUT, PROBE_BODY_LIMIT)
    except Unreachable:
        return None


def _probe_url(address: str, probe: DeclaredProbe) -> str:
    return address.rstrip("/") + probe.path


def _compare_probe(http: Http, probe: DeclaredProbe, before: str, after: str) -> tuple[Verdict, Difference | None]:
    """Send the probe twice to the previous release's address and once to the new one's; a
    difference is sent once more to both, and counts only when it holds"""
    old, new = _probe_url(before, probe), _probe_url(after, probe)
    first, second = _send(http, old), _send(http, old)
    answer = _send(http, new)
    if first is None or second is None:
        return Verdict.UNCHECKED, None
    verdict, _ = _verdict((first, second), answer, probe.ignore)
    if verdict is not Verdict.DIFFERENT:
        return verdict, None
    third = _send(http, old)
    again = _send(http, new)
    if third is None:
        return Verdict.UNCHECKED, None
    return _verdict((third, first, second), again, probe.ignore)


_CHANGES = re.compile(r"^[ \t]*Changes answers:(?P<names>.*)$", re.MULTILINE)


def changes_answers(body: str) -> frozenset[str]:
    """The probes a pull request body's `Changes answers: <name>, <name>` lines name"""
    named = (n.strip().strip("`").strip() for found in _CHANGES.finditer(body) for n in found["names"].split(","))
    return frozenset(n for n in named if n)


def _explained(git: Git, github: GitHub, previous: Version, new: Version, differ: Sequence[str]) -> dict[str, int]:
    """The pull request that explains each differing probe its body's `Changes answers:` line
    names: those merged between the two tags, read newest first until every probe is named"""
    left = set(differ)
    by: dict[str, int] = {}
    for number in git.merged_pulls(previous.tag, new.tag):
        if not left:
            break
        named = changes_answers(github.pull_body(number)) & left
        by.update(dict.fromkeys(named, number))
        left -= named
    return by


@dataclass(frozen=True, slots=True)
class Compared:
    """What comparing the current deployment found, before anything is written: the status
    it writes, and the differences no pull request explains"""

    previous: Version
    state: DeploymentState
    description: str
    text: str  # for the summary, without what was written
    differences: tuple[tuple[DeclaredProbe, Difference], ...] = ()  # the unexplained ones


def _status_description(text: str) -> str:
    return f"{COMPARE_PREFIX} {text}"[:_DESCRIPTION_LIMIT]


def _web(address: str) -> bool:
    return urllib.parse.urlsplit(address).scheme in ("http", "https")


def _compare(git: Git, github: GitHub, http: Http, seen: Observed, tags: Sequence[Tag]) -> Compared | str | None:
    """Compare the current deployment's answers with the previous release's, once per
    deployment (spec 084), writing nothing: the status to write, a report of why none is, or
    None when this run doesn't compare. A failed read of a pull request's body raises"""
    env = seen.env
    if not env.probes or seen.current is None or seen.tag is None:
        return None  # an environment without probes makes no request beyond its health check (D-63)
    if env.health is not None and (seen.probe is None or not seen.probe.healthy):
        return None
    if any(_compared(s) for s in seen.statuses):
        return None
    replaced = next(_earlier(github, seen, tags), None)
    if replaced is not None and replaced.tag >= seen.tag:  # a rollback: never compared with what it replaced
        return None
    previous = _previous(github, seen, tags)
    if previous is None:
        return "not compared: no previous release"
    if previous.tag >= seen.tag:
        return None
    addresses = []
    for tag, statuses in ((seen.tag, seen.statuses), (previous.tag, previous.statuses)):
        found = address(statuses)
        if found is None:
            return f"not compared: {tag.tag} has no environment_url"
        if not _web(found):
            return f"not compared: {tag.tag}'s environment_url {shown_url(found)} is not an http(s) URL"
        addresses.append(found)
    after, before = addresses
    results = {p.name: (p, *_compare_probe(http, p, before, after)) for p in env.probes}

    def named(verdict: Verdict) -> list[str]:
        return [name for name, (_, v, _) in results.items() if v is verdict]

    unchecked, unstable = named(Verdict.UNCHECKED), named(Verdict.UNSTABLE)
    if len(unchecked) == len(results):
        return f"not compared: {previous.tag.tag} at {shown_url(before)} unreachable"
    notes = "".join(
        f" ({label}: {', '.join(names)})"
        for label, names in (("unstable", unstable), ("unchecked", unchecked))
        if names
    )
    was = previous.tag.tag
    if differ := named(Verdict.DIFFERENT):
        # the pull requests' bodies are read only now, when a difference holds
        by = _explained(git, github, previous.tag, seen.tag, differ)
        explained = [name for name in differ if name in by]
        unexplained = [name for name in differ if name not in by]
        pulls = ", ".join(f"#{n}" for n in sorted(set(by.values())))
        if not unexplained:
            names = ", ".join(explained)
            return Compared(
                previous.tag,
                DeploymentState.SUCCESS,
                _status_description(f"differs from {was} on {names}, explained by {pulls}"),
                f"compared with {was}: differs on {names}, explained by {pulls}{notes}",
            )
        names = ", ".join(unexplained)
        also = f" (explained by {pulls}: {', '.join(explained)})" if explained else ""
        differences = []
        for name in unexplained:
            probe, _, difference = results[name]
            assert difference is not None  # a difference that holds says how
            differences.append((probe, difference))
        return Compared(
            previous.tag,
            DeploymentState.FAILURE,
            _status_description(f"answers differ from {was} on {names}"),
            f"compared with {was}: differs on {names}{also}{notes}",
            tuple(differences),
        )
    same = named(Verdict.SAME)
    if not same:
        return f"not compared: no probe answered steadily on {was}{notes}"
    return Compared(
        previous.tag,
        DeploymentState.SUCCESS,
        _status_description(f"same answers as {was} on {len(same)} probes"),
        f"compared with {was}: same on {len(same)} probes{notes}",
    )


def _shown_path(path: str) -> str:
    """A probe's path as an incident shows it: without its query or fragment, which may carry
    a token, and with no backtick to break a code span"""
    return path.split("?", 1)[0].split("#", 1)[0].replace("`", "'")


def _shown_pointer(path: JsonPath) -> str:
    """A JSON pointer as an incident shows it: escaped as RFC 6901 writes it, on one line,
    capped, in a code span; the answer's keys and indices only, never a value"""
    if not path:
        return "the whole answer"
    text = "".join("/" + s.replace("~", "~0").replace("/", "~1") for s in path)
    text = "".join(c if c.isprintable() and c != "`" else "?" for c in text)
    if len(text) > _POINTER_LIMIT:
        text = text[: _POINTER_LIMIT - 3] + "..."
    return f"`{text}`"


def _difference_lines(compared: Compared, tag: Version) -> list[str]:
    """One line per probe whose answers differ, unexplained: its name, its path without the
    query, both statuses, at most ten differing pointers, and an array's lengths"""
    lines = []
    for probe, diff in compared.differences:
        after = "no HTTP answer" if diff.after is None else f"HTTP {diff.after}"
        line = (
            f"- `{probe.name}` (`{_shown_path(probe.path)}`): HTTP {diff.before} on {compared.previous.tag},"
            f" {after} on {tag.tag}"
        )
        if diff.pointers:
            sized = {p: (a, b) for p, a, b in diff.lengths}
            shown = []
            for pointer in diff.pointers[:_POINTERS_SHOWN]:
                lengths = f": {sized[pointer][0]} vs {sized[pointer][1]} items" if pointer in sized else ""
                shown.append(_shown_pointer(pointer) + lengths)
            more = len(diff.pointers) - _POINTERS_SHOWN
            line += f"; differs at {', '.join(shown)}" + (f", and {more} more" if more > 0 else "")
        elif diff.note and diff.after is not None:
            line += f"; {diff.note}"
        lines.append(line)
    return lines


def compare_incident_title(env: str, tag: Version, previous: Version) -> str:
    return f"Incident: {env} answers differently on {tag.tag} than {previous.tag}"


def compare_incident_body(policy: Policy, seen: Observed, compared: Compared, rollback: Rollback) -> str:
    """A compare incident's body: the probes whose answers differ and how, never a value of
    either answer, since an incident is an issue anyone with read access sees"""
    assert seen.tag is not None
    env = seen.env.name
    lanes = ", ".join(str(lane) for lane in Lane if lane in policy.blocker_lanes)
    lines = [
        incident_line(env, seen.tag, rollback.to, rollback.state, Cause.COMPARE),
        f"**{env}** answers differently on **{seen.tag.tag}** than on **{compared.previous.tag}**, the release"
        " before it, and no pull request merged between them names these probes on a `Changes answers:` line.",
        "",
        *_difference_lines(compared, seen.tag),
        "",
        f"**Rollback**: {rollback.text}.",
    ]
    if rollback.how:
        lines += ["", *rollback.how]
    passes = "that passes its health check" if seen.env.health is not None else "whose deployment reaches success"
    lines += [
        "",
        f"While this issue is open, the {lanes} lanes don't release: the `{policy.operate.incident_label}`"
        " label holds them like the blocker label. Close it once resolved, by hand or with a hotfix pull"
        f' request\'s "Fixes #N". shipmill comments here once {env} runs a tag other than {seen.tag.tag} {passes},'
        " and doesn't roll back a second time if the rollback fails its checks too.",
    ]
    return "\n".join(lines) + "\n"


def _compare_incident(
    policy: Policy,
    github: GitHub,
    seen: Observed,
    compared: Compared,
    tags: Sequence[Tag],
    known: Sequence[Incident],
    hold: Hold,
    dry_run: bool,
) -> str:
    """Open the environment's incident for answers that differ, at once, and roll back as a
    failed health check does; comment on the tag's open incident instead of opening another"""
    assert seen.tag is not None
    env = seen.env.name
    would = "would " if dry_run else ""
    opened = [i for i in known if i.env == env and i.tag == seen.tag and not i.issue.closed]
    if opened:
        incident = opened[0]
        # an incident healthy again is rolled back for this as for a failed check; any other
        # has its rollback made, proposed, or stopped already
        rollback = (
            _rollback(policy, github, seen, tags, hold, dry_run) if incident.state is IncidentState.HEALTHY else None
        )
        if not dry_run:
            text = [f"{env} answers differently on {seen.tag.tag} than {compared.previous.tag}.", ""]
            text += _difference_lines(compared, seen.tag)
            if rollback is not None:
                text += ["", f"**Rollback**: {rollback.text}.", *(("", *rollback.how) if rollback.how else ())]
            github.comment_issue(incident.number, "\n".join(text))
            state, to = (rollback.state, rollback.to) if rollback is not None else (incident.state, incident.to)
            github.update_issue(incident.number, incident.issue.title, incident.moved(state, to, Cause.COMPARE))
        tail = f"; {rollback.text}" if rollback is not None else ""
        return f"{would}comment on incident #{incident.number}: answers differently{tail}"
    rollback = _rollback(policy, github, seen, tags, hold, dry_run)
    if dry_run:
        return f"would open an incident; {rollback.text}"
    fix = f"grant `issues: write` to the job that calls operate.yml in {OPERATE_CALLER}"
    try:
        number = github.create_issue(
            compare_incident_title(env, seen.tag, compared.previous),
            compare_incident_body(policy, seen, compared, rollback),
            (policy.operate.incident_label,),
        )
    except ReleaseError as exc:
        raise ReleaseError(f"{exc}; if GitHub refused it (403): {fix}") from exc
    return f"opened incident #{number}; {rollback.text}"


def _mark_compared(
    policy: Policy,
    github: GitHub,
    seen: Observed,
    compared: Compared,
    tags: Sequence[Tag],
    known: Sequence[Incident],
    hold: Hold,
    dry_run: bool,
) -> str:
    """Write the compare's status, and for a difference no pull request explains, its incident
    first: if opening it fails, the next run compares again and tries again"""
    assert seen.current is not None
    mark = "would mark" if dry_run else "marked"
    done = [f"{compared.text}, {mark} {compared.state}"]
    if compared.state is DeploymentState.FAILURE:
        done.append(_compare_incident(policy, github, seen, compared, tags, known, hold, dry_run))
    if not dry_run:
        github.create_deployment_status(seen.current.id, compared.state, compared.description)
    return "; ".join(done)


# -- one run ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    environment: str
    tag: str
    health: str
    action: str


@dataclass(frozen=True, slots=True)
class Wanted:
    """A deploy this run would make: the tag, and why"""

    tag: Version
    why: str
    promote: bool  # from a source environment, rather than a missed lane deploy
    since: dt.datetime  # a run of the environment's workflow on the tag since then deployed it already


def _minutes(span: dt.timedelta) -> int:
    return int(span.total_seconds() // 60)


def _bake_target(env: Environment, environments: Mapping[str, Environment]) -> int:
    """The longest bake any environment promoted from this one waits for; 0 when none is"""
    return max((e.bake_minutes for e in environments.values() if e.source == env.name), default=0)


def _health_text(seen: Observed, target: int, rollback_after: int, now: dt.datetime) -> str:
    if seen.current is None:
        return "no deployment"
    if not seen.env.health:
        return "no health URL"
    if seen.tag is None or seen.probe is None:
        return "not checked"
    if not seen.probe.healthy:
        since = f", failing for {_minutes(now - seen.failing_since)} min" if seen.failing_since else ""
        count = f", {min(seen.failed_checks, rollback_after)} of {rollback_after} failed checks to roll back"
        return f"unhealthy: {seen.probe.detail}{since}{count}"
    healthy = seen.healthy_for(now) or dt.timedelta()
    if target and _minutes(healthy) < target:
        return f"healthy ({seen.probe.detail}), baking {_minutes(healthy)} of {target} min"
    return f"healthy ({seen.probe.detail})"


def _status(seen: Observed, target: int, rollback_after: int, now: dt.datetime) -> tuple[DeploymentState, str] | None:
    """The status the current deployment should carry, when it differs from its latest. A
    failed check is written each time until rollback_after stand in a row: they count them"""
    if seen.current is None or seen.probe is None:
        return None
    if not seen.probe.healthy:
        if seen.failed_checks > rollback_after:
            return None
        return DeploymentState.FAILURE, f"{STATUS_PREFIX}: {seen.probe.detail}"[:_DESCRIPTION_LIMIT]
    healthy = seen.healthy_for(now) or dt.timedelta()
    if _minutes(healthy) >= target:
        wanted = (DeploymentState.SUCCESS, f"{STATUS_PREFIX}: baked" if target else f"{STATUS_PREFIX}: healthy")
    else:
        wanted = (DeploymentState.IN_PROGRESS, f"{STATUS_PREFIX}: baking for {target} min")
    health = [s for s in seen.statuses if not _compared(s)]
    if health and health[-1].state is wanted[0]:
        return None
    return wanted[0], wanted[1][:_DESCRIPTION_LIMIT]


def _lane_versions(lane: Lane, tags: Sequence[Tag]) -> list[Tag] | None:
    """The tags a lane releases; None for hotfix, whose tags look like stable ones"""
    if lane is Lane.DEV:
        return [t for t in tags if t.version.dev is not None]
    if lane is Lane.RC:
        return [t for t in tags if t.version.pre is not None and t.version.dev is None]
    if lane is Lane.STABLE:
        return [t for t in tags if t.version.is_stable]
    return None


def _wanted(
    seen: Observed,
    observed: Mapping[str, Observed],
    tags: Sequence[Tag],
    now: dt.datetime,
    differing: frozenset[str],
) -> Wanted | str:
    """The deploy this environment waits for, or why none; differing names the environments
    whose current deployment answers differently from its previous release (spec 084)"""
    env = seen.env
    if env.source is not None:
        source = observed[env.source]
        if source.current is None:
            return f"{env.source} has no deployment to promote"
        if source.tag is None:
            return f"{env.source}'s deployment ref {source.current.ref!r} names no release tag"
        if seen.tag is not None and seen.tag >= source.tag:
            return f"on {seen.tag.tag}" if seen.tag == source.tag else f"ahead of {env.source} ({source.tag.tag})"
        if env.source in differing:
            return f"{env.source} answers differently on {source.tag.tag}"
        healthy = source.healthy_for(now)
        if healthy is None:
            return f"{env.source} is unhealthy on {source.tag.tag}"
        if _minutes(healthy) < env.bake_minutes:
            return f"{source.tag.tag} baking on {env.source}: {_minutes(healthy)} of {env.bake_minutes} min"
        why = f"healthy on {env.source} for the {env.bake_minutes} min bake"
        # the source's own run of a shared workflow made its deployment, so it started before it
        return Wanted(source.tag, why, promote=True, since=source.current.created_at)
    assert env.lane is not None  # an environment takes a lane or a source
    released = _lane_versions(env.lane, tags)
    if released is None:
        return "up to date (hotfix tags aren't told from stable ones, so a missed hotfix deploy isn't caught)"
    newest = max(released, key=lambda t: t.version) if released else None
    if newest is None:
        return f"no {env.lane} release yet"
    if seen.current is None:
        return f"no deployment yet; {newest.name} is the newest {env.lane} release"
    if seen.tag is None:
        return f"deployment ref {seen.current.ref!r} names no release tag"
    if seen.tag >= newest.version:
        return "up to date"
    if now - newest.date < MISSED_GRACE:
        return f"{newest.name} just landed; its deploy may still be starting"
    why = f"the newest {env.lane} release, which its deploy missed"
    return Wanted(newest.version, why, promote=False, since=newest.date)


def _started(github: GitHub, env: Environment, tag: Version, since: dt.datetime) -> WorkflowRun | None:
    """The newest run of the environment's workflow on the tag started since then"""
    runs = [r for r in github.workflow_runs(env.workflow, tag.tag) if r.created_at >= since]
    return runs[0] if runs else None


def deploy_marker(env: str) -> str:
    return f"<!-- shipmill:propose deploy={env} -->"


def _tag_line(tag: Version) -> str:
    return f"<!-- shipmill:tag={tag.tag} -->"


def proposal_title(env: Environment, wanted: Wanted) -> str:
    return f"Ready to {'promote' if wanted.promote else 'deploy'} {wanted.tag.tag} to {env.name}"


def proposal_body(env: Environment, wanted: Wanted, cause: str) -> str:
    approve = f"gh workflow run {OPERATE_CALLER.name} -f approve={env.name} -f dry-run=false"
    if cause.startswith(f"held by {HOLD_LABEL}"):
        how = f"Close the open `{HOLD_LABEL}` issues first; then approve it:"
    else:
        how = "To deploy it, approve it:"
    return "\n".join(
        [
            deploy_marker(env.name),
            _tag_line(wanted.tag),
            f"shipmill would deploy **{wanted.tag.tag}** to {env.name} now ({wanted.why}), but {cause}.",
            "",
            how,
            "",
            "```",
            approve,
            "```",
            "",
            f"Approving starts `{env.workflow}` with this tag once and closes this issue. Each operate run"
            " updates this issue while the deploy waits.",
        ]
    )


_TAG_LINE = re.compile(r"<!-- shipmill:tag=(?P<tag>\S+) -->")


def _close_deployed(github: GitHub, seen: Observed, dry_run: bool) -> str | None:
    """Close the environment's open deploy proposal once the environment runs its tag or a
    later one, whoever deployed it; what it did"""
    if seen.current is None or seen.tag is None:
        return None
    issue = find_proposal(github, deploy_marker(seen.env.name))
    if issue is None:
        return None
    found = _TAG_LINE.search(issue.body)
    proposed = Version.of_tag(found["tag"]) if found else None
    if proposed is not None and proposed > seen.tag:
        return None
    if dry_run:
        return f"would close proposal #{issue.number}: {seen.tag.tag} deployed"
    text = f"{seen.env.name} runs {seen.tag.tag} now (deployment {seen.current.id})."
    if proposed != seen.tag:
        text += f" This issue proposed {proposed.tag if proposed else 'another tag'}, so it is closed too."
    github.close_issue(issue.number, text)
    return f"closed proposal #{issue.number}: {seen.tag.tag} deployed"


def _act(
    policy: Policy,
    github: GitHub,
    env: Environment,
    wanted: Wanted,
    hold: Hold,
    dry_run: bool,
) -> str:
    stage = Stage.deploy(EnvironmentName(env.name))
    level = policy.autonomy.effective(stage, hold)
    would = "would " if dry_run else ""
    if level is Autonomy.ACT:
        if not dry_run:
            github.dispatch(env.workflow, wanted.tag.tag, wanted.tag.tag, env.inputs)
        return f"{would}dispatch {env.workflow} with {wanted.tag.tag} ({wanted.why})"
    cause = policy.autonomy.cause(stage, hold)
    if level is Autonomy.OBSERVE:
        return f"would deploy {wanted.tag.tag} ({wanted.why}), but {cause}"
    if dry_run:
        return f"would propose {wanted.tag.tag} ({wanted.why}): {cause}"
    fix = f"grant `issues: write` to the job that calls operate.yml in {OPERATE_CALLER}"
    number, outcome = upsert(
        github, deploy_marker(env.name), proposal_title(env, wanted), proposal_body(env, wanted, cause), fix
    )
    return f"proposal #{number} {outcome}: {wanted.tag.tag} ({cause})"


def operate(policy: Policy, git: Git, github: GitHub, http: Http, now: dt.datetime, dry_run: bool) -> list[Report]:
    """One run over every environment; git is operate's checkout, which holds the release tags"""
    environments = policy.environments
    tags = git.tags()
    hold = Hold.read(github) if environments else Hold()
    observed = {name: observe(github, http, env, tags, now) for name, env in environments.items()}
    rollback_after = policy.operate.rollback_after
    # every compare before any write: a failed read of a pull request's body stops the run
    # with nothing written for its environment, and a promotion sees a difference found now
    compares = {name: _compare(git, github, http, seen, tags) for name, seen in observed.items()}
    failed = {
        name
        for name, found in compares.items()
        if isinstance(found, Compared) and found.state is DeploymentState.FAILURE
    }
    differing = frozenset(failed | {name for name, seen in observed.items() if _differed(seen.statuses)})
    checked = any(seen.probe is not None for seen in observed.values())
    # without a health check, a compared environment's deployment success may end its compare incident
    unchecked = any(s.env.health is None and s.env.probes and s.current is not None for s in observed.values())
    known = incidents(policy, github) if checked or failed or unchecked else []
    reports = []
    for name, seen in observed.items():
        target = _bake_target(seen.env, environments)
        actions = []
        status = _status(seen, target, rollback_after, now)
        # the incident before the status: if opening it fails, the next run still counts
        # this check, and tries again
        incident = _incident(policy, github, seen, tags, known, hold, now, dry_run)
        if status is not None:
            assert seen.current is not None  # a status is only wanted for a current deployment
            if not dry_run:
                github.create_deployment_status(seen.current.id, *status)
            actions.append(f"{'would mark' if dry_run else 'marked'} {status[0]}")
        if incident is not None:
            actions.append(incident)
        # after the health status: the compare follows a check this run passed
        compared = compares[name]
        if isinstance(compared, Compared):
            actions.append(_mark_compared(policy, github, seen, compared, tags, known, hold, dry_run))
        elif compared is not None:
            actions.append(compared)
        wanted = _wanted(seen, observed, tags, now, differing)
        waits = False  # a deploy waits: its proposal is updated, not closed
        if isinstance(wanted, str):
            actions.append(wanted)
        elif (tried := seen.tried(wanted.tag)) is not None:
            states = github.deployment_statuses(tried.id)
            state = states[-1].state if states else DeploymentState.PENDING
            actions.append(f"{wanted.tag.tag} was deployed here already ({state}); shipmill doesn't deploy it again")
        elif (started := _started(github, seen.env, wanted.tag, wanted.since)) is not None:
            # a deploy job makes its deployment only when it starts, after the jobs it needs and
            # a wait for a runner: until then the run is the only sign the tag was dispatched
            actions.append(
                f"{seen.env.workflow} already ran with {wanted.tag.tag} ({started.status}, run {started.id});"
                " shipmill doesn't deploy it again"
            )
        else:
            waits = True
            actions.append(_act(policy, github, seen.env, wanted, hold, dry_run))
        if not waits and (closed := _close_deployed(github, seen, dry_run)) is not None:
            actions.append(closed)
        tag = seen.tag.tag if seen.tag else (seen.current.ref if seen.current else "-")
        health = _health_text(seen, target, rollback_after, now)
        reports.append(Report(name, tag, health, "; ".join(actions)))
    return reports


def approve(policy: Policy, github: GitHub, name: str, dry_run: bool) -> str:
    """Deploy the tag a proposal issue names, once, and close the issue; a person acting, so
    it goes under propose and observe, but never under the hold (D-8)"""
    env = policy.environments.get(name)
    if env is None:
        known = ", ".join(policy.environments) or "none"
        raise ReleaseError(f"no environment {name!r} in [environments]; known: {known}")
    hold = Hold.read(github)
    if hold.on:
        raise ReleaseError(f"{hold.reason}; close it to approve a deploy")
    issue = find_proposal(github, deploy_marker(name))
    if issue is None:
        raise ReleaseError(f"no open proposal to deploy to {name}; operate opens one when a deploy waits on approval")
    found = _TAG_LINE.search(issue.body)
    if found is None:
        raise ReleaseError(f"proposal #{issue.number} names no tag; the next operate run rewrites it")
    tag = Version.of_tag(found["tag"])
    tried = [d for d in github.deployments(name) if d.ref.removeprefix("refs/tags/") == tag.tag]
    if tried:
        raise ReleaseError(
            f"{tag.tag} was deployed to {name} already (deployment {tried[0].id}); close #{issue.number}"
        )
    running = [r for r in github.workflow_runs(env.workflow, tag.tag) if r.status != "completed"]
    if running:
        raise ReleaseError(
            f"{env.workflow} is running with {tag.tag} already (run {running[0].id}, {running[0].status});"
            f" close #{issue.number} once its deployment shows"
        )
    if dry_run:
        return f"would dispatch {env.workflow} with {tag.tag} to {name} and close #{issue.number}"
    github.dispatch(env.workflow, tag.tag, tag.tag, env.inputs)
    github.close_issue(issue.number, f"Approved: started `{env.workflow}` with {tag.tag} for {name}.")
    return f"dispatched {env.workflow} with {tag.tag} to {name}; closed #{issue.number}"


def approve_rollback(policy: Policy, github: GitHub, name: str, dry_run: bool) -> str:
    """Start the rollback an incident proposes, once; a person acting, so it goes under
    propose and observe, but never under the hold (D-8)"""
    env = policy.environments.get(name)
    if env is None:
        known = ", ".join(policy.environments) or "none"
        raise ReleaseError(f"no environment {name!r} in [environments]; known: {known}")
    hold = Hold.read(github)
    if hold.on:
        raise ReleaseError(f"{hold.reason}; close it to approve a rollback")
    proposed = [
        i
        for i in incidents(policy, github)
        if i.env == name and not i.issue.closed and i.state is IncidentState.PROPOSED
    ]
    if not proposed:
        raise ReleaseError(
            f"no open incident proposes a rollback of {name}; operate proposes one under propose or a hold"
        )
    incident = proposed[0]
    assert incident.to is not None  # a proposed rollback names its tag
    to = incident.to
    deployments = github.deployments(name)
    bad = [d for d in deployments if d.ref.removeprefix("refs/tags/") == incident.tag.tag]
    after = [d for d in deployments if d.ref.removeprefix("refs/tags/") == to.tag and bad and d.id > bad[0].id]
    if after:
        raise ReleaseError(
            f"{to.tag} was deployed to {name} after {incident.tag.tag} already (deployment {after[0].id})"
        )
    running = [r for r in github.workflow_runs(env.workflow, to.tag) if r.status != "completed"]
    if running:
        raise ReleaseError(
            f"{env.workflow} is running with {to.tag} already (run {running[0].id}, {running[0].status})"
        )
    if dry_run:
        return f"would dispatch {env.workflow} with {to.tag} to {name}, rolling back for incident #{incident.number}"
    url = github.dispatch(env.workflow, to.tag, to.tag, env.inputs)
    run = f": {url}" if url else ""
    github.update_issue(incident.number, incident.issue.title, incident.moved(IncidentState.ROLLED_BACK, to))
    github.comment_issue(incident.number, f"Approved: rolled back, started `{env.workflow}` with {to.tag}{run}.")
    return f"dispatched {env.workflow} with {to.tag} to {name}; rolled back for incident #{incident.number}"


def summary(reports: Sequence[Report], dry_run: bool) -> str:
    if not reports:
        return "No [environments] in the config: nothing to operate.\n"
    lines = [
        f"### shipmill operate{' (dry run)' if dry_run else ''}",
        "",
        "| Environment | Tag | Health | Action |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r.environment} | {r.tag} | {r.health.replace('|', '/')} | {r.action.replace('|', '/')} |" for r in reports
    ]
    return "\n".join(lines) + "\n"
