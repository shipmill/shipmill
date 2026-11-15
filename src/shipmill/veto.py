"""The veto windows a release would ship (spec 059): the notify decisions on the merged pull
requests in a candidate's base and not in the lane's newest tag, and on the issues they close,
read from the forge alone.

A decided marker counts when it is a comment's first line, by the App of [agents] app_id or an
OWNER, MEMBER, or COLLABORATOR (D-29). It holds a lane while its `until` is later than now, or
while a veto after it is unhandled: a person's comment (an OWNER, MEMBER, or COLLABORATOR, not
a bot, without the agent marker, D-62) whose first word is `veto`, with no newer trusted
`<!-- shipmill:veto-handled -->` comment, as triage_state.py reads VETOED (S-030-14).
"""

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from shipmill import agent_marker
from shipmill.errors import ReleaseError
from shipmill.github import GitHub, IssueComment, ShippedPull
from shipmill.gitrepo import Git, Tag

LONGEST = dt.timedelta(hours=168)  # the longest veto window, veto_hours' ceiling
SLACK = dt.timedelta(hours=1)  # read pull requests updated this much before the range's oldest commit
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
GHOST = "ghost"  # the login a deleted account's comment reads with
DECIDED = re.compile(r"<!-- shipmill:decided(?:\s[^>]*)?-->")
DECIDED_FIELDS = re.compile(r"<!-- shipmill:decided zone=([a-z][a-z-]*) until=(\S+) -->")
UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z", re.ASCII)
HANDLED = re.compile(r"<!-- shipmill:veto-handled(?:\s[^>]*)?-->")
VETO = re.compile(r"veto\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Window:
    """A decided marker that holds a lane: its item, zone, until, and whether a veto of it waits"""

    item: str  # "#196", or "owner/repo#12" for an issue of another repository
    zone: str
    until: dt.datetime
    vetoed: bool

    def __str__(self) -> str:
        if self.vetoed:
            return f"{self.item} {self.zone} vetoed, until the veto is handled"
        return f"{self.item} {self.zone} until {self.until:%Y-%m-%d %H:%M} UTC"


def first_line(body: str) -> str:
    return body.lstrip().split("\n", 1)[0].strip()


@dataclass
class Trust:
    """Who may write a decided or veto-handled marker: an OWNER, MEMBER, or COLLABORATOR, or the
    App of [agents] app_id, whose id is asked of GitHub once per Bot login (D-29)"""

    github: GitHub
    app_id: int | None
    _apps: dict[str, int] = field(default_factory=dict)

    def __call__(self, comment: IssueComment) -> bool:
        if comment.association in TRUSTED:
            return True
        if not comment.bot or self.app_id is None:
            return False
        if comment.author not in self._apps:
            self._apps[comment.author] = self.github.app_id(comment.author)
        return self._apps[comment.author] == self.app_id


def by_person(comment: IssueComment) -> bool:
    """A comment that can be a person's veto: an OWNER, MEMBER, or COLLABORATOR's, not a bot's
    or a deleted account's, and not carrying the agent marker (D-16, D-62)"""
    if comment.bot or comment.author.lower() == GHOST:
        return False
    return comment.association in TRUSTED and not agent_marker.carries(comment.body)


def _until(item: str, comment: IssueComment) -> tuple[str, dt.datetime]:
    """The zone and until of a trusted decided marker; ReleaseError naming the item and the
    comment when its until isn't a UTC time or lies more than LONGEST after the comment"""
    where = f"{item}: the decided marker of @{comment.author}'s comment at {comment.created_at:%Y-%m-%d %H:%M} UTC"
    found = DECIDED_FIELDS.fullmatch(first_line(comment.body))
    if found is None:
        raise ReleaseError(f"{where} is not <!-- shipmill:decided zone=<id> until=<UTC time> -->")
    zone, text = found.group(1), found.group(2)
    bad = ReleaseError(f"{where} has until={text}, not a UTC time such as 2026-10-20T14:00:00Z")
    if not UTC_TIME.fullmatch(text):
        raise bad
    try:
        until = dt.datetime.fromisoformat(text)
    except ValueError:  # the shape of a time with no such day or hour, such as 2026-10-32
        raise bad from None
    if until - comment.created_at > LONGEST:
        raise ReleaseError(f"{where} has until={text}, more than {LONGEST.days * 24} hours after the comment")
    return zone, until


def windows(item: str, comments: Sequence[IssueComment], now: dt.datetime, trusted: Trust) -> list[Window]:
    """The windows an item's comments, oldest first, hold open: each trusted decided marker
    whose until is later than now, or that a veto after it, still unhandled, answers"""
    found = []
    for i, comment in enumerate(comments):
        if not DECIDED.fullmatch(first_line(comment.body)) or not trusted(comment):
            continue
        zone, until = _until(item, comment)
        veto, handled = -1, -1
        for j in range(i + 1, len(comments)):
            later = comments[j]
            if HANDLED.fullmatch(first_line(later.body)) and trusted(later):
                handled = j
            elif by_person(later) and VETO.match(first_line(later.body)):
                veto = j
        vetoed = veto > handled
        if vetoed or until > now:
            found.append(Window(item, zone, until, vetoed))
    return found


def shipped(git: Git, github: GitHub, base: str, tag: Tag | None, now: dt.datetime) -> list[ShippedPull]:
    """The merged pull requests a candidate with this base ships: those whose merge commit is
    in base and not in the lane's newest tag; with no tag yet, those merged in the last LONGEST
    whose merge commit is in base. GitHub is asked nothing when the range holds no commit"""
    if tag is None:
        since = now - LONGEST
        return [p for p in github.shipped_pulls(since) if p.merged_at >= since and git.is_ancestor(p.merge, base)]
    commits = git.commits_since(tag.commit, base)
    if not commits:
        return []
    return [p for p in github.shipped_pulls(min(commits.values()) - SLACK) if p.merge in commits]


def holding(pulls: Sequence[ShippedPull], now: dt.datetime, trusted: Trust) -> list[Window]:
    """The windows the pull requests and the issues they close hold open, oldest until first;
    an issue two of them close is read once"""
    found = []
    seen = set()
    for pull in pulls:
        found += windows(pull.name, pull.comments, now, trusted)
        for issue in pull.closes:
            if issue.name not in seen:
                seen.add(issue.name)
                found += windows(issue.name, issue.comments, now, trusted)
    return sorted(found, key=lambda w: (w.until, w.item, w.zone))
