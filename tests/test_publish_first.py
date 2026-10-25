"""#598, D-50: a release publishes before it moves its references. A lane's after_publish
workflows start only once each dispatch run succeeded and PyPI serves the version; a publish
that fails or never ends leaves them unstarted and names the run. A lane without
after_publish lands as before, waiting on nothing. shipmill's own move-major-tag.yml moves
@v0 and the marketplace ref; shipmill's own config turns after_publish on in a follow-up."""

import json
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.config import config_path
from shipmill.errors import ReleaseError
from shipmill.github import RunState
from shipmill.land import Landed, Waiting, land, prepare
from shipmill.policy import Lane, Policy

from .conftest import Repo, at_day
from .test_lanes import plan

ROOT = Path(__file__).resolve().parents[1]
MOVE = ROOT / ".github" / "workflows" / "move-major-tag.yml"
RC_RULE = '[lanes.rc]\nschedule = ["daily 07:00 UTC"]\ngithub_release = true\n'
PUBLISH_FIRST = RC_RULE + 'dispatch = ["publish.yml"]\nafter_publish = ["move-major-tag.yml"]\n'
PYPI_URL = "https://pypi.org/pypi/demo/1.1.0rc1/json"
QUEUED, RUNNING = RunState("queued", ""), RunState("in_progress", "")
PASSED, FAILED = RunState("completed", "success"), RunState("completed", "failure")


@dataclass
class Clock:
    """A monotonic clock that a sleep moves forward, and PyPI's answers in turn (the last stays)"""

    answers: list[int | str] = field(default_factory=lambda: [200])  # a str is no answer: ReleaseError
    now: float = 0.0
    slept: list[float] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def pypi(self, url: str) -> int:
        self.asked.append(url)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, str):
            raise ReleaseError(f"{url}: {answer}")
        return answer

    def waiting(self, timeout: float = 600.0) -> Waiting:
        return Waiting(pypi=self.pypi, clock=self.clock, sleep=self.sleep, timeout=timeout, poll=15.0)


def configure(repo: Repo, rule: str) -> None:
    repo.write(repo.policy_file, repo.read(repo.policy_file).replace(RC_RULE, rule))
    repo.git.run("commit", "-qam", "Configure the rc lane")
    repo.git.run("push", "-q", "origin", "main")


def land_rc(repo: Repo, waiting: Waiting | None) -> Landed:
    repo.merge(1, "Added", "Feature A")
    decision = plan(repo, at_day(1))
    assert decision.lane is Lane.RC and str(decision.version) == "1.1.0rc1"
    assert decision.version is not None
    day = at_day(1).date()
    prepared = prepare(
        repo.git, repo.policy, decision.lane, decision.version, decision.base, day, commit=True, push=True
    )
    return land(
        repo.git, repo.policy, repo.github, decision.lane, decision.version, prepared.sha, decision.base, day,
        waiting=waiting,
    )  # fmt: skip


def workflows(repo: Repo) -> list[str]:
    return [d[0] for d in repo.github.dispatched]


# -- the policy ---------------------------------------------------------------------------------


def test_after_publish_reads_with_none_as_the_default(repo: Repo) -> None:
    assert all(rule.after_publish == () for rule in repo.policy.lanes.values())
    configure(repo, PUBLISH_FIRST)
    rule = repo.policy.rule(Lane.RC)
    assert (rule.dispatch, rule.after_publish) == (("publish.yml",), ("move-major-tag.yml",))


@pytest.mark.parametrize(
    ("rule", "error"),
    [
        (RC_RULE + 'after_publish = ["move-major-tag.yml"]\n', "after_publish waits on the lane's dispatch runs"),
        (RC_RULE + 'dispatch = ["p.yml"]\nafter_publish = ["../x.yml"]\n', "after_publish names a file"),
        (RC_RULE + 'dispatch = ["p.yml"]\nafter_publish = ["m.yml", "m.yml"]\n', "names a workflow twice"),
        (RC_RULE + 'dispatch = ["p.yml"]\nafter_publish = ["p.yml"]\n', "in both dispatch and after_publish"),
    ],
)
def test_a_malformed_after_publish_is_refused(repo: Repo, rule: str, error: str) -> None:
    repo.write(repo.policy_file, repo.read(repo.policy_file).replace(RC_RULE, rule))
    with pytest.raises(ReleaseError, match=re.escape(error)):
        Policy.load(config_path(repo.root))


