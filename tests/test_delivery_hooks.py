"""Spec 026: the plugin's delivery hooks, driven as Claude Code drives them: hooks/delivery.py
as a subprocess, the hook input JSON on stdin, and a temporary git repo as the cwd"""

import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "delivery.py"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hooks"
SHIPMILL = ["uvx", "--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill"]

APP = '[agents]\nprs = true\napp_id = 5209412\n[hooks]\nprivate = ["owner/**"]\n'
AGENTS = "[agents]\nprs = true\n"
RELEASE_ONLY = 'name = "demo"\nmode = "release"\n'


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def git_repo(root: Path, config: str | None, origin: bool = False) -> Path:
    """A git repo holding config as its .github/shipmill.toml; with origin, a pushed main and
    origin/HEAD set"""
    if origin:
        remote = root.with_name(f"{root.name}-origin.git")
        _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=root.parent)
        _git("clone", "-q", str(remote), str(root), cwd=root.parent)
    else:
        root.mkdir(parents=True)
        _git("init", "-q", "-b", "main", cwd=root)
    if config is not None:
        (root / ".github").mkdir()
        (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    if origin:
        (root / "README.md").write_text("# demo\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init", cwd=root)
        _git("checkout", "-q", "-B", "main", cwd=root)
        _git("push", "-q", "origin", "main", cwd=root)
        _git("remote", "set-head", "origin", "main", cwd=root)
    return root


@dataclass(frozen=True)
class Sandbox:
    app: Path  # [agents] with app_id and [hooks] private, an origin remote, origin/HEAD set
    agents: Path  # [agents] without app_id
    release: Path  # a config with no [agents]
    bare: Path  # a repo with no config
    outside: Path  # a folder outside any repo


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> Sandbox:
    base = tmp_path_factory.mktemp("hooks")
    outside = base / "outside"
    outside.mkdir()
    return Sandbox(
        app=git_repo(base / "app", APP, origin=True),
        agents=git_repo(base / "agents", AGENTS),
        release=git_repo(base / "release", RELEASE_ONLY),
        bare=git_repo(base / "bare", None),
        outside=outside,
    )


def fixture(name: str, cwd: Path, command: str | None = None) -> dict[str, Any]:
    """A fixture's hook input, run in cwd, with its command replaced when given"""
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    data["cwd"] = str(cwd)
    if command is not None:
        data["tool_input"]["command"] = command
    return data


def hook(data: object, mode: str = "pre", cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """delivery.py as Claude Code runs it"""
    where = cwd if cwd is not None else Path(data["cwd"]) if isinstance(data, dict) else ROOT
    text = data if isinstance(data, str) else json.dumps(data)
    return subprocess.run(
        [sys.executable, str(SCRIPT), mode], input=text, cwd=where, capture_output=True, text=True, check=False
    )


def bash(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return hook(fixture("bash-read.json", cwd, command))


def allowed(result: subprocess.CompletedProcess[str]) -> None:
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def refused(result: subprocess.CompletedProcess[str], rule: str, source: str) -> list[str]:
    """S-026-9: exit 2 and exactly three stderr lines; the Instead line's words"""
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 3, lines
    assert result.stderr.endswith("\n")
    assert lines[0].startswith(f"shipmill hook {rule}: ")
    assert lines[1].startswith("Rule: ") and lines[1].endswith(f" ({source})")
    assert lines[2].startswith("Instead: ")
    return shlex.split(lines[2].removeprefix("Instead: "))


# --- S-026-19: the hooks file, and a hook that can't start its script ------------------------

MODES = {"PreToolUse": "pre", "PostToolUse": "post"}
CANT_START = re.compile(
    r"shipmill hook: can't start hooks/delivery\.py \(.+\); this command runs unchecked, see shipmill doctor\n"
)


def hook_command(event: str) -> str:
    """The one command hooks/hooks.json runs for event"""
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    (command,) = [h["command"] for entry in hooks[event] for h in entry["hooks"]]
    assert isinstance(command, str)
    return command


def through_shell(
    event: str, data: dict[str, Any], env: dict[str, str], plugin_root: Path = ROOT, shell: str = "/bin/sh"
) -> subprocess.CompletedProcess[str]:
    """hooks.json's command for event as Claude Code runs it: through a shell, with
    CLAUDE_PLUGIN_ROOT set and the hook input on stdin"""
    return subprocess.run(
        [shell, "-c", hook_command(event)],
        input=json.dumps(data),
        cwd=data["cwd"],
        env={**env, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def clean_env(path: Path) -> dict[str, str]:
    """The test's environment with PATH set to path alone and no uv settings or virtualenv
    that would let uv find a Python the case means it not to"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_") and k != "VIRTUAL_ENV"}
    return {**env, "PATH": str(path), "UV_NO_CONFIG": "1"}


def only_uv(folder: Path) -> Path:
    """A PATH folder holding uv and nothing else"""
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("uv runs the hooks")
    folder.mkdir()
    (folder / "uv").symlink_to(Path(uv).resolve())
    return folder


def event_input(event: str, cwd: Path) -> dict[str, Any]:
    """A refused Bash command for the pre hook, an edit for the post hook"""
    return fixture("bash-rebase-merge-refused.json" if event == "PreToolUse" else "post-edit.json", cwd)


def cant_start(result: subprocess.CompletedProcess[str]) -> None:
    """Exit 1, never 2, and one stderr line naming shipmill doctor"""
    assert (result.returncode, result.stdout) == (1, ""), result.stderr
    assert CANT_START.fullmatch(result.stderr), result.stderr


def test_s026_19_hooks_json_declares_both_hooks() -> None:
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == set(MODES)
    assert [entry["matcher"] for entry in hooks["PreToolUse"]] == ["Bash"]
    assert [entry["matcher"] for entry in hooks["PostToolUse"]] == ["Edit|Write|MultiEdit"]
    for event, mode in MODES.items():
        command = hook_command(event)
        named = re.match(r'd="\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)"; ', command)
        assert named is not None, command
        assert named.group(1) == "hooks/delivery.py"
        assert (ROOT / named.group(1)).is_file()
        assert "uv python find --no-project '>=3.11'" in command
        assert "uv python install '>=3.11'" in command
        assert command.count(f'exec "$p" "$d" {mode};') == 1


def test_s026_19_hook_command_runs_the_script(box: Sandbox) -> None:
    """The pre command refuses a refused fixture with the script's own exit 2"""
    if shutil.which("uv") is None:
        pytest.fail("uv runs the hooks")
    data = fixture("bash-rebase-merge-refused.json", box.agents)
    refused(through_shell("PreToolUse", data, dict(os.environ)), "rebase-merge", "D-33")


SHELLS = [s for s in ("/bin/sh", "/bin/bash", "/bin/dash", "/bin/zsh") if Path(s).is_file()]


@pytest.mark.parametrize("shell", SHELLS)
def test_s026_19_hook_command_runs_under_each_shell(box: Sandbox, tmp_path: Path, shell: str) -> None:
    """A refused fixture still exits 2, and a missing uv exits 1, under every shell present"""
    data = fixture("bash-rebase-merge-refused.json", box.agents)
    refused(through_shell("PreToolUse", data, dict(os.environ), shell=shell), "rebase-merge", "D-33")
    empty = tmp_path / "empty"
    empty.mkdir()
    cant_start(through_shell("PreToolUse", data, clean_env(empty), shell=shell))


def test_s026_19_hook_command_quotes_a_plugin_root_with_spaces(box: Sandbox, tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.fail("uv runs the hooks")
    plugin = tmp_path / "plugin root"
    shutil.copytree(ROOT / "hooks", plugin / "hooks")
    data = fixture("bash-rebase-merge-refused.json", box.agents)
    refused(through_shell("PreToolUse", data, dict(os.environ), plugin), "rebase-merge", "D-33")


def test_s026_19_allowed_command_through_the_hook_exits_0(box: Sandbox) -> None:
    if shutil.which("uv") is None:
        pytest.fail("uv runs the hooks")
    allowed(through_shell("PreToolUse", fixture("bash-read.json", box.app), dict(os.environ)))


@pytest.mark.parametrize("event", sorted(MODES))
def test_s026_19_no_uv_on_path_exits_1(box: Sandbox, tmp_path: Path, event: str) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = through_shell(event, event_input(event, box.agents), clean_env(empty))
    cant_start(result)
    assert "(uv is not on PATH)" in result.stderr


@pytest.mark.parametrize("event", sorted(MODES))
def test_s026_19_failing_uv_exits_1(box: Sandbox, tmp_path: Path, event: str) -> None:
    """A uv that exits 2 for every call, as uv does when it can't get a Python"""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "uv").write_text("#!/bin/sh\necho 'error: no Python' >&2\nexit 2\n", encoding="utf-8")
    (fake / "uv").chmod(0o755)
    result = through_shell(event, event_input(event, box.agents), clean_env(fake))
    cant_start(result)
    assert "(uv can find or install no Python 3.11 or newer)" in result.stderr


@pytest.mark.parametrize("event", sorted(MODES))
def test_s026_19_uv_printing_no_path_exits_1(box: Sandbox, tmp_path: Path, event: str) -> None:
    """A uv whose python find exits 0 but prints no path: the hook still exits 1, not 127"""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake / "uv").chmod(0o755)
    result = through_shell(event, event_input(event, box.agents), clean_env(fake))
    cant_start(result)
    assert "(uv can find or install no Python 3.11 or newer)" in result.stderr


@pytest.mark.parametrize("setting", [{"UV_OFFLINE": "1"}, {"UV_PYTHON_DOWNLOADS": "never"}], ids=["offline", "never"])
@pytest.mark.parametrize("event", sorted(MODES))
def test_s026_19_no_python_uv_can_get_exits_1(
    box: Sandbox, tmp_path: Path, event: str, setting: dict[str, str]
) -> None:
    """The real uv, limited to its own Pythons in an empty folder, offline or with downloads
    off: it can neither find nor install a Python 3.11"""
    installs = tmp_path / "pythons"
    installs.mkdir()
    env = {
        **clean_env(only_uv(tmp_path / "bin")),
        "UV_MANAGED_PYTHON": "1",
        "UV_PYTHON_INSTALL_DIR": str(installs),
        **setting,
    }
    result = through_shell(event, event_input(event, box.agents), env)
    cant_start(result)
    assert "(uv can find or install no Python 3.11 or newer)" in result.stderr
    assert [p.name for p in installs.iterdir() if not p.name.startswith(".")] == []  # nothing downloaded


@pytest.mark.parametrize("event", sorted(MODES))
def test_s026_19_missing_script_exits_1(box: Sandbox, tmp_path: Path, event: str) -> None:
    result = through_shell(
        event, event_input(event, box.agents), clean_env(only_uv(tmp_path / "bin")), tmp_path / "no-plugin"
    )
    cant_start(result)
    assert f"(no file {tmp_path / 'no-plugin' / 'hooks' / 'delivery.py'})" in result.stderr


def test_s026_19_script_runs_under_python_311(box: Sandbox) -> None:
    """The hook needs only Python 3.11 (tomllib), whatever the package needs"""
    uv = shutil.which("uv")
    assert uv is not None, "uv runs the hooks"
    # uv reports a download on stderr; install 3.11 first so the measured run's stderr is the hook's
    subprocess.run([uv, "python", "install", "3.11"], capture_output=True, check=True)
    data = json.dumps(fixture("bash-force-push-refused.json", box.agents))
    command = [uv, "run", "--no-project", "--python", "3.11", "python", str(SCRIPT), "pre"]
    result = subprocess.run(command, input=data, cwd=box.agents, capture_output=True, text=True, check=False)
    refused(result, "force-push", "D-36")


# --- S-026-2: where the rules apply ----------------------------------------------------------

REFUSED_FIXTURES = sorted(p.name for p in FIXTURES.glob("bash-*-refused.json"))


SOURCES = {
    "app-writes": "D-14",
    "default-branch-push": "D-36",
    "rebase-merge": "D-33",
    "force-push": "D-36",
    "private-paths": "D-36",
}


def test_s026_17_fixtures_hold_a_refused_and_an_allowed_case_per_rule() -> None:
    names = {p.name for p in FIXTURES.glob("bash-*.json")}
    assert {f"bash-{rule}-{case}.json" for rule in SOURCES for case in ("refused", "allowed")} <= names
    for name in names:
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert set(data) >= {"session_id", "transcript_path", "cwd", "permission_mode", "hook_event_name"}
        assert (data["hook_event_name"], data["tool_name"], list(data["tool_input"])[0]) == (
            "PreToolUse",
            "Bash",
            "command",
        )


@pytest.mark.parametrize("rule", sorted(SOURCES))
def test_s026_17_each_rules_fixtures_refuse_and_allow(box: Sandbox, rule: str) -> None:
    refused(hook(fixture(f"bash-{rule}-refused.json", box.app)), rule, SOURCES[rule])
    allowed(hook(fixture(f"bash-{rule}-allowed.json", box.app if rule != "rebase-merge" else box.agents)))


@pytest.mark.parametrize("name", REFUSED_FIXTURES)
def test_s026_2_refused_fixtures_pass_where_no_agents(box: Sandbox, name: str) -> None:
    rule = name.removeprefix("bash-").removesuffix("-refused.json")
    refused(hook(fixture(name, box.app)), rule, SOURCES[rule])
    for folder in (box.outside, box.bare, box.release, box.release / ".github"):
        allowed(hook(fixture(name, folder)))


# --- S-026-3: app-writes ---------------------------------------------------------------------

GH_WRITES = (
    [f"gh issue {sub} 7" for sub in ("create", "comment", "edit", "close", "reopen", "delete", "lock", "unlock")]
    + [f"gh issue {sub} 7" for sub in ("pin", "unpin", "transfer", "develop")]
    + [f"gh pr {sub} 7" for sub in ("create", "comment", "edit", "close", "reopen", "merge", "review", "ready")]
    + [f"gh pr {sub} 7" for sub in ("lock", "unlock", "update-branch")]
    + [f"gh label {sub} bug" for sub in ("create", "edit", "delete", "clone")]
    + [f"gh release {sub} v1.0.0" for sub in ("create", "edit", "delete", "delete-asset", "upload")]
    + [f"gh workflow {sub} ci.yml" for sub in ("run", "enable", "disable")]
    + [f"gh run {sub} 123" for sub in ("rerun", "cancel", "delete")]
    + [f"gh repo {sub} o/r" for sub in ("create", "edit", "delete", "rename", "archive", "unarchive", "fork")]
    + [f"gh {group} {sub} NAME" for group in ("secret", "variable") for sub in ("set", "delete")]
    + [
        "gh issue comment 7 --body 'Fixed in #8'",
        "gh pr merge 7 --squash --delete-branch",
        "gh pr -R o/r merge 7 --squash",
        "gh api -X POST repos/o/r/issues/7/comments -f body=hi",
        "gh api --method PATCH repos/o/r/issues/7",
        "gh api --method=DELETE repos/o/r/issues/7/labels/bug",
        "gh api -XPUT repos/o/r/pulls/7/merge",
        "gh api repos/o/r/issues/7/comments -f body=hi",
        "gh api repos/o/r/labels -F name=bug",
        "gh api repos/o/r/labels --field name=bug",
        "gh api repos/o/r/labels --raw-field=name=bug",
        "gh api repos/o/r/labels --input label.json",
        "gh api graphql -f query='mutation { addComment(input: $input) { clientMutationId } }'",
        "gh api graphql -F query=@mutation.graphql",
    ]
)
GH_READS = (
    "gh pr view 7",
    "gh pr list --state open",
    "gh pr checks 7",
    "gh pr diff 7",
    "gh issue view 7 --comments",
    "gh issue list --label bug",
    "gh run view 123 --log-failed",
    "gh run list",
    "gh release view v1.0.0",
    "gh label list",
    "gh repo view o/r",
    "gh auth status",
    "gh api repos/o/r/pulls/7",
    "gh api -X GET repos/o/r/issues -f state=open",
    "gh api --method GET search/issues -F q=repo:o/r",
    "gh api graphql -f query='query { viewer { login } }'",
)


def gh_args(command: str) -> list[str]:
    words = shlex.split(command)
    return words[words.index("gh") + 1 :]


@pytest.mark.parametrize("command", GH_WRITES)
def test_s026_3_gh_write_refused_with_app_id(box: Sandbox, command: str) -> None:
    for prefix in ("", "GH_TOKEN=$T ", 'GH_TOKEN="$(cat token)" '):
        instead = refused(bash(prefix + command, box.app), "app-writes", "D-14")
        assert instead == [*SHIPMILL, "gh", *gh_args(command)]


@pytest.mark.parametrize("command", GH_WRITES)
def test_s026_3_gh_write_passes_as_shipmill_gh_or_without_app_id(box: Sandbox, command: str) -> None:
    args = shlex.join(gh_args(command))
    allowed(bash(f"shipmill gh {args}", box.app))
    allowed(bash(f"uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill gh {args}", box.app))
    allowed(bash(f"uvx --from ./shipmill shipmill gh {args}", box.app))
    allowed(bash(command, box.agents))
    allowed(bash(f"GH_TOKEN=$T {command}", box.agents))


@pytest.mark.parametrize("command", GH_READS)
def test_s026_3_gh_read_passes_with_app_id(box: Sandbox, command: str) -> None:
    allowed(bash(command, box.app))
    allowed(bash(f"GH_TOKEN=$T {command}", box.app))


def test_s026_3_refusal_fixture_names_the_rule_and_shipmill_gh(box: Sandbox) -> None:
    result = hook(fixture("bash-app-writes-refused.json", box.app))
    instead = refused(result, "app-writes", "D-14")
    assert instead == [*SHIPMILL, "gh", "pr", "comment", "412", "--body", "Reviewed: green, merging"]
    allowed(hook(fixture("bash-app-writes-allowed.json", box.app)))


# --- S-026-5: rebase-merge -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "squashed"),
    [
        ("gh pr merge 7 --rebase", "gh pr merge 7 --squash"),
        ("gh pr merge 7 -r", "gh pr merge 7 --squash"),
        ("gh pr merge 7 --rebase --delete-branch", "gh pr merge 7 --delete-branch --squash"),
        ("gh pr merge 7 -dr", "gh pr merge 7 -d --squash"),
        ("gh pr merge 7 --rebase=true --subject x", "gh pr merge 7 --subject x --squash"),
        ("gh api -X PUT repos/o/r/pulls/7/merge -f merge_method=rebase", None),
        ("gh api repos/o/r/pulls/7/merge -X PUT -fmerge_method=rebase", None),
    ],
)
def test_s026_5_rebase_merge_refused(box: Sandbox, command: str, squashed: str | None) -> None:
    instead = refused(bash(command, box.agents), "rebase-merge", "D-33")
    if squashed is not None:
        assert instead == shlex.split(squashed)
    else:
        assert instead == shlex.split(command.replace("merge_method=rebase", "merge_method=squash"))


def test_s026_5_rebase_merge_takes_the_app_fix_too(box: Sandbox) -> None:
    """With app_id both rules refuse; the first names its rule, and Instead holds both fixes"""
    result = hook(fixture("bash-rebase-merge-refused.json", box.app))
    assert refused(result, "rebase-merge", "D-33") == [*SHIPMILL, "gh", "pr", "merge", "412", "--squash"]
    refused(bash("shipmill gh pr merge 412 -r", box.app), "rebase-merge", "D-33")


def test_s026_9_rebase_merge_refusal_reads_as_the_spec_shows(box: Sandbox) -> None:
    result = hook(fixture("bash-rebase-merge-refused.json", box.agents))
    assert result.returncode == 2
    assert result.stderr == (
        "shipmill hook rebase-merge: gh pr merge 412 --rebase\n"
        "Rule: land with a squash, or a merge commit for a stack's base; never rebase-merge (D-33)\n"
        "Instead: gh pr merge 412 --squash\n"
    )


@pytest.mark.parametrize("command", ["gh pr merge 7 --squash", "gh pr merge 7 --merge", "gh pr merge 7 -s --auto"])
def test_s026_5_squash_and_merge_commit_pass(box: Sandbox, command: str) -> None:
    allowed(bash(command, box.agents))
    allowed(bash(f"shipmill gh {command.removeprefix('gh ')}", box.app))
    allowed(hook(fixture("bash-rebase-merge-allowed.json", box.agents)))


# --- S-026-6: force-push ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "lease"),
    [
        ("git push --force origin feat/x", "git push --force-with-lease=feat/x:<sha> origin feat/x"),
        ("git push -f origin feat/x", "git push --force-with-lease=feat/x:<sha> origin feat/x"),
        ("git push -uf origin feat/x", "git push --force-with-lease=feat/x:<sha> -u origin feat/x"),
        ("git push origin +feat/x", "git push --force-with-lease=feat/x:<sha> origin feat/x"),
        ("git push origin +HEAD:refs/heads/x", "git push --force-with-lease=x:<sha> origin HEAD:refs/heads/x"),
        ("git push --force-with-lease origin feat/x", "git push --force-with-lease=feat/x:<sha> origin feat/x"),
        ("git push --force-with-lease=feat/x origin feat/x", "git push --force-with-lease=feat/x:<sha> origin feat/x"),
        ("git push --force", "git push --force-with-lease=<branch>:<sha>"),
        ("git push --force --force-with-lease=x:abc123 origin x", "git push --force-with-lease=x:abc123 origin x"),
        ("git -C . push -f origin feat/x", "git -C . push --force-with-lease=feat/x:<sha> origin feat/x"),
        # a + refspec to the default branch is force-push's too, whatever default-branch-push says
        ("git push origin +main", "git push --force-with-lease=main:<sha> origin main"),
    ],
)
def test_s026_6_force_push_refused(box: Sandbox, command: str, lease: str) -> None:
    assert refused(bash(command, box.agents), "force-push", "D-36") == shlex.split(lease)
    # where origin/HEAD is main, a push to main is default-branch-push's first (S-026-4)
    rule = "default-branch-push" if command in ("git push origin +main", "git push --force") else "force-push"
    refused(bash(command, box.app), rule, "D-36")


@pytest.mark.parametrize(
    "command",
    [
        "git push --force-with-lease=feat/x:3f6b1c2d origin fix:feat/x",
        "git push --force-with-lease=feat/x:3f6b1c2d origin HEAD:feat/x",
        "git push -u origin feat/x",
        "git push origin feat/x",
        "git push",
        "git push -o ci.skip origin feat/x",
        "git push origin v1.2.0",
    ],
)
def test_s026_6_pinned_lease_and_plain_push_pass(box: Sandbox, command: str) -> None:
    allowed(bash(command, box.agents))
    if command != "git push":  # box.app is on main, whose push target is the default branch (S-026-4)
        allowed(bash(command, box.app))
    allowed(hook(fixture("bash-force-push-allowed.json", box.app)))


# --- S-026-4: default-branch-push ------------------------------------------------------------

TO_MAIN = [
    ("git push origin main", "git push origin main:<branch>"),
    ("git push origin HEAD:main", "git push origin HEAD:<branch>"),
    ("git push origin refs/heads/main", "git push origin refs/heads/main:<branch>"),
    ("git push origin :main", "git push origin :<branch>"),
    ("git push -u origin HEAD:refs/heads/main", "git push -u origin HEAD:<branch>"),
    ("git push origin HEAD", "git push origin HEAD:<branch>"),
    ("git push -o ci.skip origin feat/x main", "git push -o ci.skip origin feat/x main:<branch>"),
    ("git push", "git push origin HEAD:<branch>"),
    ("git push origin", "git push origin HEAD:<branch>"),
]
PLUS_MAIN = "git push origin +main"


def pushing_repo(root: Path, config: str = AGENTS) -> Path:
    """A clone on main whose upstream is origin/main, with origin/HEAD at main"""
    git_repo(root, config, origin=True)
    _git("branch", "-q", "--set-upstream-to=origin/main", cwd=root)
    return root


@pytest.mark.parametrize(("command", "instead"), TO_MAIN)
def test_s026_4_push_to_the_default_branch_refused(tmp_path: Path, command: str, instead: str) -> None:
    root = pushing_repo(tmp_path / "repo")
    assert refused(bash(command, root), "default-branch-push", "D-36") == shlex.split(instead)
    refused(bash(f"git -C {root} {command.removeprefix('git ')}", tmp_path), "default-branch-push", "D-36")
    refused(bash(f"cd {root} && {command}", tmp_path), "default-branch-push", "D-36")


def test_s026_4_plus_refspec_to_main_refused_with_a_lease_on_a_branch(tmp_path: Path) -> None:
    root = pushing_repo(tmp_path / "repo")
    instead = refused(bash(PLUS_MAIN, root), "default-branch-push", "D-36")
    assert instead == shlex.split("git push --force-with-lease=<branch>:<sha> origin main:<branch>")
    instead = refused(bash("git push --force", root), "default-branch-push", "D-36")
    assert instead == shlex.split("git push --force-with-lease=<branch>:<sha> origin HEAD:<branch>")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feat/x",
        "git push origin HEAD:feat/x",
        "git push origin main:feat/x",
        "git push origin refs/heads/main:refs/heads/feat/x",
        "git push origin v1.2.0",
        "git push --tags",
        "git push upstream-less-remote feat/main",
    ],
)
def test_s026_4_push_of_another_branch_passes(tmp_path: Path, command: str) -> None:
    allowed(bash(command, pushing_repo(tmp_path / "repo")))


