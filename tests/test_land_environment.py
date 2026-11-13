"""Spec 054: land.yml's `land-environment` input, which hands the environment's App key to
`shipmill land --app-key`, and `shipmill init --land-as-app`, which opts the caller in.

land.yml is read with the eval suite's strict YAML reader, and its key and land steps run here
as bash with the env GitHub gives them and a fake uvx, so their exits, files, and arguments
are proved, not only their text. actionlint accepting the file is CI's lint job (S-054-1)."""

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from shipmill import evals
from shipmill.cli import main
from shipmill.doctor import CALLER, OPERATE_CALLER
from shipmill.errors import ReleaseError
from shipmill.landing import land_environment

from .conftest import Repo
from .test_runs_on import _jobs, _unscheduled

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "land.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: Any = evals._Yaml(TEXT, "land.yml").mapping()
JOB: dict[str, Any] = DOC["jobs"]["land"]
STEPS: list[dict[str, Any]] = JOB["steps"]
KEY_STEP = "Write the App's key"
LAND_STEP = "Land, tag, and publish"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0secret\nline2secret\n-----END RSA PRIVATE KEY-----"
TODAY = ["--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill", "land"]
TODAY += ["--lane", "stable", "--version", "1.2.0", "--sha", "abc123", "--base", "def456"]
LAND_ENV = {
    "TOOL": "git+https://github.com/shipmill/shipmill@v0",
    "LANE": "stable",
    "VERSION": "1.2.0",
    "SHA": "abc123",
    "BASE": "def456",
    "GH_TOKEN": "t",
}
APP_POLICY = '\n[agents]\nprompt = "/t"\napp_id = 42\n'
OPT_IN = "      land-environment: shipmill-land\n"


def _step(name: str) -> dict[str, Any]:
    found = [s for s in STEPS if s.get("name") == name]
    assert len(found) == 1, f"one step named {name!r}"
    return found[0]


def _script(name: str) -> str:
    """A step's run script as GitHub runs it: the block scalar, dedented"""
    lines = TEXT.splitlines()
    start = lines.index(f"      - name: {name}")
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


def _bash(
    name: str, tmp_path: Path, env: dict[str, str], uvx_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run a step's script as `shell: bash` does (`bash --noprofile --norc -eo pipefail`), with
    a uvx on PATH that records its arguments, one per line, in tmp_path/uvx-args"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uvx = bin_dir / "uvx"
    script = f'#!/bin/sh\nprintf \'%s\\n\' "$@" > "{tmp_path}/uvx-args"\necho landed\nexit {uvx_exit}\n'
    uvx.write_text(script, encoding="utf-8")
    uvx.chmod(0o755)
    output, summary = tmp_path / "output", tmp_path / "summary"
    output.write_text("")
    summary.write_text("")
    full = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "RUNNER_TEMP": str(tmp_path),
    }
    argv = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _script(name)]
    proc = subprocess.run(argv, env=full | env, capture_output=True, text=True, check=False)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return proc, outputs


def _uvx_args(tmp_path: Path) -> list[str]:
    return (tmp_path / "uvx-args").read_text(encoding="utf-8").splitlines()


# S-054-1: empty, the land job lands as before


def test_s054_1_the_input_defaults_to_empty_and_the_job_names_only_it() -> None:
    declared = DOC["on"]["workflow_call"]["inputs"]["land-environment"]
    assert (declared["type"], declared["default"]) == ("string", "")
    # an empty expression names no environment; set, the caller's environment of that name
    assert JOB["environment"] == "${{ inputs.land-environment }}"


def test_s054_1_only_the_key_step_reads_a_secret_and_only_when_the_input_is_set() -> None:
    reading = [s.get("name") for s in STEPS if "secrets." in str(s)]
    assert reading == [KEY_STEP]
    assert _step(KEY_STEP)["if"] == "inputs.land-environment != ''"
    other_jobs = {name: job for name, job in DOC["jobs"].items() if name != "land"}
    assert not [name for name, job in other_jobs.items() if "secrets." in str(job) or "environment" in job]


def test_s054_1_without_the_key_land_runs_with_todays_arguments(tmp_path: Path) -> None:
    proc, _ = _bash(LAND_STEP, tmp_path, LAND_ENV | {"APP_KEY": ""})
    assert proc.returncode == 0, proc.stderr
    assert _uvx_args(tmp_path) == TODAY
    assert (tmp_path / "summary").read_text() == "landed\n"


def test_s054_1_a_failed_land_fails_the_step(tmp_path: Path) -> None:
    proc, _ = _bash(LAND_STEP, tmp_path, LAND_ENV | {"APP_KEY": ""}, uvx_exit=2)
    assert proc.returncode == 2  # pipefail: tee's success doesn't hide land's failure


# S-054-3: set, the key reaches land as a 0600 file


