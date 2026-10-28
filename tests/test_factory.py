"""Spec 044: `shipmill factory` reports this host's machinery, each check on its own, and
`shipmill status` keeps to the pipeline with one `factory` line"""

import dataclasses
import datetime as dt
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from shipmill import factory
from shipmill.app import Identity
from shipmill.cli import _parser, _status
from shipmill.errors import ReleaseError
from shipmill.factory import Host, Worktrees, worktrees_check
from shipmill.launchd import label
from shipmill.plugin import GateCli
from shipmill.status import Check, Gate, Main, Row, Verdict, host_checks, read_gate, report
from shipmill.version import Version
from shipmill.worktrees import Judged, Worktree
from shipmill.worktrees import Verdict as Kept
from tests import test_app
from tests.test_status_picture import (
    AGENTS,
    GATE,
    NOW,
    REPO,
    SHA,
    VERSION,
    VERSION_JSON,
    Fake,
    app_repo,
    facts,
    gate,
    host,
    job,
    lines,
)

CHECKOUT = Path("/src/web")
IN_SYNC = Main("main", SHA, SHA, 0, 0, True)
LABELS = ["gate", "sessions", "github app", "shipmill", "checkout", "worktrees", "prune"]  # prune: spec 045
STATUS_LABELS = [c for c in LABELS if c != "worktrees"]
SESSION = Row("AGENT_SESSION", "s1", "gate busy, started 1 min ago: shipmill acme/web", False)


def tree(path: str, verdict: Kept, reason: str | None, hours: int | None) -> Judged:
    return Judged(Worktree(Path("/src/web") / path, SHA, None), path, None, hours, verdict, reason)


CLEAN = Worktrees([tree(".", Kept.KEPT, "main checkout", None)], CHECKOUT, "main")


def fake_host(
    found: Gate = GATE,
    rows: Sequence[Row] = (VERSION,),
    sessions: Sequence[Row] = (SESSION,),
    main: Main = IN_SYNC,
    trees: Worktrees = CLEAN,
) -> Host:
    return Host(
        gate=lambda: found,
        gate_cli=lambda: None,
        rows=lambda section: sessions if section == "sessions" else rows,
        main=lambda: main,
        worktrees=lambda: trees,
        prune=lambda: None,
    )


def run_checks(found: Host) -> list[Check]:
    return factory.checks(REPO, found, "0.26.0", CHECKOUT, NOW, "shipmill")


def label_of(line: str) -> str:
    return line[2:16].strip()


def test_s044_1_status_prints_a_factory_line_after_landing_and_no_gate_app_or_shipmill_line() -> None:
    labels = [label_of(line) for line in lines(facts())[1:]]
    assert labels[-3:] == ["mode", "landing", "factory"]
    for moved in ("gate", "github app", "shipmill", "claude auth"):
        assert moved not in labels
    assert [label_of(line) for line in lines(facts(gate=gate(agents=None)))][-1] == "factory"


def test_s044_2_the_factory_line_reads_ok_or_the_problems_with_the_first() -> None:
    assert "  factory        OK" in lines(facts())
    two = facts(gate=gate(job=job(last_exit="2"), app=None, app_error="the App isn't installed"))
    assert "  factory        2 problem(s): gate failed: exit 2, launchd every 15 min; shipmill factory" in lines(two)
    # the fixes of the problems follow the line, so every reason's fix is still in the summary
    assert "                 fix: shipmill app-install acme/web" in lines(two)
    # the worktrees are never among status's checks
    assert [c.check for c in host_checks(facts())] == STATUS_LABELS


@pytest.mark.parametrize(
    ("changed", "verdict"),
    [
        (gate(job=job(loaded=False)), Verdict.STUCK),  # S-009-3
        (gate(job=job(last_run=NOW - dt.timedelta(hours=1))), Verdict.STUCK),
        (gate(job=None), Verdict.WAITS),  # no job on this Mac waits on you
        (gate(app=None, app_error="the App isn't installed"), Verdict.STUCK),  # S-009-4
        (gate(app=None, app_key=Path("/k.pem")), Verdict.IDLE),  # a key missing here is no reason
        (gate(agents=dataclasses.replace(AGENTS, app_id=None), app=None), Verdict.WAITS),  # S-009-5
        (gate(job=job(last="WAITING: session s waits on you: claude attach s")), Verdict.WAITS),
        (gate(launchd=False, job=None), Verdict.IDLE),
        (gate(cli=GateCli(Version.parse("0.25.0"), "uv tool upgrade shipmill")), Verdict.WAITS),
    ],
)
def test_s044_3_the_verdict_is_spec_009s_read_through_the_factory_checks(changed: Gate, verdict: Verdict) -> None:
    found = facts(gate=changed)
    done = report(found)
    assert done.verdict is verdict
    checks = host_checks(found)
    assert done.reasons == [r for c in checks for r in (*c.stuck, *c.yours)]
    assert report(facts(cli="0.25.0")).verdict is Verdict.WAITS  # an outdated CLI, the shipmill check's


