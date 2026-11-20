"""Spec 068, D-95: after a stable release X by a lane with close_milestone = true, land.yml's
milestone job (`shipmill close-milestone`, after the land job) closes the open milestone titled
X, first moving its open issues to the open milestone titled the lowest stable version above X;
with open issues and none above it writes nothing. A pre-release, a lane without the key, or no
milestone titled X reads and writes no milestone. A write that fails fails the milestone job
after the tag and the publish, naming the command. The land job itself touches no milestone:
its own permissions grant no `issues`, while the milestone job takes the caller's grant"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import MilestoneIssues, OpenIssue, OpenMilestone
from shipmill.land import Landed, Rollover, close_milestone, land, prepare
from shipmill.policy import Lane
from shipmill.version import Version

from .conftest import FakeGitHub, Repo, Repos, at_day
from .test_milestone_status import read

STABLE_TRIGGER = 'schedule = ["Mon 07:00 UTC"]\n'
RC_RULE = '[lanes.rc]\nschedule = ["daily 07:00 UTC"]\n'
CLOSING = "milestone = true\nclose_milestone = true\n"
GH = f"{cli_command()} gh"  # #236: the hint names the CLI as a person can run it
DAY = at_day(1).date()
LAND_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "land.yml"


def merged(repo: Repo, close: bool = True) -> None:
    """The stable and rc lanes on milestones, closing them when close, and #1 merged on main"""
    rule = CLOSING if close else "milestone = true\n"
    text = repo.read(repo.policy_file).replace(STABLE_TRIGGER, rule).replace(RC_RULE, f"{RC_RULE}{rule}")
    repo.write(repo.policy_file, text)
    repo.git.run("commit", "-qam", "Lanes on milestones")
    repo.git.run("push", "-q", "origin", "main")
    repo.merge(1, "Added", "Feature A", "src/a.py", "A = 1\n")


def setup(repos: Repos, tmp_path: Path, close: bool = True) -> Repo:
    repo, _ = repos.after(tmp_path, merged, close)
    return repo


def prepared(repo: Repo, lane: Lane, version: str) -> tuple[Version, str, str]:
    """The release commit of version on main's head, pushed to its work branch: the version,
    the commit, and its base"""
    repo.git.fetch("+refs/heads/main:refs/remotes/origin/main")
    base = repo.git.sha("origin/main")
    v = Version.parse(version)
    done = prepare(repo.git, repo.policy, lane, v, base, DAY, commit=True, push=True)
    return v, done.sha, base


def land_as(repo: Repo, lane: Lane = Lane.STABLE, version: str = "1.1.0") -> Landed:
    policy = repo.policy
    v, sha, base = prepared(repo, lane, version)
    return land(repo.git, policy, repo.github, lane, v, sha, base, DAY)


def rolled(repo: Repo, lane: Lane = Lane.STABLE, version: str = "1.1.0") -> Rollover:
    """The release landed, then the milestone job's rollover of it"""
    land_as(repo, lane, version)
    return close_milestone(repo.policy, repo.github, lane, Version.parse(version))


def holding(repo: Repo, title: str, *open_issues: int, closed: tuple[int, ...] = ()) -> None:
    """The milestone's issues as GitHub lists them: open ones, and closed ones by number"""
    issues = tuple((n, "") for n in sorted((*open_issues, *closed)))
    listed = tuple(OpenIssue(n, f"Issue {n}", frozenset()) for n in open_issues)
    repo.github.milestone_lists[title] = MilestoneIssues("o/demo", issues, listed)


def test_s068_2_an_empty_milestone_is_closed_and_the_summary_says_so(repos: Repos, tmp_path: Path) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0), OpenMilestone(4, "1.2.0", 2)]
    done = rolled(repo)
    assert repo.git.remote_tag("v1.1.0") and repo.github.releases[-1][0] == "v1.1.0"
    assert repo.github.milestone_writes == [("close", 3)]
    assert done == Rollover("milestone 1.1.0 closed")
    assert repo.github.milestone_reads == []  # no open issue: none read


