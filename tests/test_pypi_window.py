"""#597: a release's tag, `@v0`, and the marketplace ref move minutes before PyPI serves the
package, and uv caches PyPI's index up to ten minutes. A skill script's `uvx shipmill==<v>` in
that window retries once with the index refreshed, then watch_state.py reports the wait as a
PYPI_WAIT row instead of exiting 2; and a launchd job on the floating `@v0` git source, which
never lags, gets its rewrite to shipmill@latest whether or not the gate's CLI lags"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import status as shipmill_status
from shipmill.doctor import Check, PluginRow, plugin_checks
from shipmill.gate import parse_findings
from shipmill.launchd import DEFAULT_TOOL, OLD_TOOL, build, gate_cli, read_job
from shipmill.plugin import GateCli, publish_fix
from shipmill.status import report
from shipmill.version import Version
from tests.test_status_picture import facts, lines

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
INTAKE = ROOT / "skills" / "product-intake" / "scripts" / "intake_state.py"
UPSTREAM = ROOT / "skills" / "github-issue-triage" / "scripts" / "upstream_state.py"
REPO = "o/r"


def load(path: Path, name: str) -> ModuleType:
    sys.path.insert(0, str(path.parent))  # upstream_state.py imports its sibling scripts
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses look their module up by name
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load(SCRIPT, "watch_state_597")


@pytest.fixture(scope="module")
def version(ws: ModuleType) -> str:
    found: str = ws.plugin_version()
    return found


def no_version(version: str) -> str:
    """uv's stderr, as `uvx shipmill==0.0.999 --version` prints it: wrapped at 80 columns"""
    return (
        "  × No solution found when resolving tool dependencies:\n"
        f"  ╰─▶ Because there is no version of shipmill=={version} and you require\n"
        f"      shipmill=={version}, we can conclude that your requirements are\n"
        "      unsatisfiable.\n"
    )


NETWORK = (
    "error: Failed to fetch: `https://pypi.org/simple/shipmill/`\n"
    "  Caused by: Request failed after 3 retries\n"
    "  Caused by: error sending request for url (https://pypi.org/simple/shipmill/)\n"
    "  Caused by: dns error: failed to lookup address information\n"
)


def other_resolution(version: str) -> str:
    """Another package missing, not shipmill: never PyPI's wait for the release"""
    return (
        "  × No solution found when resolving tool dependencies:\n"
        f"  ╰─▶ Because there is no version of click==99.0 and shipmill=={version} depends on\n"
        f"      click==99.0, we can conclude that shipmill=={version} cannot be used.\n"
    )


def proc(cmd: list[str], code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, code, out, err)


