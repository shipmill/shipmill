"""How many of the issues a stable promotion's rc fixed have a confirmed requester (spec 021):
reported in the promotion's reason, never a gate (S-021-8)"""

import datetime as dt
import re
from dataclasses import dataclass

from shipmill.errors import ReleaseError
from shipmill.github import VOTE_COMMENTS, VOTE_REACTIONS, GitHub, RequesterVotes
from shipmill.gitrepo import Git
from shipmill.version import PATTERN, Version

# a notice's first line, as shipped.py writes it and the watch reads it (spec 021, D-29)
MARKER = re.compile(r"^<!-- shipmill:available: (\S+) (\S+) -->\s*$")
PRE_RELEASE = "pre-release"


@dataclass(frozen=True, slots=True)
class Count:
    confirmed: int
    fixed: int

    def __str__(self) -> str:
        return f"{self.confirmed} of {self.fixed} requesters confirmed"


def pre_release(tag: str) -> bool:
    """A dev, a, b, or rc version tag, whose notice asks the requester to answer"""
    text = tag.removeprefix("v")
    return PATTERN.fullmatch(text) is not None and not Version.parse(text).is_stable


def confirmed(votes: RequesterVotes) -> bool:
    """Whether the requester reacted 👍 to the issue's newest pre-release notice, as the
    watch's REQUESTER_CONFIRMED reads it (S-021-6); a marker naming no pre-release tag is no
    notice, since anyone can write one. An answer that may lie past what was read is refused
    rather than counted as none"""
    if votes.requester is None:
        return False
    newest = None
    for comment in votes.comments:
        marker = MARKER.match(comment.first_line)
        if marker is not None and marker.group(1) == PRE_RELEASE and pre_release(marker.group(2)):
            newest = comment
    if newest is None:
        if votes.earlier:
            raise ReleaseError(f"#{votes.number} has more than {VOTE_COMMENTS} comments and none read is a notice")
        return False
    if votes.requester in newest.thumbs_up:
        return True
    if newest.more:
        raise ReleaseError(f"#{votes.number}'s pre-release notice has more than {VOTE_REACTIONS} 👍s")
    return False


def count(git: Git, github: GitHub, since: str | None, base: str) -> Count:
    """The closed issues with a fix base holds and since (the last stable tag; None before
    the first) doesn't, and how many of their requesters confirmed. Only issues closed from
    the day before base's oldest commit past since are read: an issue closes after its fix
    is committed"""
    oldest = git.oldest_commit_time(since, base)
    if oldest is None:
        return Count(0, 0)
    numbers = github.closed_since((oldest - dt.timedelta(days=1)).date())
    fixed = [
        close.number
        for close in (github.issue_closes(numbers) if numbers else [])
        if not close.open
        and any(
            git.is_ancestor(fix, base) and not (since is not None and git.is_ancestor(fix, since))
            for fix in close.fixes
        )
    ]
    votes = github.requester_votes(fixed) if fixed else []
    return Count(sum(confirmed(v) for v in votes), len(fixed))