def test_s068_2_shipmill_close_milestone_prints_the_summary_line(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """land.yml's milestone job tees its stdout into the Release run's summary"""
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    land_as(repo)
    capsys.readouterr()
    argv = ["--repo", str(repo.root), "close-milestone", "--lane", "stable", "--version", "1.1.0"]
    assert main(argv, github=repo.github) == 0
    assert capsys.readouterr().out == "milestone 1.1.0 closed\n"
    assert repo.github.milestone_writes == [("close", 3)]


def test_s068_3_open_issues_move_to_the_lowest_stable_version_above_then_x_closes(repos: Repos, tmp_path: Path) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [
        OpenMilestone(3, "1.1.0", 2),
        OpenMilestone(4, "2.0.0", 0),
        OpenMilestone(5, "1.2.0", 1),
        OpenMilestone(6, "1.1.1rc1", 0),  # no stable version
        OpenMilestone(7, "Someday", 0),
        OpenMilestone(8, "1.0.9", 0),  # below X
    ]
    holding(repo, "1.1.0", 12, 14, closed=(11,))
    done = rolled(repo)
    # each open issue to 1.2.0, then X closed; #11, closed, is never written, so it stays in X
    assert repo.github.milestone_writes == [("#12", 5), ("#14", 5), ("close", 3)]
    assert done == Rollover("milestone 1.1.0 closed; #12, #14 moved to 1.2.0")


def test_s068_4_open_issues_and_no_milestone_above_write_nothing_and_read_overtaken(
    repos: Repos, tmp_path: Path
) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(4, "1.0.9", 0), OpenMilestone(5, "Later", 0)]
    holding(repo, "1.1.0", 12)
    done = rolled(repo)
    assert repo.github.milestone_writes == []
    assert done.failed == ""
    assert done.said.startswith("milestone 1.1.0 left open: it has open issues")
    rows, error = read(repo, at_day(2))
    assert error is None
    (overtaken,) = [r for r in rows if r.state == "MILESTONE_OVERTAKEN"]
    assert (overtaken.milestone, overtaken.number) == ("1.1.0", 3)
    assert overtaken.detail.startswith("v1.1.0 exists; the stable lane cuts ")


def test_s068_5_a_pre_release_reads_and_writes_no_milestone(repos: Repos, tmp_path: Path) -> None:
    repo = setup(repos, tmp_path)
    repo.github.milestone_error = "a pre-release reads no milestone"
    repo.github.open = [OpenMilestone(3, "1.1.0", 0), OpenMilestone(4, "1.1.0rc1", 0)]
    done = rolled(repo, Lane.RC, "1.1.0rc1")
    assert repo.git.remote_tag("v1.1.0rc1")
    assert (repo.github.open_reads, repo.github.milestone_reads, repo.github.milestone_writes) == (0, [], [])
    assert done == Rollover()


def test_s068_5_a_lane_without_close_milestone_reads_and_writes_no_milestone(repos: Repos, tmp_path: Path) -> None:
    repo = setup(repos, tmp_path, close=False)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    done = rolled(repo)
    assert repo.git.remote_tag("v1.1.0")
    assert (repo.github.open_reads, repo.github.milestone_reads, repo.github.milestone_writes) == (0, [], [])
    assert done == Rollover()


class Unreachable(FakeGitHub):
    """GitHub that fails every milestone call, as a token without `issues` would"""

    def open_milestones(self) -> list[OpenMilestone]:
        raise AssertionError("read a milestone")

    def milestone_issues(self, title: str) -> MilestoneIssues:
        raise AssertionError("read a milestone's issues")


@pytest.mark.parametrize(("close", "lane", "version"), [(False, "stable", "1.1.0"), (True, "rc", "1.1.0rc1")])
def test_s068_5_the_job_without_the_key_or_on_a_pre_release_calls_github_for_nothing(
    repo: Repo, capsys: pytest.CaptureFixture[str], close: bool, lane: str, version: str
) -> None:
    """A caller that grants no `issues: write` and sets no close_milestone keeps working"""
    merged(repo, close)
    capsys.readouterr()
    argv = ["--repo", str(repo.root), "close-milestone", "--lane", lane, "--version", version]
    assert main(argv, github=Unreachable()) == 0
    assert capsys.readouterr() == ("", "")


def test_s068_5_no_milestone_titled_x_writes_nothing(repos: Repos, tmp_path: Path) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "v1.1.0", 0), OpenMilestone(4, "1.2.0", 1)]  # neither is titled 1.1.0
    done = rolled(repo)
    assert repo.github.open_reads == 1  # the one read that finds no milestone titled X
    assert (repo.github.milestone_reads, repo.github.milestone_writes) == ([], [])
    assert done == Rollover()


def failed_job(repo: Repo, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """The release landed, then `shipmill close-milestone` with milestone writes failing: its
    exit code, stdout, and stderr"""
    repo.github.milestone_write_error = "Resource not accessible by integration (HTTP 403)"
    v, sha, base = prepared(repo, Lane.STABLE, "1.1.0")
    land(repo.git, repo.policy, repo.github, Lane.STABLE, v, sha, base, DAY)
    # the release stands: the tag on origin, main moved, the GitHub release and the publish made
    assert repo.git.remote_tag("v1.1.0") and repo.git.remote_branch("main") == sha
    assert repo.github.releases[-1][0] == "v1.1.0"
    assert [d[0] for d in repo.github.dispatched] == ["publish.yml"]
    capsys.readouterr()
    argv = ["--repo", str(repo.root), "close-milestone", "--lane", "stable", "--version", "1.1.0"]
    code = main(argv, github=repo.github)
    done = capsys.readouterr()
    return code, done.out, done.err


def test_s068_6_a_failed_close_fails_the_job_after_the_release_naming_the_command(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "1.1.0", 0)]
    code, out, err = failed_job(repo, capsys)
    assert code == 1
    command = f"{GH} api -X PATCH repos/{{owner}}/{{repo}}/milestones/3 -f state=closed"
    assert err.startswith("shipmill: v1.1.0 is released; milestone 1.1.0: closing it failed: ")
    assert "(HTTP 403)" in err and err.rstrip().endswith(f"run {command}")
    assert f"run {command}" in out  # the Release run's summary says it too


