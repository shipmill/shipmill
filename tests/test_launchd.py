"""The launchd job that runs the gate on a Mac"""

import os
import plistlib
from pathlib import Path

import pytest

from shipmill.cli import _parser
from shipmill.errors import ReleaseError
from shipmill.launchd import (
    BASE_PATH,
    DEFAULT_TOOL,
    OLD_TOOL,
    build,
    cli_fix,
    find_tool,
    is_temporary,
    job_tool,
    label,
    read_job,
)


def tools(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True)
    for name in names:
        tool = folder / name
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
    return folder


def nothing(folder: str) -> bool:
    return False


def test_the_label_is_safe_and_per_repo() -> None:
    assert label("romamo/Treaty_X") == "dev.shipmill.gate.romamo.treaty-x"
    with pytest.raises(ReleaseError, match="owner/name"):
        label("treaty")


def test_temporary_folders_are_skipped() -> None:
    assert is_temporary("/var/folders/xs/abc/T/cmux-cli-shims/6AA9")
    assert is_temporary("/tmp/shims")
    assert not is_temporary("/opt/homebrew/bin")


def test_a_tool_is_found_past_a_skipped_shim(tmp_path: Path) -> None:
    shim = tools(tmp_path / "shims", "claude")
    real = tools(tmp_path / "bin", "claude")
    path = os.pathsep.join([str(shim), str(real)])
    assert find_tool("claude", path, skip=lambda f: f == str(shim)) == real / "claude"
    with pytest.raises(ReleaseError, match="gh is not on PATH"):
        find_tool("gh", path, skip=nothing)


def test_the_job_runs_the_gate_with_a_stable_path(tmp_path: Path) -> None:
    local = tools(tmp_path / "local", "claude", "uvx")
    brew = tools(tmp_path / "brew", "gh", "git")
    path = os.pathsep.join([str(local), str(brew)])
    checkout = tmp_path / "treaty-gate"
    job = build("romamo/treaty", checkout, 15, "git+x@v0", ["--permission-mode=auto"], tmp_path, path, nothing)
    data = plistlib.loads(job.document)
    assert data["Label"] == job.label == "dev.shipmill.gate.romamo.treaty"
    assert data["ProgramArguments"] == [
        str(local / "uvx"),
        "--from",
        "git+x@v0",
        "shipmill",
        "--repo",
        str(checkout),
        "gate",
        "romamo/treaty",
        "--refresh",
        "--claude-arg=--permission-mode=auto",
    ]
    assert data["StartInterval"] == 900 and data["WorkingDirectory"] == str(checkout)
    assert data["EnvironmentVariables"]["PATH"].split(os.pathsep) == [str(local), str(brew), *BASE_PATH]
    assert job.plist == tmp_path / "Library" / "LaunchAgents" / "dev.shipmill.gate.romamo.treaty.plist"
    assert data["StandardOutPath"] == data["StandardErrorPath"] == str(job.log)


@pytest.mark.parametrize(
    "extra", [["--permission-mode=auto"], ["--allowedTools", "Bash(npm *)"], ["--model", "opus", "-v"]]
)
def test_launchd_claude_args_parse_back_as_the_gates(tmp_path: Path, extra: list[str]) -> None:
    """#192: each --claude-arg reaches the job's gate as the same flag. A `--claude-arg`
    followed by a separate dash-led value is an argparse error, which failed every tick"""
    path = tools(tmp_path / "bin", "claude", "uvx", "gh", "git")
    job = build("romamo/treaty", tmp_path / "gate", 15, "x", extra, tmp_path, str(path), nothing)
    args = plistlib.loads(job.document)["ProgramArguments"]
    parsed = _parser().parse_args(args[args.index("--repo") :])
    assert parsed.command == "gate" and parsed.claude_arg == extra


def test_the_interval_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="5..1440"):
        build("romamo/treaty", tmp_path, 1, "x", [], tmp_path, "", nothing)


