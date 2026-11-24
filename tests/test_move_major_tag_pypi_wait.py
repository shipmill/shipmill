"""#1470: PyPI's simple index can list a release minutes after publish.yml's upload passed, and
move-major-tag.yml's first resolve of the release's shipmill was inside git's credential helper
in the token's check, so uv's "no version of shipmill==X" read as a bad SHIPMILL_LAND_KEY. A
step before the check now waits, bounded, until the index serves the version (D-50), and fails
with its own error naming the index when it never does.

The wait's script runs here as bash with fake `uvx` and `sleep`, so its tries, its bound, and its
error are proved, not only its text."""

import os
from pathlib import Path

from tests.test_move_major_tag_app import (
    CHECK_STEP,
    KEY_STEP,
    OPTED_IN,
    STEPS,
    TAG_STEP,
    _bash,
    _check_env,
    _fake,
    _outputs,
    _script,
    _step,
    checkout,  # noqa: F401  # the fixture pushable builds on
    pushable,  # noqa: F401  # the fixture the refused check runs in
)

WAIT_STEP = "Wait for PyPI to serve the release"
RESOLVE = 'uvx --refresh-package shipmill --from "shipmill==$version" shipmill --version'


def test_the_wait_runs_where_the_apps_steps_run_and_before_the_tokens_check() -> None:
    """An empty land-environment or a tag that isn't the newest skips it, as it skips the App's
    steps, so a run that pushes nothing waits on nothing"""
    wait = _step(WAIT_STEP)
    assert wait["if"] == OPTED_IN
    assert wait["env"] == {"TAG": "${{ inputs.tag }}"}  # never interpolated into the script
    assert "${{" not in _script(WAIT_STEP)
    assert "secrets." not in str(wait) and "APP_KEY" not in str(wait)
    names = [s.get("name") for s in STEPS]
    assert names.index(KEY_STEP) < names.index(WAIT_STEP) < names.index(CHECK_STEP) < names.index(TAG_STEP)


def test_the_wait_resolves_the_releases_shipmill_past_uvs_cache() -> None:
    script = _script(WAIT_STEP)
    assert 'version="${TAG#v}"' in script
    assert RESOLVE in script
    assert "for waited in $(seq 0 20 600); do" in script  # every 20 s, for up to 10 minutes


def _wait(tmp_path: Path, fails: int) -> tuple[int, str, list[str], list[str]]:
    """Run the wait against a uvx that fails `fails` times before it resolves; its exit, its
    output, uvx's argv per try, and the sleeps it asked for"""
    record = tmp_path / "record"
    record.mkdir()
    fake = _fake(
        tmp_path / "bin",
        "uvx",
        f'echo "$*" >> "{record}/uvx"\n'
        f'if [ "$(wc -l < "{record}/uvx")" -le {fails} ]; then\n'
        '  echo "No solution found when resolving tool dependencies" >&2\n'
        "  exit 1\n"
        "fi\n"
        'echo "shipmill 0.67.0"\n',
    )
    _fake(fake, "sleep", f'echo "$*" >> "{record}/sleep"\n')
    work = tmp_path / "work"
    work.mkdir()
    env = {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "TAG": "v0.67.0", "HOME": str(tmp_path)}
    proc, _ = _bash(WAIT_STEP, work, tmp_path, env)
    tries = (record / "uvx").read_text().splitlines()
    sleeps = (record / "sleep").read_text().splitlines() if (record / "sleep").exists() else []
    return proc.returncode, proc.stdout, tries, sleeps


def test_a_version_the_index_serves_at_once_waits_on_nothing(tmp_path: Path) -> None:
    code, out, tries, sleeps = _wait(tmp_path, fails=0)
    assert code == 0, out
    assert tries == ["--refresh-package shipmill --from shipmill==0.67.0 shipmill --version"]
    assert sleeps == []
    assert "PyPI serves shipmill 0.67.0" in out
    assert _outputs(tmp_path) == {}


def test_the_wait_tries_again_every_20_s_until_the_index_serves_the_version(tmp_path: Path) -> None:
    """The v0.160.0 runs: the index listed the version about 2.5 minutes after the upload"""
    code, out, tries, sleeps = _wait(tmp_path, fails=8)
    assert code == 0, out
    assert len(tries) == 9 and set(tries) == {"--refresh-package shipmill --from shipmill==0.67.0 shipmill --version"}
    assert sleeps == ["20"] * 8
    assert "::error::" not in out


def test_out_of_time_the_wait_fails_naming_the_index_and_not_the_key(tmp_path: Path) -> None:
    code, out, tries, sleeps = _wait(tmp_path, fails=1000)
    assert code == 1
    assert len(tries) == 31 and sleeps == ["20"] * 30  # 10 minutes of waits, then no sleep after the last try
    errors = [line for line in out.splitlines() if line.startswith("::error::")]
    assert len(errors) == 1
    error = errors[0]
    assert error.startswith("::error::move-major-tag: PyPI's index doesn't serve shipmill 0.67.0")
    assert "10 minutes" in error and "Nothing was pushed" in error and "rerun" in error
    assert "SHIPMILL_LAND_KEY" not in out and "App" not in error
    assert _outputs(tmp_path) == {}


def test_the_tokens_check_refreshes_uvs_cache_and_no_longer_blames_pypi() -> None:
    """By the check, the wait resolved the version, so its error is the key's and the App's alone;
    its helper refreshes shipmill as the wait does, so a stale restored cache can't hide it"""
    script = _script(CHECK_STEP)
    assert 'uvx --refresh-package shipmill --from "shipmill==${TAG#v}" shipmill app-token' in script
    error = next(line for line in script.splitlines() if "::error::" in line)
    assert "PyPI" not in error
    assert "SHIPMILL_LAND_KEY" in error and "Contents: write" in error


def test_a_refused_check_names_the_key_not_pypi(pushable: Path, tmp_path: Path) -> None:  # noqa: F811
    fake = _fake(tmp_path / "bin", "git", 'echo "remote: Permission denied" >&2\nexit 128\n')
    env = _check_env(tmp_path, tmp_path / "k.pem") | {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    proc, _ = _bash(CHECK_STEP, pushable, tmp_path, env)
    assert proc.returncode == 1
    assert "SHIPMILL_LAND_KEY" in proc.stdout and "PyPI" not in proc.stdout
