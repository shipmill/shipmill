"""Spec 022: `shipmill milestones` prints MILESTONE_WAITING while a goal's milestone, its
issues closed, waits on its specs, and MILESTONE_OVERTAKEN once a stable tag took an open
milestone's version, naming the version the lane cuts next; watch_state.py reads it, and
`shipmill status` reads watch_state.py (#475)"""

import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import status as shipmill_status
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import Milestone, OpenMilestone, parse_open_milestones
from shipmill.policy import Lane
from shipmill.status import MilestoneRow, Row, Verdict, read_milestones, report

from .conftest import Repo, Repos, at_day
from .test_lanes import plan, release
from .test_milestones import closed, in_milestone, land_on_main, milestone_policy, plan_stable, rc_cut, spec
from .test_status_picture import facts, lines

WATCH_STATE = Path(__file__).resolve().parents[1] / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"


def read(repo: Repo, now: dt.datetime) -> tuple[list[MilestoneRow], str | None]:
    """The read `shipmill milestones` makes once it fetched the default branch"""
    repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
    head = repo.git.sha("origin/main")
    return read_milestones("o/demo", repo.root, head, repo.github, now, "shipmill")


def watch_state() -> ModuleType:
    spec_ = importlib.util.spec_from_file_location("watch_state", WATCH_STATE)
    assert spec_ is not None and spec_.loader is not None
    module = importlib.util.module_from_spec(spec_)
    sys.modules[spec_.name] = module  # dataclasses look their module up by name
    spec_.loader.exec_module(module)
    return module


def on_github(repo: Repo) -> None:
    """origin's URL names o/demo on GitHub, as the CLI reads it, while git fetches from a
    local bare copy of the origin"""
    origin = Path(repo.git.run("remote", "get-url", "origin").strip())
    copy = origin.parent / "github.com" / "o" / "demo.git"
    repo.git.run("clone", "-q", "--bare", str(origin), str(copy))
    repo.git.run("remote", "set-url", "origin", str(copy))


def milestones(repo: Repo, now: dt.datetime, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    """`shipmill milestones`'s output in the repo's checkout"""
    capsys.readouterr()
    argv = ["--repo", str(repo.root), "milestones", "--now", now.isoformat(), *flags]
    assert main(argv, github=repo.github) == 0
    return capsys.readouterr().out


def test_s022_8_a_milestone_whose_goal_isnt_built_reads_waiting_with_its_reasons(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(
        tmp_path, rc_cut, {"021-goal.md": spec(21, "approved", "#11"), "023-other.md": spec(23, "built", "#12")}
    )
    in_milestone(repo, (11, "Build A"), (12, "Build B"))
    repo.github.closes[12] = closed(12)
    rows, error = read(repo, at_day(5))
    reasons = (
        "milestone 1.1.0: S-021 is approved, not built; milestone 1.1.0: S-023's #12 closed with no merged pull request"
    )
    assert (rows, error) == ([MilestoneRow("MILESTONE_WAITING", "1.1.0", reasons)], None)
    found = facts(*(r.row() for r in rows))
    assert f"  milestone      MILESTONE_WAITING {reasons}" in lines(found)
    assert report(found).verdict is Verdict.IDLE  # the build work is the factory's, not a reason


def test_s022_8_a_fix_after_the_rc_names_the_rc(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "built", "#11")})
    late = repo.merge(2, "Fixed", "Fix B, after the rc")
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, late)
    rows, _ = read(repo, at_day(5))
    assert rows == [MilestoneRow("MILESTONE_WAITING", "1.1.0", "milestone 1.1.0: S-021's #11 is not in v1.1.0rc1")]


def test_s022_8_no_row_while_the_milestone_has_open_issues_or_its_goal_is_done(repos: Repos, tmp_path: Path) -> None:
    repo, fix = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "approved", "#11")})
    repo.github.milestones["1.1.0"] = Milestone(1, 1)  # the ordinary wait
    assert read(repo, at_day(5)) == ([], None)
    in_milestone(repo, (11, "Build A"))
    land_on_main(repo, "built", {"docs/specs/021-goal.md": spec(21, "built", "#11")})
    repo.github.closes[11] = closed(11, fix)
    assert read(repo, at_day(5)) == ([], None)
    assert plan_stable(repo).lane is Lane.STABLE  # done: the plan is due by it


def test_s022_8_no_row_and_nothing_read_without_a_milestone_or_a_milestone_lane(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "approved", "#11")})
    assert read(repo, at_day(5)) == ([], None)  # no milestone named 1.1.0, none open
    assert repo.github.milestone_reads == []
    milestone_policy_off(repo)
    repo.github.milestone_error = "no read is made without a lane that sets milestone = true"
    in_milestone(repo, (11, "Build A"))
    repo.github.open = [OpenMilestone(3, "1.0.0", 1)]
    reads = repo.github.open_reads
    assert read(repo, at_day(5)) == ([], None)
    assert repo.github.open_reads == reads


