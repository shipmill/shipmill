"""#1371: operate.yml opens its deploy proposal ("Ready to promote") as the App when the
caller passes the App's private key as the optional SHIPMILL_OPERATE_KEY secret and the
config sets [agents] app_id, so the maintainer queue, which trusts the --bot-login and never
github-actions[bot] (S-069-9, D-30), shows it as a PROMOTION row (S-069-5). The token is
limited to the repository and issues: write (D-90's --permission); without the secret the
workflow token opens it, as before.

The workflow is read with the eval suite's strict YAML reader, and its token step runs here as
bash with the env GitHub gives it and a fake uvx on PATH, so its exits, outputs, and the key
file are proved, not only its text, as tests/test_move_major_tag_app.py does for its App steps."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from shipmill import evals
from shipmill.cli import PROPOSAL_TOKEN, _proposer
from shipmill.github import GhCli

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "operate.yml").read_text(encoding="utf-8")
DOC: Any = evals._Yaml(TEXT, "operate.yml").mapping()
STEPS: list[dict[str, Any]] = DOC["jobs"]["operate"]["steps"]
TOKEN_STEP = "Mint the App's token for the proposals"
OPERATE_STEP = "Operate"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0secret\nline2secret\n-----END RSA PRIVATE KEY-----"
CONFIG = "[agents]\napp_id = 42   # the App\n"


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


def _uvx(tmp_path: Path, exit_code: int = 0) -> Path:
    """A uvx that records its argv and the key file's mode, and prints a token (or fails)"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uvx = bin_dir / "uvx"
    uvx.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            printf '%s\\n' "$@" > "{tmp_path}/argv"
            while [ $# -gt 0 ]; do
              if [ "$1" = --app-key ]; then
                python3 -c 'import os, sys; print(format(os.stat(sys.argv[1]).st_mode & 0o777, "o"))' "$2" \
                  > "{tmp_path}/mode"
                cp "$2" "{tmp_path}/key-seen"
              fi
              shift
            done
            if [ {exit_code} -ne 0 ]; then echo "shipmill: the App isn't installed" >&2; exit {exit_code}; fi
            echo ghs_minted
            """
        )
    )
    uvx.chmod(0o755)
    return bin_dir


def _bash(tmp_path: Path, cwd: Path, env: dict[str, str], exit_code: int = 0) -> subprocess.CompletedProcess[str]:
    """Run the token step as the runner's default shell does (`bash -e`)"""
    (tmp_path / "output").write_text("")
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    full = {
        "PATH": f"{_uvx(tmp_path, exit_code)}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_REPOSITORY": "o/r",
        "RUNNER_TEMP": str(runner_temp),
        "TOOL": "git+https://github.com/shipmill/shipmill@v0",
    }
    argv = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _script(TOKEN_STEP)]
    return subprocess.run(argv, cwd=cwd, env=full | env, capture_output=True, text=True, check=False)


def _outputs(tmp_path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())


def _checkout(tmp_path: Path, config: str | None) -> Path:
    checkout = tmp_path / "checkout"
    (checkout / ".github").mkdir(parents=True)
    if config is not None:
        (checkout / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    return checkout


def test_the_key_is_an_optional_secret_only_the_token_step_reads() -> None:
    declared = DOC["on"]["workflow_call"]["secrets"]
    assert list(declared) == ["SHIPMILL_OPERATE_KEY"]
    assert declared["SHIPMILL_OPERATE_KEY"]["required"] == "false"  # the strict reader keeps scalars as text
    assert [s.get("name") for s in STEPS if "secrets." in str(s)] == [TOKEN_STEP]
    names = [s.get("name") for s in STEPS]
    assert names.index(TOKEN_STEP) < names.index(OPERATE_STEP)


def test_operate_keeps_the_workflow_token_and_gets_the_apps_for_the_proposals() -> None:
    env = _step(OPERATE_STEP)["env"]
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env[PROPOSAL_TOKEN] == "${{ steps.app.outputs.token }}"
    assert _step(TOKEN_STEP)["id"] == "app"


def test_without_the_secret_the_proposals_keep_the_workflow_token(tmp_path: Path) -> None:
    proc = _bash(tmp_path, _checkout(tmp_path, CONFIG), {"KEY": ""})
    assert proc.returncode == 0, proc.stderr
    assert "workflow token" in proc.stdout
    assert _outputs(tmp_path) == {} and not (tmp_path / "argv").exists()  # nothing minted


def test_with_the_key_and_app_id_it_mints_an_issues_write_token(tmp_path: Path) -> None:
    proc = _bash(tmp_path, _checkout(tmp_path, CONFIG), {"KEY": PEM})
    assert proc.returncode == 0, proc.stderr
    assert _outputs(tmp_path) == {"token": "ghs_minted"}
    argv = (tmp_path / "argv").read_text().splitlines()
    assert argv[:4] == ["--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill", "app-token"]
    assert argv[4] == "o/r"
    assert argv[argv.index("--app-id") + 1] == "42"
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--permission"] == ["issues=write"]  # D-90
    assert "--git-credential" not in argv
    # the key reached the mint in a file only the job's user reads, and is gone after
    assert (tmp_path / "key-seen").read_text() == PEM + "\n"
    assert (tmp_path / "mode").read_text().strip() == "600"
    assert list((tmp_path / "runner").iterdir()) == []
    # every line of the key, and the token, masked before anything prints them
    for secret in [*PEM.splitlines(), "ghs_minted"]:
        assert f"::add-mask::{secret}" in proc.stdout


def test_a_key_without_app_id_fails(tmp_path: Path) -> None:
    for config in ("[agents]\n", None):
        case = tmp_path / ("no-app-id" if config else "no-config")
        case.mkdir()
        proc = _bash(case, _checkout(case, config), {"KEY": PEM})
        assert proc.returncode == 1
        assert "::error::" in proc.stdout and "[agents] app_id" in proc.stdout
        assert not (case / "argv").exists()


def test_a_failed_mint_fails_and_leaves_no_key(tmp_path: Path) -> None:
    proc = _bash(tmp_path, _checkout(tmp_path, CONFIG), {"KEY": PEM}, exit_code=2)
    assert proc.returncode == 1
    assert "::error::" in proc.stdout and "SHIPMILL_OPERATE_KEY" in proc.stdout
    assert _outputs(tmp_path) == {}
    assert list((tmp_path / "runner").iterdir()) == []


def test_the_proposer_is_gh_with_the_apps_token_only_when_it_is_set(tmp_path: Path) -> None:
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\n")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    environ = {"PATH": str(tmp_path), "GH_TOKEN": "ghs_workflow"}
    assert _proposer(tmp_path, environ, "CHANGELOG.md") is None
    assert _proposer(tmp_path, environ | {PROPOSAL_TOKEN: ""}, "CHANGELOG.md") is None
    proposer = _proposer(tmp_path, environ | {PROPOSAL_TOKEN: "ghs_app"}, "CHANGES.md")
    assert isinstance(proposer, GhCli)
    assert proposer.env is not None and proposer.env["GH_TOKEN"] == "ghs_app"
    assert proposer.changelog == "CHANGES.md"
