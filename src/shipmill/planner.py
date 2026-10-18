"""Decide whether a lane releases now: a candidate (what would be released), its triggers
(what makes it due), and its gates (what holds it)"""

import datetime as dt
import fnmatch
import json
from dataclasses import dataclass, field
from enum import StrEnum

from shipmill import fragments, milestones
from shipmill.autonomy import Autonomy, Hold, Stage
from shipmill.changelog import Changelog, Entry
from shipmill.errors import ReleaseError
from shipmill.github import GitHub
from shipmill.gitrepo import WORKFLOWS, Git, Tag
from shipmill.policy import PRIORITY, BumpFrom, Lane, LaneRule, Mode, Policy
from shipmill.version import ZERO, Part, Version

BREAKING = "a breaking change waits for the maintainer's decision"  # a breaking stable candidate's cause


class Event(StrEnum):
    PUSH = "push"
    SCHEDULE = "schedule"
    MANUAL = "workflow_dispatch"


@dataclass(frozen=True, slots=True)
class Hotfix:
    prs: tuple[int, ...]
    from_tag: str | None = None


@dataclass(frozen=True, slots=True)
class Proposal:
    """A due release shipmill doesn't make by itself, and why: a person starts the lane"""

    lane: Lane
    version: Version
    base: str
    cause: str  # "release autonomy is propose", "held by shipmill-hold #N", or BREAKING

    def as_dict(self) -> dict[str, str]:
        return {"lane": self.lane.value, "version": str(self.version), "base": self.base, "cause": self.cause}

    @classmethod
    def from_dict(cls, raw: object) -> Proposal:
        if not isinstance(raw, dict) or set(raw) != {"lane", "version", "base", "cause"}:
            raise ReleaseError(f"a proposal has lane, version, base, and cause; got {raw!r}")
        if not all(isinstance(v, str) and v for v in raw.values()):
            raise ReleaseError(f"a proposal's fields are non-empty strings; got {raw!r}")
        if raw["lane"] not in set(Lane):
            raise ReleaseError(f"a proposal's lane is one of {[ln.value for ln in Lane]}; got {raw['lane']!r}")
        return cls(Lane(raw["lane"]), Version.parse(raw["version"]), raw["base"], raw["cause"])