def test_s026_4_bare_push_on_another_branch_passes(tmp_path: Path) -> None:
    root = pushing_repo(tmp_path / "repo")
    _git("checkout", "-q", "-b", "feat/x", cwd=root)
    _git("push", "-q", "-u", "origin", "feat/x", cwd=root)
    allowed(bash("git push", root))
    allowed(bash("git push origin HEAD", root))
    refused(bash("git push origin main", root), "default-branch-push", "D-36")


def test_s026_4_bare_push_without_an_upstream_passes(tmp_path: Path) -> None:
    root = pushing_repo(tmp_path / "repo")
    _git("checkout", "-q", "-b", "feat/new", cwd=root)
    allowed(bash("git push", root))


@pytest.mark.parametrize("command", [command for command, _ in TO_MAIN])
def test_s026_4_every_push_passes_when_switched_off_or_origin_head_unset(tmp_path: Path, command: str) -> None:
    off = pushing_repo(tmp_path / "off", AGENTS + "[hooks]\ndefault_branch = false\n")
    allowed(bash(command, off))
    unset = pushing_repo(tmp_path / "unset")
    _git("remote", "set-head", "origin", "--delete", cwd=unset)
    allowed(bash(command, unset))


def test_s026_4_plus_main_is_still_a_force_push_when_switched_off(tmp_path: Path) -> None:
    """force-push has no switch (S-026-6): a + refspec needs a pinned lease wherever it points"""
    off = pushing_repo(tmp_path / "off", AGENTS + "[hooks]\ndefault_branch = false\n")
    refused(bash(PLUS_MAIN, off), "force-push", "D-36")
    unset = pushing_repo(tmp_path / "unset")
    _git("remote", "set-head", "origin", "--delete", cwd=unset)
    refused(bash(PLUS_MAIN, unset), "force-push", "D-36")


