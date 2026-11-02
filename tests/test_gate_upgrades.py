"""Spec 047: the gate's sweep proposes the config upgrades as the App, before its own read.
The proposal's seams (the config at the default branch's head, GitHub as the App, GitHub for
a dry run's read) are fakes that log each call beside the source's reads, so the order shows"""

import datetime as dt
import json
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill.app import Identity
from shipmill.cli import _with_tick
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.findings import Finding
from shipmill.gate import Action, Decision, Upgrader, head_config, state_dir, tick_lines, upgrade_fix
from shipmill.github import UPGRADE_LABEL, Forbidden
from shipmill.gitrepo import Git
from shipmill.status import read_upgrades
from shipmill.upgrades import Offer, Outcome, Proposals, Proposed, UpgradeId, find, marker, title
from shipmill.walk import SWEEP, Changes, Swept

from .conftest import POLICY, FakeGitHub
from .test_factory import fake_host, run_checks
from .test_gate import checkout, git_
from .test_gate_walk import INCIDENT, LATER, NOW, REPO, Source, cfg, tick
from .test_status_picture import REPO as FACTORY_REPO
from .test_status_picture import facts, gate, lines

__all__ = ["checkout"]  # the fixture, imported for the tests below

APP = Identity(7, "demo-agent", 99, Path("/k.pem"))
FRAGMENTS = find(UpgradeId("changelog-fragments"))
AUTONOMY = find(UpgradeId("agent-autonomy"))
# changelog-fragments pending; agent-autonomy decided by [autonomy] land
PENDING = POLICY + '\n[agents]\nprompt = "/t"\n\n[autonomy]\nland = "propose"\n'
# changelog-fragments decided; agent-autonomy pending, under an upgrade level of observe
OBSERVED = (
    POLICY.replace("[changelog]\n", '[changelog]\nfragments = "changelog.d"\n')
    + '\n[agents]\nprompt = "/t"\n\n[autonomy]\nupgrade = "observe"\n'
)


@dataclass
class UpgradeSource(Source):
    """A state read whose sweep reads the upgrade issues open on the fake GitHub, as
    watch_state.py --sweep's UPGRADE_PENDING rows do"""

    github: FakeGitHub = field(default_factory=FakeGitHub)

    def sweep(self, changes: Changes) -> list[Finding]:
        self.reads.append("sweep")
        open_ = self.github.open_labelled_issues(UPGRADE_LABEL)
        return [Finding("UPGRADE_PENDING", f"#{i.number}", "ask", True, (), "watch") for i in open_]


@dataclass
class Seams:
    """An Upgrader's three seams, each call logged in reads"""

    raw: Mapping[str, Any]
    github: FakeGitHub
    reads: list[str]
    apps: list[Identity] = field(default_factory=list)

    def upgrader(self) -> Upgrader:
        def config() -> Mapping[str, Any]:
            self.reads.append("config")
            return self.raw

        def as_app(identity: Identity) -> FakeGitHub:
            self.reads.append("as app")
            self.apps.append(identity)
            return self.github

        def reader() -> FakeGitHub:
            self.reads.append("reader")
            return self.github

        return Upgrader(config, as_app, reader)


def setup(text: str = PENDING, github: FakeGitHub | None = None) -> tuple[UpgradeSource, Seams]:
    hub = github or FakeGitHub()
    source = UpgradeSource(github=hub)
    return source, Seams(tomllib.loads(text), hub, source.reads)


def swept_tick(git: Git, source: UpgradeSource, seams: Seams, app: bool = True, **flags: Any) -> Decision:
    """A tick that sweeps, with [agents] app_id set when app"""
    agents = cfg(app_id=7) if app else cfg()
    return tick(
        git,
        source,
        agents=agents,
        app=lambda app_id: APP,
        app_env=lambda identity: {},
        upgrades=seams.upgrader(),
        **flags,
    )


def stored(git: Git) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((state_dir(git) / SWEEP).read_text())
    return found


def test_s047_1_a_sweep_opens_the_upgrade_issue_as_the_app_before_its_own_read(checkout: Git) -> None:
    source, seams = setup()
    decision = swept_tick(checkout, source, seams)
    assert source.reads.index("as app") < source.reads.index("sweep")
    assert seams.apps == [APP]
    (issue,) = seams.github.open_labelled_issues(UPGRADE_LABEL)
    assert issue.body.split("\n", 1)[0] == marker(FRAGMENTS)
    # the sweep's own read already sees it: its UPGRADE_PENDING row is the tick's work
    pending = Finding("UPGRADE_PENDING", f"#{issue.number}", "ask", True, (), "watch")
    assert decision.work == (pending,)
    swept = Swept.load(state_dir(checkout) / SWEEP)
    assert swept is not None and swept.rows == (pending,)
    proposed = {"id": "changelog-fragments", "issue": issue.number, "outcome": "opened"}
    assert stored(checkout)["upgrades"] == {"proposed": [proposed]}


