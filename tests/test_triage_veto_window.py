"""Spec 067: triage_state.py holds a spec's build issues through its approval's veto window"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
SPEC = "docs/specs/067-accepted-spec-notify.md"
BUILD = f"Builds part of spec S-067, `{SPEC}`: the acceptance criteria below.\n\n- S-067-9: ...\n"
APP = "shipmill-app[bot]"
UTC = dt.timezone.utc  # noqa: UP017 (the script's own spelling, Python 3.10)
# The decided comment posted at 09:00 with a 24-hour window, the pull request merged at 12:00
DECIDED = (
    "<!-- shipmill:decided zone=accepted-spec until=2026-11-16T09:00:00Z -->\n@amy Decided without waiting: approve"
)
POSTED, MERGED = "2026-11-15T09:00:00Z", "2026-11-15T12:00:00Z"


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def at(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def note(body: str, when: str, who: str = "amy", association: str = "OWNER", bot: bool = False) -> dict[str, Any]:
    author = {"__typename": "Bot", "login": who.removesuffix("[bot]")} if bot else {"__typename": "User", "login": who}
    return {"body": body, "createdAt": when, "author": author, "authorAssociation": association}


def app(body: str, when: str = POSTED) -> dict[str, Any]:
    """The App's comment: GraphQL gives a Bot's login without "[bot]", and shipmill gh adds the agent marker"""
    return note(body + "\n\n<!-- shipmill:agent -->", when, APP, "NONE", bot=True)


def pull(
    number: int = 50,
    comments: list[dict[str, Any]] | None = None,
    files: tuple[str, ...] = (SPEC,),
    merged: str = MERGED,
    updated: str = MERGED,
    more_files: str | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "mergedAt": merged,
        "updatedAt": updated,
        "files": {
            "pageInfo": {"hasNextPage": more_files is not None, "endCursor": more_files},
            "nodes": [{"path": p} for p in files],
        },
        "comments": {"nodes": [app(DECIDED)] if comments is None else comments},
    }


def build_issue(number: int = 7, body: str = BUILD, triaged: bool = True) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"issue {number}",
        "body": body,
        "labels": {"nodes": []},
        "comments": {"nodes": [{"body": "Triage: implement", "createdAt": MERGED}] if triaged else []},
        "timelineItems": {"nodes": []},
    }


class FakeGitHub:
    """Serves the decided pull requests' pages, keyed by (query name, number, cursor)"""

    def __init__(self, ts: ModuleType, pages: dict[tuple[str, int | None, str | None], dict[str, Any]]) -> None:
        names = ("DECIDED_PRS_PAGE", "PR_FILES_PAGE", "PR_COMMENTS_PAGE")
        self.names = {getattr(ts, n): n for n in names}
        self.pages = pages
        self.calls: list[tuple[str, int | None, str | None]] = []

    def __call__(self, query: str, variables: dict[str, str | int]) -> dict[str, Any]:
        number, cursor = variables.get("number"), variables.get("cursor")
        assert number is None or isinstance(number, int)
        assert cursor is None or isinstance(cursor, str)
        key = (self.names[query], number, cursor)
        self.calls.append(key)
        return {"data": {"repository": self.pages[key]}}


