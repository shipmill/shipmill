"""The github-ship-watch skill's metrics, from fixture data and a fake GraphQL runner"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "metrics.py"
END = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)  # noqa: UP017 (these tests run on 3.10 too)


@pytest.fixture(scope="module")
def mx() -> ModuleType:
    spec = importlib.util.spec_from_file_location("metrics", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def day(n: float) -> str:
    """n days before END, as GitHub writes a time"""
    return (END - dt.timedelta(days=n)).isoformat().replace("+00:00", "Z")


def window(mx: ModuleType, days: int = 30) -> Any:
    return mx.Window(END - dt.timedelta(days=days), END)


def release(tag: str, published: str, *, pre: bool = False) -> dict[str, Any]:
    return {"tagName": tag, "publishedAt": published, "isDraft": False, "isPrerelease": pre}


def pull(
    number: int,
    merged: str,
    merge: str = "",
    first: str = "",
    by: tuple[str, str] = ("User", "alice"),
    approvers: tuple[tuple[str, str], ...] = (),
    body: str = "",
    messages: tuple[str, ...] = ("Fix a thing",),
    more: str | None = None,
    closes: tuple[tuple[int, str] | dict[str, Any], ...] = (),
    created: str = "",
    reviews: tuple[dict[str, Any], ...] = (),
    files: tuple[str, ...] = (),
    commits: tuple[dict[str, Any], ...] = (),
    more_reviews: str | None = None,
    more_files: str | None = None,
) -> dict[str, Any]:
    """messages: the PR's commit messages, oldest first; more: a cursor to more commits;
    closes: the issues GitHub links it to close, as (number, createdAt) or a closing() node;
    created: when the PR was opened (default its first commit, else its merge); reviews: every
    review (review()), files: its changed files' paths, commits: commit() nodes in place of
    messages, each with a cursor to more"""
    listed = list(commits) or [commit(first or merged, m) for m in messages]
    return {
        "number": number,
        "createdAt": created or first or merged,
        "updatedAt": merged,
        "mergedAt": merged,
        "body": body,
        "mergeCommit": {"oid": merge or f"m{number}"},
        "mergedBy": {"__typename": by[0], "login": by[1]},
        "closingIssuesReferences": {"nodes": [c if isinstance(c, dict) else closing(*c) for c in closes]},
        "commits": {"pageInfo": {"hasNextPage": more is not None, "endCursor": more}, "nodes": listed},
        "reviews": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"author": {"__typename": t, "login": login}} for t, login in approvers],
        },
        "verdicts": page(list(reviews), more_reviews),
        "files": page([{"path": p} for p in files], more_files),
    }


def commit(authored: str, message: str = "Fix a thing", parents: int = 1) -> dict[str, Any]:
    return {"commit": {"authoredDate": authored, "message": message, "parents": {"totalCount": parents}}}


def review(
    state: str,
    at: str,
    oid: str = "h1",
    author: tuple[str, str] = ("User", "alice"),
    association: str = "MEMBER",
    body: str = "",
) -> dict[str, Any]:
    """A review as PULLS reads its verdicts"""
    return {
        "state": state,
        "authorAssociation": association,
        "submittedAt": at,
        "body": body,
        "commit": {"oid": oid},
        "author": {"__typename": author[0], "login": author[1]},
    }


PERSON = ("User", "alice")
MARKER = "<!-- shipmill:agent -->"


def closing(
    number: int,
    created: str,
    *comments: tuple[str, str, tuple[str, str]],
    body: str = "",
    author: tuple[str, str] | None = PERSON,
    more: str | None = None,
) -> dict[str, Any]:
    """An issue a PR closes; comments as (createdAt, body, (author type, login)), oldest
    first; more: a cursor to more comments"""
    return {
        "url": f"https://github.com/o/r/issues/{number}",
        "number": number,
        "createdAt": created,
        "body": body,
        "author": None if author is None else {"__typename": author[0], "login": author[1]},
        "repository": {"owner": {"login": "o"}, "name": "r"},
        "comments": {
            "pageInfo": {"hasNextPage": more is not None, "endCursor": more},
            "nodes": [
                {"createdAt": at, "body": text, "author": {"__typename": who[0], "login": who[1]}}
                for at, text, who in comments
            ],
        },
    }


def issue(number: int, created: str, closed: str | None = None, *comments: tuple[str, str]) -> dict[str, Any]:
    """Comments as (createdAt, body), oldest first"""
    return {
        "number": number,
        "createdAt": created,
        "closedAt": closed,
        "comments": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"createdAt": at, "body": body} for at, body in comments],
        },
    }


def deployment(env: str, created: str, *states: str) -> dict[str, Any]:
    return {
        "environment": env,
        "createdAt": created,
        "statuses": {"pageInfo": {"hasNextPage": False}, "nodes": [{"state": s} for s in states]},
    }


def data(mx: ModuleType, **fields: Any) -> Any:
    base: dict[str, Any] = {
        "releases": [],
        "shipped": {},
        "hotfixes": set(),
        "pulls": [],
        "deployed": False,
        "deployments": [],
        "incidents": [],
        "blockers": [],
    }
    base.update(fields)
    if base["releases"] and isinstance(base["releases"][0], dict):
        base["releases"] = mx.stable_releases(base["releases"])
    return mx.Data(**base)


def by_name(mx: ModuleType, d: Any, days: int = 30) -> dict[str, Any]:
    return {m.name: m for m in mx.measures(d, window(mx, days))}


def test_an_empty_window_reads_no_data_never_zero(mx: ModuleType) -> None:
    old = [release("v1.0.0", day(60))]
    found = by_name(mx, data(mx, releases=old, pulls=[pull(1, day(50))]))
    for m in found.values():
        assert m.value is None, m.name
        assert m.text == "no data", m.name
        assert m.json()["value"] is None


def test_a_repo_without_deployments_counts_stable_releases(mx: ModuleType) -> None:
    releases = [
        release("v1.1.0", day(2)),
        release("v1.1.0rc1", day(5), pre=True),
        release("v1.0.1", day(9)),
        release("v1.0.0", day(40)),
    ]
    m = by_name(mx, data(mx, releases=releases))["Deploy frequency"]
    assert m.extra == {"source": "releases", "count": 2}
    assert m.value == pytest.approx(2 / (30 / 7))
    assert "v1.1.0 v1.0.1" in m.detail


def test_deployments_count_per_environment_only_when_they_reached_success(mx: ModuleType) -> None:
    deploys = [
        deployment("prod", day(1), "IN_PROGRESS", "SUCCESS", "FAILURE"),  # a later health failure still deployed
        deployment("prod", day(3), "IN_PROGRESS", "FAILURE"),
        deployment("staging", day(4), "SUCCESS"),
    ]
    found = by_name(mx, data(mx, deployed=True, deployments=deploys, releases=[release("v1.0.0", day(2))]))
    m = found["Deploy frequency"]
    assert m.extra["source"] == "deployments"
    assert m.extra["environments"] == {"prod": 1, "staging": 1}
    assert found["Change failure rate"].text == "0%"  # two deploys, no incident: a real zero


def test_deployed_but_none_in_the_window_is_no_data(mx: ModuleType) -> None:
    m = by_name(mx, data(mx, deployed=True))["Deploy frequency"]
    assert m.value is None


def test_lead_time_runs_from_the_first_commit_to_the_first_release_that_shipped_it(mx: ModuleType) -> None:
    releases = [release("v1.2.0", day(1)), release("v1.1.0", day(5)), release("v1.0.0", day(40))]
    # c1 is first shipped by v1.1.0; a later release listing it again doesn't move it
    shipped = {"v1.1.0": {"c1", "c2"}, "v1.2.0": {"c1", "c3"}}
    pulls = [
        pull(1, day(6), "c1", first=day(7)),  # 2 days to v1.1.0
        pull(2, day(5.5), "c2", first=day(6)),  # 1 day
        pull(3, day(2), "c3", first=day(5)),  # 4 days to v1.2.0
        pull(4, day(0.5), "c4"),  # merged, not released yet
    ]
    m = by_name(mx, data(mx, releases=releases, shipped=shipped, pulls=pulls))["Lead time for changes"]
    assert m.value == pytest.approx(48.0)
    assert m.extra == {"p90": pytest.approx(96.0), "count": 3}
    assert m.detail == "3 PRs in 2 releases"


def test_the_previous_release_is_the_next_lower_version_not_the_last_published(mx: ModuleType) -> None:
    releases = mx.stable_releases(
        [release("v2.1.1", day(1)), release("v1.9.9", day(3)), release("v2.1.0", day(20)), release("v2.0.0", day(50))]
    )
    assert mx.previous(releases[0], releases).tag == "v2.1.0"
    assert mx.previous(releases[-1], releases) is None


def test_change_failure_without_deployments_counts_blockers_and_hotfixes(mx: ModuleType) -> None:
    releases = [release("v1.0.2", day(1)), release("v1.0.1", day(10)), release("v1.0.0", day(20))]
    blockers = [issue(7, day(12)), issue(3, day(45))]  # #3 opened before the window
    d = data(mx, releases=releases, hotfixes={"v1.0.1"}, blockers=blockers, incidents=[issue(9, day(2))])
    m = by_name(mx, d)["Change failure rate"]
    assert m.value == pytest.approx(2 / 3)
    assert m.detail == "1 blocker issues + 1 hotfixes / 3 releases: #7 v1.0.1"


def test_change_failure_with_deployments_counts_incidents(mx: ModuleType) -> None:
    deploys = [deployment("prod", day(n), "SUCCESS") for n in (1, 2, 3, 4)]
    d = data(mx, deployed=True, deployments=deploys, incidents=[issue(9, day(2))], blockers=[issue(7, day(3))])
    m = by_name(mx, d)["Change failure rate"]
    assert m.value == pytest.approx(0.25)
    assert m.detail == "1 incidents / 4 deploys: #9"


def test_time_to_restore_takes_the_healthy_comment_or_the_close_whichever_is_first(mx: ModuleType) -> None:
    incidents = [
        issue(1, day(10), day(5), (day(9), "prod is healthy again on v1.0.1 (200 in 30 ms).")),  # 1 day
        issue(2, day(6), day(3), (day(4), "a person's note")),  # closed: 3 days
        issue(3, day(2)),  # still open
        issue(4, day(50), day(40)),  # restored before the window
    ]
    m = by_name(mx, data(mx, incidents=incidents))["Time to restore"]
    assert m.value == pytest.approx(48.0)
    assert m.extra == {"count": 2, "open": 1}


def test_an_earlier_window_counts_what_was_open_at_its_end(mx: ModuleType) -> None:
    incidents = [
        issue(1, day(12), day(9)),  # restored in the earlier window: 3 days
        issue(2, day(9), day(3)),  # restored after it: open at its end
        issue(3, day(2)),  # opened after it
    ]
    earlier = mx.Window(END - dt.timedelta(days=14), END - dt.timedelta(days=7))
    m = mx.time_to_restore(data(mx, incidents=incidents), earlier)
    assert m.value == pytest.approx(72.0)
    assert m.extra == {"count": 1, "open": 1}


def test_until_reads_a_date_or_a_time_with_its_offset(mx: ModuleType) -> None:
    assert mx.until("2026-09-24", END) == dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)  # noqa: UP017
    assert mx.until("2026-09-24T12:00:00+02:00", END) == dt.datetime(2026, 9, 24, 10, tzinfo=dt.timezone.utc)  # noqa: UP017
    assert mx.until("2026-09-24T10:00:00Z", END) == dt.datetime(2026, 9, 24, 10, tzinfo=dt.timezone.utc)  # noqa: UP017


@pytest.mark.parametrize(
    ("text", "error"),
    [("2026-09-24T10:00:00", "needs a time's offset"), ("last week", "must be a date"), ("2026-10-02", "future")],
)
def test_until_refuses_a_naive_malformed_or_future_time(
    mx: ModuleType, capsys: pytest.CaptureFixture[str], text: str, error: str
) -> None:
    with pytest.raises(SystemExit) as refused:
        mx.until(text, END)
    assert refused.value.code == 2
    assert error in capsys.readouterr().err


def test_d69_issue_to_release_runs_from_the_issue_to_the_release_that_shipped_its_close(mx: ModuleType) -> None:
    # D-69 (#921): no notice is read; an issue's release is the first in-window stable release
    # that shipped a merged PR closing it
    releases = [release("v1.2.0", day(1)), release("v1.1.0", day(5)), release("v1.0.0", day(40))]
    shipped = {"v1.1.0": {"c1", "c2"}, "v1.2.0": {"c3"}}
    pulls = [
        pull(1, day(6), "c1", closes=((1, day(8)),)),  # 3 days to v1.1.0
        pull(2, day(5.5), "c2", closes=((2, day(6)),)),  # 1 day
        pull(3, day(2), "c3", closes=((2, day(6)), (3, day(4)))),  # #2 counts once, at v1.1.0; #3 3 days
        pull(4, day(0.5), "c4", closes=((4, day(1)),)),  # not released yet
        pull(5, day(3), "c5"),  # closes nothing
    ]
    m = by_name(mx, data(mx, releases=releases, shipped=shipped, pulls=pulls))["Issue to release"]
    assert m.value == pytest.approx(72.0)
    assert m.extra == {"p90": pytest.approx(72.0), "count": 3}
    assert m.detail == "3 issues closed by a PR a stable release shipped"


def test_human_touch_counts_a_person_merging_or_approving(mx: ModuleType) -> None:
    bot = ("Bot", "github-actions")
    pulls = [
        pull(1, day(1)),  # a person merged
        pull(2, day(2), by=bot, approvers=(("User", "bob"),)),  # a bot merged what a person approved
        pull(3, day(3), by=bot, approvers=(("Bot", "copilot"),)),  # no person
        pull(4, day(4), by=("User", "renovate[bot]")),  # a bot login on a user
        pull(5, day(5), by=("User", "release-robot")),  # a machine user named by --bot
        pull(6, day(50)),  # merged before the window
    ]
    d = data(mx, pulls=pulls, bots=frozenset({"release-robot"}))
    m = by_name(mx, d)["Human touch"]
    assert m.value == pytest.approx(2 / 5)
    assert m.extra == {"merges": 5, "merged_by_person": 1, "approved_by_person": 1}
    assert "an agent merging with a person's token counts as the person" in m.detail


def test_agent_share_reads_the_footer_and_trailers_and_the_human_gate(mx: ModuleType) -> None:
    footer = "Summary\n\n🤖 generated with [claude code](https://claude.com/claude-code)"
    trailer = "Fix it\n\nco-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
    session = "Fix it\n\nCLAUDE-SESSION: https://claude.ai/code/session_x"
    pulls = [
        pull(1, day(1), body=footer, approvers=(("User", "bob"),)),  # agent-made, a person approved
        pull(2, day(2), messages=("Start", trailer)),  # a later commit's trailer
        pull(3, day(3), messages=(session,), approvers=(("Bot", "copilot"),)),  # a bot's approval is no gate
        pull(4, day(4), body="Mentions Co-Authored-By: Claude mid-line", approvers=(("User", "bob"),)),
        pull(5, day(5), messages=("Thanks to Claude-Session: none",)),  # not a trailer at a line's start
        pull(6, day(50), body=footer),  # merged before the window
    ]
    m = by_name(mx, data(mx, pulls=pulls))["Agent share"]
    assert m.value == pytest.approx(3 / 5)
    assert m.extra == {"merges": 5, "agent_made": 3, "approved_by_person": 1}
    assert m.detail == "3 of 5 merges agent-made; a person approved 1 of them in a review"


def test_agent_share_is_zero_without_a_mark_and_no_data_without_merges(mx: ModuleType) -> None:
    assert by_name(mx, data(mx, pulls=[pull(1, day(1))]))["Agent share"].text == "0%"
    assert by_name(mx, data(mx))["Agent share"].value is None


def test_the_markdown_form_is_a_table(mx: ModuleType) -> None:
    w = window(mx)
    text = mx.render("o/r", 30, w, mx.measures(data(mx), w), "markdown")
    assert "| Measure | Value | Detail |" in text
    assert "| Deploy frequency | no data |" in text


def test_the_table_form_aligns_its_value_column(mx: ModuleType) -> None:
    w = window(mx)
    found = mx.measures(data(mx), w)
    rows = mx.render("o/r", 30, w, found, "table").splitlines()[1:]
    assert len({row.index(m.text, len(m.name)) for row, m in zip(rows, found, strict=True)}) == 1


# -- fetch, against a fake GraphQL runner ---------------------------------------------------------


def page(nodes: list[Any], cursor: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": nodes, **extra}


def ok(repository: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"repository": repository}}


class FakeGitHub:
    """Answers each query the script sends from fixture pages, rejecting pages over limit"""

    def __init__(self, mx: ModuleType, limit: int = 1000) -> None:
        self.mx = mx
        self.limit = limit
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.answers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            mx.RELEASES: self.releases,
            mx.COMPARE: self.compare,
            mx.LINE: self.line,
            mx.PULLS: self.pulls,
            mx.PULL_COMMITS: self.pull_commits,
            mx.PULL_VERDICTS: self.pull_verdicts,
            mx.PULL_FILES: self.pull_files,
            mx.ISSUE_COMMENTS: self.issue_comments,
            mx.DEPLOYMENTS: self.deployments,
            mx.LABELLED: lambda v: ok({"issues": page([])}),
        }

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        name = next(k for k, v in vars(self.mx).items() if v is query and k.isupper())
        self.calls.append((name, dict(variables)))
        if variables.get("size", 0) > self.limit:
            return {"errors": [{"type": "RESOURCE_LIMITS_EXCEEDED", "message": "too costly"}]}
        return self.answers[query](variables)

    def releases(self, v: dict[str, Any]) -> dict[str, Any]:
        if "cursor" not in v:
            return ok({"releases": page([release("v1.0.1", day(2))], "r1")})
        return ok({"releases": page([release("v1.0.0", day(40))])})

    def compare(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["base"], v["head"]) == ("refs/tags/v1.0.0", "refs/tags/v1.0.1")
        return ok({"base": {"compare": {"commits": page([{"oid": "c1", "committedDate": day(3)}])}}})

    def line(self, v: dict[str, Any]) -> dict[str, Any]:
        assert v["branch"] == "refs/heads/release/1.0"
        return ok({"line": {"compare": {"status": "BEHIND"}}})

    def pulls(self, v: dict[str, Any]) -> dict[str, Any]:
        return ok({"pullRequests": page([pull(1, day(3), "c1", first=day(4), more="p1", closes=((7, day(6)),))])})

    def pull_commits(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["number"], v["cursor"]) == (1, "p1")
        return ok({"pullRequest": {"commits": page([commit(day(3), "Last\n\nClaude-Session: https://x")])}})

    def pull_verdicts(self, v: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"no PR's reviews should be paged here: {v}")

    def pull_files(self, v: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"no PR's files should be paged here: {v}")

    def issue_comments(self, v: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"no issue's comments should be paged here: {v}")

    def deployments(self, v: dict[str, Any]) -> dict[str, Any]:
        return ok({"deployments": page([], totalCount=0)})


def test_fetch_pages_shrinks_rejected_pages_and_finds_a_hotfix(mx: ModuleType) -> None:
    gh = FakeGitHub(mx, limit=30)
    w = window(mx)
    d = mx.fetch("o/r", w, frozenset(), "incident", "release-blocker", run=gh)
    assert [r.tag for r in d.releases] == ["v1.0.1", "v1.0.0"]  # the second page was read
    assert d.shipped == {"v1.0.1": {"c1"}}
    assert d.hotfixes == {"v1.0.1"}
    assert not d.deployed
    sizes = [v["size"] for name, v in gh.calls if name == "RELEASES"]
    assert sizes == [100, 50, 25, 25]  # halved until accepted, and the smaller size stuck
    found = by_name(mx, d)
    assert found["Lead time for changes"].value == pytest.approx(48.0)
    assert found["Agent share"].extra["agent_made"] == 1  # the trailer was on the PR's second page of commits
    assert found["Change failure rate"].value == pytest.approx(1.0)  # the one release was a hotfix
    assert found["Issue to release"].value == pytest.approx(96.0)  # #7, opened day 6, in v1.0.1 on day 2


def test_a_page_rejected_at_the_floor_fails(mx: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGitHub(mx, limit=5)
    with pytest.raises(SystemExit) as exc:
        mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=gh)
    assert exc.value.code == 2
    assert "rejected releases even at 10 per page" in capsys.readouterr().err


def test_a_malformed_repo_fails(mx: ModuleType) -> None:
    with pytest.raises(SystemExit):
        mx.fetch("no-slash", window(mx), frozenset(), "incident", "release-blocker", run=FakeGitHub(mx))


class DeployedLongAgo(FakeGitHub):
    """Recent deployments to staging only; production's last one is on the second page"""

    def deployments(self, v: dict[str, Any]) -> dict[str, Any]:
        if "cursor" not in v:
            nodes = [deployment("staging", day(1), "SUCCESS"), deployment("staging", day(40), "SUCCESS")]
            return ok({"deployments": page(nodes, "d1", totalCount=3)})
        return ok({"deployments": page([deployment("production", day(60), "SUCCESS")], totalCount=3)})


