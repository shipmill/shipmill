"""Spec 049: credit the decider. With [agents] credit = "decider", a merge through `shipmill
gh pr merge` names in a Co-authored-by trailer each trusted person a record shows decided
the change, so the merge of the App's pull request shows on their profile.

The records are read by sources, in the spec's order; a source names people, and `deciders`
keeps the trusted ones, once each, never a bot, the App, or the pull request's author. The
body the merge would have had is rebuilt as GitHub writes it, and the trailers go after it.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from shipmill.errors import ReleaseError

# The author associations a record's author is trusted by, as needs-decision reads replies
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_TRAILER_EMAIL = re.compile(r"^co-authored-by:.*<([^<>\s]+)>\s*$", re.IGNORECASE | re.MULTILINE)
_NO_STATE = frozenset({"COMMENTED", "PENDING"})  # reviews that leave a person's state as it was
_TRAILER_LINE = re.compile(r"[A-Za-z0-9-]+: .+")


@dataclass(frozen=True, slots=True)
class Person:
    """An account as a record names it; bot is GitHub's type Bot, which an App's account has"""

    login: str
    bot: bool

    @classmethod
    def parse(cls, user: Mapping[str, Any]) -> Person:
        login = str(user["login"])
        return cls(login, user["type"] == "Bot" or login.endswith("[bot]"))


@dataclass(frozen=True, slots=True)
class Pull:
    """The pull request a merge names, as `GET /repos/<owner>/<repo>/pulls/<n>` gives it"""

    number: int
    author: Person
    title: str
    body: str

    @classmethod
    def parse(cls, pull: Mapping[str, Any]) -> Pull:
        return cls(int(pull["number"]), Person.parse(pull["user"]), str(pull["title"]), pull["body"] or "")


@dataclass(frozen=True, slots=True)
class Review:
    """A submitted review; user None for a deleted account"""

    user: Person | None
    state: str  # APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED
    association: str

    @classmethod
    def parse(cls, review: Mapping[str, Any]) -> Review:
        user = review["user"]
        return cls(
            None if user is None else Person.parse(user), str(review["state"]), str(review["author_association"])
        )


@dataclass(frozen=True, slots=True)
class Commit:
    """A commit of the pull request: its message, and its author as the commit gives them,
    with the GitHub account linked to them (None when none is)"""

    message: str
    name: str
    email: str
    login: str | None

    @classmethod
    def parse(cls, commit: Mapping[str, Any]) -> Commit:
        author = commit["commit"]["author"]
        linked = commit["author"]
        login = None if linked is None else str(linked["login"])
        return cls(str(commit["commit"]["message"]), str(author["name"]), str(author["email"]), login)


@dataclass(frozen=True, slots=True)
class Account:
    """An account as `GET /users/<login>` gives it; name None when the profile has none"""

    id: int
    login: str
    name: str | None

    @classmethod
    def parse(cls, user: Mapping[str, Any]) -> Account:
        name = user["name"]
        return cls(int(user["id"]), str(user["login"]), None if name is None or not str(name).strip() else str(name))

    @property
    def email(self) -> str:
        """The noreply address GitHub credits the account's commits to"""
        return f"{self.id}+{self.login}@users.noreply.github.com"

    @property
    def trailer(self) -> str:
        name = self.login if self.name is None else self.name.strip()
        return f"Co-authored-by: {name} <{self.email}>"


class Message(StrEnum):
    """The repo's squash_merge_commit_message or merge_commit_message: the body GitHub writes"""

    PR_BODY = "PR_BODY"
    COMMIT_MESSAGES = "COMMIT_MESSAGES"
    BLANK = "BLANK"
    PR_TITLE = "PR_TITLE"


@dataclass(frozen=True, slots=True)
class Messages:
    """The repo's two settings, as `GET /repos/<owner>/<repo>` gives them"""

    squash: Message
    merge: Message

    @classmethod
    def parse(cls, repo: Mapping[str, Any]) -> Messages:
        def setting(key: str) -> Message:
            value = repo[key]
            if value not in {m.value for m in Message}:
                raise ReleaseError(
                    f"GitHub gave the repo's {key} as {value!r}, not one of {[m.value for m in Message]}"
                )
            return Message(value)

        return cls(setting("squash_merge_commit_message"), setting("merge_commit_message"))