def test_s054_3_the_key_step_runs_before_land_and_hands_over_only_a_path() -> None:
    names = [s.get("name") for s in STEPS]
    assert names.index(KEY_STEP) < names.index(LAND_STEP)
    key = _step(KEY_STEP)
    assert key["id"] == "key"
    assert key["env"] == {"KEY": "${{ secrets.SHIPMILL_LAND_KEY }}", "ENVIRONMENT": "${{ inputs.land-environment }}"}
    assert _step(LAND_STEP)["env"]["APP_KEY"] == "${{ steps.key.outputs.path }}"


def test_s054_3_the_key_is_masked_and_written_mode_0600_under_runner_temp(tmp_path: Path) -> None:
    proc, outputs = _bash(KEY_STEP, tmp_path, {"KEY": PEM, "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 0, proc.stderr
    # every non-empty line of the key masked, and nothing else printed
    assert proc.stdout.splitlines() == [f"::add-mask::{line}" for line in PEM.splitlines()]
    path = Path(outputs["path"])
    assert path.parent == tmp_path
    assert path.read_text(encoding="utf-8") == PEM + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert set(outputs) == {"path"}


def test_s054_3_with_the_key_land_passes_app_key(tmp_path: Path) -> None:
    key = tmp_path / "shipmill-land-key.pem"
    proc, _ = _bash(LAND_STEP, tmp_path, LAND_ENV | {"APP_KEY": str(key)})
    assert proc.returncode == 0, proc.stderr
    assert _uvx_args(tmp_path) == [*TODAY, "--app-key", str(key)]


def test_s054_3_an_empty_secret_fails_before_land_naming_it_and_the_environment(tmp_path: Path) -> None:
    proc, outputs = _bash(KEY_STEP, tmp_path, {"KEY": "", "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 1
    assert proc.stdout.startswith("::error::shipmill land: the environment shipmill-land has no SHIPMILL_LAND_KEY")
    assert "Nothing was pushed" in proc.stdout
    assert outputs == {}
    assert not (tmp_path / "shipmill-land-key.pem").exists()
    assert not (tmp_path / "uvx-args").exists()


# S-054-18: shipmill init --land-as-app


def _with_app(repo: Repo) -> None:
    repo.write(repo.policy_file, repo.read(repo.policy_file) + APP_POLICY)


def test_s054_18_init_without_the_flag_writes_todays_release_workflow(repo: Repo) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    written = (repo.root / CALLER).read_text(encoding="utf-8")
    assert written == _unscheduled()
    assert "land-environment" not in written


def test_s054_18_caller_land_as_app_sets_the_environment_on_the_land_job(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    _with_app(repo)
    capsys.readouterr()
    assert main(["--repo", str(repo.root), "init", "--caller", "--force", "--land-as-app"]) == 0
    text = (repo.root / CALLER).read_text(encoding="utf-8")
    jobs = _jobs(text)
    assert OPT_IN in jobs["land"].split("    with:\n", 1)[1].split("    permissions:\n", 1)[0]
    assert not [name for name in jobs if name != "land" and "land-environment" in jobs[name]]
    # apart from the one line, the file is the one written without the flag
    assert text.replace(OPT_IN, "") == _unscheduled()
    assert land_environment(text) == "shipmill-land"  # as doctor's landing row reads it
    assert "SHIPMILL_LAND_KEY" in capsys.readouterr().out


def test_s054_18_land_as_app_without_app_id_exits_2_naming_it_and_writes_nothing(repo: Repo) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    before = (repo.root / CALLER).read_bytes()
    with pytest.raises(ReleaseError, match=r"sets no \[agents\] app_id"):
        main(["--repo", str(repo.root), "init", "--caller", "--force", "--land-as-app"])
    assert (repo.root / CALLER).read_bytes() == before
    # the full init writes a policy with no app_id: it refuses before any write, exit 2
    (repo.root / CALLER).unlink()
    (repo.root / ".github" / "shipmill.toml").unlink()
    argv = [sys.executable, "-m", "shipmill", "--repo", str(repo.root), "init", "--land-as-app"]
    out = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert out.returncode == 2
    assert "[agents] app_id" in out.stderr and "init --caller --land-as-app" in out.stderr
    assert not (repo.root / CALLER).exists() and not (repo.root / ".github" / "shipmill.toml").exists()


@pytest.mark.parametrize("flag", ["--operate", "--downstream"])
def test_s054_18_land_as_app_is_refused_where_no_release_workflow_is_written(repo: Repo, flag: str) -> None:
    _with_app(repo)
    with pytest.raises(ReleaseError, match="--land-as-app"):
        main(["--repo", str(repo.root), "init", flag, "--force", "--land-as-app"])
    assert not (repo.root / OPERATE_CALLER).exists()
