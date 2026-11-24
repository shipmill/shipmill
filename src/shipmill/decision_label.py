"""#1312: the needs-decision label goes on and comes off only as the protocol says.

`shipmill gh issue edit` and `shipmill gh pr edit` as the App, with --add-label or
--remove-label naming needs-decision (`app_gh.label_edit`), read the item's comments first.
Adding the label is refused, exit 2, unless the item's newest needs-decision question by the App
or an OWNER, MEMBER, or COLLABORATOR is newer than every comment that answers or touches it: a
person's reply, a relay by the App, counted or not, or a withdrawn marker by the App or a trusted
author (#1331), so after a relay that isn't counted the label goes back on only after the re-ask
(D-93). Removing it is refused unless, after the newest such question, there is a person's reply,
a relay `parse_relay` counts (D-93), or a withdrawn marker by the App or a trusted author. The
wheel's `triage_state.py` is the one reading: its `question`, `replies`, `relayed_after`,
`relay_refused_to`, `marked`, and `trusted`, the code the scripts trust; nothing here parses a
question or a relay itself. The relay is read after the question found here, a person's when
one asked after the App, not after the one `relayed` would find (#1340).

#1484: on a pull request the label goes on only under a question naming its current head, and
`shipmill gh` posts no question on a pull request without its head line nor a relay out of the
relay grammar (D-93), each read by pr_gate.py's and retro.py's own readers (`hold_question`).
"""

import functools
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType

from shipmill import cli_command
from shipmill.app_gh import DECISION_LABEL, GhCapture, LabelEdit, posted_comment
from shipmill.bundle import skills_dir
from shipmill.errors import ReleaseError
from shipmill.pr_plan import _gate as _pr_gate

QUESTION_MARKER = "<!-- shipmill:needs-decision -->"  # triage_state.py's DECISION_MARKER
WITHDRAWN_MARKER = "<!-- shipmill:withdrawn -->"  # the first line of a comment taking a question back
_TRIAGE = ("github-issue-triage", "scripts", "triage_state.py")
_NAME = "shipmill_triage_state"
# every page of an item's comments, one JSON line each: (login, author association, body)
_JQ = '.[] | [(.user.login // "ghost"), (.author_association // "NONE"), (.body // "")] | @json'
Comment = tuple[str, str, str]  # (login, author association, body), as triage_state.py reads a comment


@functools.cache
def _triage() -> ModuleType:
    """The wheel's triage_state.py, loaded once"""
    script = skills_dir().joinpath(*_TRIAGE)
    found = importlib.util.spec_from_file_location(_NAME, script)
    if found is None or found.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(found)
    sys.modules[_NAME] = module  # its dataclasses look their module up by name
    found.loader.exec_module(module)
    return module


def read_comments(
    capture: GhCapture, binary: Path, env: Mapping[str, str], repo: str, edit: LabelEdit
) -> list[Comment]:
    """The item's comments, oldest first, as triage_state.py reads them, through gh with env:
    every page of `repos/<repo>/issues/<n>/comments`, which holds a pull request's too. A deleted
    account's login reads ghost. Comments that can't be read exit 2, so the label doesn't move"""
    path = f"repos/{repo}/issues/{edit.number}/comments"

    def refused(why: str) -> ReleaseError:
        return ReleaseError(
            f"{edit.what} {edit.number} with {DECISION_LABEL} is refused: its comments can't be read ({why}), and "
            "shipmill gh reads the needs-decision question before the label moves (#1312); the edit didn't run"
        )

    code, out = capture([str(binary), "api", "--paginate", path, "--jq", _JQ], env)
    if code != 0:
        raise refused(f"gh api {path} exited {code}")
    comments: list[Comment] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise refused("gh's answer isn't JSON") from None
        if not isinstance(row, list) or len(row) != 3 or not all(isinstance(part, str) for part in row):
            raise refused(f"gh printed {line[:80]!r}, not a comment")
        comments.append((row[0], row[1], row[2]))
    return comments


def _asked(comments: list[Comment], bot_login: str) -> int | None:
    """The newest needs-decision question by the App or an OWNER, MEMBER, or COLLABORATOR, by
    triage_state.py's `question`: the App's, unless a person asked after it, then the person's"""
    ts = _triage()
    found: int | None = ts.question(comments, bot_login)
    if found is None:
        found = ts.question(comments, None)
    return found


def _settled_by(comments: list[Comment], bot_login: str, asked: int) -> str | None:
    """What came after the question at asked that answers or touches it, or None: a person's
    reply, a relay by the App, counted or not, or a withdrawn marker by the App or a trusted author"""
    ts = _triage()
    after = comments[asked + 1 :]
    if any(ts.replies(comment, bot_login) for comment in after):
        return "a person's reply"
    if ts.relayed_after(comments, bot_login, asked) is not None:
        return "a relay"
    if any(
        ts.marked(body, WITHDRAWN_MARKER) and ts.trusted(author, association, bot_login)
        for author, association, body in after
    ):
        return "a withdrawn marker"
    return None


