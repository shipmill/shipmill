"""Spec 047, `shipmill deprecations`: which connected repos still rely on each deprecated key,
each with its migrating upgrade's state, read from GitHub alone (D-63's evidence)"""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.cli import main
from shipmill.deprecations import CATALOGUE, DeprecationId, find
from shipmill.deprecations_report import (
    GhReads,
    RepoName,
    StateKind,
    UpgradeState,
    fleet_repos,
    report,
    upgrade_state,
)
from shipmill.errors import ReleaseError
from shipmill.github import UPGRADE_LATER_LABEL, Issue, PullRequest
from shipmill.launchd import DEFAULT_TOOL, build, gate_repos, label
from shipmill.upgrades import Upgrade, UpgradeId, body
from shipmill.upgrades import find as find_upgrade
from shipmill.walk import DECISION_LABEL

from .conftest import POLICY

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 2)
CLOSED = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
_MIGRATES = find(DeprecationId("agents-prs")).upgrade
assert _MIGRATES is not None
UPGRADE = find_upgrade(_MIGRATES)  # agents-prs's migrating upgrade, whichever the catalogue names
BRANCH = f"shipmill/upgrade-{UPGRADE.id}"
PLAIN = POLICY + '\n[agents]\nprompt = "/t"\n'
PRS = PLAIN + "prs = true\n"
CREDIT = PLAIN + 'credit = "off"\n'  # agents-credit, an entry with no migrating upgrade


def proposal(number: int, *labels: str, closed: bool = False, upgrade: Upgrade = UPGRADE) -> Issue:
    """The upgrade's shipmill-upgrade issue, as upgrade --propose writes it"""
    return Issue(number, "t", body(upgrade), CLOSED if closed else None, ("shipmill-upgrade", *labels))


@dataclass
class Fake:
    """Each repo's config text (an exception: the read fails), upgrade issues, and open pulls"""

    configs: dict[str, str | ReleaseError]
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    pulls: dict[str, list[PullRequest]] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)

    def config(self, repo: RepoName) -> str:
        self.seen.append(("config", str(repo)))
        found = {name.lower(): text for name, text in self.configs.items()}[repo.key]  # GitHub ignores case
        if isinstance(found, ReleaseError):
            raise found
        return found

    def upgrade_issues(self, repo: RepoName) -> Sequence[Issue]:
        self.seen.append(("issues", str(repo)))
        return self.issues.get(str(repo), [])

    def open_pulls(self, repo: RepoName) -> Sequence[PullRequest]:
        self.seen.append(("pulls", str(repo)))
        return self.pulls.get(str(repo), [])


def run(args: list[str], fake: Fake, home: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["deprecations", *args], deprecation_reads=fake, home=home, today=TODAY)
    return code, capsys.readouterr().out


def test_s047_12_a_repo_setting_agents_prs_is_listed_under_it_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake({"acme/web": PRS, "acme/api": PLAIN}, issues={"acme/web": [proposal(12)]})
    code, out = run(["--repo", "acme/web", "--repo", "acme/api"], fake, tmp_path, capsys)
    assert code == 1
    assert out.splitlines()[:3] == [
        "2 repos read on 2026-11-02: acme/web, acme/api",
        f"agents-prs: [agents] prs, replaced by [autonomy] land; upgrade: {UPGRADE.id}",
        "  acme/web: issue #12 open",
    ]
    assert "  none of 2 repos" in out.split("agents-prompt-land:", 1)[1]


def test_s047_12_with_no_repo_relying_each_deprecation_reads_none_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake({"acme/web": PLAIN, "acme/api": POLICY})
    code, out = run(["--repo", "acme/web", "--repo", "acme/api"], fake, tmp_path, capsys)
    assert code == 0
    assert out.count("  none of 2 repos\n") == len(CATALOGUE)
    assert [s for s in fake.seen if s[0] != "config"] == []  # nothing relies: no issue or pull read