def test_s044_4_a_check_that_fails_to_run_is_stuck_and_the_report_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, home = app_repo(tmp_path, app_id=False)
    plist = home / "Library" / "LaunchAgents" / f"{label(test_app.REPO)}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("not a plist\n", encoding="utf-8")
    fake = Fake(0)
    args = _parser().parse_args(["--repo", str(root), "status"])
    api, signer = test_app.FakeApi(), test_app.FakeSigner()
    assert _status(root, args, fake, api, signer, home=home, platform="darwin", now=NOW, login=host) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{test_app.REPO} (https://github.com/{test_app.REPO}): STUCK\n")
    factory_line = next(line for line in out.splitlines() if line.startswith("  factory "))
    assert factory_line.startswith("  factory        2 problem(s): gate ERROR: ")
    for shown in ("repo", "autonomy", "to triage", "open issues", "pull requests", "mode", "landing"):
        assert any(label_of(line) == shown for line in out.splitlines()), shown
    # S-044-5: status never runs `shipmill worktrees`
    assert not any("worktrees" in cmd for cmd in fake.seen)


BOT_OK = {"state": "BOT_OK", "subject": test_app.REPO, "detail": "release.yml ok", "agent": False}


class HostReadFails(Fake):
    """watch_state.py on a host where one section's read fails (#745): the full run fails on
    it unless --no-host leaves the host's rows out, and --host <section> fails on its own"""

    def __init__(self, section: str, error: str) -> None:
        super().__init__(0)
        self.section, self.error = section, error

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if not cmd[1].endswith("watch_state.py"):
            return super().__call__(cmd)
        self.seen.append(cmd)
        failing = subprocess.CompletedProcess(cmd, 1, "", f"Traceback (most recent call last):\n{self.error}\n")
        if "--host" in cmd:
            section = cmd[cmd.index("--host") + 1]
            if section == self.section:
                return failing
            out = "" if section == "sessions" else json.dumps(VERSION_JSON) + "\n"
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if "--no-host" not in cmd:
            return failing
        return subprocess.CompletedProcess(cmd, 0, json.dumps(BOT_OK) + "\n", "")


def status_with(tmp_path: Path, runner: Fake) -> int:
    root, home = app_repo(tmp_path)  # with the App and its key: off a Mac every other check passes
    args = _parser().parse_args(["--repo", str(root), "status"])
    api, signer = test_app.FakeApi(), test_app.FakeSigner()
    return _status(root, args, runner, api, signer, home=home, platform="linux", now=NOW, login=host)


@pytest.mark.parametrize(
    ("section", "error"),
    [
        ("sessions", "__main__.Refused: error: claude agents --json printed no JSON: Expecting value"),
        ("shipmill", "__main__.Refused: error: claude plugin list --json printed no JSON: Expecting value"),
    ],
)
def test_s044_4_a_failed_host_section_read_is_its_checks_error_and_the_report_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], section: str, error: str
) -> None:
    runner = HostReadFails(section, error)
    assert status_with(tmp_path, runner) == 0  # spec 008's code, of the rows read
    out = capsys.readouterr().out
    assert out.startswith(f"{test_app.REPO} (https://github.com/{test_app.REPO}): STUCK\n")
    shown = f"{section} ERROR: watch_state.py --host {section} failed (exit 1): {error}"
    factory_line = next(line for line in out.splitlines() if line.startswith("  factory "))
    assert factory_line.startswith(f"  factory        1 problem(s): {shown}; ")
    assert factory_line.endswith(" factory")
    for label_ in ("repo", "autonomy", "to triage", "open issues", "pull requests", "mode", "landing"):
        assert any(label_of(line) == label_ for line in out.splitlines()), label_
    # the full run leaves the host's rows to the sections, each read once on its own
    full = [c for c in runner.seen if c[1].endswith("watch_state.py") and "--host" not in c]
    assert len(full) == 1 and "--no-host" in full[0]
    assert [c[c.index("--host") + 1] for c in runner.seen if "--host" in c] == ["sessions", "shipmill"]
    assert not any("--host-wide" in c for c in runner.seen)  # status reads the repo's shadowing row (#764)


