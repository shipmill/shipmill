"""#1312: the needs-decision label goes on and comes off only as the protocol says.

`shipmill gh issue edit` and `shipmill gh pr edit` as the App, with --add-label or
--remove-label naming needs-decision (`app_gh.label_edit`), read the item's comments first.
Adding the label is refused, exit 2, unless the item carries a needs-decision question by the App
or an OWNER, MEMBER, or COLLABORATOR; removing it is refused unless, after the newest such
question, there is a person's reply, a relay `parse_relay` counts (D-93), or a withdrawn marker
by the App or a trusted author. The wheel's `triage_state.py` is the one reading: its `question`,
`replies`, `relayed`, `relay_refused`, `marked`, and `trusted`, the code the scripts trust;
nothing here parses a question or a relay itself.
"""

import functools
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType

from shipmill import cli_command
from shipmill.app_gh import DECISION_LABEL, GhCapture, LabelEdit
from shipmill.bundle import skills_dir
from shipmill.errors import ReleaseError

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


def adding_refusal(comments: list[Comment], bot_login: str, edit: LabelEdit, repo: str) -> str | None:
    """Why adding the label is refused, or None: the item carries no question"""
    if _asked(comments, bot_login) is not None:
        return None
    group = edit.what.split()[1]
    return (
        f"{edit.what} {edit.number} --add-label {DECISION_LABEL} is refused: {repo}#{edit.number} carries no "
        "needs-decision question by the App or an OWNER, MEMBER, or COLLABORATOR, so the label would park it with "
        f"nothing to answer (D-21). Post the question first, a comment whose first line is `{QUESTION_MARKER}` "
        f"(`{cli_command()} gh {group} comment {edit.number} --body-file <file>`, as github-issue-triage's "
        "needs-decision.md says), then add the label"
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
    relay: tuple[int, str] | None = ts.relayed(comments, bot_login)
    reason: str | None = None
    if relay is not None and relay[0] > asked:
        reason = ts.relay_refused(comments, bot_login, relay[0])
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
    """#1312: exit 2, before gh runs, when the edit adds the label to an item with no question,
    or removes it with nothing after the newest question that settles it. The comments are read
    with env, the App's, and bot_login gives the App's bot login, which tells its questions and
    relays. Fails closed: a login or comments that can't be read refuse the edit"""
    repo = edit.target(default)
    try:
        login = bot_login()
    except ReleaseError as exc:
        raise ReleaseError(
            f"{edit.what} {edit.number} with {DECISION_LABEL} is refused: the App's bot login, which tells its "
            f"questions and relays, can't be read: {exc}"
        ) from None
    comments = read_comments(capture, binary, env, repo, edit)
    refusals = [
        refusal
        for refusal in (
            adding_refusal(comments, login, edit, repo) if edit.adds else None,
            removing_refusal(comments, login, edit, repo) if edit.removes else None,
        )
        if refusal is not None
    ]
    if refusals:
        raise ReleaseError("\n".join(refusals))