@dataclass(frozen=True, slots=True)
class Decision:
    mode: Mode
    action: str  # "release", "propose", or "skip"
    reason: str
    lane: Lane | None = None
    version: Version | None = None
    base: str = ""
    merges: tuple[str, ...] = ()  # a hotfix's merge commits, in PR order
    prs: tuple[int, ...] = ()
    proposals: tuple[Proposal, ...] = ()  # with action "propose"

    def outputs(self) -> dict[str, str]:
        return {
            "mode": self.mode.value,
            "action": self.action,
            "reason": self.reason,
            "lane": self.lane.value if self.lane else "",
            "version": str(self.version) if self.version else "",
            "base": self.base,
            "merges": " ".join(self.merges),
            "prs": " ".join(str(p) for p in self.prs),
            "proposals": json.dumps([p.as_dict() for p in self.proposals]) if self.proposals else "",
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    version: Version
    base: str
    why: str
    merges: tuple[str, ...] = ()
    prs: tuple[int, ...] = ()
    source: str = ""  # what the base is, when not main's head: the rc a promotion's base is
    breaking: bool = False  # a stable candidate whose pending entries bump the major part (spec 029)


@dataclass(frozen=True, slots=True)
class _Deferred:
    """Why a lane skips this run, named in the reason of the lane that releases instead"""

    why: str


@dataclass
class Planner:
    git: Git
    policy: Policy
    github: GitHub
    now: dt.datetime
    _tags: list[Tag] = field(default_factory=list)
    _hold: Hold | None = None

    def __post_init__(self) -> None:
        self._tags = self.git.tags()

    # -- state read from tags ------------------------------------------------------------

    def last_stable(self) -> Tag | None:
        stable = [t for t in self._tags if t.version.is_stable]
        return max(stable, key=lambda t: t.version) if stable else None

    def _lane_tags(self, lane: Lane) -> list[Tag]:
        if lane is Lane.DEV:
            return [t for t in self._tags if t.version.dev is not None]
        if lane is Lane.RC:
            marker = self.policy.rule(Lane.RC).marker
            return [t for t in self._tags if t.version.pre == marker and t.version.dev is None]
        return [t for t in self._tags if t.version.is_stable]

    def _last_release_time(self, lane: Lane) -> dt.datetime | None:
        tags = self._lane_tags(Lane.STABLE if lane is Lane.HOTFIX else lane)
        return max((t.date for t in tags), default=None)

    def _has_tag(self, version: Version) -> bool:
        return any(t.version == version for t in self._tags)

    def changelog_at(self, rev: str) -> Changelog:
        text = self.git.show(rev, self.policy.changelog)
        if text is None:
            raise ReleaseError(f"no {self.policy.changelog} at {rev[:12]}")
        return Changelog(text, self.policy.style)

    def fragments_at(self, rev: str) -> list[Entry]:
        """The changelog fragments' entries at rev, read through git, never the checkout (spec 013)"""
        return fragments.entries(fragments.at_revision(self.git, self.policy, rev))

    def target(self, pending: list[Entry], rev: str) -> Version:
        """The stable version main's head leads to: the last stable bumped by what is pending,
        or the open pre-release series if that is higher"""
        last = self.last_stable()
        base = last.version if last else ZERO
        part = self._part(pending, rev, last)
        version = base.bump(part)
        series = [t.version.release for t in self._tags if not t.version.is_stable and t.version.release > base]
        return max([version, *series])

    def _part(self, pending: list[Entry], rev: str, last: Tag | None) -> Part:
        if self.policy.bump_from is BumpFrom.HEADINGS:
            parts = []
            for entry in pending:
                if entry.heading is None or entry.heading not in self.policy.bump_headings:
                    raise ReleaseError(
                        f"CHANGELOG heading {entry.heading!r} is not in the policy's [bump] lists; add it"
                    )
                parts.append(self.policy.bump_headings[entry.heading])
            return max(parts, key=lambda p: p.rank, default=Part.PATCH)
        if last is None:
            raise ReleaseError("bump from = 'paths' needs a stable release tag to diff against")
        changed = self.git.changed_paths(last.commit, rev)
        hits = [p for p in changed if any(fnmatch.fnmatch(p, g) for g in self.policy.minor_paths)]
        return Part.MINOR if hits else Part.PATCH

    def _breaking(self, pending: list[Entry]) -> bool:
        """Whether the entries hold one under a `major` heading: read from the headings, not
        the version, since before 1.0 a major bump moves the minor. Paths never bump the major"""
        if self.policy.bump_from is not BumpFrom.HEADINGS:
            return False
        major = {h for h, part in self.policy.bump_headings.items() if part is Part.MAJOR}
        return any(entry.heading in major for entry in pending)

    # -- candidates ------------------------------------------------------------------------

    def _candidate(self, lane: Lane, head: str) -> _Candidate | _Deferred | str:
        """What the lane would release from main's head, or why there is nothing to"""
        rule = self.policy.rule(lane)
        changelog = self.changelog_at(head)
        pending = changelog.pending(self.fragments_at(head))
        if lane is Lane.STABLE and rule.promote:
            return self._promotion(rule, head)
        if lane is Lane.DEV:
            covered = [t for t in self._tags if self.git.is_ancestor(head, t.commit)]
            if covered:
                return f"{max(covered, key=lambda t: t.date).name} already holds main's head"
            # after 1.4.0rc2, a dev build is 1.4.0rc3.devN: 1.4.0.devN would sort before the rc
            target = self.target(pending, head)
            series = target
            if Lane.RC in self.policy.lanes:
                marker = self.policy.lanes[Lane.RC].marker
                rcs = [t.version.pre_n or 0 for t in self._lane_tags(Lane.RC) if t.version.release == target]
                if rcs:
                    series = target.with_pre(marker, max(rcs) + 1)
            version = series.with_dev(self.git.first_parent_count(head))
            return _Candidate(version, head, f"{len(pending)} pending entries; dev build of {series}")
        if not pending:
            return f"nothing pending under {fragments.where(self.policy)}"
        target = self.target(pending, head)
        if lane is Lane.RC:
            same = [t for t in self._lane_tags(Lane.RC) if t.version.release == target]
            if any(self.git.is_ancestor(head, t.commit) for t in same):
                return f"an rc of {target} already holds main's head"
            n = max((t.version.pre_n or 0 for t in same), default=0) + 1
            return _Candidate(target.with_pre(rule.marker, n), head, f"{len(pending)} pending entries")
        return _Candidate(target, head, f"{len(pending)} pending entries", breaking=self._breaking(pending))

    def _promotion(self, rule: LaneRule, head: str) -> _Candidate | _Deferred | str:
        last = self.last_stable()
        floor = last.version if last else ZERO
        soak = dt.timedelta(days=rule.min_soak_days)
        rcs = [t for t in self._lane_tags(Lane.RC) if t.version.release > floor]
        if not rcs:
            return f"no rc after {floor} to promote"
        ripe = [t for t in rcs if self.now - t.date >= soak]
        if not ripe:
            youngest = min(self.now - t.date for t in rcs)
            return f"no rc has soaked {rule.min_soak_days} day(s); the oldest candidate is {youngest.days} day(s) old"
        rc = max(ripe, key=lambda t: t.version)
        version = rc.version.release
        if self._has_tag(version):
            return f"{version.tag} exists already"
        # an rc cut by the bot is a stamp commit off main whose first parent is main's commit;
        # an rc tagged on main itself (a release commit) is its own base
        on_main = self.git.is_ancestor(rc.commit, "HEAD")
        base = rc.commit if on_main else self.git.first_parent(rc.commit)
        # the rc sections of version an earlier release bot wrote are pending too (D-25)
        changelog = self.changelog_at(base)
        promoted = changelog.promoted(version, self.fragments_at(base))
        if not promoted:
            sections = changelog.rc_sections(version)
            found = (
                f"its rc sections {', '.join(f'[{v}]' for v in sections)} hold no entries"
                if sections
                else f"no [{version}rcN] section"
            )
            return f"{rc.name}'s base has nothing pending under {fragments.where(self.policy)}, and {found}"
        # the run's CI is a local reusable workflow, read at the run's commit, not at the rc's:
        # once main's CI moved on, it would test the rc's tree with CI the rc never soaked with (D-28)
        if self.git.differs(rc.commit, head, WORKFLOWS):
            return _Deferred(
                f"the CI workflows ({WORKFLOWS}) changed since {rc.name}; the next rc carries them"
                " and soaks before it's promoted"
            )
        return _Candidate(
            version,
            base,
            f"promotes {rc.name}, soaked {(self.now - rc.date).days} day(s)",
            source=rc.name,
            breaking=self._breaking(promoted),
        )

    def _hotfix(self, hotfix: Hotfix) -> _Candidate:
        if not hotfix.prs:
            raise ReleaseError("a hotfix needs the pull requests to ship, such as --hotfix-prs 12,15")
        stable = [t for t in self._tags if t.version.is_stable]
        if hotfix.from_tag:
            source = Version.of_tag(hotfix.from_tag)
            if not source.is_stable or not self._has_tag(source):
                raise ReleaseError(f"--hotfix-from {hotfix.from_tag}: not a stable release tag")
        else:
            if not stable:
                raise ReleaseError("a hotfix needs a stable release to start from")
            source = max(t.version for t in stable)
        in_series = [t for t in stable if t.version.series == source.series]
        latest = max(in_series, key=lambda t: t.version)
        version = Version(latest.version.major, latest.version.minor, latest.version.patch + 1)
        if self._has_tag(version):
            raise ReleaseError(f"{version.tag} exists already")
        branch = f"release/{source.series}"
        base = self.git.remote_branch(branch) or latest.commit
        if not self.git.is_ancestor(latest.commit, base):
            raise ReleaseError(f"{branch} does not contain {latest.name}")
        merges = tuple(self.github.merge_commit(pr) for pr in hotfix.prs)
        for pr, merge in zip(hotfix.prs, merges, strict=True):
            if not self.git.is_ancestor(merge, "HEAD"):
                raise ReleaseError(f"#{pr} landed as {merge[:12]}, which is not on {self.policy.branch}")
        listed = ", ".join(f"#{p}" for p in hotfix.prs)
        return _Candidate(version, base, f"hotfix of {latest.name} with {listed}", merges, hotfix.prs)

    # -- triggers and gates ----------------------------------------------------------------

    def _due(self, lane: Lane, candidate: _Candidate, head: str) -> str | milestones.Verdict | None:
        """Which trigger made the lane due; None when none did, or the milestone's verdict
        when its issues are closed but the goal behind them isn't done (spec 022)"""
        rule = self.policy.rule(lane)
        if rule.quiet_minutes is not None:
            quiet = self.now - self.git.commit_time(head)
            if quiet >= dt.timedelta(minutes=rule.quiet_minutes):
                return f"main quiet for {int(quiet.total_seconds() // 60)} min"
        last = self._last_release_time(lane)
        for window in rule.schedule:
            start = window.latest_start(self.now)
            if start is not None and (last is None or last < start):
                return f"window '{window.text}' opened at {start:%Y-%m-%d %H:%M} UTC"
        if rule.milestone:
            milestone = self.github.milestone(str(candidate.version.release))
            if milestone is not None and milestone.open_issues == 0 and milestone.closed_issues > 0:
                found = self.milestone_verdict(candidate, head)
                return found.reason if found.done else found
        return None

    def milestone_verdict(self, candidate: _Candidate, head: str) -> milestones.Verdict:
        """Whether the goal of the candidate's milestone, closed already, is done: its specs
        at main's head, their build issues' fixes in the candidate's base"""
        where = candidate.source or ("main's head" if candidate.base == head else candidate.base[:12])
        app_id = self.policy.agents.app_id if self.policy.agents else None
        title = str(candidate.version.release)
        return milestones.verdict(self.git, self.github, title, head, candidate.base, where, app_id)

    def hold(self) -> Hold:
        """The stop switch, read once per plan and only once a lane is due"""
        if self._hold is None:
            self._hold = Hold.read(self.github)
        return self._hold

    def _held(self, lane: Lane) -> str | None:
        if lane in self.policy.freeze_lanes:
            for freeze in self.policy.freezes:
                if freeze.holds(self.now):
                    return f"frozen {freeze.first}..{freeze.last}"
        if lane in self.policy.blocker_lanes:
            # an open incident (shipmill operate opens one when it rolls back) holds the same
            # lanes the blocker label does, until a person or a hotfix's "Fixes #N" closes it
            for label in (self.policy.blocker_label, self.policy.incident_label):
                if label and (blockers := self.github.open_issues(label)):
                    return f"open '{label}' issues: {', '.join(blockers)}"
        return None

    def _autonomy(self, lane: Lane, candidate: _Candidate) -> tuple[Autonomy, str]:
        """How far a trigger releases the candidate by itself, and why not further. A breaking
        stable candidate is at most propose, as the hold makes every stage (D-8, D-39); a
        person starting the lane by hand doesn't come here"""
        level = self.policy.autonomy.effective(Stage.release(), self.hold())
        cause = self.policy.autonomy.cause(Stage.release(), self.hold())
        if lane is Lane.STABLE and candidate.breaking and level is not Autonomy.OBSERVE:
            # the hold names itself first: it stops the hand start that releases a breaking change
            return Autonomy.PROPOSE, cause if self.hold().on else BREAKING
        return level, cause

    # -- the decision --------------------------------------------------------------------------

    def plan(
        self, event: Event, lane: Lane | None = None, dry_run: bool = False, hotfix: Hotfix | None = None
    ) -> Decision:
        mode = Mode.DRY_RUN if dry_run and self.policy.mode is not Mode.OFF else self.policy.mode
        if mode is Mode.OFF:
            return Decision(mode, "skip", "the policy's mode is off")
        if (lane is Lane.HOTFIX) != (hotfix is not None):
            raise ReleaseError("the hotfix lane and --hotfix-prs go together")
        if lane is not None and event is not Event.MANUAL:
            raise ReleaseError("--lane picks a lane by hand: it needs a workflow_dispatch run")
        head = self.git.sha("HEAD")
        lanes = [lane] if lane else [ln for ln in PRIORITY if ln in self.policy.lanes and ln is not Lane.HOTFIX]
        skipped = []
        proposals = []
        unplanned: ReleaseError | None = None  # the stable lane's, when it couldn't work out a candidate
        notes = []  # why a lane before the releasing one skipped, named in the release's reason
        for current in lanes:
            self.policy.rule(current)
            if hotfix:
                candidate: _Candidate | _Deferred | str = self._hotfix(hotfix)
            elif current is Lane.STABLE and lane is None:
                # a stable lane that can't read its candidate (a bad rc section to fold, #296)
                # doesn't stop rc and dev; the plan fails with its error only if they don't release
                try:
                    candidate = self._candidate(current, head)
                except ReleaseError as error:
                    unplanned = error
                    skipped.append(f"{current}: not planned, {error}")
                    notes.append(f"{current}: not planned, {error}")
                    continue
            else:
                candidate = self._candidate(current, head)
            if isinstance(candidate, _Deferred):
                skipped.append(f"{current}: {candidate.why}")
                notes.append(f"{current}: {candidate.why}")
                continue
            if isinstance(candidate, str):
                skipped.append(f"{current}: {candidate}")
                continue
            if self._has_tag(candidate.version):
                skipped.append(f"{current}: {candidate.version.tag} exists already")
                continue
            if lane:
                due: str | milestones.Verdict | None = "started by hand"
            elif current is Lane.STABLE:
                # a goal the stable lane can't read (a spec naming no issue, #296's kind of
                # error) doesn't stop rc and dev either; any other error, the milestone's own
                # read included, fails the plan as before, so an outage never releases an rc
                try:
                    due = self._due(current, candidate, head)
                except milestones.GoalError as error:
                    unplanned = error
                    skipped.append(f"{current}: not planned, {error}")
                    notes.append(f"{current}: not planned, {error}")
                    continue
            else:
                due = self._due(current, candidate, head)
            if due is None:
                skipped.append(f"{current}: {candidate.version} is ready but no trigger is due")
                continue
            if isinstance(due, milestones.Verdict):
                # what holds a goal is named even when a later lane releases (spec 022)
                skipped.append(f"{current}: {candidate.version} is ready but no trigger is due; {due.reason}")
                notes.append(f"{current}: {due.reason}")
                continue
            held = self._held(current)
            if held is not None:
                skipped.append(f"{current}: {candidate.version} held, {held}")
                continue
            if lane is not None:
                # a person started the lane: autonomy is the bot's, but the hold stops people
                # too, except for a hotfix, the usual cure for the incident behind a hold
                if self.hold().on and lane is not Lane.HOTFIX:
                    skipped.append(
                        f"{current}: {candidate.version} {self.hold().reason}; close it to release by hand"
                        " (a hotfix can still be started by hand)"
                    )
                    continue
            elif (gate := self._autonomy(current, candidate))[0] is not Autonomy.ACT:
                level, cause = gate
                if level is Autonomy.OBSERVE:
                    skipped.append(f"{current}: {candidate.version} is due ({due}), but {cause}")
                else:
                    proposals.append(Proposal(current, candidate.version, candidate.base, cause))
                continue
            return Decision(
                mode,
                "release",
                "; ".join([f"{current} {candidate.version}: {candidate.why}", due, *notes]),
                current,
                candidate.version,
                candidate.base,
                candidate.merges,
                candidate.prs,
            )
        if proposals:
            proposed = [f"{p.lane}: {p.version} is due, proposed instead of released: {p.cause}" for p in proposals]
            return Decision(mode, "propose", "; ".join(proposed + skipped), proposals=tuple(proposals))
        if unplanned is not None:
            raise unplanned
        return Decision(mode, "skip", "; ".join(skipped) or "no lane enabled")
