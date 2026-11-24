"""#1313: an open person's item (labelled role:<name> or human) whose sub-issue parent closed
reads STALE_HANDOFF, an action, until a trusted still-waits comment after the close; the watch
lists it in an ISSUES row of its own; and `shipmill gh issue close`, as the App, refuses to close
an issue with an open person's sub-issue. No test reaches the network"""

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.app_gh import IssueClose, issue_close
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.walk import TIERS

from .conftest import guarded_home
from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_needs_decision import load
from .test_triage_human import BOT, by, classify, handoff, person, said

SKILLS = Path(__file__).resolve().parents[1] / "skills"
STILL_WAITS = "<!-- shipmill:still-waits -->"
AGENT = "\n\n<!-- shipmill:agent -->"
CLOSED_AT = "2026-11-17T09:00:00Z"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_stale", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_stale", SKILLS / "github-ship-watch" / "scripts" / "watch_state.py")


def under(
    item: dict[str, Any], state: str = "CLOSED", closed: str | None = CLOSED_AT, repo: str = "o/r"
) -> dict[str, Any]:
    """item as a sub-issue of o/r#5 (or repo's), in state, closed at closed"""
    item["parent"] = {
        "number": 5,
        "state": state,
        "closedAt": closed if state == "CLOSED" else None,
        "repository": {"nameWithOwner": repo},
        "milestone": None,
    }
    return item


def still_waits(at: str, **who: Any) -> dict[str, Any]:
    return said(f"{STILL_WAITS}\nThe DNS change still needs `@ana`'s hand.", at, **who)


# -- triage_state.py ---------------------------------------------------------------------------


@pytest.mark.parametrize("labels", [("role:maintainer",), ("human",), ("Role:Infra", "bug")])
def test_1313_a_persons_item_under_a_closed_parent_reads_stale_handoff(ts: ModuleType, labels: tuple[str, ...]) -> None:
    item = under(person([handoff("2026-11-15T10:00:00Z")], labels=labels))
    assert classify(ts, item) == ("STALE_HANDOFF", "parent o/r#5 closed")
    assert "STALE_HANDOFF" in ts.ACTION


def test_1313_it_names_a_parent_in_another_repo(ts: ModuleType) -> None:
    assert classify(ts, under(person(), repo="acme/home")) == ("STALE_HANDOFF", "parent acme/home#5 closed")


def test_1313_it_comes_before_with_person_handoff_and_the_holds(ts: ModuleType) -> None:
    """Read after gated's states and before OFF_MILESTONE, NO_ASSIGNEE, BLOCKED, and WITH_PERSON"""
    assert classify(ts, under(person(people=())))[0] == "STALE_HANDOFF"  # would read NO_ASSIGNEE
    blocked = under(person(body="Depends on #3\n"))
    assert classify(ts, blocked, {("o", "r", 3): "OPEN"})[0] == "STALE_HANDOFF"  # would read BLOCKED
    item = under(person([handoff("2026-11-15T10:00:00Z")]))
    item["parent"]["milestone"] = {"title": "v2"}
    assert classify(ts, item)[0] == "STALE_HANDOFF"  # would read OFF_MILESTONE


@pytest.mark.parametrize(
    "item",
    [
        under(person([handoff("2026-11-15T10:00:00Z")]), state="OPEN"),  # the parent is open
        person([handoff("2026-11-15T10:00:00Z")]),  # no parent, or the forge reads none
    ],
    ids=["open-parent", "no-parent"],
)
def test_1313_an_open_or_absent_parent_reads_as_before(ts: ModuleType, item: dict[str, Any]) -> None:
    assert classify(ts, item) == ("WITH_PERSON", "with @ana since 2026-11-15T10:00:00Z")


def test_1313_an_agents_item_under_a_closed_parent_reads_as_before(ts: ModuleType) -> None:
    item = under(person(labels=("bug",)))
    item["comments"]["nodes"] = [said("Triage: implement", "2026-11-01T10:00:00Z")]
    assert classify(ts, item)[0] == "NEEDS_PR"


