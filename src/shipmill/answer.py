"""Spec 107: `shipmill decision answer`, `goal-plan answer`, `project`, and `opportunity accept`
write the maintainer's answer a session heard, in the form the item's reader counts, as
`shipmill gh` writes, and remove `needs-decision` when it is on.

The item picks the reader: an open needs-decision question (triage_state.py and retro.py's relay
grammar, D-93), a plan (`goal-plan`, intake_state.py's plan answer, specs 096 and 098), a
project head (`project`, its stop, spec 106), or an accepted opportunity (`opportunity` and
`planned`, its goal, spec 106). The comment is always the relay header, a blank line, the bare
answer line, and an optional `Note:` line: the one form every reader reads alike. Before any
write, the comment is read back by the reader that will count it, so a drift fails here."""

import datetime as dt
import functools
import importlib.util
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.agent_marker import marked
from shipmill.bundle import skills_dir
from shipmill.decision_label import _asked, _settled_by, _triage
from shipmill.errors import ReleaseError

DECISION_LABEL = "needs-decision"
PLAN_LABEL = "goal-plan"
PROJECT_LABEL = "project"
OPPORTUNITY_LABEL = "opportunity"
ACCEPTED_LABEL = "planned"
MARKER = "Triage:"  # intake_state.py's default --marker, the prefix of a triage comment
AGENT = "Claude Code"
NEW_GOAL = "new"  # `--goal new`: `accept new goal`
_INTAKE = ("product-intake", "scripts", "intake_state.py")
_INTAKE_NAME = "shipmill_intake_state"
# A send-back is an edit: its text may not start as another answer would read (intake_state.py)
_OTHER_ANSWERS = ("accept", "decline", "hold until", "answer by")


class Kind(StrEnum):
    QUESTION = "decision"
    PLAN = "goal-plan"
    PROJECT = "project"
    OPPORTUNITY = "opportunity"


# The labels an item of each kind carries
LABELS: dict[Kind, frozenset[str]] = {
    Kind.PLAN: frozenset({PLAN_LABEL}),
    Kind.PROJECT: frozenset({PROJECT_LABEL}),
    Kind.OPPORTUNITY: frozenset({OPPORTUNITY_LABEL, ACCEPTED_LABEL}),
}
# Each kind's verbs; a number or --own answers a question
VERBS: dict[Kind, tuple[str, ...]] = {
    Kind.PLAN: ("accept", "decline", "hold", "send-back"),
    Kind.PROJECT: ("continue", "hold", "stop"),
    Kind.OPPORTUNITY: ("accept",),
}
# Which flags each answer takes; any other flag given is refused
_FLAGS: dict[tuple[Kind, str], frozenset[str]] = {
    (Kind.PLAN, "accept"): frozenset({"only", "except"}),
    (Kind.PLAN, "decline"): frozenset({"reason"}),
    (Kind.PLAN, "hold"): frozenset({"until"}),
    (Kind.PLAN, "send-back"): frozenset({"reason"}),
    (Kind.PROJECT, "continue"): frozenset(),
    (Kind.PROJECT, "hold"): frozenset(),
    (Kind.PROJECT, "stop"): frozenset({"reason"}),
    (Kind.OPPORTUNITY, "accept"): frozenset({"goal"}),
}


@functools.cache
def _intake() -> ModuleType:
    """The wheel's intake_state.py, loaded once"""
    script = skills_dir().joinpath(*_INTAKE)
    found = importlib.util.spec_from_file_location(_INTAKE_NAME, script)
    if found is None or found.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(found)
    sys.modules[_INTAKE_NAME] = module  # its dataclasses look their module up by name
    found.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class Comment:
    login: str  # as REST spells it, a Bot's with "[bot]"
    association: str
    body: str
    created_at: str  # ISO 8601, as GitHub writes it


@dataclass(frozen=True, slots=True)
class Item:
    number: int
    pull: bool
    open: bool
    labels: frozenset[str]
    body: str
    created_at: str
    comments: tuple[Comment, ...]

    def triage_comments(self, extra: Iterable[Comment] = ()) -> list[tuple[str, str, str]]:
        """The comments as triage_state.py reads them: (login, author association, body)"""
        return [(c.login, c.association, c.body) for c in (*self.comments, *extra)]

    def node(self, extra: Iterable[Comment] = ()) -> dict[str, Any]:
        """The item as intake_state.py reads an issue from GraphQL"""
        return {
            "number": self.number,
            "body": self.body,
            "createdAt": self.created_at,
            "comments": {
                "nodes": [
                    {
                        "author": {"login": c.login},
                        "authorAssociation": c.association,
                        "body": c.body,
                        "createdAt": c.created_at,
                    }
                    for c in (*self.comments, *extra)
                ]
            },
        }


