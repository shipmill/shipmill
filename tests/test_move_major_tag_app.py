"""#1179: move-major-tag.yml pushes the marketplace commit as the App when its
`land-environment` input names the environment land.yml lands through (spec 054), since a
ruleset whose only bypass actor is the App refuses the workflow token's push to main. The
major tag's force-push stays with the workflow token, as land's tags do (spec 054: a branch
ruleset doesn't cover tags). Empty, both push with the workflow token, as before. #1188: a
dry-run push as the App proves its token before the major tag moves, so a bad key or an App
that can't push fails with nothing pushed.

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
CHECK_STEP = "Check the App's token"
APP_STEP = "Push as the App"
TAG_STEP = "Point the major tag at the release"
MARKETPLACE_STEP = "Point the marketplace at the release"
# #1188: opted in, and only when a reference moves; a release that isn't the newest needs no key
OPTED_IN = "inputs.land-environment != '' && steps.check.outputs.newest == 'true'"
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
    for name in (KEY_STEP, CHECK_STEP, APP_STEP):
        assert _step(name)["if"] == OPTED_IN
    # the push steps read no key and no token: the App's credential reaches git through GITHUB_ENV
    for name in (TAG_STEP, MARKETPLACE_STEP):
        assert "APP_KEY" not in _step(name).get("env", {}) and "token" not in str(_step(name)).lower()
        assert "GIT_CONFIG" not in str(_step(name))


def test_the_app_steps_run_only_when_a_reference_moves() -> None:
    """#1188: a release that isn't the newest stable one moves nothing, so it reads no key and
    sets up no App; the steps gate on the check's output as the push steps do"""
    gated = [s for s in STEPS if "land-environment != ''" in str(s.get("if", ""))]
    assert len(gated) == 4  # setup-uv, the key, the check, the App's settings
    assert all(s["if"] == OPTED_IN for s in gated)
    assert _step(TAG_STEP)["if"] == _step(MARKETPLACE_STEP)["if"] == "steps.check.outputs.newest == 'true'"


def test_the_major_tag_pushes_before_the_app_config_exists_and_stays_a_force_push() -> None:
    """GITHUB_ENV reaches only the steps after the one that writes it: the major tag's push,
    before it, goes with the workflow token (spec 054); the marketplace's, after it, as the App.
    The key step's checks and the token's check come before either push, so a half-done opt-in,
    a bad key, or an App that can't push pushes nothing (#1188)"""
    names = [s.get("name") for s in STEPS]
    assert (
        names.index(KEY_STEP)
        < names.index(CHECK_STEP)
        < names.index(TAG_STEP)
        < names.index(APP_STEP)
        < names.index(MARKETPLACE_STEP)
    )
    assert 'git push -f origin "refs/tags/$major"' in _script(TAG_STEP)
    for name in (KEY_STEP, CHECK_STEP):  # their settings reach no later step but through the App's
        assert "GITHUB_ENV" not in _script(name)
    # the check's only push is a dry run, which sends nothing
    pushes = [line.strip() for line in _script(CHECK_STEP).splitlines() if "git push" in line]
    assert pushes == ['git push --dry-run --force -q origin "HEAD:refs/heads/$BRANCH"']


def test_the_header_says_the_apps_push_starts_the_push_workflows() -> None:
    """#1188: as spec 054 says of land's commits, a push as the App starts workflows"""
    header = " ".join(line.lstrip("# ") for line in TEXT.split("\non:")[0].splitlines())
    assert "The marketplace commit, pushed as the App, starts the `on: push` workflows on the" in header
    assert "default branch (ci.yml, release.yml)" in header


# Set, the key becomes a 0600 file and git a credential helper that holds no token


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / ".github").mkdir(parents=True)
    (work / ".github" / "shipmill.toml").write_text('mode = "auto"\n\n[agents]\nprompt = "/t"\napp_id = 42\n')
    return work


def test_the_key_step_hands_over_only_a_path_and_the_app_id() -> None:
    key = _step(KEY_STEP)
    assert key["id"] == "key"
    assert key["env"] == {"KEY": "${{ secrets.SHIPMILL_LAND_KEY }}", "ENVIRONMENT": "${{ inputs.land-environment }}"}
    check = _step(CHECK_STEP)
    assert check["id"] == "app"
    assert (check["env"]["APP_KEY"], check["env"]["APP_ID"]) == (
        "${{ steps.key.outputs.path }}",
        "${{ steps.key.outputs.app-id }}",
    )
    assert _step(APP_STEP)["env"]["CONFIG"] == "${{ steps.app.outputs.config }}"