def test_s031_18_the_job_runs_shipmill_at_latest_unless_tool_names_another(tmp_path: Path) -> None:
    assert DEFAULT_TOOL == "shipmill@latest"
    parser = _parser()
    assert parser.parse_args(["launchd", "romamo/treaty"]).tool == "shipmill@latest"
    assert parser.parse_args(["launchd", "romamo/treaty", "--tool", "shipmill==0.50.0"]).tool == "shipmill==0.50.0"
    path = tools(tmp_path / "bin", "claude", "uvx", "gh", "git")
    job = build("romamo/treaty", tmp_path / "gate", 15, DEFAULT_TOOL, [], tmp_path, str(path), nothing)
    args = plistlib.loads(job.document)["ProgramArguments"]
    assert args[1:4] == ["--from", "shipmill@latest", "shipmill"]
    assert job_tool(plistlib.loads(job.document)) == "shipmill@latest"


def written(
    tmp_path: Path, tool: str, every: int = 15, extra: list[str] | None = None, key: Path | None = None
) -> Path:
    """The repo's job, written where launchd reads it under tmp_path as home"""
    path = tools(tmp_path / "bin", "claude", "uvx", "gh", "git")
    job = build("romamo/treaty", tmp_path / "gate", every, tool, extra or [], tmp_path, str(path), nothing, key)
    job.plist.parent.mkdir(parents=True)
    job.plist.write_bytes(job.document)
    return tmp_path / "gate"


def test_s031_17_a_job_on_the_old_v0_source_is_written_again_by_the_latest(tmp_path: Path) -> None:
    gate = written(tmp_path, OLD_TOOL, every=30, extra=["--model", "opus"], key=Path("/k/app.pem"))
    assert OLD_TOOL == "git+https://github.com/shipmill/shipmill@v0"
    assert cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty") == (
        f"uvx shipmill@latest --repo {gate} launchd romamo/treaty --every 30 --app-key /k/app.pem"
        " --claude-arg=--model --claude-arg=opus"
    )


def test_s031_17_a_default_job_keeps_its_flags_short(tmp_path: Path) -> None:
    gate = written(tmp_path, OLD_TOOL)
    assert cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty") == (
        f"uvx shipmill@latest --repo {gate} launchd romamo/treaty"
    )


@pytest.mark.parametrize(
    "tool", ["shipmill==0.50.0", "git+https://github.com/romamo/shipmill@v0", "git+https://example.com/fork@main"]
)
def test_s031_17_a_job_on_any_source_but_latest_is_written_again(tmp_path: Path, tool: str) -> None:
    """#570: `uv tool upgrade shipmill` never changes a launchd job, whatever its source"""
    gate = written(tmp_path, tool, key=Path("/k/app.pem"))
    assert cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty") == (
        f"uvx shipmill@latest --repo {gate} launchd romamo/treaty --app-key /k/app.pem"
    )


def test_s031_17_the_rewrite_quotes_paths_with_spaces(tmp_path: Path) -> None:
    home = tmp_path / "my home"
    gate = written(home, "shipmill==0.50.0", key=home / "app key.pem")
    assert cli_fix(read_job("romamo/treaty", home), "romamo/treaty") == (
        f"uvx shipmill@latest --repo '{gate}' launchd romamo/treaty --app-key '{home / 'app key.pem'}'"
    )


def test_s031_17_a_job_on_latest_is_run_again_now(tmp_path: Path) -> None:
    """Its uvx looks shipmill@latest up on every run, so the next run catches up; the fix runs it now"""
    written(tmp_path, DEFAULT_TOOL)
    assert cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty") == (
        f"launchctl kickstart gui/{os.getuid()}/dev.shipmill.gate.romamo.treaty"
    )


def test_s031_17_a_gate_without_a_job_is_a_tool_install_uv_upgrades(tmp_path: Path) -> None:
    assert cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty") == "uv tool upgrade shipmill"


def test_a_plist_that_is_not_a_job_is_refused(tmp_path: Path) -> None:
    plist = tmp_path / "Library" / "LaunchAgents" / "dev.shipmill.gate.romamo.treaty.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps(["not", "a", "job"]))
    with pytest.raises(ReleaseError, match="not a launchd job"):
        read_job("romamo/treaty", tmp_path)
    plist.write_bytes(plistlib.dumps({"Label": "x", "ProgramArguments": "uvx"}))
    with pytest.raises(ReleaseError, match="ProgramArguments"):
        cli_fix(read_job("romamo/treaty", tmp_path), "romamo/treaty")