def test_an_environment_deployed_only_before_the_window_still_counts_as_deployed(mx: ModuleType) -> None:
    gh = DeployedLongAgo(mx)
    d = mx.fetch("o/r", window(mx), frozenset({"production"}), "incident", "release-blocker", run=gh)
    assert d.deployed
    assert d.deployments == []
    assert by_name(mx, d)["Deploy frequency"].value is None  # no data, not the releases


class FirstDeployedLater(FakeGitHub):
    """The repo's only deployment came after an earlier window's end"""

    def deployments(self, v: dict[str, Any]) -> dict[str, Any]:
        return ok({"deployments": page([deployment("production", day(1), "SUCCESS")], totalCount=1)})


def test_a_repo_that_first_deployed_after_the_window_counts_releases_in_it(mx: ModuleType) -> None:
    earlier = mx.Window(END - dt.timedelta(days=14), END - dt.timedelta(days=7))
    d = mx.fetch("o/r", earlier, frozenset(), "incident", "release-blocker", run=FirstDeployedLater(mx))
    assert not d.deployed
    assert mx.deploy_frequency(d, earlier).detail == "no deployments, and no stable release in the window"


# -- spec 066: issue to release by stage ----------------------------------------------------------

STAGES = [
    "Issue to first agent comment",
    "Issue to PR opened",
    "Issue to PR opened, person-filed",
    "Issue to PR opened, agent-filed",
    "PR opened to merged",
    "Merged to release",
]
QUALITY = ["Rework cycles", "First-pass merge rate", "Review time", "Plan match"]  # spec 078
DECIDED = ["Decided work credited", "Decided work written as the decider"]  # spec 109
BEFORE = ["Deploy frequency", "Lead time for changes", "Change failure rate", "Time to restore", "Issue to release"]