@dataclass(frozen=True, slots=True)
class Request:
    kind: Kind  # the entity the command names: decision, goal-plan, project, or opportunity
    number: int
    answer: str | None  # an option's number or a verb; None with --own
    by: str
    own: str | None = None
    only: str | None = None
    excepted: str | None = None
    until: str | None = None
    reason: str | None = None
    goal: str | None = None
    note: str | None = None
    relayed_by: str = AGENT
    dry_run: bool = False

    def flags(self) -> dict[str, str]:
        """The answer's flags that were given, by name"""
        given = {
            "only": self.only,
            "except": self.excepted,
            "until": self.until,
            "reason": self.reason,
            "goal": self.goal,
            "own": self.own,
        }
        return {name: value for name, value in given.items() if value is not None}


@dataclass(frozen=True, slots=True)
class Composed:
    kind: Kind
    body: str  # the comment, without the agent marker shipmill gh appends
    unlabel: bool  # needs-decision is on and comes off


class Hub(Protocol):
    def viewer(self) -> str:
        """The login shipmill gh writes as: the App's bot, or the host's"""
        ...

    def item(self, number: int) -> Item: ...

    def comment(self, item: Item, body: str) -> str:
        """Post body on the item through shipmill gh; the comment's URL"""
        ...

    def unlabel(self, item: Item) -> None:
        """Remove needs-decision through shipmill gh"""
        ...


def _line(name: str, value: str) -> str:
    """A one-line value of a flag, stripped; refused when empty or on several lines"""
    text = value.strip()
    if not text:
        raise ReleaseError(f"answer's --{name} is empty; give the text on one line")
    if "\n" in text or "\r" in text:
        raise ReleaseError(f"answer's --{name} holds several lines; a reader reads one, so give it on one line")
    return text


def open_question(item: Item, bot_login: str) -> str | None:
    """The body of the item's newest needs-decision question when nothing answers or touches it
    yet, as `shipmill gh`'s label rule reads it (#1312, #1331); None otherwise"""
    comments = item.triage_comments()
    asked = _asked(comments, bot_login)
    if asked is None or _settled_by(comments, bot_login, asked) is not None:
        return None
    return comments[asked][2]


def option_line(question: str, number: str) -> str:
    """`<k>. <the option's name as listed>`, for an option the question lists; refused otherwise"""
    rt = _triage().retro_module()
    listed: dict[int, str] = {}
    for line in question.splitlines():
        found = rt.OPTION.match(line)
        if found is not None:
            text = found.group(2)
            name = text.split(rt.RECOMMENDED, 1)[0] if rt.RECOMMENDED in text else text.split(": ", 1)[0]
            listed[int(found.group(1))] = name.strip()
    if not number.isdigit() or int(number) not in listed:
        options = ", ".join(str(k) for k in sorted(listed)) or "none"
        raise ReleaseError(
            f"the question lists no option {number} (its options: {options}); give one it lists or --own"
        )
    return f"{int(number)}. {listed[int(number)]}"


def _refuse_flags(kind: Kind, verb: str, given: dict[str, str]) -> None:
    allowed = _FLAGS[(kind, verb)]
    extra = sorted(set(given) - allowed)
    if extra:
        flags = ", ".join(f"--{name}" for name in extra)
        raise ReleaseError(f"{verb} on a {kind} takes no {flags}")


def _ids(value: str) -> str:
    """`W-1,W-3` written as the accept writes them, `W-1, W-3`"""
    parts = [part.strip() for part in value.replace(" ", ",").split(",") if part.strip()]
    if not parts:
        raise ReleaseError("answer accept's item list is empty; name the plan's Work ids, as W-1,W-3")
    return ", ".join(parts)