def test_s026_4_fixtures(box: Sandbox) -> None:
    instead = refused(hook(fixture("bash-default-branch-push-refused.json", box.app)), "default-branch-push", "D-36")
    assert instead == shlex.split("git push origin main:<branch>")
    allowed(hook(fixture("bash-default-branch-push-allowed.json", box.app)))


# --- S-026-7: private-paths ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "instead"),
    [
        ("cp owner/notes.md {out}/notes.md", "leave owner/notes.md in the repo"),
        ("mv owner/notes.md {out}/", "leave owner/notes.md in the repo"),
        ("rsync -av owner/ {out}/", "leave owner/ in the repo"),
        ("rsync -a --exclude .git -e ssh owner/notes.md host:backup/", "leave owner/notes.md in the repo"),
        ("cp -r owner {out}", "leave owner in the repo"),
        ("cp -R ./owner/plans/q4.md ../elsewhere/", "leave ./owner/plans/q4.md in the repo"),
        ("cp -t {out} owner/notes.md", "leave owner/notes.md in the repo"),
        ("cp --target-directory={out} owner/notes.md", "leave owner/notes.md in the repo"),
        ("cp owner/* {out}", "leave 'owner/*' in the repo"),
        ("cp -r . {out}/copy", "leave . in the repo"),
        ("cp README.md owner/notes.md {out}", "cp README.md {out}"),
        ("rsync -a docs owner {out}", "rsync -a docs {out}"),
        ("cd owner && cp notes.md {out}", "leave notes.md in the repo"),
        ("cd docs && cp ../owner/notes.md /tmp/notes.md", "leave ../owner/notes.md in the repo"),
    ],
)
def test_s026_7_copy_of_a_private_path_out_of_the_repo_refused(box: Sandbox, command: str, instead: str) -> None:
    run = command.format(out=box.outside)
    words = refused(bash(run, box.app), "private-paths", "D-36")
    assert words == shlex.split(instead.format(out=box.outside))
    allowed(bash(run, box.agents))  # no private key: every copy passes