def staged(mx: ModuleType) -> Any:
    """Four counted issues: #2 closed by two PRs in two releases, #4 by two PRs in one, #3's PR
    opened before it, #5's PR not released yet"""
    releases = [release("v1.2.0", day(1)), release("v1.1.0", day(5)), release("v1.0.0", day(40))]
    shipped = {"v1.1.0": {"c1", "c2"}, "v1.2.0": {"c3", "c4", "c5"}}
    pulls = [
        pull(6, day(0.5), "c6", closes=((5, day(1)),)),  # not released
        pull(5, day(1.2), "c5", created=day(1.3), closes=((4, day(3)),)),  # same release as #4's, merged later
        pull(3, day(2), "c3", created=day(3), closes=((2, day(6.5)), (3, day(2.5)))),  # #3 filed after its PR
        pull(4, day(1.5), "c4", created=day(2), closes=((4, day(3)),)),
        pull(1, day(6), "c1", created=day(7), closes=(closing(1, day(8), (day(7.5), MARKER, PERSON), body=MARKER),)),
        pull(2, day(5.5), "c2", created=day(6), closes=((2, day(6.5)),)),
    ]
    return data(mx, releases=releases, shipped=shipped, pulls=pulls)


def test_s066_1_the_stages_follow_issue_to_release_in_the_json(mx: ModuleType) -> None:
    w = window(mx)
    found = json.loads(mx.render("o/r", 30, w, mx.measures(staged(mx), w), "json"))["measures"]
    assert [m["measure"] for m in found] == [*BEFORE, *STAGES, "Human touch", "Agent share", *DECIDED, *QUALITY]
    for m in found[len(BEFORE) : len(BEFORE) + len(STAGES)]:
        assert m["unit"] == "hours", m["measure"]
        assert set(m) >= {"value", "p90", "count", "text"}, m["measure"]
    empty = json.loads(mx.render("o/r", 30, w, mx.measures(data(mx), w), "json"))["measures"]
    for m in empty[len(BEFORE) : len(BEFORE) + len(STAGES)]:
        assert (m["value"], m["text"], m["unit"]) == (None, "no data", "hours"), m["measure"]