def milestone_policy_off(repo: Repo) -> None:
    text = repo.read(repo.policy_file)
    land_on_main(repo, "no milestone", {repo.policy_file: text.replace("milestone = true\n", "")})


def test_a_goal_the_plan_cant_read_is_shown_not_dropped(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#475: `shipmill milestones` prints the error, and watch_state.py warns with it on
    stderr, with no row"""
    repo, _ = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "built", "#99")})
    in_milestone(repo, (99, "Build"))  # #99 isn't on GitHub
    rows, error = read(repo, at_day(5))
    assert rows == [] and error is not None and "Could not resolve" in error
    on_github(repo)
    printed = milestones(repo, at_day(5), capsys, "--json")
    assert json.loads(printed) == {"milestones": [], "error": error}
    assert f"not read: {error}" in milestones(repo, at_day(5), capsys)
    assert watch_state().milestone_rows(printed) == []
    warned = capsys.readouterr().err
    assert warned.startswith("warning: shipmill milestones: not read: ") and "Could not resolve" in warned


def stable_released(repo: Repo) -> None:
    """1.1.0 released on the stable lane's schedule, then the milestone lane set, with a fix
    pending on main"""
    repo.merge(1, "Added", "Feature A", "src/a.py", "A = 1\n")
    release(repo, plan(repo, at_day(1)))  # 1.1.0rc1
    release(repo, plan(repo, at_day(5)))  # 1.1.0, by the Monday window
    assert repo.git.ok("rev-parse", "-q", "--verify", "refs/tags/v1.1.0")
    milestone_policy(repo)
    repo.merge(2, "Fixed", "Fix B")


def test_s022_10_an_open_milestone_a_stable_tag_took_reads_overtaken_with_the_next_version(
    repos: Repos, tmp_path: Path
) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.2.0", 1), OpenMilestone(5, "Someday", 1)]
    rows, error = read(repo, at_day(6))
    rename = "gh api -X PATCH repos/o/demo/milestones/3 -f title=1.1.1"  # no app_id: plain gh (S-037-12)
    detail = "v1.1.0 exists; the stable lane cuts 1.1.1 next"
    assert (rows, error) == ([MilestoneRow("MILESTONE_OVERTAKEN", "1.1.0", detail, 3, "1.1.1", rename)], None)
    found = report(facts(*(r.row() for r in rows)))
    assert found.verdict is Verdict.WAITS
    text = lines(facts(*(r.row() for r in rows)))
    assert "  milestone      MILESTONE_OVERTAKEN 1.1.0: v1.1.0 exists; the stable lane cuts 1.1.1 next" in text
    assert f"                 fix: {rename}" in text


def test_s037_12_the_rename_goes_through_shipmill_gh_only_with_app_id_set(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]
    config = repo.root / ".github" / "shipmill.toml"
    config.write_text(config.read_text(encoding="utf-8") + '\n[agents]\nprompt = "/t"\napp_id = 7\n', encoding="utf-8")
    rows, _ = read(repo, at_day(6))
    assert [r.fix for r in rows] == ["shipmill gh api -X PATCH repos/o/demo/milestones/3 -f title=1.1.1"]


def test_s022_10_the_next_version_is_the_lanes_candidate(repos: Repos, tmp_path: Path) -> None:
    """With an rc to promote, the stable lane cuts that rc's version next"""
    repo, _ = repos.after(tmp_path, stable_released)
    repo.merge(3, "Added", "Feature C")
    release(repo, plan(repo, at_day(6)))  # 1.2.0rc1
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]
    rows, _ = read(repo, at_day(10))
    assert [r.detail for r in rows] == ["v1.1.0 exists; the stable lane cuts 1.2.0 next"]


def test_s022_10_no_row_while_no_stable_tag_took_an_open_milestone(repos: Repos, tmp_path: Path) -> None:
    repo, _ = repos.after(tmp_path, rc_cut)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.0.0rc1", 1), OpenMilestone(5, "v1.0.0", 1)]
    assert read(repo, at_day(2)) == ([], None)