@pytest.mark.parametrize(
    "comment",
    [
        still_waits("2026-11-18T10:00:00Z"),  # the --bot-login
        still_waits("2026-11-18T10:00:00Z", **by("romamo", "OWNER")),
        still_waits("2026-11-18T10:00:00Z", **by("kim", "MEMBER")),
    ],
    ids=["app", "owner", "member"],
)
def test_1313_a_trusted_still_waits_after_the_close_ends_it(ts: ModuleType, comment: dict[str, Any]) -> None:
    item = under(person([handoff("2026-11-15T10:00:00Z"), comment]))
    assert classify(ts, item) == ("WITH_PERSON", "with @ana since 2026-11-15T10:00:00Z")


@pytest.mark.parametrize(
    "comment",
    [
        still_waits("2026-11-16T10:00:00Z"),  # before the parent's close
        still_waits("2026-11-18T10:00:00Z", **by("mallory", "NONE")),  # an outsider's
        said(f"{STILL_WAITS}\nIt waits.{AGENT}", "2026-11-18T10:00:00Z", **by("romamo", "OWNER")),  # agent text
        said(f"Ok.\n{STILL_WAITS}", "2026-11-18T10:00:00Z", **by("romamo", "OWNER")),  # not its first line
        still_waits("2026-11-18T10:00:00Z", **by("ghost", "OWNER")),  # a deleted account's
    ],
    ids=["before-close", "outsider", "agent-marked", "quoted", "ghost"],
)
def test_1313_no_trusted_still_waits_after_the_close_keeps_it(ts: ModuleType, comment: dict[str, Any]) -> None:
    item = under(person([handoff("2026-11-15T10:00:00Z"), comment]))
    assert classify(ts, item)[0] == "STALE_HANDOFF"


def test_1313_a_parent_with_no_close_time_counts_no_still_waits(ts: ModuleType) -> None:
    item = under(person([still_waits("2026-11-18T10:00:00Z")]), closed=None)
    assert classify(ts, item)[0] == "STALE_HANDOFF"


def test_1313_the_parent_is_read_in_the_same_query(ts: ModuleType) -> None:
    """No new API call: the parent's state and close time join the field OFF_MILESTONE reads"""
    assert "parent { number state closedAt repository { nameWithOwner }" in ts.QUERY
    assert "parent" not in ts.TEXT_QUERY  # without the forge's relations, no STALE_HANDOFF


def test_1313_gated_states_come_first(ts: ModuleType) -> None:
    item = under(person(labels=("role:maintainer", "upstream")))
    assert ts.gated(item, BOT, False)[0] == "UPSTREAM"


# -- watch_state.py and the gate ---------------------------------------------------------------


def line(number: int, state: str, note: str) -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": note})


def test_1313_the_watch_lists_it_in_an_issues_row_with_its_fix(ws: ModuleType) -> None:
    assert "STALE_HANDOFF" in ws.TRIAGE_ACTION
    triage = "\n".join(
        [line(7, "STALE_HANDOFF", "parent o/r#5 closed"), line(9, "STALE_HANDOFF", ""), line(4, "NEW", "")]
    )
    issues = [r for r in ws.intake("o/r", 1, triage, [], lambda n: [], BOT) if r.state == "ISSUES"]
    assert [(r.detail, r.fix) for r in issues] == [
        ("NEW #4", "/shipmill:github-issue-triage o/r"),
        (
            "STALE_HANDOFF #7 #9",
            "close it or say why it still waits on the maintainer: /shipmill:github-issue-triage o/r",
        ),
    ]
    assert [r.detail for r in ws.split_issues(issues, decided=False)] == ["NEW #4", "STALE_HANDOFF #7 #9"]


def test_1313_the_gate_hands_it_in_tier_6() -> None:
    assert "ISSUES STALE_HANDOFF" in TIERS[6]


# -- shipmill gh issue close -------------------------------------------------------------------


@dataclass
class SubIssues:
    """Stands in for the gh that reads an issue's open sub-issues: records each argv and env,
    and prints each (URL, labels) as the jq filter would"""

    found: list[tuple[str, list[str]]] = field(default_factory=list)
    code: int = 0
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env)))
        return self.code, "".join(json.dumps(list(row)) + "\n" for row in self.found)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    return Host(fakes, record, guarded_home(tmp_path / "home"))


