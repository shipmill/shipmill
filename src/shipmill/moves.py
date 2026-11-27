"""Spec 108: the lifecycle moves a person makes that answer no item, one command each, entity
then verb: a project head's add, focus, unfocus, and resume, and hold's `held` label beside spec
107's comment.

Each is the maintainer's: the App's relay naming them comes first, in spec 107's form, then the
label, both through `shipmill gh`'s path. The head is read as `intake_state.py --projects` reads
it, so a move its reader wouldn't count, or that would read otherwise than meant, is refused
before any write."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from shipmill import answer, cli_command
from shipmill.agent_marker import marked
from shipmill.errors import ReleaseError

PROJECT_LABEL = answer.PROJECT_LABEL
FOCUS_LABEL = "focus"
HELD_LABEL = "held"
CHECK_TITLE = "Check: "  # a check issue's title (spec 042, 106)
STOP_DUE = "PROJECT_STOP_DUE"


class Verb(StrEnum):
    ADD = "add"
    FOCUS = "focus"
    UNFOCUS = "unfocus"
    HOLD = "hold"
    RESUME = "resume"


# The relay's line for each move (spec 108's table), and its label step: (add, remove)
LINES: dict[Verb, str] = {
    Verb.ADD: "project",
    Verb.FOCUS: "focus",
    Verb.UNFOCUS: "unfocus",
    Verb.HOLD: "hold",
    Verb.RESUME: "resume",
}
LABELS: dict[Verb, tuple[str | None, str | None]] = {
    Verb.ADD: (PROJECT_LABEL, None),
    Verb.FOCUS: (FOCUS_LABEL, None),
    Verb.UNFOCUS: (None, FOCUS_LABEL),
    Verb.HOLD: (HELD_LABEL, None),
    Verb.RESUME: (None, HELD_LABEL),
}


class StepFailed(Exception):
    """A step after the first write failed: the CLI exits with gh's code, saying which step and
    the URL of what it wrote (S-108-12)"""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Head:
    """One head as `intake_state.py --projects --json` reads it"""

    number: int
    state: str
    check: int | None


@dataclass(frozen=True, slots=True)
class Projects:
    """The checkout's heads, and the product's slots under `[agents] projects` (None without it)"""

    heads: dict[int, Head]
    limit: int | None = None
    active: int = 0
    room: int | None = None


def read_projects(out: str) -> Projects:
    """`intake_state.py --projects --json`'s lines: the first line's `projects` slots, and a
    `kind: project` row per head; refused when a line isn't JSON or a row lacks its fields"""
    heads: dict[int, Head] = {}
    slots: dict[str, int] | None = None
    for text in out.splitlines():
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            raise ReleaseError(f"intake_state.py --projects printed a line that isn't JSON: {text[:200]!r}") from None
        if not isinstance(line, dict):
            raise ReleaseError(f"intake_state.py --projects printed a line that isn't an object: {text[:200]!r}")
        if "projects" in line and slots is None:
            slots = line["projects"]
        if line.get("kind") != "project":
            continue
        try:
            number, state, check = int(line["number"]), str(line["state"]), line["check"]
        except KeyError, TypeError, ValueError:
            raise ReleaseError(
                f"intake_state.py --projects printed a head without its fields: {text[:200]!r}"
            ) from None
        heads[number] = Head(number, state, None if check is None else int(check))
    if slots is None:
        return Projects(heads)
    try:
        return Projects(heads, int(slots["limit"]), int(slots["active"]), int(slots["room"]))
    except KeyError, TypeError, ValueError:
        raise ReleaseError(f"intake_state.py --projects printed slots without limit, active, room: {slots}") from None


@dataclass(frozen=True, slots=True)
class Request:
    verb: Verb
    number: int
    by: str
    note: str | None = None
    relayed_by: str = answer.AGENT
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    """What a move writes: the relay's body (without the agent marker), whether needs-decision
    comes off (hold answering an idle question, spec 107), and the label it moves"""

    body: str
    unlabel: bool
    add: str | None
    remove: str | None


class Hub(answer.Hub, Protocol):
    def label(self, item: answer.Item, add: str | None, remove: str | None) -> None:
        """Add or remove one label through shipmill gh; StepFailed with gh's code when it fails"""
        ...

    def projects(self, bot_login: str) -> Projects:
        """The heads as `intake_state.py --projects --json` reads them"""
        ...


def _maintainer(by: str, maintainers: frozenset[str]) -> None:
    if by.lower() not in maintainers:
        names = ", ".join(sorted(maintainers)) or "nobody"
        raise ReleaseError(
            f"--by {by} is not the maintainer (`{cli_command()} roles` gives {names}), and no reader counts a relay "
            "naming anyone else (D-68)"
        )