class CreditReads(Protocol):
    """What the credit reads of the pull request and its repo; GhCli is one, tests pass a fake"""

    def credit_pull(self, number: int) -> Pull: ...

    def credit_reviews(self, number: int) -> list[Review]:
        """Every submitted review, oldest first, as GitHub lists them"""
        ...

    def credit_commits(self, number: int) -> list[Commit]:
        """The pull request's commits, in commit order"""
        ...

    def credit_account(self, login: str) -> Account: ...

    def credit_messages(self) -> Messages: ...


CreditReader = Callable[[Path, Path, Mapping[str, str]], CreditReads]  # checkout, gh, and env in


@dataclass(frozen=True, slots=True)
class Named:
    """A record naming a person as one who decided the change: trusted by its own rule (an
    author association, or for a label event a permission), and why, as the stderr line says"""

    person: Person
    trusted: bool
    why: str  # such as "approved the pull request"


Source = Callable[[CreditReads, Pull], list[Named]]


def approvers(reads: CreditReads, pull: Pull) -> list[Named]:
    """S-049-3: each person whose latest review is APPROVED, trusted by that review's author
    association, in the order of their reviews. As GitHub reads a review's state, a comment
    doesn't count: an approval stands until a later DISMISSED or CHANGES_REQUESTED"""
    latest: dict[str, tuple[Person, Review]] = {}
    for review in reads.credit_reviews(pull.number):
        if review.user is not None and review.state not in _NO_STATE:
            latest.pop(review.user.login.lower(), None)  # a later review moves them to its place
            latest[review.user.login.lower()] = (review.user, review)
    return [
        Named(person, review.association in TRUSTED, "approved the pull request")
        for person, review in latest.values()
        if review.state == "APPROVED"
    ]


# The records that name a decider, in the spec's order; each person is credited by the first
# that names them. Issue #786 adds answerers, issue authors, and planned accepters after these
SOURCES: tuple[Source, ...] = (approvers,)


def deciders(reads: CreditReads, pull: Pull, sources: Sequence[Source] = SOURCES) -> list[Named]:
    """S-049-7: the trusted people the sources name, in order, each once; never a bot, the App
    (a bot too), or the pull request's author, whom the commit already credits"""
    seen = {pull.author.login.lower()}
    found: list[Named] = []
    for source in sources:
        for named in source(reads, pull):
            key = named.person.login.lower()
            if named.trusted and not named.person.bot and key not in seen:
                seen.add(key)
                found.append(named)
    return found


def default_body(setting: Message, pull: Pull, commits: Sequence[Commit], squash: bool) -> str:
    """S-049-8: the body GitHub writes for the setting, with the co-author trailers a squash
    gets by default: one per distinct author of the commits other than the pull request's"""
    text = ""
    if setting is Message.PR_BODY:
        text = pull.body.strip()
    elif setting is Message.COMMIT_MESSAGES and len(commits) == 1:
        text = commits[0].message.partition("\n")[2].strip()
    elif setting is Message.COMMIT_MESSAGES:
        text = "\n\n".join(f"* {c.message.strip()}" for c in commits)
    if not squash:
        return text
    named = trailer_emails(text)
    others: list[str] = []
    for commit in commits:
        if commit.login is not None and commit.login.lower() == pull.author.login.lower():
            continue
        if commit.email.lower() not in named:
            named.add(commit.email.lower())
            others.append(f"Co-authored-by: {commit.name} <{commit.email}>")
    return with_trailers(text, others)


def trailer_emails(text: str) -> set[str]:
    """The emails text's Co-authored-by trailers name, lowercased"""
    return {email.lower() for email in _TRAILER_EMAIL.findall(text)}


def with_trailers(text: str, trailers: Sequence[str]) -> str:
    """text with trailers after it: in its last paragraph when that holds trailers already, as
    git reads only the last one, else in a paragraph of their own"""
    text = text.rstrip()
    if not trailers:
        return text
    if not text:
        return "\n".join(trailers)
    last = text.rpartition("\n\n")[2]
    joint = "\n" if all(_TRAILER_LINE.fullmatch(line) for line in last.splitlines()) else "\n\n"
    return text + joint + "\n".join(trailers)


def credited_body(base: str, accounts: Sequence[Account]) -> str | None:
    """base with one trailer per account its trailers don't already name by email, compared
    without case; None when every account is named already, so nothing changes"""
    named = trailer_emails(base)
    new = [a.trailer for a in accounts if a.email.lower() not in named]
    return None if not new else with_trailers(base, new)