def test_s022_10_a_milestone_its_own_release_shipped_is_not_overtaken(repos: Repos, tmp_path: Path) -> None:
    """GitHub leaves a milestone open after its version ships: with no open issues, the tag
    shipped its goal rather than took it, so there is nothing to rename"""
    repo, fix = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "built", "#11")})
    in_milestone(repo, (11, "Build A"))
    repo.github.closes[11] = closed(11, fix)
    release(repo, plan_stable(repo))  # 1.1.0, due by its milestone
    assert repo.git.ok("rev-parse", "-q", "--verify", "refs/tags/v1.1.0")
    repo.merge(2, "Fixed", "Fix B")
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    assert read(repo, at_day(6)) == ([], None)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]  # an issue still open: taken before done
    rows, _ = read(repo, at_day(6))
    assert [r.state for r in rows] == ["MILESTONE_OVERTAKEN"]


def test_s022_10_a_milestone_never_changes_the_bump(repos: Repos, tmp_path: Path) -> None:
    """The plan reads no open milestone, and an overtaken 1.1.0 and a closed 1.2.0 leave the
    fix pending a patch: the rc is 1.1.1rc1, and stable promotes it as 1.1.1"""
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.2.0", 1)]
    repo.github.milestones["1.2.0"] = Milestone(0, 2)
    rc = plan(repo, at_day(6))
    assert (rc.lane, str(rc.version)) == (Lane.RC, "1.1.1rc1"), rc.reason
    release(repo, rc)
    repo.github.milestones["1.1.1"] = Milestone(0, 1)
    stable = plan(repo, at_day(10))
    assert (stable.lane, str(stable.version)) == (Lane.STABLE, "1.1.1"), stable.reason
    assert repo.github.open_reads == 0


def test_s022_10_shipmill_milestones_prints_the_overtaken_row_and_the_watch_reads_it(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#475: the row's milestone, number, next version, and the rename through `shipmill gh`;
    watch_state.py makes it an action with the rename as its fix, never an agent's"""
    repo, _ = repos.after(tmp_path, stable_released)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1)]
    on_github(repo)
    repo.git.run("push", "-q", "origin", "+HEAD:refs/tags/v0")  # a moving major tag, moved on origin
    repo.git.run("tag", "-f", "v0", "HEAD~1")
    printed = milestones(repo, at_day(6), capsys, "--json")
    rename = "gh api -X PATCH repos/o/demo/milestones/3 -f title=1.1.1"  # no app_id (S-037-12)
    detail = "v1.1.0 exists; the stable lane cuts 1.1.1 next"
    row = {"state": "MILESTONE_OVERTAKEN", "milestone": "1.1.0", "detail": detail}
    assert json.loads(printed) == {"milestones": [row | {"number": 3, "next": "1.1.1", "fix": rename}], "error": None}
    assert milestones(repo, at_day(6), capsys) == f"MILESTONE_OVERTAKEN 1.1.0: {detail}\n  fix: {rename}\n"
    ws = watch_state()
    (found,) = ws.milestone_rows(printed)
    assert found.json() == {"state": "MILESTONE_OVERTAKEN", "subject": "1.1.0", "detail": detail} | {
        "agent": False,
        "fix": rename,
    }
    assert found.text().endswith(f"\n{ws.FIX_INDENT}fix: {rename}")
    assert "MILESTONE_OVERTAKEN" in ws.ACTION and "MILESTONE_OVERTAKEN" not in ws.AGENT


