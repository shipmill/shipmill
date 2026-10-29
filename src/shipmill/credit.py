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
# The needs-decision protocol (skills/github-issue-triage/references/needs-decision.md): a
# question's first line, and the first line of an answer the App relays from a session, which
# names the person bare or in a code span (D-61); a login as GitHub allows one, a bare one
# ending the line or followed by a space or punctuation, so `@app[bot]` or `@org/team` names
# nobody rather than the account its first part spells
MARKER = "<!-- shipmill:needs-decision -->"
_LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
_DECISION_BY = re.compile(
    rf"Decision by (?:@(?P<bare>{_LOGIN})(?=$|\s|[,;:)]|[.!?](?:\s|$))|`@(?P<span>{_LOGIN})`(?![\w`-]))"
)
# The permissions on the repo a label event's author is trusted by; GitHub's legacy
# `permission` field reads maintain as write, and a custom role as the one it builds on
WRITERS = frozenset({"admin", "maintain", "write"})
OPPORTUNITY = "opportunity"  # product-intake's opportunity issue, and the label that accepts it
PLANNED = "planned"


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


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment on an issue or a pull request, as `GET .../issues/<n>/comments` gives it;
    user None for a deleted account"""

    user: Person | None
    association: str
    body: str

    @classmethod
    def parse(cls, comment: Mapping[str, Any]) -> Comment:
        user = comment["user"]
        return cls(
            None if user is None else Person.parse(user), str(comment["author_association"]), comment["body"] or ""
        )


@dataclass(frozen=True, slots=True)
class Filed:
    """An issue the pull request closes, or its sub-issue parent (parent None for a parent,
    whose own parent isn't read); author None for a deleted account; labels lowercased"""

    number: int
    author: Person | None
    association: str
    labels: frozenset[str]
    parent: Filed | None


# The GraphQL query of the issues a pull request closes and their parents (credit_closes)
CLOSES_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
    "nameWithOwner pullRequest(number: $number) { closingIssuesReferences(first: 100) { "
    "pageInfo { hasNextPage } nodes { ...filed parent { ...filed } } } } } } "
    "fragment filed on Issue { number repository { nameWithOwner } authorAssociation "
    "author { login __typename } labels(first: 100) { pageInfo { hasNextPage } nodes { name } } }"
)


def closes_of(found: Any, number: int) -> list[Filed]:
    """CLOSES_QUERY's answer for pull request number: the issues of its repo it closes, each
    with its parent when that is of the repo too. Anything malformed, or a list past one page,
    is refused, since a misread would credit the wrong person"""

    def refuse(what: str) -> ReleaseError:
        return ReleaseError(f"gh api graphql printed {what} for #{number}'s closing issues: {str(found)[:300]}")

    def page(holder: Any, key: str) -> list[Any]:
        connection = holder.get(key) if isinstance(holder, dict) else None
        if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
            raise refuse(f"no {key}")
        info = connection.get("pageInfo")
        if not isinstance(info, dict):
            raise refuse(f"no {key}")
        if info.get("hasNextPage") is not False:
            raise refuse(f"more than one page of {key}")
        return list(connection["nodes"])

    def issue(node: Any, parent: Filed | None) -> Filed:
        if not isinstance(node, dict) or not isinstance(node.get("number"), int):
            raise refuse("an issue without a number")
        author = node.get("author")
        person = None
        if isinstance(author, dict) and isinstance(author.get("login"), str):
            login, bot = author["login"], author.get("__typename") == "Bot"
            person = Person(login + "[bot]" if bot and not login.endswith("[bot]") else login, bot)
        elif author is not None:
            raise refuse(f"an author {author!r} of #{node['number']}")
        labels = page(node, "labels")
        if not all(isinstance(label, dict) and isinstance(label.get("name"), str) for label in labels):
            raise refuse(f"a label without a name on #{node['number']}")
        names = frozenset(str(label["name"]).lower() for label in labels)
        return Filed(int(node["number"]), person, str(node.get("authorAssociation")), names, parent)

    def home(node: Any) -> str:
        where = node.get("repository") if isinstance(node, dict) else None
        name = where.get("nameWithOwner") if isinstance(where, dict) else None
        if not isinstance(name, str):
            raise refuse("an issue without its repository")
        return name.lower()

    if not isinstance(found, dict) or found.get("errors"):
        raise refuse("errors or no object")
    data = found.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict) or not isinstance(repository.get("nameWithOwner"), str):
        raise refuse("no repository")
    repo = repository["nameWithOwner"].lower()
    closes: list[Filed] = []
    for node in page(repository.get("pullRequest"), "closingIssuesReferences"):
        if home(node) != repo:
            continue  # an issue of another repo: its records are that repo's, not this one's
        parent = node.get("parent")
        closes.append(issue(node, None if parent is None or home(parent) != repo else issue(parent, None)))
    return closes


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

    def credit_closes(self, number: int) -> list[Filed]:
        """The issues of the pull request's repo it closes, by GitHub's closing references, in
        GitHub's order, each with its sub-issue parent when that is in the repo too"""
        ...

    def credit_comments(self, number: int) -> list[Comment]:
        """Every comment on the issue or pull request, oldest first"""
        ...

    def credit_labelers(self, number: int, label: str) -> list[Person | None]:
        """Who added label to the issue, one per `labeled` event, oldest first; None for a
        deleted account"""
        ...

    def credit_permission(self, login: str) -> str:
        """The person's permission on the repo: admin, write, read, or none"""
        ...