def test_s066_2_each_stage_is_measured_against_the_earliest_released_pr(mx: ModuleType) -> None:
    d = staged(mx)
    closed = {c.issue["number"]: c for c in mx.closed_issues(d, window(mx))}
    # the earliest release wins (#2: v1.1.0 over v1.2.0), and on a tie the earliest merge (#4: PR 4)
    assert {n: c.pr["number"] for n, c in closed.items()} == {1: 1, 2: 2, 3: 3, 4: 4}
    found = by_name(mx, d)
    assert found["Issue to release"].extra["count"] == 4
    to_pr = found["Issue to PR opened"]  # 24, 12, -12, 24
    assert (to_pr.value, to_pr.extra) == (pytest.approx(18.0), {"p90": pytest.approx(24.0), "count": 4})
    to_merge = found["PR opened to merged"]  # 24, 12, 24, 12
    assert (to_merge.value, to_merge.extra) == (pytest.approx(18.0), {"p90": pytest.approx(24.0), "count": 4})
    to_release = found["Merged to release"]  # 24, 12, 24, 12
    assert (to_release.value, to_release.extra["count"]) == (pytest.approx(18.0), 4)


def test_s066_3_the_three_stages_sum_to_issue_to_release(mx: ModuleType) -> None:
    for c in mx.closed_issues(staged(mx), window(mx)):
        parts = mx.hours(c.opened, c.created) + mx.hours(c.created, c.merged) + mx.hours(c.merged, c.release.published)
        assert parts == pytest.approx(mx.hours(c.opened, c.release.published)), c.issue["number"]
        if c.issue["number"] == 3:
            assert mx.hours(c.opened, c.created) == pytest.approx(-12.0)  # its PR was opened first


def test_s066_4_the_first_agent_comment_by_the_release(mx: ModuleType) -> None:
    releases = [release("v1.1.0", day(5)), release("v1.0.0", day(40))]
    inline = "a person quoting <!-- shipmill:agent --> mid-line"
    issues = [
        closing(
            1,
            day(8),
            (day(7.9), "Looks good", PERSON),
            (day(7.8), inline, PERSON),
            (day(7.5), f"Triage: implement\n\n{MARKER}", PERSON),  # the marker on its own line: 12 h
        ),
        closing(2, day(8), (day(7), "on it", ("Bot", "shipmill-app"))),  # a Bot: 24 h
        closing(3, day(8), (day(7.75), "bump", ("User", "renovate[bot]"))),  # a [bot] login: 6 h
        closing(4, day(8), (day(6), "noted", ("User", "release-robot"))),  # a --bot login: 48 h
        closing(5, day(8), (day(4), MARKER, ("Bot", "shipmill-app"))),  # only after the release
        closing(6, day(8), (day(7), inline, PERSON)),  # none
    ]
    pulls = [pull(n, day(6), f"c{n}", closes=(i,)) for n, i in enumerate(issues, start=1)]
    shipped = {"v1.1.0": {f"c{n}" for n in range(1, 7)}}
    d = data(mx, releases=releases, shipped=shipped, pulls=pulls, bots=frozenset({"release-robot"}))
    m = by_name(mx, d)["Issue to first agent comment"]
    assert m.value == pytest.approx(18.0)
    assert m.extra == {"p90": pytest.approx(48.0), "count": 4}
    assert m.detail == "4 issues; 2 with no agent comment by their release left out"
    lone = data(mx, releases=releases, shipped=shipped, pulls=pulls[4:])
    m = by_name(mx, lone)["Issue to first agent comment"]
    assert (m.value, m.detail) == (None, "no agent comment by its release on any of 2 issues, all left out")


def test_s066_5_issue_to_pr_opened_by_who_filed_the_issue(mx: ModuleType) -> None:
    releases = [release("v1.1.0", day(5)), release("v1.0.0", day(40))]
    issues = [
        closing(1, day(8), body=f"Filed by the gate\n{MARKER}"),  # agent: the marker
        closing(2, day(8), author=("Bot", "shipmill-app")),  # agent: a Bot
        closing(3, day(8), author=("User", "dependabot[bot]")),  # agent: a [bot] login
        closing(4, day(8), author=("User", "release-robot")),  # agent: a --bot login
        closing(5, day(9), body="quoting <!-- shipmill:agent --> mid-line"),  # person
        closing(6, day(9)),  # person
        closing(7, day(9), author=None),  # person: a deleted account
    ]
    pulls = [pull(n, day(6), f"c{n}", created=day(7), closes=(i,)) for n, i in enumerate(issues, start=1)]
    shipped = {"v1.1.0": {f"c{n}" for n in range(1, 8)}}
    d = data(mx, releases=releases, shipped=shipped, pulls=pulls, bots=frozenset({"release-robot"}))
    found = by_name(mx, d)
    agent, person = found["Issue to PR opened, agent-filed"], found["Issue to PR opened, person-filed"]
    assert (agent.value, agent.extra["count"]) == (pytest.approx(24.0), 4)
    assert (person.value, person.extra["count"]) == (pytest.approx(48.0), 3)
    assert agent.extra["count"] + person.extra["count"] == found["Issue to PR opened"].extra["count"]


class CommentPages(FakeGitHub):
    """#7's agent comment is on its comments' third page, #8 has a comment past the release"""

    def pulls(self, v: dict[str, Any]) -> dict[str, Any]:
        first = closing(7, day(6), (day(5.5), "a person's note", PERSON), more="k1")
        late = closing(8, day(6), (day(1), "after the release", PERSON), more="j1")
        return ok({"pullRequests": page([pull(1, day(3), "c1", created=day(4), closes=(first, late))])})

    def issue_comments(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["owner"], v["name"], v["number"]) == ("o", "r", 7)
        nodes: dict[str, tuple[list[dict[str, Any]], str]] = {
            "k1": (
                [{"createdAt": day(5), "body": "another note", "author": {"__typename": "User", "login": "a"}}],
                "k2",
            ),
            "k2": ([{"createdAt": day(4), "body": f"Triage\n{MARKER}", "author": None}], "k3"),
        }
        found, cursor = nodes[v["cursor"]]
        return ok({"issue": {"comments": page(found, cursor)}})


def test_s066_6_comments_are_paged_only_until_the_first_agent_comment(mx: ModuleType) -> None:
    gh = CommentPages(mx)
    d = mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=gh)
    cursors = [v["cursor"] for name, v in gh.calls if name == "ISSUE_COMMENTS"]
    assert cursors == ["k1", "k2"]  # k2 held the agent comment; #8's page held one past the release
    m = by_name(mx, d)["Issue to first agent comment"]
    assert (m.value, m.extra["count"]) == (pytest.approx(48.0), 1)
    assert m.detail == "1 issues; 1 with no agent comment by their release left out"


def test_s066_6_metrics_reads_nothing_but_github_through_gh(mx: ModuleType) -> None:
    source = SCRIPT.read_text()
    assert source.count("subprocess.run(") == 1
    assert 'cmd = ["gh", "api", "graphql"' in source
    for other in ("open(", "os.environ", "getenv", "urllib", "http.client", "socket", "pathlib", "read_text"):
        assert other not in source, other