@pytest.mark.parametrize(
    "command",
    [
        "cp owner/notes.md tmp/notes.md",
        "cp -r owner docs/owner-copy",
        "mv owner/notes.md owner/old/notes.md",
        "rsync -a owner/ {app}/tmp/owner/",
        "cd owner && cp notes.md ../tmp/",
        "cp README.md {out}",
        "rsync -av docs/ host:site/",
        "cp ownership.md {out}",
        "cp -t docs owner/notes.md",
        "cp {out}/a.md {out}/b.md",
        "cat owner/notes.md",
    ],
)
def test_s026_7_copy_inside_the_repo_or_of_another_path_passes(box: Sandbox, command: str) -> None:
    allowed(bash(command.format(out=box.outside, app=box.app), box.app))


def test_s026_7_fixtures(box: Sandbox) -> None:
    refused(hook(fixture("bash-private-paths-refused.json", box.app)), "private-paths", "D-36")
    allowed(hook(fixture("bash-private-paths-allowed.json", box.app)))
    allowed(hook(fixture("bash-private-paths-refused.json", box.agents)))


# --- The gate's own commands -----------------------------------------------------------------

GATE_COMMANDS = (
    "uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill gh pr merge 7 --squash",
    "uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill gh issue comment 7 --body-file tmp/verdict.md",
    "uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill gh pr create --title T --body-file tmp/pr.md",
    "uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill gh label create shipmill-hold --color FF0000",
    "shipmill gh pr merge 7 --squash",
    "git push -u origin feat/441-delivery-hooks",
    "git push --force-with-lease=feat/441-delivery-hooks:3f6b1c2d origin fix:feat/441-delivery-hooks",
    "git -C /tmp/worktree push -u origin feat/x",
    "git fetch origin",
    "git rebase origin/main",
    'git commit -m "Add the hooks" -- hooks/delivery.py',
    "gh pr view 7 --json state,mergeable,statusCheckRollup",
    "gh pr checks 7",
    "gh issue view 7 --comments",
    "gh run view 123 --log-failed",
    "gh api repos/shipmill/shipmill/pulls/7",
    "gh api graphql -f query='query { repository(owner: $o, name: $r) { id } }' -f o=shipmill -f r=shipmill",
    "uv run pytest -q",
    "uv run --no-project python skills/github-issue-triage/scripts/specs.py check",
)