def adding_refusal(comments: list[Comment], bot_login: str, edit: LabelEdit, repo: str) -> str | None:
    """Why adding the label is refused, or None: the newest question waits, with nothing after it
    that answers or touches it (#1331). An item with no question, or whose newest question a
    person's reply, a relay (counted or not, D-93), or a withdrawn marker follows, is refused"""
    group = edit.what.split()[1]
    head = f"{edit.what} {edit.number} --add-label {DECISION_LABEL} is refused"
    item = f"{repo}#{edit.number}"
    ask = (
        f"a comment whose first line is `{QUESTION_MARKER}` (`{cli_command()} gh {group} comment {edit.number} "
        "--body-file <file>`, as github-issue-triage's needs-decision.md says), then add the label"
    )
    asked = _asked(comments, bot_login)
    if asked is None:
        return (
            f"{head}: {item} carries no needs-decision question by the App or an OWNER, MEMBER, or COLLABORATOR, so "
            f"the label would park it with nothing to answer (D-21). Post the question first, {ask}"
        )
    found = _settled_by(comments, bot_login, asked)
    if found is None:
        return None
    return (
        f"{head}: after {item}'s newest needs-decision question, {found} came, so the label would park it on a "
        "question already answered or taken back (D-21). Post a new question first, after a relay that isn't "
        "counted with its `<!-- shipmill:relay-refused <reason> -->` and `Relay not counted` lines under the zone "
        f"line (needs-decision.md, The relay grammar, D-93), {ask}"
    )


def removing_refusal(comments: list[Comment], bot_login: str, edit: LabelEdit, repo: str) -> str | None:
    """Why removing the label is refused, or None: after the newest question there is a
    person's reply, a relay that counts (D-93), or a withdrawn marker by the App or a trusted
    author. With no question at all a person parked the item, and only a person unparks it"""
    ts = _triage()
    item = f"{repo}#{edit.number}"
    head = f"{edit.what} {edit.number} --remove-label {DECISION_LABEL} is refused"
    asked = _asked(comments, bot_login)
    if asked is None:
        return (
            f"{head}: {item} carries no needs-decision question by the App or an OWNER, MEMBER, or COLLABORATOR, so a "
            "person labelled it by hand to park it, and only that person takes the label off, by hand "
            "(github-issue-triage's needs-decision.md, While it waits)"
        )
    after = comments[asked + 1 :]
    if any(ts.replies(comment, bot_login) for comment in after):
        return None
    if any(
        ts.marked(body, WITHDRAWN_MARKER) and ts.trusted(author, association, bot_login)
        for author, association, body in after
    ):
        return None
    relay: tuple[int, str] | None = ts.relayed_after(comments, bot_login, asked)
    reason: str | None = None
    if relay is not None:
        reason = ts.relay_refused_to(comments, asked, relay[0])
        if reason is None:
            return None
    found = "nothing answers it"
    if reason is not None:
        found = f"its relay isn't counted ({ts.RELAY_NOT_COUNTED.format(reason=reason)}, D-93)"
    return (
        f"{head}: after {item}'s newest needs-decision question, {found}. The label comes off after one of: a reply "
        "by an OWNER, MEMBER, or COLLABORATOR without the agent marker; a relay of an answer given in the session, "
        "``Decision by `@<login>`, relayed by <agent>`` with its answer line in the relay grammar (needs-decision.md, "
        f"The relay grammar); or, to take the question back, a comment whose first line is `{WITHDRAWN_MARKER}`, "
        "by the App, saying why"
    )


def hold_label(
    edit: LabelEdit,
    default: str | None,
    binary: Path,
    env: Mapping[str, str],
    capture: GhCapture,
    bot_login: Callable[[], str],
) -> None:
    """#1312: exit 2, before gh runs, when the edit adds the label to an item with no question
    or whose newest question something already answers or touches (#1331), or to a pull request
    whose waiting question doesn't name its current head in full (#1484, read once the question
    passes), or removes it with nothing after the newest question that settles it. The
    comments are read with env, the App's, and bot_login gives the App's bot login, which tells
    its questions and relays.
    Fails closed: a login or comments that can't be read refuse the edit"""
    repo = edit.target(default)
    try:
        login = bot_login()
    except ReleaseError as exc:
        raise ReleaseError(
            f"{edit.what} {edit.number} with {DECISION_LABEL} is refused: the App's bot login, which tells its "
            f"questions and relays, can't be read: {exc}"
        ) from None
    comments = read_comments(capture, binary, env, repo, edit)
    adding = adding_refusal(comments, login, edit, repo) if edit.adds else None
    asked = _asked(comments, login) if edit.adds and adding is None else None
    if asked is not None:  # #1484: the question waits; on a pull request it names the current head
        head = read_head(capture, binary, env, repo, edit)
        adding = None if head is None else head_refusal(comments[asked][2], head, edit, repo)
    refusals = [
        refusal
        for refusal in (adding, removing_refusal(comments, login, edit, repo) if edit.removes else None)
        if refusal is not None
    ]
    if refusals:
        raise ReleaseError("\n".join(refusals))