def test_s044_4_the_host_sections_rows_and_exit_code_join_the_pictures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Outdated(HostReadFails):
        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if "--host" in cmd and cmd[cmd.index("--host") + 1] == "shipmill":
                self.seen.append(cmd)
                row = {"state": "SHIPMILL_OUTDATED", "subject": "plugin user", "agent": False, "fix": "update it"}
                rows = [VERSION_JSON, {**row, "detail": "0.25.0, latest v0.26.0; update it"}]
                return subprocess.CompletedProcess(cmd, 1, "".join(json.dumps(r) + "\n" for r in rows), "")
            return super().__call__(cmd)

    assert status_with(tmp_path, Outdated("none", "")) == 1  # spec 008: an action row among a section's
    out = capsys.readouterr().out
    assert out.startswith(f"{test_app.REPO} (https://github.com/{test_app.REPO}): WAITS ON YOU\n")
    factory_line = next(line for line in out.splitlines() if line.startswith("  factory "))
    assert factory_line.startswith("  factory        1 problem(s): shipmill ")
    assert "plugin user 0.26.0, local 0.26.0, update available: update it; " in factory_line


def test_s044_4_a_failed_gate_cli_read_is_the_shipmill_checks_error() -> None:
    found = facts(gate=gate(cli_error="state/cli.json is not JSON"))
    assert report(found).verdict is Verdict.STUCK
    assert "  factory        1 problem(s): shipmill ERROR: state/cli.json is not JSON; shipmill factory" in lines(found)


def test_s044_5_status_reads_no_worktree_row() -> None:
    from shipmill.status import PLACED

    assert "WORKTREE_STALE" not in PLACED


def test_s044_6_factory_prints_its_checks_in_order_with_spec_009s_values() -> None:
    found = run_checks(fake_host())
    assert [c.check for c in found] == LABELS
    text = factory.text(found).splitlines()
    assert [label_of(line) for line in text] == [
        "gate",
        "sessions",
        "github app",
        "shipmill",
        "checkout",
        "worktrees",
        "prune",
    ]
    assert text == [
        "  gate           OK, launchd every 15 min",
        "  sessions       1: gate busy (s1)",
        "  github app     active",
        "  shipmill       0.26.0, up to date",
        "  checkout       in sync",
        "  worktrees      0 removable, 1 kept",
        "  prune          never ran here",
    ]
    assert factory.exit_code(found) == 0


def test_s044_7_the_worktrees_line_counts_and_lists_kept_shipmill_ones_over_seven_days() -> None:
    week = 7 * 24
    found = Worktrees(
        [
            tree(".", Kept.KEPT, "main checkout", None),
            tree("tmp/shipmill-gate", Kept.KEPT, "current checkout", week * 4),
            tree("tmp/mine", Kept.KEPT, "not a shipmill worktree", week * 4),
            tree(".claude/worktrees/done", Kept.REMOVABLE, None, week * 4),
            tree(".claude/worktrees/week", Kept.KEPT, "detached HEAD", week),
            tree("tmp/wt-old", Kept.KEPT, "2 commit(s) not landed", week + 1),
            tree("tmp/wt a", Kept.KEPT, "open PR #7", week * 3),
        ],
        Path("/work/r"),
        "trunk",
    )
    check = worktrees_check(found)
    assert (check.ok, check.value) == (False, "1 removable, 6 kept")
    assert check.lines() == [
        "  worktrees      1 removable, 6 kept",
        "                 tmp/wt-old: 2 commit(s) not landed; created 7d ago",
        "                 fix: see the work not landed: git -C /work/r/tmp/wt-old log origin/trunk..HEAD; then push it"
        " and open a pull request, or remove it: git -C /work/r worktree remove /work/r/tmp/wt-old",
        "                 tmp/wt a: open PR #7; created 21d ago",
        "                 fix: see the work not landed: git -C '/work/r/tmp/wt a' log origin/trunk..HEAD; then push it"
        " and open a pull request, or remove it: git -C /work/r worktree remove '/work/r/tmp/wt a'",
    ]
    assert worktrees_check(CLEAN).ok


def test_s044_8_a_check_that_fails_to_run_prints_its_error_and_the_rest_still_run() -> None:
    def broken() -> Gate:
        raise ReleaseError("launchctl print failed (exit 113): Could not find service\nmore detail")

    def unreadable(section: str) -> Sequence[Row]:
        if section == "shipmill":
            raise subprocess.CalledProcessError(2, ["claude"])
        return [SESSION]

    found = run_checks(dataclasses.replace(fake_host(), gate=broken, rows=unreadable))
    assert [(c.check, c.ok) for c in found] == [
        ("gate", False),
        ("sessions", True),
        ("github app", False),
        ("shipmill", False),
        ("checkout", True),
        ("worktrees", True),
        ("prune", True),
    ]
    text = factory.text(found).splitlines()
    assert text[0] == "  gate           ERROR: launchctl print failed (exit 113): Could not find service"
    assert text[2] == "  github app     ERROR: launchctl print failed (exit 113): Could not find service"
    assert text[3].startswith("  shipmill       ERROR: Command '['claude']' returned non-zero exit status 2")
    assert text[4:] == [
        "  checkout       in sync",
        "  worktrees      0 removable, 1 kept",
        "  prune          never ran here",
    ]