class Uvx:
    """uvx's answers in turn, every call recorded"""

    def __init__(self, *answers: tuple[int, str, str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        code, out, err = self.answers.pop(0)
        return proc(cmd, code, out, err)


# -- the retry ------------------------------------------------------------------------------


def test_only_uvs_no_version_error_for_the_pinned_release_reads_as_unserved(ws: ModuleType, version: str) -> None:
    cmd = ["uvx", f"shipmill=={version}", "plan"]
    assert ws.unserved(cmd, proc(cmd, 1, err=no_version(version))) == version
    assert ws.unserved(cmd, proc(cmd, 2, err=no_version(version).replace("\n      ", " "))) == version  # unwrapped
    assert ws.unserved(cmd, proc(cmd, 1, err=NETWORK)) is None
    assert ws.unserved(cmd, proc(cmd, 1, err=other_resolution(version))) is None
    assert ws.unserved(cmd, proc(cmd, 1, err=no_version("0.0.1"))) is None  # another version than the call's
    assert ws.unserved(cmd, proc(cmd, 0, err=no_version(version))) is None  # it ran
    tool = ["uvx", "--from", f"shipmill=={version}", "shipmill", "plan"]  # --tool: unchanged
    assert ws.unserved(tool, proc(tool, 1, err=no_version(version))) is None


def test_the_pinned_cli_retries_once_with_the_index_refreshed(ws: ModuleType, version: str) -> None:
    cmd = ["uvx", f"shipmill=={version}", "--repo", "/c", "worktrees", "--json"]
    uvx = Uvx((1, "", no_version(version)), (0, "{}", ""))
    assert ws.pinned(cmd, uvx).stdout == "{}"
    assert uvx.calls == [cmd, ["uvx", "--refresh-package", "shipmill", *cmd[1:]]]


@pytest.mark.parametrize("err", [NETWORK, "x"], ids=["network", "other"])
def test_any_other_uvx_failure_is_not_retried(ws: ModuleType, version: str, err: str) -> None:
    cmd = ["uvx", f"shipmill=={version}", "plan"]
    uvx = Uvx((1, "", err))
    assert ws.pinned(cmd, uvx).returncode == 1 and uvx.calls == [cmd]


def test_a_second_no_version_raises_the_wait_and_any_other_failure_stops_the_watch(
    ws: ModuleType, version: str
) -> None:
    cmd = ["uvx", f"shipmill=={version}", "plan"]
    with pytest.raises(ws.PypiWait) as waited:
        ws.pinned_run(cmd, Uvx((1, "", no_version(version)), (1, "", no_version(version))))
    assert waited.value.version == version
    with pytest.raises(SystemExit) as stopped:
        ws.pinned_run(cmd, Uvx((1, "", no_version(version)), (1, "", NETWORK)))
    assert stopped.value.code == 2


# -- the PYPI_WAIT row ----------------------------------------------------------------------


def test_the_row_waits_on_pypi_with_the_publish_fix_and_starts_nothing(ws: ModuleType, version: str) -> None:
    row = ws.pypi_wait_row(version, "the release plan")
    assert (row.state, row.subject, row.detail) == (
        "PYPI_WAIT",
        f"shipmill=={version}",
        "waits for PyPI; not read: the release plan",
    )
    assert row.fix == publish_fix(Version.parse(version))  # doctor's and status's wording (#569)
    assert row.json()["agent"] is False and "PYPI_WAIT" not in ws.ACTION | ws.AGENT
    assert "PYPI_WAIT" in str(ws.__doc__)
    found = parse_findings(json.dumps(row.json()))  # the gate reads it, and starts no session for it
    assert [(f.state, f.agent) for f in found] == [("PYPI_WAIT", False)]


def test_the_waits_of_one_pass_merge_into_one_row_per_version(ws: ModuleType, version: str) -> None:
    rows = [
        ws.pypi_wait_row(version, "the release plan"),
        ws.Row("BOT_OK", "release.yml", ""),
        ws.pypi_wait_row(version, "worktrees"),
        ws.pypi_wait_row(version, "milestones"),
    ]
    merged = ws.merged_waits(rows)
    assert [(r.state, r.detail) for r in merged] == [
        ("PYPI_WAIT", "waits for PyPI; not read: the release plan, worktrees, milestones"),
        ("BOT_OK", ""),
    ]


def test_status_reads_the_row_under_other_with_its_fix_and_no_verdict(ws: ModuleType, version: str) -> None:
    """Report only: the tick's own PYPI_WAIT already makes status wait on you while PyPI 404s"""
    row = ws.pypi_wait_row(version, "worktrees")
    parsed = shipmill_status.parse_rows(json.dumps(row.json()))
    assert (parsed[0].state, parsed[0].agent, parsed[0].fix) == ("PYPI_WAIT", False, row.fix)
    assert "PYPI_WAIT" not in {*shipmill_status.STUCK_ROWS, *shipmill_status.YOURS_ROWS, *shipmill_status.PLACED}
    found = facts(parsed[0])
    assert report(found).reasons == []
    text = lines(found)
    at = next(i for i, line in enumerate(text) if f"PYPI_WAIT shipmill=={version} waits for PyPI" in line)
    assert text[at].lstrip().startswith("other") and row.fix in text[at + 1]


class Spawned:
    """watch_state's spawn for a plan: uvx's answers in turn, git worktree add and remove pass"""

    def __init__(self, *answers: tuple[int, str, str]) -> None:
        self.uvx = Uvx(*answers)
        self.calls: list[list[str]] = []

    def __call__(
        self, cmd: list[str], cwd: Path | None, env: dict[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        return self.uvx(cmd) if cmd[0] == "uvx" else proc(cmd, 0)


def plan_checkout(tmp_path: Path) -> Path:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text('mode = "release"\n')
    return tmp_path


def test_a_plan_pypi_doesnt_serve_yet_is_the_row_in_place_of_the_plan(
    ws: ModuleType, version: str, tmp_path: Path
) -> None:
    spawned = Spawned((1, "", no_version(version)), (1, "", no_version(version)))
    due, rows = ws.bot_plan(REPO, plan_checkout(tmp_path), ws.POLICY, "main", None, "release.yml", spawned)
    assert due is None
    assert [(r.state, r.detail) for r in rows] == [("PYPI_WAIT", "waits for PyPI; not read: the release plan")]
    assert [c[:3] for c in spawned.calls] == [
        ["git", "worktree", "add"],
        ["uvx", f"shipmill=={version}", "plan"],
        ["uvx", "--refresh-package", "shipmill"],
        ["git", "worktree", "remove"],
    ]


def test_a_plan_the_refreshed_index_lists_reads_its_release(ws: ModuleType, version: str, tmp_path: Path) -> None:
    decision = json.dumps({"action": "release", "reason": "stable 1.0.0: main quiet", "lane": "stable"})
    spawned = Spawned((1, "", no_version(version)), (0, decision, ""))
    due, rows = ws.bot_plan(REPO, plan_checkout(tmp_path), ws.POLICY, "main", None, "release.yml", spawned)
    assert (due, rows) == (ws.Due("stable 1.0.0: main quiet", "stable"), [])


@pytest.mark.parametrize("tool", [None, "shipmill==1.2.3"], ids=["pinned", "tool"])
def test_a_plan_failing_on_anything_else_still_stops_the_watch(
    ws: ModuleType, version: str, tmp_path: Path, tool: str | None
) -> None:
    err = NETWORK if tool is None else no_version(version)  # --tool's form is never read as the wait
    with pytest.raises(SystemExit):
        ws.bot_plan(REPO, plan_checkout(tmp_path), ws.POLICY, "main", tool, "release.yml", Spawned((1, "", err)))


def test_worktrees_and_milestones_pypi_doesnt_serve_are_the_row(ws: ModuleType, version: str, tmp_path: Path) -> None:
    def waiting(cmd: list[str]) -> str:
        return str(ws.pinned_run(cmd, Uvx((1, "", no_version(version)), (1, "", no_version(version)))))

    rows = ws.stale_worktrees(tmp_path, None, "main", waiting)
    assert [(r.state, r.detail) for r in rows] == [("PYPI_WAIT", "waits for PyPI; not read: worktrees")]
    (tmp_path / "m").mkdir()
    policy = plan_checkout(tmp_path / "m") / ws.POLICY
    policy.write_text("[lanes.stable]\nmilestone = true\n")
    rows = ws.milestones(tmp_path / "m", ws.POLICY, None, waiting)
    assert [(r.state, r.detail) for r in rows] == [("PYPI_WAIT", "waits for PyPI; not read: milestones")]


def test_plans_whose_goals_pypi_doesnt_serve_raise_the_wait(ws: ModuleType, version: str, tmp_path: Path) -> None:
    failed = f"error: shipmill product show failed with exit 1: {no_version(version).strip()}"

    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        return proc(cmd, 2, err=failed + "\n")

    with pytest.raises(ws.PypiWait):
        ws.plans_run(REPO, tmp_path, None, None, None, execute)
    with pytest.raises(SystemExit, match="2"):  # --tool's form: as before
        ws.plans_run(REPO, tmp_path, "shipmill==1.2.3", None, None, execute)


def test_upstream_reports_pypi_doesnt_serve_are_the_row_not_unreadable(
    ws: ModuleType, version: str, tmp_path: Path
) -> None:
    def execute(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        return proc(cmd, 2, err=no_version(version))

    rows = ws.upstream_rows(REPO, tmp_path, None, execute)
    assert [(r.state, r.detail) for r in rows] == [("PYPI_WAIT", "waits for PyPI; not read: upstream reports")]

    def broken(cmd: list[str], cwd: Path | None, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
        return proc(cmd, 2, err=NETWORK)

    assert [r.state for r in ws.upstream_rows(REPO, tmp_path, None, broken)] == ["UPSTREAM_UNREADABLE"]


def test_the_intake_and_upstream_scripts_retry_the_pinned_cli_once(version: str, tmp_path: Path) -> None:
    intake = load(INTAKE, "intake_state_597")
    goals = json.dumps({"goals": [{"id": "G-1", "text": "ship"}]})
    uvx = Uvx((1, "", no_version(version)), (0, goals, ""))
    assert [g.id for g in intake.uvx_goals(None, uvx)()] == ["G-1"]
    assert uvx.calls[1][:4] == ["uvx", "--refresh-package", "shipmill", f"shipmill=={version}"]
    upstream = load(UPSTREAM, "upstream_state_597")
    uvx = Uvx((1, "", no_version(version)), (0, json.dumps({"data": {}}), ""))
    assert upstream.default_readers(REPO, tmp_path, uvx)("o/other")("query", {}) == {"data": {}}
    assert uvx.calls[1][:4] == ["uvx", "--refresh-package", "shipmill", f"shipmill=={version}"]


# -- a launchd job on the floating @v0 source -----------------------------------------------


def job(tmp_path: Path, tool: str) -> dict[str, object] | None:
    folder = tmp_path / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("claude", "uvx", "gh", "git"):
        (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    built = build(REPO, tmp_path / "gate", 30, tool, ["--model", "opus"], tmp_path, str(folder), lambda f: False)
    built.plist.parent.mkdir(parents=True)
    built.plist.write_bytes(built.document)
    return read_job(REPO, tmp_path)


LATEST = Version.parse("0.66.0")


def test_a_job_on_v0_owes_its_rewrite_while_its_cli_is_current(tmp_path: Path) -> None:
    cli = gate_cli(LATEST, job(tmp_path, OLD_TOOL), REPO)
    rewrite = f"uvx shipmill@latest --repo {tmp_path / 'gate'} launchd {REPO} --every 30"
    rewrite += " --claude-arg=--model --claude-arg=opus"
    assert cli.fix == rewrite and not cli.lags(LATEST) and cli.owes(LATEST)
    assert cli.line(LATEST) == (
        f"the gate's launchd job runs shipmill from {OLD_TOOL}, a git tag rather than the release PyPI serves;"
        f" move it to shipmill@latest: {rewrite}"
    )


@pytest.mark.parametrize("tool", [DEFAULT_TOOL, "shipmill==0.66.0"], ids=["latest", "pinned"])
def test_a_job_on_latest_or_a_pinned_tool_owes_nothing_while_current(tmp_path: Path, tool: str) -> None:
    cli = gate_cli(LATEST, job(tmp_path, tool), REPO)
    assert not cli.owes(LATEST)
    if tool == DEFAULT_TOOL:  # S-031-17: it keeps its kickstart fix
        assert cli.fix == f"launchctl kickstart gui/{os.getuid()}/dev.shipmill.gate.o.r"


def test_a_tool_install_keeps_uv_tool_upgrade(tmp_path: Path) -> None:
    assert gate_cli(Version.parse("0.65.0"), None, REPO) == GateCli(Version.parse("0.65.0"), "uv tool upgrade shipmill")
    assert not gate_cli(LATEST, None, REPO).owes(LATEST)


def session_rows(ws: ModuleType) -> list[PluginRow]:
    rows = ws.plugin_rows([{"id": "shipmill@shipmill", "scope": "user", "version": "0.66.0"}], None, "v0.66.0", [], [])
    return [PluginRow(r.state, r.subject, r.detail) for r in rows]


def test_doctor_warns_on_a_job_on_v0_with_its_rewrite(ws: ModuleType, tmp_path: Path) -> None:
    cli = gate_cli(LATEST, job(tmp_path, OLD_TOOL), REPO)
    found = [c for c in plugin_checks(lambda: session_rows(ws), cli) if c.name == "gate cli"]
    assert found == [Check("WARN", "gate cli", cli.line(LATEST))]
    current = gate_cli(LATEST, job(tmp_path / "l", DEFAULT_TOOL), REPO)
    assert [c for c in plugin_checks(lambda: session_rows(ws), current) if c.name == "gate cli"] == []
