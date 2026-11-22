"""Spec 088 (#1473): what `shipmill status --item` says beside an item's conditions. The
holder's step, from the item's newest trusted hand-off comment; what waits on the item,
transitively and across repos, from chains.py show's walk (spec 017, the holds spec 086 counts)
and this repo's triage_state.py BLOCKED notes; and the issues its open pull requests close.
Every read here only reads (S-088-12)."""

import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from shipmill.errors import ReleaseError
from shipmill.gate import StateRunner, skills_dir
from shipmill.status import gh_read

HANDOFF_MARKER = "<!-- shipmill:handoff -->"  # triage_state.py's HANDOFF_MARKER
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})  # triage_state.py's TRUSTED (D-16)
STEP_LIMIT = 200  # a step longer than this is cut, with an ellipsis
CLOSING_LIMIT = 50  # the closing references read per pull request
REF = re.compile(r"(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>[1-9]\d*)")
WAIT = re.compile(r"(?P<ref>[\w.-]+/[\w.-]+#\d+):(?P<state>\w+)")  # item_status.py's WAIT
MENTIONS = re.compile(r"^(?:@[\w.-]+(?:/[\w.-]+)?[\s,]*)+")
LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
WAITING_STATES = frozenset({"BLOCKED", "CYCLE"})  # chains.py show's open issue held by an open item
CHAIN_BUCKET = {"BLOCKED": "parked", "CYCLE": "to triage"}  # the picture's line for each (ISSUE_LINES)

CLOSING = (
    f"closingIssuesReferences(first: {CLOSING_LIMIT}) " + "{ nodes { number state repository { nameWithOwner } } }"
)
ITEM_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        comments(last: 100) { nodes { body createdAt authorAssociation author { __typename login } } }
        closedByPullRequestsReferences(first: 20, includeClosedPrs: false) {
          nodes { number state repository { nameWithOwner } CLOSING_FIELDS }
        }
      }
      ... on PullRequest {
        comments(last: 100) { nodes { body createdAt authorAssociation author { __typename login } } }
        CLOSING_FIELDS
      }
    }
  }
}
""".replace("CLOSING_FIELDS", CLOSING)


@dataclass(frozen=True, slots=True, order=True)
class ItemRef:
    """An issue or pull request as owner/name#N; compared case-blind on its repo"""

    repo: str
    number: int

    @classmethod
    def parse(cls, text: str) -> ItemRef:
        found = REF.fullmatch(text)
        if found is None:
            raise ReleaseError(f"{text!r} is no owner/name#N reference")
        return cls(found["repo"], int(found["number"]))

    @property
    def key(self) -> tuple[str, int]:
        return self.repo.casefold(), self.number

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}"

    def shown(self, home: ItemRef) -> str:
        """#N in home's repo, else owner/name#N"""
        return f"#{self.number}" if self.repo.casefold() == home.repo.casefold() else str(self)


# each open issue held by an open item: its reference, chains.py's state, and what holds it
Holds = dict[tuple[str, int], tuple[ItemRef, str, tuple[ItemRef, ...]]]


@dataclass(frozen=True, slots=True)
class Step:
    """S-088-13: the step a trusted hand-off quotes, and the day it was posted"""

    text: str
    date: str  # YYYY-MM-DD

    def record(self) -> dict[str, str]:
        return {"text": self.text, "date": self.date}


@dataclass(frozen=True, slots=True)
class Closing:
    """S-088-15: one open pull request and the open issues merging it closes"""

    pull: ItemRef
    issues: tuple[ItemRef, ...]

    def record(self) -> dict[str, object]:
        return {"pull": str(self.pull), "issues": [str(i) for i in self.issues]}


@dataclass(frozen=True, slots=True)
class Waiter:
    """S-088-14: an open issue that waits on the item, its bucket, and the open items it waits on"""

    ref: ItemRef
    bucket: str
    waits_on: tuple[ItemRef, ...]

    def record(self) -> dict[str, object]:
        return {"ref": str(self.ref), "bucket": self.bucket, "waits_on": [str(r) for r in self.waits_on]}


@dataclass(frozen=True, slots=True)
class ItemRead:
    """The item's own GraphQL read: its newest trusted hand-off's step and its closing pull requests"""

    step: Step | None
    closes: tuple[Closing, ...]