# -- spec 078: agent quality measures --------------------------------------------------------------

FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
RECORD = "<!-- shipmill:review merge -->\n\nVerdict: MERGE"


def agent(number: int, merged: str = "", created: str = "", body: str = "", **kw: Any) -> dict[str, Any]:
    """An agent's PR (Claude Code's footer), opened day 3 and merged day 1 unless given; its
    commits are authored when it was opened, so none is a fix commit"""
    created = created or day(3)
    return pull(number, merged or day(1), first=created, created=created, body=f"{body}\n\n{FOOTER}", **kw)


def plan(*files_lines: str) -> str:
    return "\n".join(
        ["## Plan", "", "- Serves: G-2", *files_lines, "- Order: tests first", "", "## Summary", "", "Text"]
    )


def test_s078_1_the_quality_measures_follow_agent_share_over_its_agent_prs(mx: ModuleType) -> None:
    pulls = [
        agent(1, reviews=(review("APPROVED", day(2)),), files=("src/a.py",), body=plan("- Files: `src/a.py`")),
        agent(2),
        pull(3, day(2)),  # a person's PR: not measured
        agent(4, merged=day(50), created=day(51)),  # merged before the window
    ]
    w = window(mx)
    found = json.loads(mx.render("o/r", 30, w, mx.measures(data(mx, pulls=pulls), w), "json"))["measures"]
    names = [m["measure"] for m in found]
    share = names.index("Agent share") + len(DECIDED)  # spec 109's two measures come between
    assert names[share + 1 :] == QUALITY
    quality = {m["measure"]: m for m in found[share + 1 :]}
    assert quality["Rework cycles"]["count"] == found[names.index("Agent share")]["agent_made"] == 2
    assert quality["Rework cycles"]["unit"] == "count"
    assert (quality["First-pass merge rate"]["unit"], quality["Plan match"]["unit"]) == ("ratio", "ratio")
    timed = quality["Review time"]
    assert (timed["unit"], timed["value"], timed["p90"], timed["count"]) == ("hours", 24.0, 24.0, 1)
    assert quality["Plan match"]["value"] == 1.0
    for empty in (data(mx), data(mx, pulls=[pull(3, day(2))])):  # no PR merged; only a person's
        measured = json.loads(mx.render("o/r", 30, w, mx.measures(empty, w), "json"))["measures"]
        for m in measured[share + 1 :]:
            assert (m["value"], m["text"]) == (None, "no data"), m["measure"]
            assert by_name(mx, empty)[m["measure"]].detail == "no agent PR merged in the window"


def test_s078_2_a_verdict_is_a_bot_review_record_or_a_trusted_persons_decision(mx: ModuleType) -> None:
    bots = frozenset({"release-robot"})
    verdicts = [
        review("COMMENTED", day(2), body=RECORD, author=("Bot", "shipmill-app"), association="NONE"),
        review("COMMENTED", day(2), body="  <!-- shipmill:review refuse -->\nNo", author=("User", "ci[bot]")),
        review("COMMENTED", day(2), body=RECORD, author=("User", "release-robot")),  # a --bot login
        review("APPROVED", day(2), association="OWNER"),
        review("CHANGES_REQUESTED", day(2), association="COLLABORATOR"),
        review("APPROVED", day(2), association="MEMBER", body="Looks good"),
    ]
    nones = [
        review("COMMENTED", day(2), association="OWNER"),  # a trusted person's comment
        review("APPROVED", day(2), association="CONTRIBUTOR"),  # an outsider (D-16)
        review("CHANGES_REQUESTED", day(2), association="NONE"),
        review("COMMENTED", day(2), body=RECORD),  # a person's marker
        review("APPROVED", day(2), author=("Bot", "copilot"), association="NONE"),  # a bot's approval, no record
        review("APPROVED", day(2), author=("User", "release-robot")),  # a --bot login is no person
        review("COMMENTED", day(2), body="<!-- shipmill:review merge --> quoted", author=("Bot", "shipmill-app")),
        review("PENDING", day(2), body=RECORD, author=("Bot", "shipmill-app")),  # not submitted
    ]
    assert all(mx.verdict(r, bots) for r in verdicts)
    assert not any(mx.verdict(r, bots) for r in nones)
    # a record and an approval at h1 are one round; the request for changes at h2 another
    rounds = (
        *verdicts[:1],
        verdicts[3],
        review("CHANGES_REQUESTED", day(1.5), oid="h2"),
        review("COMMENTED", day(1), oid="h3"),
    )
    assert mx.rework(agent(1, reviews=rounds), bots).rounds == 2


def test_s078_3_a_fix_commit_is_one_parent_authored_after_the_pr_opened(mx: ModuleType) -> None:
    commits = (
        commit(day(6)),  # written before the PR opened, rebased after it: kept its author date
        commit(day(4)),  # a fix
        commit(day(3), "Merge branch 'main'", parents=2),  # a merge of the base
        commit(day(2)),  # a fix
    )
    found = mx.rework(agent(1, created=day(5), commits=commits), frozenset())
    assert (found.fixes, found.rounds, found.cycles) == (2, 0, 2)


class ReworkForge(FakeGitHub):
    """Three agent PRs merged in the window: #1 with its second round, its fix commit, and a
    changed file on second pages; a person's PR and an agent's merged before the window, each
    with more pages that must not be read"""

    def pulls(self, v: dict[str, Any]) -> dict[str, Any]:
        first = agent(
            1,
            created=day(6),
            commits=(commit(day(7), "Start\n\nClaude-Session: https://x"),),
            more="c1",
            reviews=(review("CHANGES_REQUESTED", day(5.5)),),
            more_reviews="v1",
            files=("src/a.py",),
            more_files="f1",
            body=plan("- Files: `src/`"),
        )
        nodes = [
            first,
            agent(2, created=day(6), reviews=(review("APPROVED", day(5)),)),
            agent(3, created=day(6)),
            pull(4, day(2), reviews=(review("APPROVED", day(3)),), more_reviews="x", more_files="x"),
            agent(5, merged=day(40), created=day(41), more="x", more_reviews="x", more_files="x"),
        ]
        return ok({"pullRequests": page(nodes)})

    def pull_commits(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["number"], v["cursor"]) == (1, "c1")
        return ok({"pullRequest": {"commits": page([commit(day(5), "Address the review")])}})

    def pull_verdicts(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["number"], v["cursor"]) == (1, "v1")
        record = review("COMMENTED", day(4), oid="h2", body=RECORD, author=("Bot", "shipmill-app"), association="NONE")
        return ok({"pullRequest": {"verdicts": page([record])}})

    def pull_files(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["number"], v["cursor"]) == (1, "f1")
        return ok({"pullRequest": {"files": page([{"path": "src/b/c.py"}])}})


def test_s078_4_rework_cycles_and_first_pass_merge_rate_over_a_scripted_forge(mx: ModuleType) -> None:
    gh = ReworkForge(mx)
    d = mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=gh)
    paged = [(name, v["number"], v["cursor"]) for name, v in gh.calls if name.startswith("PULL_")]
    assert paged == [("PULL_COMMITS", 1, "c1"), ("PULL_VERDICTS", 1, "v1"), ("PULL_FILES", 1, "f1")]
    assert [(r.number, r.rounds, r.fixes, r.cycles) for r in mx.reworks(d, window(mx))] == [
        (1, 2, 1, 2),  # rounds h1 and h2, one fix commit
        (2, 1, 0, 0),
        (3, 0, 0, 0),  # no verdict, no fix
    ]
    found = by_name(mx, d)
    cycles = found["Rework cycles"]
    assert cycles.value == pytest.approx(2 / 3)
    assert cycles.extra == {"count": 3, "review_rounds": pytest.approx(1.0), "fix_commits": pytest.approx(1 / 3)}
    assert cycles.detail == "3 agent PRs: mean 1.0 review rounds, 0.3 fix commits"
    rate = found["First-pass merge rate"]
    assert (rate.value, rate.text) == (pytest.approx(2 / 3), "67%")
    assert rate.extra == {"first_pass": 2, "agent_merges": 3}
    assert rate.detail == "2 of 3 agent PRs merged with 0 rework cycles"
    assert found["Plan match"].extra == {"matched": 1, "planned": 1, "no_plan": 2}  # src/b/c.py is under src/


