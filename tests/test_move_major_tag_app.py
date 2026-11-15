"""#1179: move-major-tag.yml pushes the major tag and the marketplace commit as the App when its
`land-environment` input names the environment land.yml lands through (spec 054), since a
ruleset whose only bypass actor is the App refuses the workflow token's push to main. Empty,
it pushes with the workflow token, as before.

The workflow is read with the eval suite's strict YAML reader, and its key and App steps run
here as bash with the env GitHub gives them, so their exits, files, and the git config they
hand the push steps are proved, not only their text. The push steps themselves are run by
tests/test_publish_first.py; actionlint accepting the file is CI's lint job."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from shipmill import evals
from shipmill.landing import land_environment

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "move-major-tag.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC: Any = evals._Yaml(TEXT, "move-major-tag.yml").mapping()
JOB: dict[str, Any] = DOC["jobs"]["move"]
STEPS: list[dict[str, Any]] = JOB["steps"]
KEY_STEP = "Write the App's key"
APP_STEP = "Push as the App"
TAG_STEP = "Point the major tag at the release"
MARKETPLACE_STEP = "Point the marketplace at the release"
OPTED_IN = "inputs.land-environment != ''"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0secret\nline2secret\n-----END RSA PRIVATE KEY-----"


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


def _bash(name: str, cwd: Path, tmp_path: Path, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run a step's script as the runner's default shell does (`bash -e`); the process and the
    GITHUB_ENV file it may write"""
    output, github_env = tmp_path / "output", tmp_path / "github-env"
    output.write_text("")
    github_env.write_text("")
    full = {
        "PATH": os.environ["PATH"],
        "GITHUB_OUTPUT": str(output),
        "GITHUB_ENV": str(github_env),
        "RUNNER_TEMP": str(tmp_path),
    }
    argv = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _script(name)]
    proc = subprocess.run(argv, cwd=cwd, env=full | env, capture_output=True, text=True, check=False)
    return proc, github_env


def _outputs(tmp_path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())


def _config(github_env: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in github_env.read_text().splitlines())


# Empty, the job pushes as before


def test_the_input_is_additive_and_defaults_to_the_workflow_token() -> None:
    inputs = DOC["on"]["workflow_dispatch"]["inputs"]
    assert inputs["tag"]["required"] == "true"  # the strict reader keeps scalars as text
    declared = inputs["land-environment"]
    assert declared["type"] == "string" and "required" not in declared  # land dispatches with its tag alone
    # an empty expression names no environment; set, the environment of that name, as land.yml
    assert JOB["environment"] == "${{ inputs.land-environment }}"


def test_the_default_follows_the_environment_this_repository_lands_through() -> None:
    """land dispatches this workflow with its tag alone, so the input's default is what a
    release gets: it names the environment release.yml's land job lands through, or none"""
    caller = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert DOC["on"]["workflow_dispatch"]["inputs"]["land-environment"]["default"] == (land_environment(caller) or "")


def test_only_the_key_step_reads_a_secret_and_the_app_steps_run_only_when_the_input_is_set() -> None:
    reading = [s.get("name") for s in STEPS if "secrets." in str(s)]
    assert reading == [KEY_STEP]
    setup_uv = [s for s in STEPS if str(s.get("uses", "")).startswith("astral-sh/setup-uv@")]
    assert [s.get("if") for s in setup_uv] == [OPTED_IN]
    assert setup_uv[0]["with"] == {"version": "0.13.7"}  # D-80: land.yml's pin
    assert _step(KEY_STEP)["if"] == OPTED_IN
    assert _step(APP_STEP)["if"] == OPTED_IN
    # the push steps read no key and no token: the App's credential reaches git through GITHUB_ENV
    for name in (TAG_STEP, MARKETPLACE_STEP):
        assert "APP_KEY" not in _step(name).get("env", {}) and "token" not in str(_step(name)).lower()


def test_the_app_steps_run_before_either_push_and_the_major_tag_stays_a_force_push() -> None:
    names = [s.get("name") for s in STEPS]
    assert names.index(KEY_STEP) < names.index(APP_STEP) < names.index(TAG_STEP) < names.index(MARKETPLACE_STEP)
    assert 'git push -f origin "refs/tags/$major"' in _script(TAG_STEP)


# Set, the key becomes a 0600 file and git a credential helper that holds no token