def test_s047_12_id_prints_that_deprecations_block_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake({"acme/web": PRS})
    code, out = run(["agents-credit", "--repo", "acme/web"], fake, tmp_path, capsys)
    assert code == 0  # acme/web relies on agents-prs, not on the one asked about
    assert out.splitlines()[1:] == [
        "agents-credit: [agents] credit, replaced by [agents] author; upgrade: none",
        "  none of 1 repos",
    ]


def test_s047_12_an_unknown_id_names_the_known_ones(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake({"acme/web": PRS})
    with pytest.raises(ReleaseError, match="unknown deprecation nope; known: agents-prs, agents-prompt-land"):
        run(["nope", "--repo", "acme/web"], fake, tmp_path, capsys)
    assert fake.seen == []


@pytest.mark.parametrize(
    ("issues", "pulls", "config", "wanted"),
    [
        ([proposal(12)], [], PRS, "issue #12 open"),
        ([proposal(12, DECISION_LABEL)], [], PRS, "asked, waiting"),
        ([proposal(12, UPGRADE_LATER_LABEL)], [], PRS, "not now"),
        ([proposal(12, closed=True)], [], PRS, "declined"),
        ([proposal(12)], [PullRequest(30, BRANCH)], PRS, "pull request #30 open"),
        ([], [PullRequest(31, BRANCH)], PRS, "pull request #31 open"),
        ([], [PullRequest(32, "feat/other")], PRS, "not proposed"),
        ([], [], PRS, "not proposed"),
    ],
)
def test_s047_13_the_upgrade_state_comes_from_its_issues_and_pull_requests(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    issues: list[Issue],
    pulls: list[PullRequest],
    config: str,
    wanted: str,
) -> None:
    fake = Fake({"acme/web": config}, issues={"acme/web": issues}, pulls={"acme/web": pulls})
    code, out = run(["agents-prs", "--repo", "acme/web"], fake, tmp_path, capsys)
    assert code == 1
    assert out.splitlines()[2] == f"  acme/web: {wanted}"


def test_s047_13_an_entry_with_no_upgrade_reads_not_proposed_without_reading_issues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake({"acme/web": CREDIT})
    code, out = run(["agents-credit", "--repo", "acme/web"], fake, tmp_path, capsys)
    assert (code, out.splitlines()[2]) == (1, "  acme/web: not proposed")
    assert fake.seen == [("config", "acme/web")]


def test_s047_13_the_first_open_issue_counts_and_another_upgrades_issue_doesnt() -> None:
    autonomy = find_upgrade(UpgradeId("agent-autonomy"))
    other = Issue(5, "t", "<!-- shipmill-upgrade: changelog-fragments 0.37.0 -->\n", None, ("shipmill-upgrade",))
    raw = {"agents": {"prompt": "/t", "prs": True}}
    issues = [other, proposal(14, DECISION_LABEL, upgrade=autonomy), proposal(12, upgrade=autonomy)]
    assert upgrade_state(autonomy, raw, issues, []) == UpgradeState(StateKind.ISSUE_OPEN, 12)
    assert upgrade_state(autonomy, raw, [other], []) == UpgradeState(StateKind.NOT_PROPOSED)
    # closed while the config holds the upgrade's keys: accepted, not declined, and nothing proposes it again
    closed = [proposal(12, closed=True, upgrade=autonomy)]
    assert upgrade_state(autonomy, raw, closed, []) == UpgradeState(StateKind.DECLINED, 12)
    decided = {**raw, "autonomy": {"land": "propose"}}
    assert upgrade_state(autonomy, decided, closed, []) == UpgradeState(StateKind.NOT_PROPOSED)


@pytest.mark.parametrize(
    ("config", "said"),
    [
        (ReleaseError("gh api failed (exit 1): gh: Not Found (HTTP 404)"), "HTTP 404"),
        ('name = "x"\n[agents\n', "acme/api"),  # not TOML
        (PLAIN + "nope = 1\n", "nope"),  # a key no shipmill knew: the config doesn't parse
    ],
)
def test_s047_14_a_repo_that_cant_be_read_exits_2_naming_it_and_prints_no_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str | ReleaseError, said: str
) -> None:
    fake = Fake({"acme/web": PRS, "acme/api": config})
    with pytest.raises(ReleaseError) as raised:
        run(["--repo", "acme/web", "--repo", "acme/api"], fake, tmp_path, capsys)
    message = str(raised.value)
    assert message.startswith("can't read 1 of 2 repos, and an unread repo never counts as relying on nothing")
    assert "\n  acme/api: " in message and said in message and "acme/web:" not in message
    assert capsys.readouterr().out == ""