def test_s078_5_review_time_runs_to_the_first_verdict_and_leaves_out_prs_without_one(mx: ModuleType) -> None:
    pulls = [
        agent(
            1,
            created=day(4),
            reviews=(review("COMMENTED", day(3.9)), review("APPROVED", day(3.5)), review("APPROVED", day(2), oid="h2")),
        ),  # 12 h: a comment is no verdict
        agent(2, created=day(4), reviews=(review("CHANGES_REQUESTED", day(3)),)),  # 24 h
        agent(3, created=day(4), reviews=(review("COMMENTED", day(3)),)),  # no verdict
        agent(4, created=day(4)),  # no review
    ]
    d = data(mx, pulls=pulls)
    assert mx.review_times(d, window(mx)) == [(1, pytest.approx(12.0)), (2, pytest.approx(24.0))]
    m = by_name(mx, d)["Review time"]
    assert (m.value, m.extra) == (pytest.approx(18.0), {"p90": pytest.approx(24.0), "count": 2})
    assert m.detail == "2 agent PRs; 2 with no verdict left out"
    m = by_name(mx, data(mx, pulls=pulls[2:]))["Review time"]
    assert (m.value, m.text, m.detail) == (None, "no data", "no verdict on any of 2 agent PRs, all left out")


def test_s078_6_plan_match_reads_the_files_line_of_the_one_plan(mx: ModuleType) -> None:
    pulls = [
        agent(1, body=plan("- Files: `src/a.py`, `docs/`"), files=("src/a.py", "docs/x/y.md")),  # equal, under
        agent(
            2, body=plan("- Files: `skills/**/*.py`, `tests/test_?.py`"), files=("skills/a/b/c.py", "tests/test_x.py")
        ),
        agent(3, body=plan("- Files: `src/*.py`"), files=("src/a.py", "src/sub/b.py")),  # * doesn't cross /
        agent(4, body=plan("- Files: `src/new.py`"), files=("src/new.py",)),  # renamed: listed by its new path
        agent(5, body="Fixes #1", files=("src/a.py",)),  # no plan
        agent(6, body=plan("- Files: src/a.py"), files=("src/a.py",)),  # a Files: line with no backticked path
        agent(7, body=plan("- Files: `src/a.py`") + "\n\n" + plan("- Files: `src/a.py`"), files=("src/a.py",)),
        agent(8, body="## Plan\n\n- Serves: G-2\n\n## Summary\n\n- Files: `src/a.py`", files=("src/a.py",)),
        agent(9, body="```\n## Plan\n- Files: `src/a.py`\n```", files=("src/a.py",)),  # a fenced example
    ]
    m = by_name(mx, data(mx, pulls=pulls))["Plan match"]
    assert (m.value, m.text) == (pytest.approx(3 / 4), "75%")
    assert m.extra == {"matched": 3, "planned": 4, "no_plan": 5}
    assert m.detail == "3 of 4 planned agent PRs changed only files their plan names; 5 with no plan left out"
    m = by_name(mx, data(mx, pulls=pulls[4:]))["Plan match"]
    assert (m.value, m.detail) == (None, "no plan naming its files on any of 5 agent PRs, all left out")


# -- spec 109: decided work credited, and written as the decider -----------------------------------

APP = ("Bot", "shipmill-app")
QUESTION = "<!-- shipmill:needs-decision -->\n@amy Decision needed: which one?"
BOT_TRAILER = "Co-authored-by: shipmill-app[bot] <123+shipmill-app[bot]@users.noreply.github.com>"


def actor(who: tuple[str, str]) -> dict[str, Any]:
    return {"__typename": who[0], "login": who[1]}


def note(body: str, who: tuple[str, str] = PERSON, association: str = "MEMBER") -> dict[str, Any]:
    """A comment as DECIDED and THREAD_COMMENTS read it"""
    return {"body": body, "authorAssociation": association, "author": actor(who)}


def merge_commit(author: str | None = None, *authors: str | None, message: str = "Merge") -> dict[str, Any]:
    """A merge commit: the account its git author resolves to (None: none), and the accounts
    GitHub credits it to (None: a trailer it doesn't resolve)"""
    return {
        "message": message,
        "author": {"user": None if author is None else {"login": author}},
        "authors": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"user": None if a is None else {"login": a}} for a in authors],
        },
    }


def filed(
    number: int,
    author: tuple[str, str] = PERSON,
    association: str = "MEMBER",
    body: str = "",
    labels: tuple[str, ...] = (),
    parent: dict[str, Any] | None = None,
    repo: str = "o/r",
    comments: tuple[dict[str, Any], ...] = (),
    more: str | None = None,
) -> dict[str, Any]:
    """An issue as DECIDED's filed fragment reads it; more: a cursor to more comments"""
    return {
        "number": number,
        "repository": {"nameWithOwner": repo},
        "authorAssociation": association,
        "body": body,
        "author": actor(author),
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in labels]},
        "comments": page(list(comments), more),
        "parent": parent,
    }