# -- land -----------------------------------------------------------------------------------------


def test_a_lane_without_after_publish_waits_on_nothing(repo: Repo) -> None:
    configure(repo, RC_RULE + 'dispatch = ["publish.yml", "move-major-tag.yml"]\n')
    landed = land_rc(repo, None)  # as today: every workflow at once, no run read, no PyPI asked
    assert workflows(repo) == ["publish.yml", "move-major-tag.yml"]
    assert landed.published == ("github-release", "publish.yml", "move-major-tag.yml")
    assert repo.github.run_reads == []


def test_references_move_only_after_the_publish_run_passed_and_pypi_serves_it(repo: Repo) -> None:
    configure(repo, PUBLISH_FIRST)
    time = Clock(answers=[404, 404, 200])
    repo.github.run_states[1] = [QUEUED, RUNNING, PASSED]
    landed = land_rc(repo, time.waiting())
    assert repo.git.remote_tag("v1.1.0rc1")  # the tag first: publish.yml checks it out
    assert workflows(repo) == ["publish.yml", "move-major-tag.yml"]
    assert repo.github.dispatched[-1] == ("move-major-tag.yml", "main", "v1.1.0rc1", {})
    # the run GitHub named when publish.yml was dispatched, read until it ended
    assert repo.github.run_reads == [1, 1, 1]
    assert time.asked == [PYPI_URL] * 3  # pyproject.toml's [project] name, at the version
    assert time.slept == [15.0] * 4  # no real sleep: the injected one
    assert landed.published == ("github-release", "publish.yml", "move-major-tag.yml")


@pytest.mark.parametrize(
    ("states", "said"),
    [
        ([QUEUED, FAILED], "publish.yml run https://github.com/o/demo/actions/runs/1 ended failure"),
        ([RunState("completed", "cancelled")], "actions/runs/1 ended cancelled"),
        ([QUEUED], "publish.yml run https://github.com/o/demo/actions/runs/1 is still queued after 600s"),
    ],
)
def test_a_publish_that_fails_or_never_ends_leaves_the_references(
    repo: Repo, states: list[RunState], said: str
) -> None:
    configure(repo, PUBLISH_FIRST)
    time = Clock()
    repo.github.run_states[1] = states
    with pytest.raises(ReleaseError) as refused:
        land_rc(repo, time.waiting())
    message = str(refused.value)
    assert said in message
    assert "move-major-tag.yml not started, so the references stay on the previous release" in message
    assert "gh workflow run move-major-tag.yml --ref main -f tag=v1.1.0rc1" in message
    assert workflows(repo) == ["publish.yml"]  # never move-major-tag.yml
    assert time.asked == []  # PyPI is asked only once the run passed
    assert repo.git.remote_tag("v1.1.0rc1")


@pytest.mark.parametrize(("answer", "said"), [(404, "HTTP 404"), ("timed out", "no answer (")])
def test_a_version_pypi_never_serves_leaves_the_references(repo: Repo, answer: int | str, said: str) -> None:
    configure(repo, PUBLISH_FIRST)
    time = Clock(answers=[answer])
    with pytest.raises(ReleaseError, match=rf"PyPI still answers {re.escape(said)}.*{re.escape(PYPI_URL)}"):
        land_rc(repo, time.waiting(timeout=60.0))
    assert workflows(repo) == ["publish.yml"]
    assert len(time.asked) == 5  # at 0, 15, 30, 45, and 60 seconds, the deadline


def test_the_runs_and_pypi_share_one_deadline(repo: Repo) -> None:
    configure(repo, PUBLISH_FIRST)
    time = Clock(answers=[404])
    repo.github.run_states[1] = [QUEUED, QUEUED, QUEUED, PASSED]  # 45 of the 60 seconds
    with pytest.raises(ReleaseError, match="PyPI still answers HTTP 404"):
        land_rc(repo, time.waiting(timeout=60.0))
    assert len(time.asked) == 2  # at 45 and 60 seconds


def test_a_dispatch_that_names_no_run_is_not_waited_on_by_guessing(repo: Repo) -> None:
    configure(repo, PUBLISH_FIRST)
    repo.github.no_run_url = True
    with pytest.raises(ReleaseError, match="dispatching publish.yml named no run"):
        land_rc(repo, Clock().waiting())
    assert workflows(repo) == ["publish.yml"] and repo.github.run_reads == []