def _relay(request: Request, line: str) -> str:
    body = f"Decision by `@{request.by}`, relayed by {answer._line('relayed-by', request.relayed_by)}\n\n{line}"
    if request.note is not None:
        body += f"\n\nNote: {answer._line('note', request.note)}"
    return body


def _read_back(item: answer.Item, body: str, line: str, bot_login: str, maintainers: frozenset[str]) -> None:
    """Refuse a relay the head's reader wouldn't read as the move's line"""
    posted = answer.Comment(bot_login, "NONE", marked(body), answer._after(item))
    intake = answer._intake()
    read = intake.relayed_answer(answer.posted_node(posted), bot_login, answer.MARKER, maintainers)
    if read is None or intake.PLANS.first_line(read) != line:
        raise ReleaseError(f"#{item.number}'s reader doesn't read `{line}` as the move; nothing was written")


def compose(
    item: answer.Item,
    request: Request,
    bot_login: str,
    maintainers: frozenset[str],
    projects: Callable[[], Projects],
    is_open: Callable[[int], bool],
) -> Step:
    """The move's writes, refused (ReleaseError) for one its reader wouldn't count; is_open
    reads whether an issue is open (the head's check issue, which intake names closed too)"""
    verb = request.verb
    _maintainer(request.by, maintainers)
    where = f"project {verb}"
    if item.pull:
        raise ReleaseError(f"#{item.number} is a pull request; {where} moves an issue")
    if not item.open:
        raise ReleaseError(f"#{item.number} is closed, so {where} moves nothing")
    # hold is spec 107's answer too, so it answers a head's idle question; the others refuse one
    if verb is not Verb.HOLD and answer.DECISION_LABEL in item.labels and answer.open_question(item, bot_login):
        raise ReleaseError(
            f"#{item.number} has an open needs-decision question, which a relay here would answer: answer it with "
            f"`{cli_command()} decision answer {item.number}` first"
        )
    if verb is Verb.ADD:
        if answer.PLAN_LABEL in item.labels:
            raise ReleaseError(f"#{item.number} is a goal's plan (`{answer.PLAN_LABEL}`), which is no project head")
        if item.title.startswith(CHECK_TITLE):
            raise ReleaseError(f"#{item.number} is a check issue (its title starts `{CHECK_TITLE}`), not a head")
        if PROJECT_LABEL in item.labels:
            raise ReleaseError(f"#{item.number} is labelled `{PROJECT_LABEL}` already")
    else:
        found = projects()
        head = found.heads.get(item.number)
        if head is None:
            raise ReleaseError(f"#{item.number} is no project head as `intake_state.py --projects` reads one")
        if head.state == STOP_DUE:
            raise ReleaseError(f"project #{item.number} has a stop pending, which a newer relay would lift")
        _labels(item, verb)
        if verb is Verb.RESUME:
            if head.check is None or not is_open(head.check):
                raise ReleaseError(
                    f"project #{item.number} has no open check issue, so it would not read active: file it with "
                    f"`{cli_command()} project check {item.number}` first"
                )
            if found.room == 0:
                raise ReleaseError(
                    f"no slot is free under [agents] projects ({found.active} of {found.limit} active), so "
                    f"#{item.number} starts in its turn"
                )
    add, remove = LABELS[verb]
    if verb is Verb.HOLD:  # spec 107's comment, which takes needs-decision off an idle question it answers
        held = answer.Request(
            answer.Kind.PROJECT,
            request.number,
            verb.value,
            request.by,
            note=request.note,
            relayed_by=request.relayed_by,
        )
        composed = answer.compose(item, held, bot_login, maintainers, lambda: frozenset())
        return Step(composed.body, composed.unlabel, add, remove)
    line = LINES[verb]
    body = _relay(request, line)
    _read_back(item, body, line, bot_login, maintainers)
    return Step(body, False, add, remove)


def _labels(item: answer.Item, verb: Verb) -> None:
    if verb is Verb.FOCUS and FOCUS_LABEL in item.labels:
        raise ReleaseError(f"project #{item.number} is in focus already")
    if verb is Verb.UNFOCUS and FOCUS_LABEL not in item.labels:
        raise ReleaseError(f"project #{item.number} isn't labelled `{FOCUS_LABEL}`, so it has no focus to take off")
    if verb is Verb.HOLD and HELD_LABEL in item.labels:
        raise ReleaseError(f"project #{item.number} is labelled `{HELD_LABEL}` already")
    if verb is Verb.RESUME and HELD_LABEL not in item.labels:
        raise ReleaseError(f"project #{item.number} isn't labelled `{HELD_LABEL}`, so there is no hold to lift")