def decided_node(
    author: tuple[str, str] = APP,
    comments: tuple[dict[str, Any], ...] = (),
    closes: tuple[dict[str, Any], ...] = (),
    merge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A PR as DECIDED reads it"""
    return {
        "author": actor(author),
        "mergeCommit": merge or merge_commit(),
        "comments": page(list(comments)),
        "closingIssuesReferences": {"pageInfo": {"hasNextPage": False}, "nodes": list(closes)},
    }


def thread(
    mx: ModuleType,
    number: int,
    author: tuple[str, str] = PERSON,
    association: str = "MEMBER",
    body: str = "",
    labels: tuple[str, ...] = (),
    comments: tuple[dict[str, Any], ...] = (),
    labelers: tuple[tuple[str, str], ...] = (),
) -> Any:
    return mx.Thread(
        number, actor(author), association, body, frozenset(labels), list(comments), [actor(w) for w in labelers]
    )


def decision(
    mx: ModuleType,
    reviews: tuple[dict[str, Any], ...] = (),
    comments: tuple[dict[str, Any], ...] = (),
    issues: tuple[Any, ...] = (),
    merge: dict[str, Any] | None = None,
    author: tuple[str, str] = APP,
    permissions: dict[str, str] | None = None,
) -> Any:
    return mx.Decision(actor(author), list(reviews), list(comments), list(issues), merge, dict(permissions or {}))


def approved(login: str, association: str = "MEMBER", body: str = "") -> dict[str, Any]:
    return review("APPROVED", day(2), author=("User", login), association=association, body=body)


def decided_data(mx: ModuleType, *decisions: Any, bots: frozenset[str] = frozenset()) -> Any:
    """One PR merged in the window per decision, numbered from 1"""
    pulls = [pull(n, day(1)) for n in range(1, len(decisions) + 1)]
    return data(mx, pulls=pulls, decisions=dict(enumerate(decisions, start=1)), bots=bots)


class DecidedForge(FakeGitHub):
    """Twelve PRs merged in the window, each named by one of spec 049's sources or by none, and
    #13, merged before it, whose records must not be read"""

    SOURCES: dict[int, dict[str, Any]] = {
        1: {"reviews": (approved("bob"),)},  # bob approved
        2: {"reviews": (approved("bob"), review("CHANGES_REQUESTED", day(1.5), author=("User", "bob")))},
        3: {"reviews": (approved("bob"), review("COMMENTED", day(1.5), author=("User", "bob")))},  # still approved
        4: {"comments": (note(QUESTION, APP, "NONE"), note("Option A", ("User", "amy"), "COLLABORATOR"))},
        5: {"comments": (note(f"Decision by `@amy`\n\napply\n\n{MARKER}", APP, "NONE"),)},  # the App's relay
        6: {"closes": (filed(20, ("User", "carol"), "OWNER"),)},
        7: {"closes": (filed(21, ("User", "zed"), "NONE", parent=filed(22, ("User", "dave"))),)},  # the parent's author
        8: {"closes": (filed(23, body=MARKER, labels=("opportunity", "Planned")),)},  # erin added planned
        9: {"closes": (filed(24, body=MARKER, parent=filed(25, body=MARKER, labels=("opportunity", "planned"))),)},
        10: {"closes": (filed(26, body=MARKER, labels=("opportunity", "planned")),)},  # gina can only read
        # hank answered on the issue, his reply on its comments' second page
        11: {"closes": (filed(27, body=MARKER, comments=(note(QUESTION, ("User", "olga"), "OWNER"),), more="k27"),)},
        12: {  # the App added planned, on ivy's accept
            "closes": (
                filed(
                    28,
                    body=MARKER,
                    labels=("opportunity", "planned"),
                    comments=(
                        note(f"Decision by @ivy, relayed by Claude Code\n\naccept G-2\n\n{MARKER}", APP, "NONE"),
                    ),
                ),
            )
        },
    }
    LABELED: dict[int, list[tuple[str, tuple[str, str]]]] = {
        23: [("planned", ("User", "zoe")), ("planned", ("User", "erin")), ("opportunity", ("User", "zoe"))],
        25: [("planned", ("User", "frank"))],
        26: [("planned", ("User", "gina"))],
        28: [("planned", APP)],
    }
    PERMISSIONS = {"erin": "WRITE", "frank": "ADMIN", "gina": "READ", "ivy": "MAINTAIN"}

    def __init__(self, mx: ModuleType) -> None:
        super().__init__(mx)
        self.answers[mx.DECIDED] = self.decided
        self.answers[mx.THREAD_COMMENTS] = self.thread_comments
        self.answers[mx.LABELERS] = self.labelers
        self.answers[mx.PERMISSION] = self.permission

    def pulls(self, v: dict[str, Any]) -> dict[str, Any]:
        nodes = [pull(n, day(1), reviews=s.get("reviews", ())) for n, s in self.SOURCES.items()]
        nodes.append(pull(13, day(40), reviews=(approved("bob"),), more_reviews="x"))
        return ok({"pullRequests": page(nodes)})

    def decided(self, v: dict[str, Any]) -> dict[str, Any]:
        found = {}
        for k in range(self.mx.BATCH):
            source = self.SOURCES[v[f"n{k}"]]
            found[f"p{k}"] = decided_node(comments=source.get("comments", ()), closes=source.get("closes", ()))
        return ok(found)

    def thread_comments(self, v: dict[str, Any]) -> dict[str, Any]:
        assert (v["number"], v["cursor"]) == (27, "k27")
        return ok({"thread": {"comments": page([note("Option B", ("User", "hank"))])}})

    def labelers(self, v: dict[str, Any]) -> dict[str, Any]:
        events = [{"label": {"name": name}, "actor": actor(who)} for name, who in self.LABELED[v["number"]]]
        return ok({"issue": {"timelineItems": page(events)}})

    def permission(self, v: dict[str, Any]) -> dict[str, Any]:
        return ok({"collaborators": {"edges": [{"permission": self.PERMISSIONS[v["login"]]}]}})


def test_s109_1_the_two_measures_follow_agent_share_in_the_json(mx: ModuleType) -> None:
    w = window(mx)
    one = decided_data(mx, decision(mx, reviews=(approved("bob"),)))
    keys = {"decided", "credited", "written_as_decider", "merges", "people"}
    for d, value in ((one, 0.0), (data(mx), None), (decided_data(mx, decision(mx)), None)):
        found = json.loads(mx.render("o/r", 30, w, mx.measures(d, w), "json"))["measures"]
        names = [m["measure"] for m in found]
        share = names.index("Agent share")
        assert names[share + 1 : share + 3] == DECIDED
        for m in found[share + 1 : share + 3]:
            assert m["unit"] == "ratio", m["measure"]
            assert set(m) >= keys | {"value"}, m["measure"]
            assert m["value"] == value, m["measure"]
            if value is None:
                assert m["text"] == "no data"
                assert by_name(mx, d)[m["measure"]].detail == "no decided PR merged in the window"


def test_s109_2_a_merge_is_decided_exactly_when_spec_049_names_a_decider(mx: ModuleType) -> None:
    d = mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=DecidedForge(mx), decided=True)
    merges, found = mx.decided_merges(d, window(mx))
    assert merges == 12
    assert {f.number: f.people for f in found} == {
        1: ["bob"],  # an approver whose latest review is APPROVED
        3: ["bob"],  # a later comment leaves the approval standing
        4: ["amy"],  # a trusted reply to a needs-decision question
        5: ["amy"],  # a bot's Decision by relay, its agent marker notwithstanding
        6: ["carol"],  # the trusted author of an issue it closes
        7: ["dave"],  # the trusted author of that issue's parent
        8: ["erin"],  # who added planned last, with write permission
        9: ["frank"],  # the same on the parent, with admin
        11: ["hank"],  # an answer on the issue it closes
        12: ["ivy"],  # the App added planned on ivy's relayed accept (D-115), ivy can maintain
    }
    m = by_name(mx, d)["Decided work credited"]
    assert (m.extra["merges"], m.extra["decided"]) == (12, 10)
    assert m.detail == "0 of 10 decided merges credited to every decider; 12 merged, 2 with no decider"


def test_s109_3_bots_outsiders_the_author_and_marked_records_name_no_decider(mx: ModuleType) -> None:
    bots = frozenset({"release-robot"})
    alone = [
        decision(mx, reviews=(review("APPROVED", day(2), author=("Bot", "copilot")),)),  # a Bot
        decision(mx, reviews=(approved("renovate[bot]"),)),  # a [bot] login
        decision(mx, reviews=(approved("release-robot"),)),  # a --bot login
        decision(mx, reviews=(approved("zed", "CONTRIBUTOR"),)),  # an outsider (D-16)
        decision(mx, reviews=(approved("alice"),), author=PERSON),  # the PR's author
        decision(mx, reviews=(approved("bob", body=f"LGTM\n\n{MARKER}"),)),  # an agent's approval
        decision(mx, issues=(thread(mx, 20, ("User", "carol"), "OWNER", body=f"Filed\n\n{MARKER}"),)),
        decision(mx, issues=(thread(mx, 21, ("Bot", "shipmill-app")),)),  # a Bot filed it
        decision(mx, issues=(thread(mx, 22, ("User", "zed"), "NONE"),)),  # an outsider filed it
        decision(mx, comments=(note(QUESTION, APP, "NONE"), note(f"Option A\n\n{MARKER}", ("User", "amy")))),
        decision(mx, comments=(note(QUESTION, APP, "NONE"), note("Option A", ("User", "zed"), "NONE"))),
        decision(mx, comments=(note("Option A", ("User", "amy")),)),  # no question asked
        decision(mx, comments=(note("Decision by @amy", ("User", "olga"), "OWNER"),)),  # a person's line, no relay
        decision(mx, comments=(note("Decision by @alice", APP, "NONE"),), author=PERSON),  # relays the author
        decision(mx, comments=(note("Decision by @release-robot", APP, "NONE"),)),  # relays a --bot login
        decision(
            mx,
            issues=(thread(mx, 23, body=MARKER, labels=("opportunity", "planned"), labelers=(APP,)),),
        ),  # the App added planned with no relay of an accept
    ]
    for one in alone:
        assert mx.deciders(one, bots) == [], one
    d = decided_data(mx, *alone, bots=bots)
    merges, found = mx.decided_merges(d, window(mx))
    assert (merges, found) == (len(alone), [])
    m = by_name(mx, d)["Decided work credited"]
    assert (m.value, m.extra["merges"], m.extra["decided"]) == (None, len(alone), 0)
    # the marker mid-line is a person's quote: carol's filing still decides
    quoted = decision(mx, issues=(thread(mx, 24, ("User", "carol"), "OWNER", body=f"quoting {MARKER} mid-line"),))
    assert mx.deciders(quoted, bots) == ["carol"]