# -- #1484: a question on a pull request names its head, and a relay keeps to its grammar ---------

_HEAD_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
    "issueOrPullRequest(number: $number) { __typename ... on PullRequest { headRefOid } } } }"
)
_HEAD_JQ = '.data.repository.issueOrPullRequest | [.__typename, (.headRefOid // "")] | @json'
# the line a pull request's question names its head on, as pr_gate.py's ASKED_AT reads it
HEAD_LINE = "<!-- shipmill:head <sha> -->"


def read_head(capture: GhCapture, binary: Path, env: Mapping[str, str], repo: str, edit: LabelEdit) -> str | None:
    """#1484: the item's current head in full when it is a pull request, None when it is an
    issue, read through gh with env in one GraphQL query; `gh issue edit` labels a pull request
    too, so the type is read, not taken from the command. Fails closed: a type or head that
    can't be read refuses the edit"""
    owner, name = repo.split("/")

    def refused(why: str) -> ReleaseError:
        return ReleaseError(
            f"{edit.what} {edit.number} --add-label {DECISION_LABEL} is refused: whether {repo}#{edit.number} is a "
            f"pull request, and its head, can't be read ({why}), and shipmill gh checks that a pull request's "
            "question names its head before the label goes on (#1484); the edit didn't run"
        )

    query = ["-f", f"query={_HEAD_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={edit.number}"]
    code, out = capture([str(binary), "api", "graphql", *query, "--jq", _HEAD_JQ], env)
    if code != 0:
        raise refused(f"gh api graphql exited {code}")
    try:
        row = json.loads(out)
    except json.JSONDecodeError:
        raise refused("gh's answer isn't JSON") from None
    if row == ["Issue", ""]:
        return None
    if (
        isinstance(row, list)
        and len(row) == 2
        and row[0] == "PullRequest"
        and isinstance(row[1], str)
        and _pr_gate().FULL_SHA.fullmatch(row[1]) is not None
    ):
        return row[1]
    raise refused(f"gh printed {out.strip()[:80]!r}, not an issue or a pull request's head")


def head_refusal(question: str, head: str, edit: LabelEdit, repo: str) -> str | None:
    """#1484: why adding the label to a pull request is refused, or None: its newest question,
    question, names head in full on its `shipmill:head` line, read by pr_gate.py's asked_at,
    or pr_gate.py discards the answer (S-055-5)"""
    named: str | None = _pr_gate().asked_at(question)
    if named == head:
        return None
    found = "names no head" if named is None else f"names {named}, not its head"
    return (
        f"{edit.what} {edit.number} --add-label {DECISION_LABEL} is refused: {repo}#{edit.number} is a pull request, "
        f"and its newest needs-decision question {found}, so pr_gate.py would discard the answer (S-055-5). Post "
        f"the question again with `<!-- shipmill:head {head} -->` under its `CI on` line (needs-decision.md, "
        "Asking), then add the label"
    )


def hold_question(args: Sequence[str]) -> None:
    """#1484: exit 2, before any token or gh, for a comment gh's args post (once `marked_args`
    made them) that the gate would discard: a needs-decision question on a pull request (`gh pr
    comment`, `gh pr close|reopen --comment`) with no `shipmill:head` line pr_gate.py's asked_at
    reads, or a relay whose first line is a `Decision by` header that retro.py's parse_relay,
    the reading pr_gate.py and the retro share, refuses (D-93). Read from the args alone; a
    question on an issue, which names no head, and every other call pass"""
    comment = posted_comment(args)
    if comment is None:
        return
    ts = _triage()
    if comment.what.startswith("gh pr ") and ts.marked(comment.body) and _pr_gate().asked_at(comment.body) is None:
        raise ReleaseError(
            f"{comment.what} is refused: it asks a needs-decision question on a pull request with no `{HEAD_LINE}` "
            "line, so pr_gate.py would discard its answer (S-055-5); put the head in full on that line under the "
            "question's `CI on` line (needs-decision.md, Asking), as `gh pr view <n> --json headRefOid -q "
            ".headRefOid` prints it"
        )
    rt = ts.retro_module()
    if rt.DECISION_BY.match(ts.first_line(comment.body)) is None:
        return
    reason: str | None = rt.parse_relay(comment.body).refused
    if reason is None:
        return
    raise ReleaseError(
        f"{comment.what} is refused: its relay is out of the relay grammar, so pr_gate.py and triage would read it "
        f"{ts.RELAY_NOT_COUNTED.format(reason=reason)} (D-93). Past the `Decision by` line write the answer line "
        "(an option as listed, or `own: <text>`), an optional `Basis: item|round|standing` line, then nothing or a "
        "line starting `Note:` (needs-decision.md, The relay grammar)"
    )