def test_s047_2_the_sweep_reads_the_config_at_the_default_branchs_head(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    git_("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    pusher = tmp_path / "pusher"
    git_("clone", "-q", str(origin), str(pusher), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git_("config", k, v, cwd=pusher)
    config = pusher / CONFIG_PATH
    config.parent.mkdir()
    config.write_text(POLICY + '\n[agents]\nprompt = "/first"\n', encoding="utf-8")
    git_("add", ".", cwd=pusher)
    git_("commit", "-q", "-m", "config", cwd=pusher)
    git_("push", "-q", "origin", "main", cwd=pusher)
    root = tmp_path / "gate"
    git_("clone", "-q", str(origin), str(root), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git_("config", k, v, cwd=root)
    # a session left the checkout on its branch, its config changed there and in the working tree
    git_("switch", "-q", "-c", "session", cwd=root)
    (root / CONFIG_PATH).write_text(POLICY + '\n[agents]\nprompt = "/session"\n', encoding="utf-8")
    git_("commit", "-q", "-am", "session", cwd=root)
    (root / CONFIG_PATH).write_text(POLICY + '\n[agents]\nprompt = "/unsaved"\n', encoding="utf-8")
    # the default branch moved since the checkout last fetched
    config.write_text(POLICY + '\n[agents]\nprompt = "/head"\n', encoding="utf-8")
    git_("commit", "-q", "-am", "head", cwd=pusher)
    git_("push", "-q", "origin", "main", cwd=pusher)
    assert head_config(Git(root))["agents"] == {"prompt": "/head"}
    assert git_("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip() == "session"  # nothing moved


def test_s047_2_a_default_branch_without_a_config_proposes_nothing_and_says_why(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    git_("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    root = tmp_path / "gate"
    git_("clone", "-q", str(origin), str(root), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git_("config", k, v, cwd=root)
    git_("commit", "-q", "--allow-empty", "-m", "one", cwd=root)
    git_("push", "-q", "origin", "main", cwd=root)
    with pytest.raises(ReleaseError, match=r"no \.github/shipmill\.toml at origin/main to propose config upgrades"):
        head_config(Git(root))


def test_s047_3_under_observe_the_sweep_opens_nothing_and_closes_a_decided_upgrades_issue(checkout: Git) -> None:
    hub = FakeGitHub()
    decided = hub.create_issue(title(FRAGMENTS), f"{marker(FRAGMENTS)}\n", (UPGRADE_LABEL,))
    gone = hub.create_issue("old", "<!-- shipmill-upgrade: plugin-update 0.50.0 -->\n", (UPGRADE_LABEL,))
    source, seams = setup(OBSERVED, hub)
    decision = swept_tick(checkout, source, seams)
    assert hub.open_labelled_issues(UPGRADE_LABEL) == []  # agent-autonomy is pending, and not opened
    assert {decided, gone} <= set(hub.closed) and hub.edits == 0
    closed = {"id": "changelog-fragments", "issue": decided, "outcome": "closed"}
    withdrawn = {"id": "plugin-update", "issue": gone, "outcome": "withdrawn"}
    assert stored(checkout)["upgrades"] == {"proposed": [closed, withdrawn]}
    assert decision.upgrades == "upgrades: 1 closed, 1 withdrawn, [autonomy] upgrade = observe"


def test_s047_4_without_app_id_the_sweep_writes_nothing_and_status_lists_the_apply_command(checkout: Git) -> None:
    source, seams = setup()
    decision = swept_tick(checkout, source, seams, app=False)
    assert seams.github.issues == {} and "sweep" in source.reads
    assert not {"config", "as app", "reader"} & set(source.reads)  # nothing read or minted for it
    assert "upgrades" not in stored(checkout)
    assert decision.upgrades == "upgrades: none proposed, [agents] sets no app_id"
    # the pending upgrade shows in status, with the command that applies it (S-014-15)
    found = lines(facts(upgrades=[Offer(FRAGMENTS, None)]))
    at = found.index(f"  upgrade        changelog-fragments (shipmill 0.37.0): {FRAGMENTS.changes}")
    assert found[at + 1] == "                 fix: shipmill upgrade --apply changelog-fragments"


def test_s047_4_status_reads_the_pending_upgrade_from_the_checkout(tmp_path: Path) -> None:
    (tmp_path / CONFIG_PATH).parent.mkdir()
    (tmp_path / CONFIG_PATH).write_text(PENDING, encoding="utf-8")

    def gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    assert read_upgrades(REPO, tmp_path, gh) == (Offer(FRAGMENTS, None),)


def test_s047_5_a_tick_that_doesnt_sweep_runs_no_proposal(checkout: Git) -> None:
    source, seams = setup()
    source.tiers = {1: [INCIDENT]}
    swept_tick(checkout, source, seams)
    assert source.reads.count("as app") == 1
    for when, signature in ((LATER, "sig"), (LATER + dt.timedelta(minutes=15), "moved")):
        source.reads.clear()
        source.signature = signature  # no change, then a change: neither sweeps
        decision = tick(
            checkout,
            source,
            when,
            agents=cfg(app_id=7),
            app=lambda app_id: APP,
            app_env=lambda identity: {},
            upgrades=seams.upgrader(),
        )
        assert "sweep" not in source.reads and decision.upgrades is None
        assert not {"config", "as app", "reader"} & set(source.reads)
    assert stored(checkout)["upgrades"]["proposed"][0]["outcome"] == "opened"  # the last sweep's, kept


def test_s047_6_the_sweep_updates_the_release_workflows_issue_and_opens_no_second(checkout: Git) -> None:
    hub = FakeGitHub()
    opened = hub.create_issue(title(FRAGMENTS), f"{marker(FRAGMENTS)}\nwritten by the upgrade job\n", (UPGRADE_LABEL,))
    source, seams = setup(github=hub)
    decision = swept_tick(checkout, source, seams)
    assert [i.number for i in hub.open_labelled_issues(UPGRADE_LABEL)] == [opened]
    assert hub.edits == 1 and "written by the upgrade job" not in hub.issues[opened].body
    assert decision.upgrades == "upgrades: 1 updated"


@dataclass
class Refusing(FakeGitHub):
    """GitHub refusing the App's issue write, as gh reports a 403"""

    def create_issue(self, title: str, body: str, labels: Sequence[str] = ()) -> int:
        raise Forbidden("gh issue create failed: Resource not accessible by integration (HTTP 403)")


def test_s047_9_a_failed_proposal_changes_no_walk_or_launch_and_is_recorded(checkout: Git, tmp_path: Path) -> None:
    source, seams = setup(github=Refusing())
    source.tiers = {1: [INCIDENT]}
    failed = swept_tick(checkout, source, seams)
    other = Git(tmp_path / "other")
    other.root.mkdir()
    git_("init", "-q", str(other.root), cwd=tmp_path)
    other.run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    plain = tick(other, Source({1: [INCIDENT]}), agents=cfg(app_id=7), app=lambda app_id: APP, app_env=lambda i: {})
    assert (failed.action, failed.work, failed.tier, failed.walk) == (plain.action, plain.work, plain.tier, plain.walk)
    assert failed.action is Action.LAUNCH and "sweep" in source.reads
    error = stored(checkout)["upgrades"]["error"]
    assert error.startswith("upgrade changelog-fragments: gh issue create failed: Resource not accessible")
    assert error.endswith(f"if GitHub refused it (403): {upgrade_fix(REPO)}")
    assert failed.upgrades == f"upgrades failed: {error}"
    # factory's gate check reads it from sweep.json: a problem, with its error and fix
    read = _with_tick(gate(), checkout)
    assert read.upgrades == Proposals(error=error)
    (check, *_) = run_checks(fake_host(found=read))
    assert check.check == "gate" and not check.ok and check.value.endswith("; upgrade proposal failed")
    assert check.record()["fixes"] == [upgrade_fix(FACTORY_REPO)]
    assert any(line.startswith("  upgrades") and error in line for line in check.lines())


def test_s047_9_a_gate_check_reads_an_older_sweep_json_and_refuses_a_malformed_one(checkout: Git) -> None:
    path = state_dir(checkout) / SWEEP
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": NOW.isoformat(), "rows": [], "tag": None}), encoding="utf-8")
    read = _with_tick(gate(), checkout)
    assert read.upgrades is None and read.sweep_error is None
    assert run_checks(fake_host(found=read))[0].ok
    path.write_text(json.dumps({"at": NOW.isoformat(), "rows": [], "tag": None, "upgrades": {}}), encoding="utf-8")
    read = _with_tick(gate(), checkout)
    assert read.sweep_error is not None and "malformed" in read.sweep_error
    assert run_checks(fake_host(found=read))[0].value.startswith("ERROR: ")


def test_s047_9_sweep_json_keeps_the_proposals_through_a_round_trip(tmp_path: Path) -> None:
    done = Proposals((Proposed(FRAGMENTS.id, 4, Outcome.OPENED), Proposed(AUTONOMY.id, 5, Outcome.UNCHANGED)))
    for upgrades in (done, Proposals(error="upgrade x: refused"), None):
        Swept(NOW, (), None, upgrades).save(tmp_path / SWEEP)
        assert Swept.load(tmp_path / SWEEP) == Swept(NOW, (), None, upgrades)
    assert done.line() == "upgrades: 1 opened, 1 unchanged" and Proposals().line() == "upgrades: none"


def test_s047_10_the_swept_ticks_decision_line_names_the_outcome(checkout: Git) -> None:
    source, seams = setup()
    decision = swept_tick(checkout, source, seams)
    first = tick_lines(decision, None, (), (), False)[0]
    assert first.startswith("LAUNCH: ") and first.endswith("; upgrades: 1 opened")


def test_s047_10_a_dry_run_writes_no_issue_and_says_what_it_would_propose(checkout: Git) -> None:
    source, seams = setup()
    decision = swept_tick(checkout, source, seams, dry_run=True, sweep_now=True)
    assert seams.github.issues == {} and "as app" not in source.reads and "reader" in source.reads
    assert decision.upgrades == "upgrades: would propose changelog-fragments"
    assert not (state_dir(checkout) / SWEEP).exists()
    assert tick_lines(decision, None, (), (), True)[0].endswith("; upgrades: would propose changelog-fragments")