def test_s068_6_a_failed_move_names_the_move_and_the_close(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = setup(repos, tmp_path)
    repo.github.open = [OpenMilestone(3, "1.1.0", 1), OpenMilestone(5, "1.2.0", 0)]
    holding(repo, "1.1.0", 12)
    code, _, err = failed_job(repo, capsys)
    assert code == 1
    assert "milestone 1.1.0: moving #12 to 1.2.0 failed, so 1.1.0 stays open" in err
    assert f"run {GH} api -X PATCH repos/{{owner}}/{{repo}}/issues/12 -F milestone=5" in err
    assert err.rstrip().endswith(f"then {GH} api -X PATCH repos/{{owner}}/{{repo}}/milestones/3 -f state=closed")
    assert repo.github.milestone_writes == [("#12", 5)]  # no close after a failed move


class UnreadIssues(FakeGitHub):
    """GitHub that fails to list a milestone's issues"""

    def milestone_issues(self, title: str) -> MilestoneIssues:
        self.milestone_reads.append(title)
        raise ReleaseError(f"gh issue list failed for milestone {title}")


def test_s068_6_a_failed_read_fails_the_job_after_the_release(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = setup(repos, tmp_path)
    repo.github = UnreadIssues(open=[OpenMilestone(3, "1.1.0", 1), OpenMilestone(5, "1.2.0", 0)])
    code, _, err = failed_job(repo, capsys)
    assert code == 1
    assert "milestone 1.1.0: reading its issues failed, so none moved to 1.2.0 and it stays open" in err
    assert (
        f"for each open issue N of 1.1.0 run {GH} api -X PATCH repos/{{owner}}/{{repo}}/issues/N -F milestone=5" in err
    )
    assert err.rstrip().endswith(f"then {GH} api -X PATCH repos/{{owner}}/{{repo}}/milestones/3 -f state=closed")
    assert repo.github.milestone_writes == []


@dataclass
class Ordered(FakeGitHub):
    """GitHub that notes each read of the open milestones"""

    seen: list[tuple[int, int]] = field(default_factory=list)

    def open_milestones(self) -> list[OpenMilestone]:
        self.seen.append((len(self.releases), len(self.dispatched)))
        return super().open_milestones()


def test_land_reads_and_writes_no_milestone_and_prints_none(
    repos: Repos, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The land job's own permissions grant no `issues`, so land leaves the milestone to the
    milestone job, even on a lane with close_milestone"""
    repo = setup(repos, tmp_path)
    github = Ordered(open=[OpenMilestone(3, "1.1.0", 0)])
    repo.github = github
    v, sha, base = prepared(repo, Lane.STABLE, "1.1.0")
    capsys.readouterr()
    argv = ["--repo", str(repo.root), "land", "--lane", "stable", "--version", str(v), "--sha", sha, "--base", base]
    assert main([*argv, "--date", str(DAY)], github=github) == 0
    assert json.loads(capsys.readouterr().out).keys() == {"tag", "placed", "synced", "published"}
    assert (github.seen, github.milestone_reads, github.milestone_writes) == ([], [], [])


def _job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    following = re.search(r"\n  [\w-]+:\n", text[start + 1 :])
    return text[start : start + 1 + following.start()] if following else text[start:]


def test_land_yml_runs_the_rollover_after_land_with_the_callers_grant() -> None:
    """D-50: the milestone is read only once the land job released and published; the job
    sets no permissions, so the caller's `issues: write` reaches it (S-068-11's grant), and no
    other job waits on it, so a failed write skips none of them"""
    text = LAND_YML.read_text(encoding="utf-8")
    job = _job(text, "milestone")
    assert job.startswith("\n  milestone:\n    needs: land\n")
    assert "    if:" not in job  # the default: land succeeded
    assert "permissions:" not in job
    assert "GH_TOKEN: ${{ github.token }}" in job
    assert 'shipmill close-milestone --lane "$LANE" --version "$VERSION" | tee -a "$GITHUB_STEP_SUMMARY"' in job
    assert "shell: bash" in job  # -eo pipefail: a failed write fails the job despite the tee
    for other in ("land", "close-proposal", "cleanup", "upgrade"):
        assert not re.search(r"^    (?:needs|if):.*milestone", _job(text, other), re.MULTILINE), other
    assert "close-milestone" not in _job(text, "land")