def test_s022_8_the_watch_reads_a_waiting_milestone_from_shipmill_milestones(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = repos.after(tmp_path, rc_cut, {"021-goal.md": spec(21, "approved", "#11")})
    in_milestone(repo, (11, "Build A"))
    on_github(repo)
    printed = milestones(repo, at_day(5), capsys, "--json")
    ws = watch_state()
    (found,) = ws.milestone_rows(printed)
    reason = "milestone 1.1.0: S-021 is approved, not built"
    assert found.json() == {"state": "MILESTONE_WAITING", "subject": "1.1.0", "detail": reason} | {
        "agent": False,
        "fix": None,
    }
    assert "MILESTONE_WAITING" not in ws.ACTION | ws.AGENT  # report only
    status_row = shipmill_status.parse_rows(json.dumps(found.json()))
    assert status_row == [Row("MILESTONE_WAITING", "1.1.0", reason, False)]  # the summary reads it as before


def test_s022_8_without_a_milestone_lane_nothing_is_run_or_read(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """#475: no lane sets milestone = true: the watch runs no `shipmill milestones`, and the
    command itself reads no milestone"""
    on_github(repo)
    assert json.loads(milestones(repo, at_day(5), capsys, "--json")) == {"milestones": [], "error": None}
    assert milestones(repo, at_day(5), capsys) == "no milestone waits or was overtaken\n"
    assert repo.github.milestone_reads == [] and repo.github.open_reads == 0
    ran: list[list[str]] = []

    def execute(cmd: list[str]) -> str:
        ran.append(cmd)
        return json.dumps({"milestones": [], "error": None})

    ws = watch_state()
    policy = Path(repo.policy_file)
    assert ws.milestones(repo.root, policy, "TOOL", execute) == []
    assert ran == []
    milestone_policy(repo)
    assert ws.milestones(repo.root, policy, "TOOL", execute) == []
    assert ran == [["uvx", "--from", "TOOL", "shipmill", "--repo", str(repo.root), "milestones", "--json"]]


WAITING = {"state": "MILESTONE_WAITING", "milestone": "1.1.0", "detail": "d", "number": None, "next": None, "fix": None}
OVERTAKEN = WAITING | {"state": "MILESTONE_OVERTAKEN", "number": 3, "next": "1.1.1", "fix": "rename"}


def printed(*rows: Mapping[str, object], error: str | None = None) -> str:
    return json.dumps({"milestones": list(rows), "error": error})


MALFORMED = [
    "not json",
    "[]",
    json.dumps({"milestones": []}),
    printed(error=""),
    json.dumps({"milestones": {}, "error": None}),
    printed({"state": "MILESTONE_WAITING"}),
    printed(WAITING | {"state": "OTHER"}),
    printed(WAITING | {"milestone": ""}),
    printed(WAITING | {"fix": "f"}),  # a waiting row with a fix
    printed(OVERTAKEN | {"number": None, "next": None, "fix": None}),  # an overtaken row without them
    printed(OVERTAKEN | {"number": True}),
    printed(OVERTAKEN | {"fix": ""}),
    printed(WAITING, error="boom"),  # rows and an error
]


def test_the_malformed_cases_differ_from_a_readable_report() -> None:
    assert [r.state for r in watch_state().milestone_rows(printed(WAITING, OVERTAKEN))] == [
        "MILESTONE_WAITING",
        "MILESTONE_OVERTAKEN",
    ]


@pytest.mark.parametrize("text", MALFORMED)
def test_a_milestones_report_the_watch_cannot_read_stops_it(text: str) -> None:
    with pytest.raises(SystemExit) as refused:
        watch_state().milestone_rows(text)
    assert refused.value.code == 2


@pytest.mark.parametrize(
    ("config", "wanted"),
    [
        ("", False),
        ("[lanes.stable]\nquiet_minutes = 30\n", False),
        ("[lanes.stable]\nmilestone = false\n", False),
        ("[lanes.rc]\nquiet_minutes = 30\n\n[lanes.stable]\nmilestone = true  # by the goal\n", True),
    ],
)
def test_the_watch_reads_a_milestone_lane_on_311_and_310(config: str, wanted: bool) -> None:
    ws = watch_state()
    policy = Path(".github/shipmill.toml")
    assert ws.milestone_lanes(config, policy) is wanted
    assert ws.milestone_lanes_310(config, policy) is wanted


@pytest.mark.parametrize(
    "config",
    [
        '[lanes.stable]\nmilestone = "yes"\n',
        "lanes = 1\n",
    ],
)
def test_the_watch_refuses_a_lanes_table_it_cannot_read(config: str) -> None:
    ws = watch_state()
    policy = Path(".github/shipmill.toml")
    for read_lanes in (ws.milestone_lanes, ws.milestone_lanes_310):
        with pytest.raises(SystemExit) as refused:
            read_lanes(config, policy)
        assert refused.value.code == 2


def test_python_310_refuses_a_lanes_form_it_cannot_read_rather_than_miss_a_milestone() -> None:
    ws = watch_state()
    policy, config = Path(".github/shipmill.toml"), "[lanes]\nstable = { milestone = true }\n"
    assert ws.milestone_lanes(config, policy) is True
    with pytest.raises(SystemExit) as refused:
        ws.milestone_lanes_310(config, policy)
    assert refused.value.code == 2


def test_parse_open_milestones_is_strict() -> None:
    found = parse_open_milestones(
        [
            {"number": 4, "title": "1.2.0", "state": "open", "open_issues": 2},
            {"number": 3, "title": "x", "state": "open", "open_issues": 0},
        ]
    )
    assert found == [OpenMilestone(3, "x", 0), OpenMilestone(4, "1.2.0", 2)]
    bad_answers: list[object] = [
        {},
        [{"number": "3", "title": "x", "state": "open", "open_issues": 0}],
        [{"number": 3, "title": "x", "state": "closed", "open_issues": 0}],
        [{"number": 3, "title": "x", "state": "open"}],
        [{"number": 3, "title": "x", "state": "open", "open_issues": True}],
    ]
    for bad in bad_answers:
        with pytest.raises(ReleaseError):
            parse_open_milestones(bad)
    with pytest.raises(ReleaseError, match="100 open milestones or more"):
        parse_open_milestones([{"number": n, "title": str(n), "state": "open"} for n in range(100)])