def test_the_key_is_masked_and_written_mode_0600_under_runner_temp(checkout: Path, tmp_path: Path) -> None:
    proc, _ = _bash(KEY_STEP, checkout, tmp_path, {"KEY": PEM, "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [f"::add-mask::{line}" for line in PEM.splitlines()]
    outputs = _outputs(tmp_path)
    assert set(outputs) == {"path", "app-id"}
    assert outputs["app-id"] == "42"
    path = Path(outputs["path"])
    assert path.parent == tmp_path
    assert path.read_text(encoding="utf-8") == PEM + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_empty_secret_fails_naming_it_and_the_environment(checkout: Path, tmp_path: Path) -> None:
    proc, _ = _bash(KEY_STEP, checkout, tmp_path, {"KEY": "", "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 1
    assert proc.stdout.startswith("::error::move-major-tag: the environment shipmill-land has no SHIPMILL_LAND_KEY")
    assert "Nothing was pushed" in proc.stdout
    assert _outputs(tmp_path) == {}


def test_without_an_app_id_the_key_step_fails_naming_it_before_any_push(checkout: Path, tmp_path: Path) -> None:
    (checkout / ".github" / "shipmill.toml").write_text('mode = "auto"\n')
    proc, _ = _bash(KEY_STEP, checkout, tmp_path, {"KEY": PEM, "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 1
    assert "[agents] app_id" in proc.stdout and "Nothing was pushed" in proc.stdout
    assert _outputs(tmp_path) == {}
    assert not (tmp_path / "shipmill-land-key.pem").exists()


def test_without_the_config_file_the_key_step_fails_naming_the_fix(checkout: Path, tmp_path: Path) -> None:
    """#1188: a missing .github/shipmill.toml is an ::error:: naming the fix, not a traceback"""
    (checkout / ".github" / "shipmill.toml").unlink()
    proc, _ = _bash(KEY_STEP, checkout, tmp_path, {"KEY": PEM, "ENVIRONMENT": "shipmill-land"})
    assert proc.returncode == 1
    errors = [line for line in proc.stdout.splitlines() if line.startswith("::error::")]
    assert len(errors) == 1
    assert "no .github/shipmill.toml" in errors[0] and "add the file with [agents] app_id" in errors[0]
    assert "dispatch with an empty land-environment. Nothing was pushed" in errors[0]
    assert "Traceback" not in proc.stderr
    assert _outputs(tmp_path) == {}
    assert not (tmp_path / "shipmill-land-key.pem").exists()


# The token's check: a dry-run push as the App before the major tag moves (#1188)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def pushable(checkout: Path, tmp_path: Path) -> Path:
    """The checkout as a clone of a bare origin whose main it has, the workflow token's header
    persisted as actions/checkout leaves it"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(checkout, "init", "-q", "-b", "main")
    _git(checkout, "add", "-A")
    _git(checkout, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "Release 0.67.0")
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-q", "origin", "main")
    _git(checkout, "config", "http.https://github.com/.extraheader", "AUTHORIZATION: basic x")
    return checkout


def _check_env(tmp_path: Path, key: Path, repo: str = "shipmill/shipmill") -> dict[str, str]:
    return {
        "APP_KEY": str(key),
        "APP_ID": "42",
        "TAG": "v0.67.0",
        "BRANCH": "main",
        "GITHUB_REPOSITORY": repo,
        "HOME": str(tmp_path),
    }


def _fake(folder: Path, name: str, body: str) -> Path:
    folder.mkdir(exist_ok=True)
    script = folder / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return folder


def test_a_refused_check_fails_before_any_push_with_the_apps_settings_alone(pushable: Path, tmp_path: Path) -> None:
    """git refusing the dry run as the App (a key that mints no token, an App that can't push)
    fails the step, which comes before the major tag's push, so nothing is pushed. The App's
    settings are in the dry run's environment only: no output, and nothing in GITHUB_ENV"""
    record = tmp_path / "record"
    record.mkdir()
    fake = _fake(
        tmp_path / "bin",
        "git",
        'printf "%s\\n" "$@" > "$RECORD/argv"\nenv | grep "^GIT_" | sort > "$RECORD/env"\n'
        'echo "remote: Permission to shipmill/shipmill.git denied" >&2\nexit 128\n',
    )
    env = _check_env(tmp_path, tmp_path / "shipmill-land-key.pem") | {
        "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}",
        "RECORD": str(record),
    }
    proc, github_env = _bash(CHECK_STEP, pushable, tmp_path, env)
    assert proc.returncode == 1
    assert proc.stdout.startswith("::error::move-major-tag: the App 42 can't push to main with SHIPMILL_LAND_KEY")
    assert "Contents: write" in proc.stdout and "Nothing was pushed" in proc.stdout
    assert _outputs(tmp_path) == {} and github_env.read_text() == ""
    assert (record / "argv").read_text().splitlines() == [
        "push",
        "--dry-run",
        "--force",
        "-q",
        "origin",
        "HEAD:refs/heads/main",
    ]
    seen = dict(line.split("=", 1) for line in (record / "env").read_text().splitlines())
    assert seen["GIT_TERMINAL_PROMPT"] == "0"
    assert (seen["GIT_CONFIG_COUNT"], seen["GIT_CONFIG_VALUE_0"], seen["GIT_CONFIG_VALUE_1"]) == ("3", "", "")
    assert seen["GIT_CONFIG_VALUE_2"].endswith("--git-credential")


def test_a_passed_check_hands_on_the_settings_and_pushes_nothing(pushable: Path, tmp_path: Path) -> None:
    before = _git(pushable, "ls-remote", "origin")
    proc, github_env = _bash(CHECK_STEP, pushable, tmp_path, _check_env(tmp_path, tmp_path / "k.pem"))
    assert proc.returncode == 0, proc.stderr
    assert "the App 42 can push to main" in proc.stdout
    assert set(_outputs(tmp_path)) == {"config"} and github_env.read_text() == ""
    assert _git(pushable, "ls-remote", "origin") == before


def _settings(pushable: Path, tmp_path: Path, key: Path, repo: str = "shipmill/shipmill") -> Path:
    """The check's settings, handed on to GITHUB_ENV by the App's step"""
    proc, _ = _bash(CHECK_STEP, pushable, tmp_path, _check_env(tmp_path, key, repo))
    assert proc.returncode == 0, proc.stderr
    config = _outputs(tmp_path)["config"]
    proc, github_env = _bash(APP_STEP, pushable, tmp_path, {"CONFIG": config, "APP_ID": "42"})
    assert proc.returncode == 0, proc.stderr
    assert "App 42" in proc.stdout
    return github_env


def test_the_push_config_clears_the_workflow_token_and_sends_the_apps_credential(
    pushable: Path, tmp_path: Path
) -> None:
    key = tmp_path / "shipmill-land-key.pem"
    github_env = _settings(pushable, tmp_path, key)
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


def test_a_key_path_with_a_space_reaches_the_helper_whole(pushable: Path, tmp_path: Path) -> None:
    """#1188: git runs the `!` helper through sh, so the key's path is quoted as shlex quotes
    it: a path with a space reaches `shipmill app-token` as one argument"""
    key = tmp_path / "runner temp" / "shipmill-land-key.pem"
    github_env = _settings(pushable, tmp_path, key)
    assert _config(github_env)["GIT_CONFIG_VALUE_2"].endswith(f"--app-key '{key}' --git-credential")
    argv = tmp_path / "argv"
    fake = _fake(tmp_path / "bin", "uvx", f'printf "%s\\n" "$@" > \'{argv}\'\nprintf "username=x\\npassword=y\\n"\n')
    git_env = {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path)} | _config(github_env)
    filled = subprocess.run(
        ["git", "-C", str(pushable), "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "password=y" in filled.stdout
    assert argv.read_text().splitlines() == [
        "--from",
        "shipmill==0.67.0",
        "shipmill",
        "app-token",
        "shipmill/shipmill",
        "--app-id",
        "42",
        "--app-key",
        str(key),
        "--git-credential",
        "get",
    ]


def test_the_push_config_reaches_git(pushable: Path, tmp_path: Path) -> None:
    """git reads the settings the step writes: the header list empty, the App's helper last"""
    github_env = _settings(pushable, tmp_path, tmp_path / "k.pem", "o/r")
    git_env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)} | _config(github_env)
    checkout = pushable
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