def test_s044_8_watch_states_host_rows_that_fail_are_the_checks_error() -> None:
    def failing(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        assert cmd[-3:] == ["--host", "sessions", "--json"]
        return subprocess.CompletedProcess(cmd, 2, "", "Traceback\nerror: claude agents --json printed no JSON\n")

    with pytest.raises(ReleaseError, match="--host sessions failed \\(exit 2\\): error: claude agents"):
        factory.read_rows(REPO, CHECKOUT, "sessions", failing, wide=True)
    assert factory.host_command(REPO, CHECKOUT, "shipmill", wide=True)[0] == sys.executable


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({}, 0),
        ({"found": gate(job=job(last_exit="2"))}, 1),
        ({"found": gate(job=None)}, 1),  # no job on this Mac: a problem with its fix
        ({"main": Main("main", SHA, "b" * 40, 1, 2, True)}, 1),  # a diverged checkout
        ({"trees": Worktrees([tree("tmp/wt-x", Kept.KEPT, "detached HEAD", 8 * 24)], CHECKOUT, "main")}, 1),
        ({"rows": (VERSION, Row("SKILL_SHADOWED", "x", "a copy", False, "rm -r /h/.claude/skills/x"))}, 1),
        ({"found": gate(launchd=False, job=None)}, 0),
        ({"main": Main("main", SHA, "b" * 40, 0, 2, True)}, 0),  # behind is the repo line's to catch up
    ],
)
def test_s044_9_factory_exits_1_on_a_problem_or_a_failed_check(changed: dict[str, object], code: int) -> None:
    found = run_checks(fake_host(**changed))  # type: ignore[arg-type]
    assert factory.exit_code(found) == code

    def broken() -> Main:
        raise ReleaseError("git fetch failed")

    assert factory.exit_code(run_checks(dataclasses.replace(fake_host(), main=broken))) == 1


def test_s044_10_json_prints_each_check_with_ok_value_and_fixes_in_order() -> None:
    found = run_checks(fake_host(found=gate(job=job(last_exit="2"))))
    printed = json.loads(factory.as_json(found))
    assert list(printed) == ["checks"]
    assert [c["check"] for c in printed["checks"]] == LABELS
    assert all(set(c) == {"check", "ok", "value", "fixes"} for c in printed["checks"])
    assert printed["checks"][0] == {
        "check": "gate",
        "ok": False,
        "value": "failed: exit 2, launchd every 15 min",
        "fixes": ["tail -n 50 /u/gate.log"],
    }
    stale = Worktrees([tree("tmp/wt-x", Kept.KEPT, "detached HEAD", 8 * 24)], CHECKOUT, "main")
    (record,) = [c for c in json.loads(factory.as_json(run_checks(fake_host(trees=stale))))["checks"] if not c["ok"]]
    assert record["check"] == "worktrees" and record["fixes"][0].startswith("see the work not landed: git -C ")
    assert _parser().parse_args(["factory", "--json"]).json


def test_s044_11_off_a_mac_the_launchd_checks_cant_check_here_and_are_no_problem(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text('[agents]\nprompt = "/t"\n', encoding="utf-8")

    def no_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"off a Mac no launchd command runs: {cmd}")

    def no_app(app_id: int, key: Path) -> Identity:
        raise AssertionError("no app_id: the App check isn't run")

    off_mac = read_gate(REPO, tmp_path, tmp_path / "home", "linux", no_command, no_app, 501)
    assert (off_mac.launchd, off_mac.job, off_mac.job_error) == (False, None, None)
    found = run_checks(fake_host(found=off_mac))
    assert found[0].lines()[0] == "  gate           can't check here: no launchd"
    assert found[0].ok
    in_status = facts(gate=dataclasses.replace(GATE, launchd=False, job=None))
    assert "  factory        can't check here: no launchd" in lines(in_status)
    assert report(in_status).verdict is Verdict.IDLE


def test_agent_config_without_app_reads_as_a_problem_in_both_commands() -> None:
    no_app = gate(agents=dataclasses.replace(AGENTS, app_id=None), app=None)
    found = run_checks(fake_host(found=no_app))
    assert [c.check for c in found if not c.ok] == ["github app"]
    assert "  factory        1 problem(s): github app not active; shipmill factory" in lines(facts(gate=no_app))