def _label_step(add: str | None, remove: str | None) -> str:
    return f"label: add `{add}`" if add is not None else f"label: remove `{remove}`"


def run(request: Request, hub: Hub, maintainers: frozenset[str], say: Callable[[str], None]) -> int:
    """Read the item, compose the move, post the relay, then move its label; print the URL"""
    bot_login = hub.viewer()
    item = hub.item(request.number)
    step = compose(
        item, request, bot_login, maintainers, lambda: hub.projects(bot_login), lambda number: hub.item(number).open
    )
    if request.dry_run:
        say(step.body)
        if step.unlabel:
            say(f"{answer.DECISION_LABEL}: comes off")
        say(_label_step(step.add, step.remove))
        return 0
    url = hub.comment(item, step.body)
    try:
        if step.unlabel:
            hub.unlabel(item)
        hub.label(item, step.add, step.remove)
    except StepFailed as exc:
        message = f"the relay is posted at {url}, but {_label_step(step.add, step.remove)} failed: {exc}"
        raise StepFailed(message, exc.code) from None
    except ReleaseError as exc:
        raise StepFailed(f"the relay is posted at {url}, but the next step failed: {exc}", 2) from None
    say(url)
    return 0


# -- `project check` (S-108-5, S-108-6): the session's own step of a start, no relay


@dataclass(frozen=True, slots=True)
class CheckRequest:
    number: int
    title: str
    check: str  # the text of --check-file
    cleanup: str | None = None  # the text of --cleanup-file
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class CheckIssue:
    title: str
    body: str


class CheckHub(answer.Hub, Protocol):
    def projects(self, bot_login: str) -> Projects: ...

    def create(self, title: str, body: str) -> str:
        """Open an issue through shipmill gh; its URL"""
        ...

    def link_child(self, head: int, child: int) -> None:
        """Link child as head's sub-issue, as `shipmill link #head --child #child` does;
        StepFailed with its code when it fails"""
        ...


def _text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ReleaseError(f"project check's {name} is empty; a check issue needs its {name}")
    return text


def compose_check(
    item: answer.Item,
    request: CheckRequest,
    bot_login: str,
    projects: Callable[[], Projects],
    is_open: Callable[[int], bool],
) -> CheckIssue:
    """The check issue to file, refused (ReleaseError) for one the head's reader wouldn't count"""
    title = _text("--title", request.title)
    if "\n" in title or "\r" in title:
        raise ReleaseError("project check's --title holds several lines; a title is one line")
    check = _text("--check-file", request.check)
    if item.pull or not item.open:
        raise ReleaseError(
            f"#{item.number} is {'a pull request' if item.pull else 'closed'}, so it gets no check issue"
        )
    head = projects().heads.get(item.number)
    if head is None:
        raise ReleaseError(f"#{item.number} is no project head as `intake_state.py --projects` reads one")
    if head.state == STOP_DUE:
        raise ReleaseError(f"project #{item.number} has a stop pending, so it gets no check issue")
    if head.check is not None and is_open(head.check):
        raise ReleaseError(f"project #{item.number} has an open check issue already, #{head.check}")
    body = f"## Check\n\n{check}\n"
    if request.cleanup is not None:
        body += f"\n## Cleanup\n\n{_text('--cleanup-file', request.cleanup)}\n"
    found = CheckIssue(f"{CHECK_TITLE}{title}", body)
    sub = {"title": found.title, "body": found.body}
    if not answer._intake().is_check(sub):
        raise ReleaseError(f"intake_state.py doesn't read `{found.title}` as a check issue; nothing was written")
    return found


def run_check(request: CheckRequest, hub: CheckHub, say: Callable[[str], None]) -> int:
    """Read the head, file its check issue, then link it as the head's sub-issue; print its URL"""
    bot_login = hub.viewer()
    item = hub.item(request.number)
    found = compose_check(
        item, request, bot_login, lambda: hub.projects(bot_login), lambda number: hub.item(number).open
    )
    if request.dry_run:
        say(f"issue: {found.title}")
        say(found.body.rstrip("\n"))
        say(f"link: #{request.number} --child the new issue")
        return 0
    url = hub.create(found.title, found.body)
    number = url.rstrip("/").rsplit("/", 1)[-1]
    if not number.isdigit():
        raise StepFailed(f"gh issue create printed {url!r}, no issue URL, so the check issue can't be linked", 1)
    try:
        hub.link_child(request.number, int(number))
    except StepFailed as exc:
        raise StepFailed(
            f"the check issue is open at {url}, but linking it to #{request.number} failed: {exc}", exc.code
        ) from None
    say(url)
    return 0