def plan_line(item: Item, verb: str, request: Request) -> str:
    """The plan answer's line (specs 096, 098); refused for one intake_state.py wouldn't count"""
    if not item.open:
        raise ReleaseError(f"plan #{item.number} is closed, so no answer moves it")
    intake = _intake()
    if verb == "accept":
        if request.only is not None and request.excepted is not None:
            raise ReleaseError("goal-plan answer accept takes --only or --except, not both")
        line = "accept"
        if request.only is not None:
            line = f"accept {_ids(request.only)}"
        elif request.excepted is not None:
            line = f"accept except {_ids(request.excepted)}"
        plan, problems = intake.PLANS.parse(item.body, None)
        if plan is None:
            where, rule = problems[0]
            raise ReleaseError(f"plan #{item.number}'s body doesn't read as a plan (line {where}: {rule})")
        read = intake.read_accept(line, tuple(i.id for i in plan.items))
        if isinstance(read, str):
            raise ReleaseError(f"`{line}` is an unclear accept of plan #{item.number}: {read}")
        return line
    if verb == "hold":
        if request.until is None:
            raise ReleaseError("goal-plan answer hold needs --until: a date YYYY-MM-DD, #N, owner/repo#N, or release")
        line = f"hold until {_line('until', request.until)}"
        stub = intake.Answer("hold", dt.datetime.now(dt.UTC), line)
        if intake.read_hold(stub) is None:
            raise ReleaseError(
                f"--until {request.until!r} is not one wake condition; give a date YYYY-MM-DD, #N, owner/repo#N, "
                "or release (spec 098)"
            )
        return line
    if request.reason is None:
        raise ReleaseError(f"goal-plan answer {verb} needs --reason")
    reason = _line("reason", request.reason)
    if verb == "decline":
        return f"decline: {reason}"
    if (
        intake.answer_kind(reason) != "edit"
        or intake.ANSWER_BY.match(reason)
        or reason.casefold().startswith(_OTHER_ANSWERS)
    ):
        raise ReleaseError(
            f"a send-back's --reason may not start with {', '.join(_OTHER_ANSWERS)}: the plan's reader would read "
            "it as that answer, not an edit"
        )
    return reason


def project_line(item: Item, verb: str, request: Request) -> str:
    if not item.open:
        raise ReleaseError(f"project #{item.number} is closed, so no answer moves it")
    if verb != "stop":
        return verb
    if request.reason is None:
        raise ReleaseError("project stop needs --reason, which its stop record gives (spec 106)")
    return f"stop: {_line('reason', request.reason)}"


def opportunity_line(item: Item, request: Request, open_goals: Callable[[], frozenset[str]]) -> str:
    if request.goal is None:
        raise ReleaseError("opportunity accept needs the goal it serves, G-<n>, or `new` for a new goal")
    goal = _line("goal", request.goal)
    if goal.casefold() == NEW_GOAL:
        return "accept new goal"
    goal = goal.upper()
    if goal not in open_goals():
        raise ReleaseError(
            f"{goal} is no open goal of kind goal in the direction (a measure, a goal of no kind, a met or dropped "
            "goal, or an id it lacks), so the opportunity would read NEEDS_GOAL"
        )
    return f"accept {goal}"


def compose(
    item: Item,
    request: Request,
    bot_login: str,
    maintainers: frozenset[str],
    open_goals: Callable[[], frozenset[str]],
) -> Composed:
    """The comment that records the answer, read back by its reader; refused (ReleaseError)
    for an answer the reader wouldn't count"""
    if request.by.lower() not in maintainers:
        names = ", ".join(sorted(maintainers)) or "nobody"
        raise ReleaseError(
            f"--by {request.by} is not the maintainer (`{cli_command()} roles` gives {names}), and no reader "
            "counts a relay naming anyone else (D-68)"
        )
    question = open_question(item, bot_login) if DECISION_LABEL in item.labels else None
    given = request.flags()
    kind = request.kind
    if kind is Kind.QUESTION:
        if question is None:
            raise ReleaseError(
                f"#{item.number} carries no open needs-decision question, so `decision answer` answers nothing"
            )
        if request.own is not None:
            if request.answer is not None:
                raise ReleaseError("decision answer takes an option's number or --own, not both")
            extra = sorted(set(given) - {"own"})
            if extra:
                raise ReleaseError(f"--own takes no {', '.join(f'--{name}' for name in extra)}")
            line = f"own: {_line('own', request.own)}"
        else:
            if given:
                raise ReleaseError(f"an option takes no {', '.join(f'--{name}' for name in sorted(given))}")
            if request.answer is None:
                raise ReleaseError("decision answer needs an option's number or --own")
            line = option_line(question, request.answer)
    else:
        label = LABELS[kind]
        if not label <= item.labels:
            names = " and ".join(f"`{name}`" for name in sorted(label))
            raise ReleaseError(
                f"#{item.number} isn't labelled {names}, so it is no {kind} and its reader doesn't count the answer"
                + (
                    f"; the `{ACCEPTED_LABEL}` label is the maintainer's accept, which no agent adds, so add it by hand"
                    if kind is Kind.OPPORTUNITY and OPPORTUNITY_LABEL in item.labels
                    else ""
                )
            )
        verb = request.answer or ""
        if verb not in VERBS[kind]:
            raise ReleaseError(f"`{verb}` doesn't answer a {kind}; its answers are {', '.join(VERBS[kind])}")
        if "own" in given:
            raise ReleaseError("--own answers a needs-decision question, with `decision answer`")
        _refuse_flags(kind, verb, given)
        if kind is Kind.PLAN:
            line = plan_line(item, verb, request)
        elif kind is Kind.PROJECT:
            line = project_line(item, verb, request)
        else:
            line = opportunity_line(item, request, open_goals)
    body = f"Decision by `@{request.by}`, relayed by {_line('relayed-by', request.relayed_by)}\n\n{line}"
    if request.note is not None:
        body += f"\n\nNote: {_line('note', request.note)}"
    # the label comes off only after an open question, as shipmill gh's label rule allows (#1312)
    composed = Composed(kind, body, question is not None)
    read_back(item, composed, line, request, bot_login, maintainers)
    return composed