def test_s109_4_credited_only_when_every_decider_is_among_the_merge_commits_authors(mx: ModuleType) -> None:
    bob, carol = (approved("bob"),), (thread(mx, 20, ("User", "carol"), "OWNER"),)
    d = decided_data(
        mx,
        decision(mx, bob, issues=carol, merge=merge_commit("alice", "alice", "bob", "carol")),  # credited
        decision(mx, bob, issues=carol, merge=merge_commit("alice", "Bob", "CAROL")),  # logins read without case
        decision(mx, bob, issues=carol, merge=merge_commit("alice", "alice", "bob", None)),  # carol's: no account
        decision(mx, bob, merge=merge_commit("alice", "alice")),  # bob not named at all
        decision(mx),  # no decider
    )
    m = by_name(mx, d)["Decided work credited"]
    assert (m.value, m.text) == (pytest.approx(0.5), "50%")
    assert (m.extra["credited"], m.extra["decided"], m.extra["merges"]) == (2, 4, 5)
    assert m.detail == "2 of 4 decided merges credited to every decider; 5 merged, 1 with no decider"


def test_s109_5_written_as_the_decider_needs_their_git_author_and_an_agent_co_author(mx: ModuleType) -> None:
    bob = (approved("bob"),)
    person = "Co-authored-by: Bob <1+bob@users.noreply.github.com>"
    d = decided_data(
        mx,
        decision(mx, bob, merge=merge_commit("bob", "bob", message=f"Fix\n\n{BOT_TRAILER}")),  # written
        decision(mx, bob, merge=merge_commit("bob", "bob", message="Fix")),  # bob's own merge
        decision(mx, bob, merge=merge_commit(None, "bob", message=f"Fix\n\n{person}")),  # the App's, bob co-author
        decision(mx, bob, merge=merge_commit("bob", "bob", message=f"Fix\n\n{person}")),  # a person co-author
        decision(mx, bob, merge=merge_commit("dave", "dave", message=f"Fix\n\n{BOT_TRAILER}")),  # not a decider
    )
    m = by_name(mx, d)["Decided work written as the decider"]
    assert (m.value, m.text) == (pytest.approx(0.2), "20%")
    assert (m.extra["written_as_decider"], m.extra["decided"]) == (1, 5)
    assert m.detail == "1 of 5 decided merges written as the decider with the agent as co-author"


def test_s109_6_people_counts_each_deciders_prs_and_only_the_json_names_them(mx: ModuleType) -> None:
    both = merge_commit("bob-q", "bob-q", "amy-k", message=f"Fix\n\n{BOT_TRAILER}")
    d = decided_data(
        mx,
        decision(mx, reviews=(approved("bob-q"), approved("amy-k")), merge=both),
        decision(mx, reviews=(approved("bob-q"),), merge=merge_commit("alice", "alice")),
        decision(mx, issues=(thread(mx, 20, ("User", "Carol-z"), "OWNER"),)),
    )
    w = window(mx)
    found = mx.measures(d, w)
    for m in (by_name(mx, d)[name] for name in DECIDED):
        assert m.extra["people"] == [
            {"login": "amy-k", "decided": 1, "credited": 1, "written_as_decider": 1},
            {"login": "bob-q", "decided": 2, "credited": 1, "written_as_decider": 1},
            {"login": "Carol-z", "decided": 1, "credited": 0, "written_as_decider": 0},
        ]
    for form in ("table", "markdown"):
        text = mx.render("o/r", 30, w, found, form)
        for login in ("amy-k", "bob-q", "Carol-z"):
            assert login not in text, (form, login)
    assert "Carol-z" in mx.render("o/r", 30, w, found, "json")


def test_s109_pulls_lists_each_decided_merge_by_number_with_its_sha_and_both_reads(mx: ModuleType) -> None:
    """#1875: the JSON names the decided merges it counted, so a checker can compare them with GitHub"""
    bob = (approved("bob"),)
    no_sha = pull(4, day(1))
    no_sha["mergeCommit"] = None
    d = data(
        mx,
        pulls=[pull(9, day(1), merge="c9"), no_sha, pull(7, day(1), merge="c7"), pull(2, day(1), merge="c2")],
        decisions={
            9: decision(mx, bob, merge=merge_commit("bob", "bob", message=f"Fix\n\n{BOT_TRAILER}")),  # both
            4: decision(mx, bob, merge=merge_commit("alice", "bob")),  # credited, no merge commit read
            7: decision(mx),  # no decider: not listed
            2: decision(mx, bob, merge=merge_commit("alice", "alice")),  # neither
        },
    )
    w = window(mx)
    found = mx.measures(d, w)
    pulls = [
        {"number": 2, "sha": "c2", "credited": False, "written_as_decider": False},
        {"number": 4, "sha": None, "credited": True, "written_as_decider": False},
        {"number": 9, "sha": "c9", "credited": True, "written_as_decider": True},
    ]
    measured = {m["measure"]: m for m in json.loads(mx.render("o/r", 30, w, found, "json"))["measures"]}
    for name in DECIDED:
        assert measured[name]["pulls"] == pulls, name
        assert (measured[name]["merges"], measured[name]["decided"]) == (4, 3), name
    for form in ("table", "markdown"):
        text = mx.render("o/r", 30, w, found, form)
        assert "pulls" not in text and "c9" not in text, form
    empty = json.loads(mx.render("o/r", 30, w, mx.measures(decided_data(mx, decision(mx)), w), "json"))
    assert [m["pulls"] for m in empty["measures"] if m["measure"] in DECIDED] == [[], []]


def test_s109_7_the_records_are_read_only_for_prs_merged_in_the_window(mx: ModuleType) -> None:
    gh = DecidedForge(mx)
    mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=gh, decided=True)

    def read(query: str, key: str = "number") -> list[Any]:
        return [v[key] for name, v in gh.calls if name == query]

    batches = [[v[f"n{k}"] for k in range(mx.BATCH)] for name, v in gh.calls if name == "DECIDED"]
    # ten PRs to a read, the last batch filled with its last PR; not #13, merged before the window
    assert batches == [list(range(1, 11)), [11, 12, *[12] * (mx.BATCH - 2)]]
    assert read("PULL_VERDICTS") == []  # #13's further reviews aren't read
    assert read("THREAD_COMMENTS") == [27]  # only a thread with more comments than its first page
    assert read("LABELERS") == [23, 25, 26, 28]  # only the opportunities labelled planned
    assert read("PERMISSION", "login") == ["erin", "frank", "gina", "ivy"]
    # trends.py's read, which measures neither, reads none of them
    quiet = DecidedForge(mx)
    d = mx.fetch("o/r", window(mx), frozenset(), "incident", "release-blocker", run=quiet)
    assert not {"DECIDED", "THREAD_COMMENTS", "LABELERS", "PERMISSION"} & {name for name, _ in quiet.calls}
    assert d.decisions == {}


# proves: S-109-7
def test_metrics_reads_github_only_through_gh_and_its_run_reads_the_deciders(mx: ModuleType) -> None:
    source = SCRIPT.read_text()
    assert source.count("subprocess.run(") == 1
    assert 'cmd = ["gh", "api", "graphql"' in source
    assert source.count("decided=True)") == 1  # main's fetch


def test_spec_109_reads_deciders_as_credit_and_triage_state_do(mx: ModuleType) -> None:
    from shipmill import agent_marker, credit

    path = SCRIPT.parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
    spec = importlib.util.spec_from_file_location("triage_state_for_metrics", path)
    assert spec is not None and spec.loader is not None
    triage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = triage
    spec.loader.exec_module(triage)
    assert mx.DECISION_BY.pattern == triage.DECISION_BY.pattern
    assert mx.NEEDS_DECISION == credit.MARKER
    assert mx.TRUSTED == credit.TRUSTED
    assert mx.WRITERS == credit.WRITERS
    assert (mx.OPPORTUNITY, mx.PLANNED) == (credit.OPPORTUNITY, credit.PLANNED)
    assert mx.NO_STATE == credit._NO_STATE
    assert mx.TRAILER_EMAIL.pattern == credit._TRAILER_EMAIL.pattern
    assert mx.AGENT_MARKER.pattern == agent_marker._LINE.pattern