def close(
    tmp_path: Path, host: Host, args: list[str], subs: SubIssues, config: str = WITH_APP, runner: Runner | None = None
) -> Runner:
    runner = Runner() if runner is None else runner
    leading = ["--app-key", str(key_file(tmp_path))] if config == WITH_APP else []
    main(
        ["--repo", str(checkout(tmp_path, config)), "gh", *leading, *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        stdin=io.StringIO(""),
        gh_capture=subs,
    )
    return runner


URL = f"https://github.com/{REPO}/issues"


@pytest.mark.parametrize(
    "found",
    [
        [(f"{URL}/13", ["role:maintainer"])],
        [(f"{URL}/14", ["bug"]), ("https://github.com/acme/lib/issues/2", ["Human", "docs"])],
    ],
    ids=["role", "human-elsewhere"],
)
def test_1313_closing_a_parent_with_an_open_persons_sub_issue_exits_2(
    tmp_path: Path, host: Host, found: list[tuple[str, list[str]]]
) -> None:
    subs = SubIssues(found)
    with pytest.raises(ReleaseError, match=r"has an open sub-issue that is a person's item.*Close each first") as err:
        close(tmp_path, host, ["issue", "close", "12", "--reason", "completed"], subs)
    item = "romamo/demo#13 (role:maintainer)" if found[0][1] == ["role:maintainer"] else "acme/lib#2 (Human)"
    assert item in str(err.value)
    [(read, env)] = subs.calls
    assert read[1:4] == ["api", "--paginate", f"repos/{REPO}/issues/12/sub_issues"]
    assert env["GH_TOKEN"].startswith("token-")  # read as the App


@pytest.mark.parametrize("found", [[], [(f"{URL}/14", ["bug", "roles"])]], ids=["none", "agents-only"])
def test_1313_closing_a_parent_with_no_open_persons_sub_issue_runs(
    tmp_path: Path, host: Host, found: list[tuple[str, list[str]]]
) -> None:
    args = ["issue", "close", f"{URL}/12", "--comment", "Done"]
    runner = close(tmp_path, host, args, SubIssues(found))
    [(argv, _)] = runner.calls
    assert argv[1:4] == ["issue", "close", f"{URL}/12"]


def test_1313_sub_issues_that_cant_be_read_refuse_the_close(tmp_path: Path, host: Host) -> None:
    runner = Runner()
    with pytest.raises(ReleaseError, match="its sub-issues can't be read.*the close didn't run"):
        close(tmp_path, host, ["issue", "close", "12"], SubIssues(code=1), runner=runner)
    assert runner.calls == []


def test_1313_as_the_host_the_close_reads_nothing(tmp_path: Path, host: Host) -> None:
    subs = SubIssues([(f"{URL}/13", ["role:maintainer"])])
    runner = close(
        tmp_path, host, ["issue", "close", "12"], subs, config='[agents]\nprompt = "/t"\nidentity = "host"\n'
    )
    assert subs.calls == [] and len(runner.calls) == 1


@pytest.mark.parametrize(
    ("args", "found"),
    [
        (["issue", "close", "12"], IssueClose(None, 12)),
        (["issue", "-R", "o/r", "close", "#12", "-r", "not planned"], IssueClose("o/r", 12)),
        (["issue", "close", "https://github.com/o/r/issues/3", "-c", "x"], IssueClose("o/r", 3)),
        (["issue", "reopen", "12"], None),
        (["pr", "close", "12"], None),
        (["issue", "close", "12", "--help"], None),
    ],
)
def test_1313_the_close_names_its_issue(args: list[str], found: IssueClose | None) -> None:
    assert issue_close(args) == found


@pytest.mark.parametrize("targets", [[], ["12", "13"], ["main"]])
def test_1313_a_close_naming_no_one_issue_exits_2(targets: list[str]) -> None:
    with pytest.raises(ReleaseError, match="needs one issue by its number or URL"):
        issue_close(["issue", "close", *targets])