@pytest.mark.parametrize("command", GATE_COMMANDS)
def test_the_gates_own_commands_pass_with_app_id(box: Sandbox, command: str) -> None:
    allowed(bash(command, box.app))


def test_plain_gh_merge_is_refused_with_app_id(box: Sandbox) -> None:
    """D-14: a squash merge is a write too, so with app_id it goes through shipmill gh"""
    result = hook(fixture("bash-rebase-merge-allowed.json", box.app))
    assert refused(result, "app-writes", "D-14") == [*SHIPMILL, "gh", "pr", "merge", "412", "--squash"]


# --- S-026-8: reading the command ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git status && gh pr merge 7 --rebase",
        "false || gh pr merge 7 --rebase",
        "echo merging; gh pr merge 7 --rebase",
        "echo y | gh pr merge 7 --rebase",
        "git fetch origin\ngh pr merge 7 --rebase",
        "A=1 B='two words' gh pr merge 7 --rebase",
        "env A=1 gh pr merge 7 --rebase",
        "gh pr merge 7 --rebase 2>&1 | tail -5",
        "for n in 7 8; do gh pr merge $n --rebase; done",
        "(gh pr merge 7 --rebase)",
        "# merge it\ngh pr merge 7 --rebase",
        "gh pr merge 7 \\\n  --rebase",
        "cat <<'EOF'\nhello\nEOF\ngh pr merge 7 --rebase",
    ],
)
def test_s026_8_refused_command_found_in_a_compound_command(box: Sandbox, command: str) -> None:
    refused(bash(command, box.agents), "rebase-merge", "D-33")


