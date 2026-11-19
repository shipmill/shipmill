"""#1313: a parent doesn't close over a person's step still open under it.

`shipmill gh issue close <n>` as the App reads the issue's open sub-issues first, every page of
`repos/<repo>/issues/<n>/sub_issues`, and refuses with exit 2, gh never running, while one of
them is a person's item (labelled `role:<name>` or `human`, as triage_state.py's item_roles
reads one, spec 017, spec 036), naming each. The session closes each such sub-issue, or relinks
it under an open issue, then closes the parent; one close per call, so nothing else is read.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path

from shipmill import cli_command
from shipmill.app_gh import GhCapture, IssueClose, issue_close
from shipmill.errors import ReleaseError

__all__ = ["hold_close", "issue_close"]

HUMAN_LABEL = "human"  # triage_state.py's HUMAN_LABEL: counts as role:maintainer
ROLE_PREFIX = "role:"  # triage_state.py's ROLE_PREFIX
# every page of the open sub-issues, one JSON line each: (its URL, its label names)
_JQ = '.[] | select(.state == "open") | [.html_url, [.labels[].name]] | @json'
_ISSUE_URL = re.compile(r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/issues/([1-9][0-9]*)")


def person_labels(labels: list[str]) -> list[str]:
    """The labels that make an issue a person's item, in label order, compared
    case-insensitively as triage_state.py's item_roles reads them; empty for any other issue"""
    return [name for name in labels if name.lower() == HUMAN_LABEL or name.lower().startswith(ROLE_PREFIX)]


def open_person_items(
    capture: GhCapture, binary: Path, env: Mapping[str, str], repo: str, close: IssueClose
) -> list[tuple[str, list[str]]]:
    """Each open sub-issue of the issue that is a person's item, as (owner/repo#N, its person
    labels), read through gh with env. Sub-issues that can't be read exit 2, so the issue
    doesn't close"""
    path = f"repos/{repo}/issues/{close.number}/sub_issues"

    def refused(why: str) -> ReleaseError:
        return ReleaseError(
            f"gh issue close {close.number} is refused: its sub-issues can't be read ({why}), and shipmill gh closes "
            "no parent over a person's step still open under it (#1313); the close didn't run"
        )

    code, out = capture([str(binary), "api", "--paginate", path, "--jq", _JQ], env)
    if code != 0:
        raise refused(f"gh api {path} exited {code}")
    found: list[tuple[str, list[str]]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise refused("gh's answer isn't JSON") from None
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not isinstance(row[1], list)
            or not all(isinstance(name, str) for name in row[1])
        ):
            raise refused(f"gh printed {line[:80]!r}, not a sub-issue")
        url = _ISSUE_URL.fullmatch(row[0])
        if url is None:
            raise refused(f"a sub-issue's URL is {row[0][:80]!r}")
        labels = person_labels(row[1])
        if labels:
            found.append((f"{url.group(1)}#{url.group(2)}", labels))
    return found


def hold_close(
    close: IssueClose, default: str | None, binary: Path, env: Mapping[str, str], capture: GhCapture
) -> None:
    """#1313: exit 2, before gh runs, when the issue close names has an open sub-issue that is a
    person's item, naming each and what to do; default is the repo gh works on when the args
    name none, and the sub-issues are read with env, the App's"""
    repo = close.target(default)
    found = open_person_items(capture, binary, env, repo, close)
    if not found:
        return
    listed = ", ".join(f"{item} ({' '.join(labels)})" for item, labels in found)
    first = found[0][0]
    raise ReleaseError(
        f"gh issue close {close.number} is refused: {repo}#{close.number} has an open sub-issue that is a person's "
        f"item, so closing it would leave that step handed off under a closed parent (#1313): {listed}. Close each "
        f"first once its step is done or no longer needed (`{cli_command()} gh issue close {first.partition('#')[2]} "
        f"-R {first.partition('#')[0]}`), or relink it under an open issue, then close #{close.number}"
    )