def decided(*pulls: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
    return {"decided": {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": list(pulls)}}


def windows(ts: ModuleType, now: str, *pulls: dict[str, Any], issues: list[dict[str, Any]] | None = None) -> Any:
    gh = FakeGitHub(ts, {("DECIDED_PRS_PAGE", None, None): decided(*pulls)})
    return ts.veto_windows("o/r", issues or [build_issue()], APP, at(now), gh)


def classify(ts: ModuleType, item: dict[str, Any], window: str | None) -> tuple[str, str]:
    found: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, None, ("o", "r"), APP, window=window)
    return found


def test_s067_9_a_build_issue_waits_out_the_window_then_reads_as_without_it(ts: ModuleType) -> None:
    item = build_issue()
    held = windows(ts, "2026-11-16T11:59:00Z", pull())
    assert held == {7: "veto window of #50 until 2026-11-16T12:00:00Z"}
    assert classify(ts, item, held.get(7)) == ("BLOCKED", "veto window of #50 until 2026-11-16T12:00:00Z")
    passed = windows(ts, "2026-11-16T12:00:00Z", pull())
    assert passed == {}
    assert classify(ts, item, passed.get(7)) == classify(ts, item, None) == ("NEEDS_PR", "")


def test_s067_9_the_window_runs_from_the_merge_never_ending_before_until(ts: ModuleType) -> None:
    # Merged at 12:00 after the 09:00 comment: veto_hours (24) from the merge, past until= 09:00
    assert windows(ts, "2026-11-16T10:00:00Z", pull())[7].endswith("until 2026-11-16T12:00:00Z")
    # Merged before the comment was posted: the window still runs to until=, the notice's own end
    early = pull(merged="2026-11-15T08:00:00Z")
    assert windows(ts, "2026-11-16T08:30:00Z", early) == {7: "veto window of #50 until 2026-11-16T09:00:00Z"}


def test_s067_9_an_untriaged_build_issue_waits_too(ts: ModuleType) -> None:
    item = build_issue(triaged=False)
    held = windows(ts, "2026-11-15T13:00:00Z", pull(), issues=[item])
    assert classify(ts, item, held.get(7))[0] == "BLOCKED"
    assert classify(ts, item, None)[0] == "NEW"


def test_s067_9_the_note_keeps_the_other_holds(ts: ModuleType) -> None:
    item = build_issue(body=BUILD + "\nDepends on #3\n")
    state, said = ts.classify_open(
        item,
        "Triage:",
        "postponed",
        {("o", "r", 3): "OPEN"},
        None,
        ("o", "r"),
        APP,
        window="veto window of #50 until x",
    )
    assert (state, said) == ("BLOCKED", "veto window of #50 until x | o/r#3:open")


@pytest.mark.parametrize(
    "comments",
    [
        pytest.param([], id="approved by a merge with no decided comment"),
        pytest.param(
            [app("<!-- shipmill:decided zone=interpretation until=2026-11-16T09:00:00Z -->\n@amy x")],
            id="a decided comment of another zone",
        ),
        pytest.param([note(DECIDED, POSTED, "mallory", "NONE")], id="an outsider's decided comment"),
        pytest.param([note(DECIDED, POSTED, "mallory", "CONTRIBUTOR")], id="a contributor's decided comment"),
        pytest.param([app("Quoting it:\n" + DECIDED)], id="the marker past the first line"),
    ],
)
def test_s067_9_only_a_trusted_accepted_spec_decided_comment_holds(
    ts: ModuleType, comments: list[dict[str, Any]]
) -> None:
    assert windows(ts, "2026-11-15T13:00:00Z", pull(comments=comments)) == {}


def test_s067_9_a_maintainers_decided_comment_holds_too(ts: ModuleType) -> None:
    assert 7 in windows(ts, "2026-11-15T13:00:00Z", pull(comments=[note(DECIDED, POSTED, "amy", "MEMBER")]))


def test_s067_9_only_the_build_issues_of_that_spec_wait(ts: ModuleType) -> None:
    other = build_issue(8, BUILD.replace("067-accepted-spec-notify", "068-other"))
    mentions = build_issue(9, f"Follows {SPEC}, see its Behaviour.\n")  # names the spec, isn't its build issue
    later = build_issue(10, "Context first.\n\n" + BUILD)  # the build line no longer first
    held = windows(ts, "2026-11-15T13:00:00Z", pull(), issues=[build_issue(), other, mentions, later])
    assert set(held) == {7}


def test_s067_9_no_build_issue_reads_no_pull_requests(ts: ModuleType) -> None:
    gh = FakeGitHub(ts, {})
    assert ts.veto_windows("o/r", [build_issue(body=f"Follows {SPEC}\n")], APP, at(MERGED), gh) == {}
    assert gh.calls == []


def test_s067_9_an_unanswered_veto_holds_past_the_window(ts: ModuleType) -> None:
    veto = note("Veto: keep it in scope", "2026-11-15T15:00:00Z")
    vetoed = pull(comments=[app(DECIDED), veto])
    assert windows(ts, "2026-11-20T00:00:00Z", vetoed) == {7: "#50 vetoed by @amy"}
    # Taken up: the session closes the build issues; one still open reads its window again
    handled = pull(comments=[app(DECIDED), veto, app("<!-- shipmill:veto-handled zone=accepted-spec -->\nReverted")])
    assert windows(ts, "2026-11-20T00:00:00Z", handled) == {}
    assert 7 in windows(ts, "2026-11-15T16:00:00Z", handled)


def test_1482_a_maintainers_relayed_veto_holds_past_the_window(ts: ModuleType) -> None:
    relayed = app("Decision by `@amy`, relayed by Claude Code\n\nown: veto keep it in scope", "2026-11-15T15:00:00Z")
    gh = FakeGitHub(ts, {("DECIDED_PRS_PAGE", None, None): decided(pull(comments=[app(DECIDED), relayed]))})
    held = ts.veto_windows("o/r", [build_issue()], APP, at("2026-11-20T00:00:00Z"), gh, maintainers=frozenset({"amy"}))
    assert held == {7: "#50 vetoed by @amy"}
    # without the maintainer given (no --role flags), the relay is no veto
    assert windows(ts, "2026-11-20T00:00:00Z", pull(comments=[app(DECIDED), relayed])) == {}


@pytest.mark.parametrize(
    "veto",
    [
        pytest.param(note("veto", "2026-11-15T15:00:00Z", "mallory", "NONE"), id="an outsider's"),
        pytest.param(
            note("veto\n\n<!-- shipmill:agent -->", "2026-11-15T15:00:00Z"), id="one carrying the agent marker"
        ),
        pytest.param(note("I would not veto this", "2026-11-15T15:00:00Z"), id="veto mid-comment"),
    ],
)
def test_s067_9_a_veto_that_never_counts_releases_with_the_window(ts: ModuleType, veto: dict[str, Any]) -> None:
    assert windows(ts, "2026-11-20T00:00:00Z", pull(comments=[app(DECIDED), veto])) == {}


@pytest.mark.parametrize(
    ("until", "message"),
    [
        ("2026-11-16T09:00:00+02:00", "not a UTC time"),
        ("tomorrow", "not a UTC time"),
        ("2026-11-15T08:00:00Z", "not within 168 hours"),
        ("2026-11-23T09:00:01Z", "not within 168 hours"),
    ],
)
def test_s067_9_an_unreadable_until_exits_2(
    ts: ModuleType, until: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    body = f"<!-- shipmill:decided zone=accepted-spec until={until} -->\n@amy x"
    with pytest.raises(SystemExit) as exc:
        windows(ts, "2026-11-15T13:00:00Z", pull(comments=[app(body)]))
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_s067_9_an_until_without_seconds_reads_as_the_release_reads_it(ts: ModuleType) -> None:
    # src/shipmill/veto.py accepts 2026-11-16T09:00Z: the same comment never stops triage for the repo
    body = "<!-- shipmill:decided zone=accepted-spec until=2026-11-16T09:00Z -->\n@amy x"
    held = windows(ts, "2026-11-15T13:00:00Z", pull(comments=[app(body)]))
    assert held == {7: "veto window of #50 until 2026-11-16T12:00:00Z"}


def test_s067_9_paging_reads_every_comment_and_file_and_stops_past_14_days(ts: ModuleType) -> None:
    chatter = [note(f"+1 ({i})", "2026-11-15T10:00:00Z") for i in range(ts.COMMENTS_CAP)]
    busy = pull(51, comments=chatter, files=("src/a.py",), more_files="f1")
    stale = pull(40, updated="2026-10-01T00:00:00Z")  # past the 14 days: never paged into
    page = {"pageInfo": {"hasPreviousPage": True, "startCursor": "c1"}, "nodes": chatter[-2:]}
    gh = FakeGitHub(
        ts,
        {
            ("DECIDED_PRS_PAGE", None, None): decided(busy, cursor="p1"),
            ("DECIDED_PRS_PAGE", None, "p1"): decided(stale, cursor="p2"),
            ("PR_COMMENTS_PAGE", 51, None): {"pullRequest": {"comments": page}},
            ("PR_COMMENTS_PAGE", 51, "c1"): {
                "pullRequest": {"comments": {"pageInfo": {"hasPreviousPage": False}, "nodes": [app(DECIDED)]}}
            },
            ("PR_FILES_PAGE", 51, "f1"): {
                "pullRequest": {"files": {"pageInfo": {"hasNextPage": False}, "nodes": [{"path": SPEC}]}}
            },
        },
    )
    held = ts.veto_windows("o/r", [build_issue()], APP, at("2026-11-15T13:00:00Z"), gh)
    assert held == {7: "veto window of #51 until 2026-11-16T12:00:00Z"}
    assert gh.calls == [
        ("DECIDED_PRS_PAGE", None, None),
        ("DECIDED_PRS_PAGE", None, "p1"),
        ("PR_COMMENTS_PAGE", 51, None),
        ("PR_COMMENTS_PAGE", 51, "c1"),
        ("PR_FILES_PAGE", 51, "f1"),
    ]


def test_s067_9_a_pull_request_without_the_decided_comment_pages_no_files(ts: ModuleType) -> None:
    gh = FakeGitHub(ts, {("DECIDED_PRS_PAGE", None, None): decided(pull(comments=[], more_files="f1"))})
    assert ts.veto_windows("o/r", [build_issue()], APP, at(MERGED), gh) == {}
    assert gh.calls == [("DECIDED_PRS_PAGE", None, None)]


def test_s067_9_the_query_reads_merged_pull_requests_labelled_decided(ts: ModuleType) -> None:
    query = ts.DECIDED_PRS_PAGE
    assert 'pullRequests(states: MERGED, labels: ["decided"]' in query
    assert "orderBy: {field: UPDATED_AT, direction: DESC}" in query