def test_s026_8_cd_and_git_c_decide_the_repo(box: Sandbox) -> None:
    refused(bash(f"cd {box.agents} && gh pr merge 7 --rebase", box.outside), "rebase-merge", "D-33")
    refused(bash(f"cd {box.agents}/.github && git push -f origin x", box.outside), "force-push", "D-36")
    refused(bash(f"git -C {box.agents} push -f origin x", box.outside), "force-push", "D-36")
    refused(bash(f"git -C {box.outside} -C ../agents push -f origin x", box.outside), "force-push", "D-36")
    allowed(bash(f"cd {box.outside} && gh pr merge 7 --rebase", box.agents))
    allowed(bash(f"cd {box.release} && git push --force", box.agents))
    allowed(bash(f"git -C {box.outside} push -f origin x", box.agents))
    allowed(bash(f"(cd {box.agents}); gh pr merge 7 --rebase", box.outside))
    refused(bash(f"(cd {box.outside}); gh pr merge 7 --rebase", box.agents), "rebase-merge", "D-33")


def test_s026_8_app_writes_follows_cd_to_the_app_repo(box: Sandbox) -> None:
    refused(bash(f"cd {box.app} && gh pr comment 7 --body hi", box.agents), "app-writes", "D-14")
    allowed(bash(f"cd {box.agents} && gh pr comment 7 --body hi", box.app))


def test_s026_8_worktree_git_file_marks_the_repo(box: Sandbox, tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _git("worktree", "add", "-q", "-b", "hooks-tree", str(tree), cwd=box.app)
    assert (tree / ".git").is_file()
    (tree / "sub").mkdir()
    refused(bash("gh pr comment 7 --body hi", tree / "sub"), "app-writes", "D-14")
    _git("worktree", "remove", "--force", str(tree), cwd=box.app)


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 7 --rebase 'unclosed",
        "bash -c 'gh pr merge 7 --rebase'",
        'sh -c "git push --force origin x"',
        'eval "gh pr merge 7 --rebase"',
        "echo $(gh pr merge 7 --rebase)",
        'echo "$(git push -f origin x)"',
        "cat <<'EOF'\ngit push --force origin x\ngh pr merge 7 --rebase\nEOF",
        "git commit -m 'never run gh pr merge 7 --rebase && git push -f'",
        "git commit -m \"$(cat <<'EOF'\nNo git push --force here\nEOF\n)\" -- hooks/delivery.py",
        "ls # git push --force",
        "git push --force-with-lease=x:$(git rev-parse origin/x) origin x",
    ],
)
def test_s026_8_unparsed_constructs_pass(box: Sandbox, command: str) -> None:
    allowed(bash(command, box.agents))


def test_s026_8_here_document_body_is_not_a_command(box: Sandbox) -> None:
    command = "uvx --from x shipmill gh pr create --body-file - <<'EOF'\nWe never git push --force origin main\nEOF"
    allowed(bash(command, box.app))
    refused(bash(command.replace("uvx --from x shipmill gh", "gh"), box.app), "app-writes", "D-14")


QUOTED_BODY = (
    "uvx --from x shipmill gh pr create --title T --body \"$(cat <<'EOF'\n"
    'The hook refuses "a && gh pr merge 5 --rebase" and "x; git push -f origin x"\n'
    "Don't (ever) do it\n"
    'EOF\n)" && echo done'
)


def test_s026_8_double_quotes_in_a_quoted_substitution_are_its_own(box: Sandbox) -> None:
    """A body's quotes inside "$(cat <<'EOF' ... EOF)" don't end the quotes around it"""
    allowed(bash(QUOTED_BODY, box.app))
    allowed(bash(QUOTED_BODY.replace("uvx --from x shipmill gh pr create", "git commit"), box.app))
    instead = refused(bash(QUOTED_BODY.replace("uvx --from x shipmill gh", "gh"), box.app), "app-writes", "D-14")
    assert instead[:-1] == [*SHIPMILL, "gh", "pr", "create", "--title", "T", "--body"]
    assert instead[-1].startswith("$(cat <<'EOF'") and 'refuses "a && gh pr merge 5 --rebase"' in instead[-1]


# --- S-026-9: what a refusal says ------------------------------------------------------------


def test_s026_9_refusal_cuts_the_command_to_200_characters(box: Sandbox) -> None:
    body = "x" * 300
    result = bash(f"gh pr merge 7 --rebase --body {body}", box.agents)
    refused(result, "rebase-merge", "D-33")
    first = result.stderr.splitlines()[0]
    assert first == f"shipmill hook rebase-merge: {f'gh pr merge 7 --rebase --body {body}'[:200]}"


def test_s026_9_refusal_stays_three_lines_with_a_multiline_argument(box: Sandbox) -> None:
    result = bash("gh pr comment 7 --body 'line one\nline two'", box.app)
    refused(result, "app-writes", "D-14")


# --- S-026-10: no subprocess, one config read ------------------------------------------------


@pytest.fixture(scope="module")
def delivery() -> ModuleType:
    spec = importlib.util.spec_from_file_location("delivery", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@dataclass
class Counted:
    """The script's injected runner and config reader, counting their calls"""

    runs: int = 0
    reads: int = 0

    def runner(self, cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.runs += 1
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    def read(self, path: Path) -> str | None:
        self.reads += 1
        return path.read_text(encoding="utf-8") if path.is_file() else None


def in_process(delivery: ModuleType, data: dict[str, Any], mode: str = "pre") -> tuple[int, Counted]:
    counted = Counted()
    stderr = io.StringIO()
    code = delivery.main([mode], io.StringIO(json.dumps(data)), stderr, counted.runner, counted.read)
    assert isinstance(code, int)
    return code, counted


@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "git status",
        "gh pr view 7",
        "gh pr comment 7 --body hi",
        "gh pr merge 7 --rebase",
        "gh pr merge 7 --squash && gh pr comment 7 -b merged && gh issue close 8",
        "shipmill gh pr merge 7 --squash; uvx --from x shipmill gh issue close 8",
        "cd .github && gh api -X POST repos/o/r/issues -f title=x",
        "cp owner/notes.md /tmp/notes.md",
        "mv README.md docs/ && rsync -a owner/ host:backup/ && cp -r . /tmp/copy",
    ],
)
def test_s026_10_no_subprocess_and_one_config_read(delivery: ModuleType, box: Sandbox, command: str) -> None:
    code, counted = in_process(delivery, fixture("bash-read.json", box.app, command))
    assert code in (0, 2)
    assert counted.runs == 0
    assert counted.reads <= 1


def test_s026_10_only_git_push_starts_git(delivery: ModuleType, box: Sandbox, tmp_path: Path) -> None:
    """A push asks git for origin/HEAD (the counting runner answers nothing, so no more);
    switched off, or in a repo without [agents], it asks nothing"""
    _, counted = in_process(delivery, fixture("bash-read.json", box.app, "git push origin feat/x"))
    assert (counted.runs, counted.reads) == (1, 1)
    _, counted = in_process(delivery, fixture("bash-read.json", box.app, "git push && git push origin HEAD"))
    assert (counted.runs, counted.reads) == (2, 1)
    off = git_repo(tmp_path / "off", AGENTS + "[hooks]\ndefault_branch = false\n")
    _, counted = in_process(delivery, fixture("bash-read.json", off, "git push origin main"))
    assert (counted.runs, counted.reads) == (0, 1)
    _, counted = in_process(delivery, fixture("bash-read.json", box.release, "git push origin main"))
    assert counted.runs == 0