def test_s047_14_a_failed_issue_read_is_an_unread_repo_too() -> None:
    class Broken(Fake):
        def upgrade_issues(self, repo: RepoName) -> Sequence[Issue]:
            raise ReleaseError("gh issue list failed (exit 1): HTTP 403")

    with pytest.raises(ReleaseError, match=r"\n  acme/web: gh issue list failed"):
        report([RepoName("acme/web")], CATALOGUE, Broken({"acme/web": PRS}))


def test_s047_14_no_gate_job_and_no_repo_named_exits_2_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ReleaseError, match="no repos to read: no gate job on this host, and no --repo or --fleet"):
        run([], Fake({}), tmp_path, capsys)


def gate_job(home: Path, repo: str) -> None:
    """The plist `shipmill launchd` writes for the repo, with stand-in tools on its PATH"""
    tools = home / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("claude", "gh", "git", "uvx"):
        (tools / name).touch(mode=0o755)
    job = build(repo, home / "gate", 15, DEFAULT_TOOL, (), home, str(tools), skip=lambda folder: False)
    job.plist.parent.mkdir(parents=True, exist_ok=True)
    job.plist.write_bytes(job.document)


def test_s047_15_with_no_repo_named_it_reads_this_hosts_gate_jobs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gate_job(tmp_path, "acme/web")
    gate_job(tmp_path, "Acme/API.v2")
    (tmp_path / "Library" / "LaunchAgents" / "com.other.job.plist").write_bytes(b"not read")
    assert gate_repos(tmp_path) == ("Acme/API.v2", "acme/web")
    fake = Fake({"acme/web": PLAIN, "Acme/API.v2": PLAIN, "acme/docs": PLAIN})
    assert run([], fake, tmp_path, capsys)[1].splitlines()[0] == "2 repos read on 2026-11-02: Acme/API.v2, acme/web"
    # --repo replaces the host's repos, and --host adds them back, each repo once
    assert run(["--repo", "acme/docs"], fake, tmp_path, capsys)[1].splitlines()[0].endswith(": acme/docs")
    first = run(["--repo", "acme/docs", "--repo", "ACME/WEB", "--host"], fake, tmp_path, capsys)[1].splitlines()[0]
    assert first == "3 repos read on 2026-11-02: acme/docs, ACME/WEB, Acme/API.v2"


def test_s047_15_a_gate_job_naming_another_repo_is_refused(tmp_path: Path) -> None:
    gate_job(tmp_path, "acme/web")
    folder = tmp_path / "Library" / "LaunchAgents"
    (folder / f"{label('acme/web')}.plist").rename(folder / f"{label('acme/api')}.plist")
    with pytest.raises(ReleaseError, match="runs the gate for acme/web, whose job is dev.shipmill.gate.acme.web"):
        gate_repos(tmp_path)