@dataclass(frozen=True, slots=True)
class Links:
    """What --item prints after the conditions: step, blocks (or why it can't be read), closes"""

    item: ItemRef
    step: Step | None
    blocks: tuple[Waiter, ...]
    blocks_error: str | None
    closes: tuple[Closing, ...]

    def lines(self) -> list[str]:
        found = []
        if self.step is not None:
            found.append(f"  step:    {self.step.text} (handoff, {self.step.date})")
        if self.blocks_error is not None:
            found.append(f"  blocks:  unread: {self.blocks_error}")
        elif self.blocks:
            found.append(f"  blocks:  {self._blocks()}")
        if self.closes:
            found.append(f"  closes:  {'; '.join(self._closing(c) for c in self.closes)}")
        return found

    def _blocks(self) -> str:
        """Each waiter with its bucket and what it waits on, the item read as this; joined by
        -> when each waits on the one before it alone (a single path), else by commas"""
        entries = []
        for w in self.blocks:
            first = sorted(w.waits_on, key=lambda r: r.key != self.item.key)  # the item first, as this
            held = ", ".join("this" if r.key == self.item.key else r.shown(w.ref) for r in first)
            entries.append(f"{w.ref} ({w.bucket}: waits on {held})")
        path = all(
            len(w.waits_on) == 1 and w.waits_on[0].key == (self.blocks[i - 1].ref if i else self.item).key
            for i, w in enumerate(self.blocks)
        )
        return (" -> " if path else ", ").join(entries)

    def _closing(self, closing: Closing) -> str:
        issues = ", ".join(i.shown(self.item) for i in closing.issues)
        return issues if closing.pull.key == self.item.key else f"{issues} (by {closing.pull.shown(self.item)})"

    def record(self) -> dict[str, object]:
        return {
            "step": None if self.step is None else self.step.record(),
            "blocks": [w.record() for w in self.blocks],
            "blocks_error": self.blocks_error,
            "closes": [c.record() for c in self.closes],
        }


def _login(author: object) -> str:
    """An author's login as --bot-login spells it: a Bot's with [bot], a deleted account's ghost"""
    if not isinstance(author, dict) or not author.get("login"):
        return "ghost"
    name = str(author["login"])
    return f"{name}[bot]" if author.get("__typename") == "Bot" and not name.endswith("[bot]") else name


def _trusted(comment: dict[str, object], bot_login: str | None) -> bool:
    """D-16, as triage_state.py's by_trusted: an OWNER, MEMBER, or COLLABORATOR, or the bot"""
    if str(comment.get("authorAssociation") or "NONE") in TRUSTED:
        return True
    return bot_login is not None and _login(comment.get("author")).casefold() == bot_login.casefold()


def step_of(body: str) -> str | None:
    """S-088-13: the steps a hand-off quotes, its first block of `>` lines with their list marks
    dropped and joined by `; `; without one, its first line after the marker, its mentions
    dropped; whitespace collapsed and cut at STEP_LIMIT. None for a hand-off with no text"""
    lines = body.strip().split("\n")[1:]
    quoted: list[str] = []
    for line in lines:
        if line.lstrip().startswith(">"):
            text = LIST_MARK.sub("", line.lstrip()[1:].strip())
            if text:
                quoted.append(text)
        elif quoted:
            break
    if quoted:
        text = "; ".join(quoted)
    else:
        first = next((line.strip() for line in lines if line.strip()), "")
        text = MENTIONS.sub("", first)
    text = " ".join(text.split())
    if not text:
        return None
    return text if len(text) <= STEP_LIMIT else text[: STEP_LIMIT - 1].rstrip() + "…"


def newest_step(comments: Sequence[dict[str, object]], bot_login: str | None) -> Step | None:
    """S-088-13: the newest trusted hand-off comment's step; a marker by anyone else never counts"""
    for c in reversed(comments):
        body = str(c.get("body") or "")
        if body.lstrip().split("\n", 1)[0].strip() != HANDOFF_MARKER or not _trusted(c, bot_login):
            continue
        text = step_of(body)
        if text is not None:
            return Step(text, str(c["createdAt"])[:10])
    return None


def _ref(node: dict[str, object]) -> ItemRef:
    repo = node["repository"]
    assert isinstance(repo, dict)
    return ItemRef(str(repo["nameWithOwner"]), int(str(node["number"])))


def _open_closing(node: dict[str, object]) -> tuple[ItemRef, ...]:
    refs = node["closingIssuesReferences"]
    assert isinstance(refs, dict)
    nodes = refs["nodes"]
    assert isinstance(nodes, list)
    return tuple(sorted({_ref(n).key: _ref(n) for n in nodes if n["state"] == "OPEN"}.values()))


def parse_item_read(text: str, item: ItemRef, bot_login: str | None) -> ItemRead:
    """The item's GraphQL answer: an issue's open closing pull requests, each with the open
    issues it closes, or a pull request's own; a malformed answer fails the read"""
    raw = json.loads(text)
    if raw.get("errors"):
        raise ReleaseError(f"gh api graphql for {item}: {raw['errors'][0].get('message', raw['errors'][0])}")
    node = raw["data"]["repository"]["issueOrPullRequest"]
    if node is None:
        raise ReleaseError(f"gh api graphql gave no item {item}")
    step = newest_step(node["comments"]["nodes"], bot_login)
    if node["__typename"] == "PullRequest":
        own = _open_closing(node)
        return ItemRead(step, (Closing(item, own),) if own else ())
    pulls = [p for p in node["closedByPullRequestsReferences"]["nodes"] if p["state"] == "OPEN"]
    closes = tuple(Closing(_ref(p), _open_closing(p)) for p in sorted(pulls, key=lambda p: _ref(p)))
    return ItemRead(step, tuple(c for c in closes if c.issues))