def test_s026_10_unguarded_command_reads_no_config(delivery: ModuleType, box: Sandbox) -> None:
    _, counted = in_process(delivery, fixture("bash-read.json", box.app, "ls && git status && gh pr view 7"))
    assert (counted.runs, counted.reads) == (0, 0)


@pytest.mark.parametrize("name", ["post-edit.json", "post-write.json", "post-multiedit.json"])
def test_s026_10_edit_starts_no_subprocess(delivery: ModuleType, box: Sandbox, name: str) -> None:
    data = fixture(name, box.app)
    data["tool_input"]["file_path"] = str(box.app / "src" / "app.py")
    assert in_process(delivery, data, "post") == (0, Counted(0, 0))
    allowed(hook(data, "post"))


def test_s026_10_edit_of_a_checked_path_outside_agents_starts_no_subprocess(delivery: ModuleType, box: Sandbox) -> None:
    for root in (box.release, box.bare):
        data = edit("post-product-check.json", root, "docs/product.md")
        assert in_process(delivery, data, "post")[0] == 0
        assert in_process(delivery, data, "post")[1].runs == 0


# --- S-026-13: the checks after an edit ------------------------------------------------------

STUB = """#!{python}
import json, os, sys
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write(os.environ.get("STUB_OUT", ""))
sys.stderr.write(os.environ.get("STUB_ERR", ""))
sys.exit(int(os.environ["STUB_EXIT"]))
"""


def edit(name: str, root: Path, rel: str) -> dict[str, Any]:
    """A PostToolUse fixture's input for an edit of rel in root"""
    data = fixture(name, root)
    data["tool_input"]["file_path"] = str(root / rel)
    return data