def test_the_key_step_hands_over_only_a_path() -> None:
    key = _step(KEY_STEP)
    assert key["id"] == "key"
    assert key["env"] == {"KEY": "${{ secrets.SHIPMILL_LAND_KEY }}", "ENVIRONMENT": "${{ inputs.land-environment }}"}
    assert _step(APP_STEP)["env"]["APP_KEY"] == "${{ steps.key.outputs.path }}"


def test_the_key_is_masked_and_written_mode_0600_under_runner_temp(tmp_path: Path) -> None:
    proc, _ = _bash(KEY_STEP, tmp_path, tmp_path, {"KEY": PEM, "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [f"::add-mask::{line}" for line in PEM.splitlines()]
    outputs = _outputs(tmp_path)
    assert set(outputs) == {"path"}
    path = Path(outputs["path"])
    assert path.parent == tmp_path
    assert path.read_text(encoding="utf-8") == PEM + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_empty_secret_fails_naming_it_and_the_environment(tmp_path: Path) -> None:
    proc, _ = _bash(KEY_STEP, tmp_path, tmp_path, {"KEY": "", "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 1
    assert proc.stdout.startswith("::error::move-major-tag: the environment shipmill-land has no SHIPMILL_LAND_KEY")
    assert "Nothing was pushed" in proc.stdout
    assert _outputs(tmp_path) == {}


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / ".github").mkdir(parents=True)
    (work / ".github" / "shipmill.toml").write_text('mode = "auto"\n\n[agents]\nprompt = "/t"\napp_id = 42\n')
    return work


def test_the_push_config_clears_the_workflow_token_and_sends_the_apps_credential(
    checkout: Path, tmp_path: Path
) -> None:
    key = tmp_path / "shipmill-land-key.pem"
    env = {"APP_KEY": str(key), "TAG": "v0.67.0", "GITHUB_REPOSITORY": "shipmill/shipmill"}
    proc, github_env = _bash(APP_STEP, checkout, tmp_path, env)
    assert proc.returncode == 0, proc.stderr
    tool = "!uvx --from shipmill==0.67.0 shipmill"
    helper = f"{tool} app-token shipmill/shipmill --app-id 42 --app-key {key} --git-credential"
    assert _config(github_env) == {
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "",  # an empty value drops the checkout's persisted workflow token
        "GIT_CONFIG_KEY_1": "credential.https://github.com.helper",
        "GIT_CONFIG_VALUE_1": "",  # an empty value drops every helper before it
        "GIT_CONFIG_KEY_2": "credential.https://github.com.helper",
        "GIT_CONFIG_VALUE_2": helper,
    }
    assert "App 42" in proc.stdout


def test_the_push_config_reaches_git(checkout: Path, tmp_path: Path) -> None:
    """git reads the settings the step writes: the header list empty, the App's helper last"""
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "config", "http.https://github.com/.extraheader", "AUTHORIZATION: basic x"],
        check=True,
    )
    env = {"APP_KEY": str(tmp_path / "k.pem"), "TAG": "v0.67.0", "GITHUB_REPOSITORY": "shipmill/shipmill"}
    proc, github_env = _bash(APP_STEP, checkout, tmp_path, env)
    assert proc.returncode == 0, proc.stderr
    git_env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)} | _config(github_env)
    shown = subprocess.run(
        ["git", "-C", str(checkout), "config", "--get-all", "credential.https://github.com.helper"],
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert shown[-1].endswith("--git-credential")
    headers = subprocess.run(
        ["git", "-C", str(checkout), "config", "--get-all", "http.https://github.com/.extraheader"],
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert headers[-1] == ""  # git's rule: the last, empty, value resets the list


def test_without_an_app_id_the_step_fails_naming_it(checkout: Path, tmp_path: Path) -> None:
    (checkout / ".github" / "shipmill.toml").write_text('mode = "auto"\n')
    env = {"APP_KEY": str(tmp_path / "k.pem"), "TAG": "v0.67.0", "GITHUB_REPOSITORY": "shipmill/shipmill"}
    proc, github_env = _bash(APP_STEP, checkout, tmp_path, env)
    assert proc.returncode == 1
    assert "[agents] app_id" in proc.stdout and "Nothing was pushed" in proc.stdout
    assert github_env.read_text() == ""