def read_item(item: ItemRef, bot_login: str | None, run: StateRunner) -> ItemRead:
    """One GraphQL read of the item: its comments and the pull requests that close it"""
    owner, name = item.repo.split("/")
    cmd = ["gh", "api", "graphql", "-f", f"query={ITEM_QUERY}"]
    cmd += ["-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={item.number}"]
    return parse_item_read(gh_read(cmd, run, f"gh api graphql for {item}"), item, bot_login)


def chains_command(item: ItemRef, bot_login: str | None) -> list[str]:
    """chains.py show's walk from the item, trusting what its repo trusts (D-16)"""
    script = skills_dir() / "github-issue-triage" / "scripts" / "chains.py"
    bot = [] if bot_login is None else ["--bot-login", bot_login]
    return [sys.executable, str(script), "show", str(item), "--json", "--trusted-only", *bot]


def chain_holds(text: str) -> Holds:
    """chains.py show --json's open issues held by an open item: each with its state and holds.
    An UNTRUSTED or UNREADABLE row, whose holds aren't read, waits on nothing here (spec 086)"""
    found: Holds = {}
    for row in json.loads(text)["rows"]:
        if row["state"] in WAITING_STATES:
            ref = ItemRef.parse(row["ref"])
            found[ref.key] = (ref, row["state"], tuple(ItemRef.parse(h) for h in row["holds"]))
    return found


def local_holds(repo: str, notes: Sequence[tuple[int, str, str]]) -> Holds:
    """This repo's BLOCKED issues from triage_state.py's notes (`owner/repo#5:open`), the
    Depends on lines a walk from the item can't find, since GitHub records no reverse of one"""
    found: Holds = {}
    for number, state, note in notes:
        if state != "BLOCKED":
            continue
        holds = tuple(
            ItemRef.parse(w["ref"])
            for w in WAIT.finditer(note)
            if w["state"].lower() not in ("closed", "merged", "not_planned")
        )
        if holds:
            ref = ItemRef(repo, number)
            found[ref.key] = (ref, state, holds)
    return found


def waiters(
    item: ItemRef,
    holds: Holds,
    local_bucket: Callable[[int], str | None],
) -> tuple[Waiter, ...]:
    """S-088-14: every open issue a path of open holds leads from to the item, nearest first,
    then by reference; the item itself never, so a cycle adds nothing of its own. An issue of
    the item's repo reads its bucket from the picture, any other its walk state's line"""
    held_by: dict[tuple[str, int], list[ItemRef]] = {}
    for ref, _, on in holds.values():
        for hold in on:
            held_by.setdefault(hold.key, []).append(ref)
    found: list[Waiter] = []
    seen = {item.key}
    level = [item]
    while level:
        later: dict[tuple[str, int], ItemRef] = {}
        for ref in level:
            for waiter in held_by.get(ref.key, ()):
                if waiter.key not in seen:
                    later.setdefault(waiter.key, waiter)
        nearest = sorted(later.values(), key=lambda r: r.key)
        for ref in nearest:
            seen.add(ref.key)
            _, state, on = holds[ref.key]
            local = ref.repo.casefold() == item.repo.casefold()
            shown = local_bucket(ref.number) if local else None
            found.append(Waiter(ref, shown or CHAIN_BUCKET[state], on))
        level = nearest
    return tuple(found)


def merged(*found: Holds) -> Holds:
    """The holds of each waiter, a walk's and the notes' together, each hold once"""
    out: Holds = {}
    for holds in found:
        for key, (ref, state, on) in holds.items():
            if key in out:
                before = out[key]
                on = tuple({r.key: r for r in (*before[2], *on)}.values())
                ref, state = before[0], before[1]
            out[key] = (ref, state, tuple(sorted(on, key=lambda r: r.key)))
    return out


@dataclass(frozen=True, slots=True)
class Reach:
    """The reads the three lines come from: the item's own, and chains.py show's walk from it
    (None for a pull request, which no walk starts from) or the first line of why it failed"""

    read: ItemRead
    chain: Holds | None
    chain_error: str | None = None


def read_chain(item: ItemRef, bot_login: str | None, run: StateRunner) -> tuple[Holds | None, str | None]:
    """chains.py show's walk from an issue: its holds, or the first line of its failure, which
    --item prints on the blocks line rather than ending on (spec 086's CHAIN_UNREADABLE reads so)"""
    proc = run(chains_command(item, bot_login))
    if proc.returncode in (0, 1) and proc.stdout.strip():
        return chain_holds(proc.stdout), None
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    return None, (lines[-1].strip() if lines else f"chains.py show exited {proc.returncode}")