def fleet_script() -> ModuleType:
    path = ROOT / "skills" / "github-ship-watch" / "scripts" / "fleet.py"
    spec = importlib.util.spec_from_file_location("deprecations_fleet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


FLEET = """\
# the maintainer's gates, on two hosts
[[repos]]
repo = "acme/web"

[[repos]]
repo = "acme/api"
incident_label = "sev"
"""


def test_s047_15_fleet_reads_github_ship_watchs_fleet_file_as_fleet_py_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(FLEET, encoding="utf-8")
    script = fleet_script()
    assert [e.repo for e in script.load(path)] == [str(r) for r in fleet_repos(path)] == ["acme/web", "acme/api"]
    gate_job(tmp_path, "acme/docs")  # --fleet replaces the host's repos too
    fake = Fake({"acme/web": PLAIN, "acme/api": PLAIN, "acme/docs": PLAIN})
    assert run(["--fleet", str(path)], fake, tmp_path, capsys)[1].splitlines()[0].endswith(": acme/web, acme/api")


@pytest.mark.parametrize(
    "text",
    [
        "",  # no [[repos]]
        "[[repos]]\nrepo = 'acme'\n",  # not owner/name
        "[[repos]]\nincident_label = 'x'\n",  # no repo
        "[[repos]]\nrepo = 'acme/web'\nbranch = 'main'\n",  # an unknown key
        "[[repos]]\nrepo = 'acme/web'\n[[repos]]\nrepo = 'ACME/web'\n",  # twice
        "owner = 'acme'\n[[repos]]\nrepo = 'acme/web'\n",  # a key beside [[repos]]
        "[[repos]\n",  # not TOML
    ],
)
def test_s047_15_a_fleet_file_fleet_py_refuses_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(text, encoding="utf-8")
    script = fleet_script()
    with pytest.raises(script.Refused):
        script.load(path)
    with pytest.raises(ReleaseError, match=str(path)):
        fleet_repos(path)


def test_s047_16_json_prints_the_specs_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake({"acme/web": PRS + "\n[roadmap]\nwip = 3\n", "acme/api": PLAIN}, issues={"acme/web": [proposal(12)]})
    code, out = run(["--repo", "acme/web", "--repo", "acme/api", "--json"], fake, tmp_path, capsys)
    assert code == 1
    relied = {
        "agents-prs": [{"repo": "acme/web", "upgrade_state": "issue #12 open", "issue": 12}],
        "roadmap": [{"repo": "acme/web", "upgrade_state": "not proposed", "issue": None}],
    }
    assert json.loads(out) == {
        "repos": ["acme/web", "acme/api"],
        "deprecations": [
            {
                "id": str(d.id),
                "replacement": d.replacement,
                "upgrade": None if d.upgrade is None else str(d.upgrade),
                "relied_on_by": relied.get(str(d.id), []),
            }
            for d in CATALOGUE
        ],
    }
    assert json.loads(out)["deprecations"][0]["upgrade"] == str(UPGRADE.id)


def test_gh_reads_name_the_repo_and_read_the_default_branchs_config() -> None:
    seen: list[list[str]] = []
    outputs = {"api": "x = 1\n", "issue": "[]", "pr": '[{"number": 4, "headRefName": "b"}]'}

    def state(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, outputs[cmd[1]], "")

    reads = GhReads(state, pause=lambda seconds: None)
    repo = RepoName("acme/web")
    assert reads.config(repo) == "x = 1\n"
    assert reads.upgrade_issues(repo) == []
    assert reads.open_pulls(repo) == [PullRequest(4, "b")]
    assert seen[0] == [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github.raw+json",
        "repos/acme/web/contents/.github/shipmill.toml",
    ]
    assert seen[1][-2:] == seen[2][-2:] == ["-R", "acme/web"]
    assert "shipmill-upgrade" in seen[1] and "--state" in seen[2]


def test_s047_17_release_lanes_gives_the_steps_to_retire_a_key() -> None:
    text = " ".join((ROOT / "docs" / "release-lanes.md").read_text(encoding="utf-8").split())
    section = text.split("### Retired keys", 1)[1].split("### ", 1)[0]
    steps = section.split("To retire a key:", 1)[1]
    order = ["Release the upgrade", "sweeps propose it", "deprecations <id>`", "none of N repos", "Then decide"]
    at = [steps.index(word) for word in order]
    assert at == sorted(at), at
    assert "date" in steps and "repos it read" in steps and "Why" in steps