def read_back(
    item: Item, composed: Composed, line: str, request: Request, bot_login: str, maintainers: frozenset[str]
) -> None:
    """Refuse a comment its reader wouldn't read as the answer composed (spec 107)"""
    posted = Comment(bot_login, "NONE", marked(composed.body), _after(item))
    if composed.unlabel:
        ts = _triage()
        comments = item.triage_comments([posted])
        asked = _asked(comments, bot_login)
        relay = ts.relayed_after(comments, bot_login, asked) if asked is not None else None
        if relay is None or relay[0] != len(comments) - 1:
            raise ReleaseError(f"#{item.number}'s label rule doesn't read the comment as a relay; nothing was written")
        refused = ts.relay_refused_to(comments, asked, relay[0])
        if refused is not None:
            raise ReleaseError(f"the relay would read `relay not counted: {refused}` (D-93); nothing was written")
    if composed.kind is Kind.QUESTION:
        return
    intake = _intake()
    node = item.node([posted])
    if composed.kind is Kind.PLAN:
        found = intake.plan_answer(node, bot_login, MARKER, maintainers)
        kind = {"send-back": "edit"}.get(request.answer or "", request.answer)
        if found is None or found.kind != kind or intake.PLANS.first_line(found.body) != line:
            raise ReleaseError(f"plan #{item.number}'s reader doesn't read `{line}` as its answer; nothing was written")
        return
    if composed.kind is Kind.PROJECT and line.startswith("stop:"):
        if intake.stop_reason(node, bot_login, MARKER, maintainers) != line.removeprefix("stop:").strip():
            raise ReleaseError(f"project #{item.number}'s reader doesn't read the stop; nothing was written")
        return
    answered = intake.relayed_answer(posted_node(posted), bot_login, MARKER, maintainers)
    if answered is None or intake.PLANS.first_line(answered) != line:
        raise ReleaseError(f"#{item.number}'s reader doesn't read `{line}` as the answer; nothing was written")
    if composed.kind is Kind.OPPORTUNITY:
        expected = intake.NEW_GOAL if line == "accept new goal" else line.removeprefix("accept ")
        if intake.accept_goal(node, MARKER, bot_login, maintainers) != expected:
            raise ReleaseError(f"opportunity #{item.number}'s reader names no goal from `{line}`; nothing was written")


def posted_node(comment: Comment) -> dict[str, Any]:
    return {
        "author": {"login": comment.login},
        "authorAssociation": comment.association,
        "body": comment.body,
        "createdAt": comment.created_at,
    }


def _after(item: Item) -> str:
    """A time after every comment of the item and now, as the posted comment's would read"""
    times = [item.created_at, *(c.created_at for c in item.comments)]
    newest = max(dt.datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times)
    now = max(newest + dt.timedelta(seconds=1), dt.datetime.now(dt.UTC))
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    request: Request,
    hub: Hub,
    maintainers: frozenset[str],
    open_goals: Callable[[], frozenset[str]],
    say: Callable[[str], None],
) -> int:
    """Read the item, compose the answer, post it and take needs-decision off; print the URL"""
    bot_login = hub.viewer()
    item = hub.item(request.number)
    composed = compose(item, request, bot_login, maintainers, open_goals)
    if request.dry_run:
        say(composed.body)
        stays = "stays: no open question" if DECISION_LABEL in item.labels else "not on the item"
        say(f"{DECISION_LABEL}: {'comes off' if composed.unlabel else stays}")
        return 0
    url = hub.comment(item, composed.body)
    if composed.unlabel:
        try:
            hub.unlabel(item)
        except ReleaseError as exc:
            raise ReleaseError(f"the answer is posted at {url}, but {DECISION_LABEL} is still on: {exc}") from None
    say(url)
    return 0