CreditReader = Callable[[Path, Path, Mapping[str, str]], CreditReads]  # checkout, gh, and env in


@dataclass(frozen=True, slots=True)
class Named:
    """A record naming a person as one who decided the change: trusted by its own rule (an
    author association, or for a label event a permission), and why, as the stderr line says"""

    person: Person
    trusted: bool
    why: str  # such as "approved the pull request"


# A source reads the records of the pull request, knowing the App's bot login (`<slug>[bot]`)
Source = Callable[[CreditReads, Pull, str], list[Named]]


def approvers(reads: CreditReads, pull: Pull, app: str) -> list[Named]:
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


def first_line(body: str) -> str:
    """A comment's first line, past any leading blank lines, as triage_state.py reads it"""
    return body.lstrip().split("\n", 1)[0].strip()


def filed(reads: CreditReads, pull: Pull) -> list[Filed]:
    """The issues the pull request closes and their parents, each once: an issue, then its
    parent, in the order of the closing references"""
    found: dict[int, Filed] = {}
    for issue in reads.credit_closes(pull.number):
        for one in (issue, issue.parent):
            if one is not None and one.number not in found:
                found[one.number] = one
    return list(found.values())


def answers(comments: Sequence[Comment], where: str, app: str) -> list[Named]:
    """S-049-4: who answered a needs-decision question in comments, by the protocol's reply
    rules: a question is a comment whose first line is the marker, by the App (its bot login,
    app) or an OWNER, MEMBER, or COLLABORATOR other than a bot; a reply is a later comment
    without the marker by a person, trusted by its author association. A comment of the App's
    whose first line is `Decision by @<login>` or ``Decision by `@<login>` `` relays the answer
    of <login>, given in a session; another bot's comment is neither a question nor a relay"""
    why = f"answered the decision on {where}"
    found: list[Named] = []
    asked = False
    for comment in comments:
        if comment.user is None:
            continue
        line = first_line(comment.body)
        by_app = comment.user.login.lower() == app.lower()
        if line == MARKER:
            asked = asked or by_app or (not comment.user.bot and comment.association in TRUSTED)
        elif comment.user.bot:
            relayed = _DECISION_BY.match(line) if by_app else None
            if relayed is not None:
                found.append(Named(Person(relayed["bare"] or relayed["span"], False), True, why))
        elif asked:
            found.append(Named(comment.user, comment.association in TRUSTED, why))
    return found


def answerers(reads: CreditReads, pull: Pull, app: str) -> list[Named]:
    """S-049-4: the answerers of needs-decision questions on the pull request, then on each
    issue it closes and that issue's parent"""
    found = answers(reads.credit_comments(pull.number), "the pull request", app)
    for issue in filed(reads, pull):
        found.extend(answers(reads.credit_comments(issue.number), f"#{issue.number}", app))
    return found


def authors(reads: CreditReads, pull: Pull, app: str) -> list[Named]:
    """S-049-5: the author of each issue the pull request closes and of its parent, trusted by
    the issue's author association, since the filing is the decision"""
    return [
        Named(issue.author, issue.association in TRUSTED, f"filed #{issue.number}")
        for issue in filed(reads, pull)
        if issue.author is not None
    ]


def accepters(reads: CreditReads, pull: Pull, app: str) -> list[Named]:
    """S-049-6: for each opportunity issue labelled planned that the pull request closes, or
    that is the parent of one, the person whose `labeled` event added planned last, trusted by
    a write, maintain, or admin permission on the repo"""
    found: list[Named] = []
    for issue in filed(reads, pull):
        if not {OPPORTUNITY, PLANNED} <= issue.labels:
            continue
        added = reads.credit_labelers(issue.number, PLANNED)
        person = added[-1] if added else None
        if person is not None:
            trusted = not person.bot and reads.credit_permission(person.login) in WRITERS
            found.append(Named(person, trusted, f"accepted #{issue.number} ({PLANNED})"))
    return found


# The records that name a decider, in the spec's order; each person is credited by the first
# that names them
SOURCES: tuple[Source, ...] = (approvers, answerers, authors, accepters)


def deciders(reads: CreditReads, pull: Pull, app: str, sources: Sequence[Source] = SOURCES) -> list[Named]:
    """S-049-7: the trusted people the sources name, in order, each once; never a bot, the App
    (app, its bot login), or the pull request's author, whom the commit already credits"""
    seen = {pull.author.login.lower(), app.lower()}
    found: list[Named] = []
    for source in sources:
        for named in source(reads, pull, app):
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