@dataclass(frozen=True)
class Stub:
    """A shipmill first on PATH that records its arguments and exits as the test sets"""

    bin: Path
    log: Path

    def run(
        self, data: dict[str, Any], code: int = 0, out: str = "", err: str = ""
    ) -> subprocess.CompletedProcess[str]:
        env = {"PATH": str(self.bin), "STUB_LOG": str(self.log), "STUB_EXIT": str(code)}
        env |= {"STUB_OUT": out, "STUB_ERR": err}
        return subprocess.run(
            [sys.executable, str(SCRIPT), "post"],
            input=json.dumps(data),
            cwd=data["cwd"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


def stub_on_path(tmp_path: Path, program: str) -> Stub:
    """A PATH holding only program, a stub"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / program
    script.write_text(STUB.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    return Stub(bin_dir, tmp_path / "calls.jsonl")


@pytest.fixture
def stub(tmp_path: Path) -> Stub:
    return stub_on_path(tmp_path, "shipmill")


EDIT_FIXTURES = ["post-edit.json", "post-write.json", "post-multiedit.json"]
CHECKED = [
    ("docs/product.md", "product"),
    ("docs/product/goals.md", "product"),
    ("docs/product/areas/release.md", "product"),
    ("REVIEW.md", "review"),
    ("src/shipmill/REVIEW.md", "review"),
]


@pytest.mark.parametrize("name", EDIT_FIXTURES)
@pytest.mark.parametrize(("rel", "check"), CHECKED)
def test_s026_13_edit_runs_its_check_and_a_pass_is_silent(
    box: Sandbox, stub: Stub, name: str, rel: str, check: str
) -> None:
    allowed(stub.run(edit(name, box.agents, rel), 0, out="ok\n"))
    assert stub.calls() == [[check, "check", "--repo", str(box.agents)]]


@pytest.mark.parametrize(("rel", "check"), CHECKED)
def test_s026_13_a_failed_check_exits_2_with_its_output(box: Sandbox, stub: Stub, rel: str, check: str) -> None:
    report = f"{rel}:5: a line the {check} check refuses\n"
    result = stub.run(edit("post-edit.json", box.agents, rel), 1, out=report, err="1 problem\n")
    assert (result.returncode, result.stdout, result.stderr) == (2, "", f"{report}1 problem\n")


@pytest.mark.parametrize(("rel", "check"), CHECKED)
def test_s026_13_a_check_exiting_2_exits_1(box: Sandbox, stub: Stub, rel: str, check: str) -> None:
    result = stub.run(edit("post-write.json", box.agents, rel), 2, err="error: bad input")
    assert result.returncode == 1
    assert result.stderr.startswith("error: bad input\n")
    assert f"{check} check --repo {box.agents}" in result.stderr and "exited 2" in result.stderr


def test_s026_13_a_check_that_cant_start_exits_1(box: Sandbox, tmp_path: Path) -> None:
    """Neither shipmill nor uvx on PATH: a visible error, not a crash"""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = Stub(empty, tmp_path / "calls.jsonl").run(edit("post-product-check.json", box.agents, "docs/product.md"))
    assert result.returncode == 1
    lines = result.stderr.splitlines()
    assert len(lines) == 1 and lines[0].startswith("shipmill hook: uvx --from ") and "didn't start" in lines[0]


def test_s026_13_without_shipmill_on_path_it_runs_through_uvx(box: Sandbox, tmp_path: Path) -> None:
    uvx = stub_on_path(tmp_path, "uvx")
    result = uvx.run(edit("post-review-check.json", box.agents, "REVIEW.md"), 1, out="REVIEW.md:3: no rule\n")
    assert (result.returncode, result.stderr) == (2, "REVIEW.md:3: no rule\n")
    assert uvx.calls() == [[*SHIPMILL[1:], "review", "check", "--repo", str(box.agents)]]


@pytest.mark.parametrize("program", ["uvx", "shipmill"])
def test_s026_13_exit_1_with_no_report_is_a_check_that_didnt_run(box: Sandbox, tmp_path: Path, program: str) -> None:
    """uvx exits 1 when it can't fetch shipmill (offline), and a traceback exits 1; the checks
    print a line per problem to stdout, so exit 1 with no stdout is an error, not a finding"""
    failing = stub_on_path(tmp_path, program)
    err = "error: Failed to resolve `--with` requirement\n"
    result = failing.run(edit("post-review-check.json", box.agents, "REVIEW.md"), 1, err=err)
    assert result.returncode == 1
    assert result.stderr.startswith(err) and "exited 1" in result.stderr


@pytest.mark.parametrize(
    "rel",
    [
        "src/app.py",
        "docs/productivity.md",
        "docs/product.md.bak",
        "docs/specs/024-intent.md",
        "REVIEW.md.orig",
        "README.md",
    ],
)
def test_s026_13_other_paths_run_no_check(box: Sandbox, stub: Stub, rel: str) -> None:
    for name in EDIT_FIXTURES:
        allowed(stub.run(edit(name, box.agents, rel), 1, out="must not run\n"))
    assert stub.calls() == []


def test_s026_13_no_check_outside_a_repo_with_agents(box: Sandbox, stub: Stub) -> None:
    for root in (box.release, box.bare):
        allowed(stub.run(edit("post-product-check.json", root, "docs/product.md"), 1, out="must not run\n"))
        allowed(stub.run(edit("post-review-check.json", root, "REVIEW.md"), 1, out="must not run\n"))
    outside = fixture("post-review-check.json", box.outside)
    outside["tool_input"]["file_path"] = str(box.outside / "REVIEW.md")
    allowed(stub.run(outside, 1, out="must not run\n"))
    assert stub.calls() == []


def test_s026_13_a_relative_file_path_is_read_against_the_cwd(box: Sandbox, stub: Stub) -> None:
    data = fixture("post-product-check.json", box.agents / ".github")
    data["tool_input"]["file_path"] = "../docs/product.md"
    allowed(stub.run(data))
    assert stub.calls() == [["product", "check", "--repo", str(box.agents)]]


def test_s026_13_a_broken_config_exits_1_naming_it(tmp_path: Path, stub: Stub) -> None:
    root = git_repo(tmp_path / "broken", "[agents\n")
    result = stub.run(edit("post-product-check.json", root, "docs/product.md"))
    assert result.returncode == 1 and "doesn't parse" in result.stderr
    assert stub.calls() == []


def test_s026_17_post_fixtures_hold_a_case_for_each_check(box: Sandbox, stub: Stub) -> None:
    for name, check in (("post-product-check.json", "product"), ("post-review-check.json", "review")):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert data["hook_event_name"] == "PostToolUse" and data["tool_name"] in ("Edit", "Write", "MultiEdit")
        assert "tool_response" in data
        rel = Path(data["tool_input"]["file_path"]).relative_to(data["cwd"]).as_posix()
        stub.log.unlink(missing_ok=True)
        allowed(stub.run(edit(name, box.agents, rel)))
        assert stub.calls() == [[check, "check", "--repo", str(box.agents)]]


# --- S-026-11: the input ---------------------------------------------------------------------


def without(data: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != key}


@pytest.mark.parametrize("key", ["hook_event_name", "tool_name", "tool_input"])
def test_s026_11_missing_field_exits_1_naming_it(box: Sandbox, key: str) -> None:
    for name, mode in (("bash-rebase-merge-refused.json", "pre"), ("post-edit.json", "post")):
        result = hook(without(fixture(name, box.agents), key), mode)
        assert result.returncode == 1
        assert key in result.stderr


@pytest.mark.parametrize("text", ["", "not json", "[]", '"gh pr merge 7 --rebase"', "null"])
def test_s026_11_not_a_json_object_exits_1(text: str) -> None:
    result = hook(text, "pre", ROOT)
    assert result.returncode == 1
    assert "JSON" in result.stderr


def test_s026_11_wrong_shapes_exit_1(box: Sandbox) -> None:
    data = fixture("bash-rebase-merge-refused.json", box.agents)
    for broken, named in (
        ({**data, "tool_input": "gh pr merge 7 --rebase"}, "tool_input"),
        ({**data, "tool_input": {"description": "x"}}, "tool_input.command"),
        ({**data, "tool_name": 3}, "tool_name"),
        ({**data, "cwd": "relative/dir"}, "cwd"),
        ({**data, "hook_event_name": "PostToolUse"}, "PreToolUse"),
    ):
        result = hook(broken, "pre", box.agents)
        assert result.returncode == 1 and named in result.stderr, result.stderr
    edit = fixture("post-edit.json", box.agents)
    result = hook({**edit, "tool_input": {"content": "x"}}, "post")
    assert result.returncode == 1 and "tool_input.file_path" in result.stderr


def test_s026_11_unknown_mode_exits_1(box: Sandbox) -> None:
    result = hook(fixture("bash-rebase-merge-refused.json", box.agents), "both")
    assert result.returncode == 1 and "usage" in result.stderr


def test_s026_11_unchecked_tool_exits_0(box: Sandbox) -> None:
    allowed(hook(fixture("read-tool.json", box.app)))
    post = fixture("post-edit.json", box.app)
    allowed(hook({**post, "tool_name": "Bash", "tool_input": {"command": "gh pr merge 7 --rebase"}}, "post"))


# --- S-026-12: a broken config ---------------------------------------------------------------

BROKEN = [
    ("[agents\napp_id = 1\n", "doesn't parse"),
    ("[agents]\napp_id = 'x'\n", "app_id"),
    ("[agents]\napp_id = 0\n", "app_id"),
    ("[agents]\napp_id = true\n", "app_id"),
    ("[agents]\n[hooks]\ndefault_branch = 'no'\n", "default_branch"),
    ("[agents]\n[hooks]\nprivate = 'owner/**'\n", "private"),
    ("[agents]\n[hooks]\nprivate = [1]\n", "private"),
    ("[agents]\n[hooks]\nsecret = true\n", "secret"),
    ("agents = 1\n", "[agents]"),
]
GUARDED = ["gh pr comment 7 --body hi", "git push origin feat/x", "gh pr merge 7 --squash", "git push --force"]
UNGUARDED = ["ls", "git status", "gh pr view 7", "shipmill gh pr comment 7 --body hi"]


@pytest.mark.parametrize(("config", "error"), BROKEN)
def test_s026_12_broken_config_refuses_guarded_commands(tmp_path: Path, config: str, error: str) -> None:
    root = git_repo(tmp_path / "broken", config)
    for command in GUARDED:
        result = bash(command, root)
        assert result.returncode == 2, (command, result.stderr)
        lines = result.stderr.splitlines()
        assert len(lines) == 3 and lines[0].startswith("shipmill hook config: ")
        assert lines[1].startswith("Rule: ") and error in lines[1] and lines[1].endswith(" (.github/shipmill.toml)")
        assert lines[2].startswith("Instead: fix .github/shipmill.toml")
    for command in UNGUARDED:
        allowed(bash(command, root))


def test_s026_12_a_valid_hooks_section_is_read(tmp_path: Path) -> None:
    config = '[agents]\napp_id = 1\n[hooks]\ndefault_branch = false\nprivate = ["owner/**"]\n'
    root = git_repo(tmp_path / "hooks", config)
    refused(bash("gh pr comment 7 --body hi", root), "app-writes", "D-14")
    allowed(bash("git push origin feat/x", root))