def test_without_pyproject_versions_land_waits_on_the_runs_alone(repo: Repo) -> None:
    configure(repo, PUBLISH_FIRST)
    repo.write(
        repo.policy_file, repo.read(repo.policy_file).replace('version_files = "pyproject"', 'version_files = "none"')
    )
    repo.git.run("commit", "-qam", "Tags and CHANGELOG only")
    repo.git.run("push", "-q", "origin", "main")
    time = Clock(answers=[404])
    land_rc(repo, time.waiting())
    assert workflows(repo) == ["publish.yml", "move-major-tag.yml"] and time.asked == []


def test_a_lane_with_after_publish_needs_a_way_to_wait(repo: Repo) -> None:
    configure(repo, PUBLISH_FIRST)
    with pytest.raises(ReleaseError, match="no way to wait"):
        land_rc(repo, None)
    assert workflows(repo) == ["publish.yml"]


# -- move-major-tag.yml ----------------------------------------------------------------------------


def _script(name: str) -> str:
    """A step's run script as GitHub runs it: the block scalar, dedented"""
    lines = MOVE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"      - name: {name}")
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


MARKETPLACE = {
    "plugins": [{"name": "shipmill", "source": {"source": "github", "repo": "shipmill/shipmill", "ref": "v0.66.0"}}]
}


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A clone of a bare origin whose main names v0.66.0 in the marketplace, tagged v0.66.0 to v0.67.0"""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "-b", "main")
    (work / ".claude-plugin").mkdir()
    (work / ".claude-plugin" / "marketplace.json").write_text(json.dumps(MARKETPLACE, indent=2) + "\n")
    _git(work, "add", "-A")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "Release 0.66.0")
    for tag in ("v0.66.0", "v0.66.1", "v0.67.0", "v0.68.0rc1"):
        _git(work, "tag", tag)
    _git(work, "push", "-q", "origin", "main", "--tags")
    return work


def _bash(name: str, cwd: Path, tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run a step's script with `bash -e`, as the runner does; the process and its outputs"""
    output = tmp_path / "output"
    output.write_text("")
    full = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GITHUB_OUTPUT": str(output)}
    proc = subprocess.run(
        ["bash", "-e", "-c", _script(name)], cwd=cwd, env=full | env, capture_output=True, text=True, check=False
    )
    return proc, output.read_text()


@pytest.mark.parametrize(("tag", "newest"), [("v0.67.0", "true"), ("v0.66.1", "false")])
def test_only_the_newest_stable_release_moves_the_references(
    checkout: Path, tmp_path: Path, tag: str, newest: str
) -> None:
    proc, output = _bash("Check the tag", checkout, tmp_path, TAG=tag)
    assert proc.returncode == 0, proc.stderr
    assert output == f"newest={newest}\n"  # an rc tag is never the newest stable


def test_the_marketplace_ref_moves_on_the_default_branch(checkout: Path, tmp_path: Path) -> None:
    proc, _ = _bash("Point the marketplace at the release", checkout, tmp_path, TAG="v0.67.0", BRANCH="main")
    assert proc.returncode == 0, proc.stderr
    assert "names v0.67.0 on main" in proc.stdout
    shown = _git(checkout, "show", "origin/main:.claude-plugin/marketplace.json")
    assert json.loads(shown)["plugins"][0]["source"]["ref"] == "v0.67.0"
    assert (
        _git(checkout, "log", "-1", "--format=%s %an", "origin/main")
        == "Point the marketplace at v0.67.0 github-actions[bot]\n"
    )
    again, _ = _bash("Point the marketplace at the release", checkout, tmp_path, TAG="v0.67.0", BRANCH="main")
    assert again.returncode == 0 and "names v0.67.0 already" in again.stdout


def test_the_marketplace_move_builds_on_main_as_it_is_now(checkout: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    (other / "x.txt").write_text("x\n")
    _git(other, "add", "-A")
    _git(other, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "A merge meanwhile")
    _git(other, "push", "-q", "origin", "main")
    proc, _ = _bash("Point the marketplace at the release", checkout, tmp_path, TAG="v0.67.0", BRANCH="main")
    assert proc.returncode == 0, proc.stderr
    assert _git(checkout, "log", "--format=%s", "origin/main").splitlines()[:2] == [
        "Point the marketplace at v0.67.0",
        "A merge meanwhile",
    ]
