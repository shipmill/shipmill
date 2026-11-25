"""A sandboxed headless launch (spec 087, #1531): `shipmill gate --sandbox` passes one inline
`--settings` JSON holding the session's env, its sandbox, and its permissions"""

import json
import plistlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.cli import _parser
from shipmill.errors import ReleaseError
from shipmill.gate import (
    GATE_SESSION,
    HEADLESS_TOOLS,
    MAINTAINER,
    RECORD,
    SANDBOX_REFUSED,
    STATE_FILES,
    Action,
    ClaudeCli,
    Sandboxer,
    gate,
    gate_paragraph,
    headless_paragraph,
    prompt,
    sandbox_for,
    state_dir,
    trusted_sandbox,
)
from shipmill.gitrepo import Git
from shipmill.launchd import build, cli_fix, read_job
from shipmill.sandbox import (
    DEFAULT_DOMAINS,
    DENIED,
    Domain,
    SandboxConfig,
    SandboxPath,
    Where,
    launch,
    project_folder,
)

from .test_app import APP_ID, REPO
from .test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, bg
from .test_gate_headless import (
    LOGIN,
    NAME,
    SESSION,
    STARTED,
    Reads,
    Spawned,
    headless,
    interactive,
    login,
    same,
)
from .test_launchd import nothing, tools

KEY = f"app-{APP_ID}.pem"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main"]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.fixture
def checkout(tmp_path: Path) -> Git:
    """A clone of a local origin named as the gate's repo, with one commit on main"""
    seed = tmp_path / "seed"
    subprocess.run([*GIT, "init", "-q", str(seed)], check=True)
    (seed / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run([*GIT, "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run([*GIT, "-C", str(seed), "commit", "-q", "-m", "first"], check=True)
    origin = tmp_path / REPO  # its URL ends in owner/name, as check_checkout reads it
    subprocess.run([*GIT, "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    root = tmp_path / "demo"
    subprocess.run([*GIT, "clone", "-q", str(origin), str(root)], check=True)
    git = Git(root)
    git.run("remote", "set-url", "origin", str(origin))
    return git


def declared(config: SandboxConfig) -> Callable[[Git], SandboxConfig]:
    return lambda git: config


NONE_DECLARED = SandboxConfig()


def sandboxer(git: Git, home: Path, config: SandboxConfig = NONE_DECLARED) -> Sandboxer:
    """The host confines, whatever it is: no test runs the real Linux probe (S-087-17)"""
    return sandbox_for(git, REPO, home, declared(config), lambda: None)


def tick(
    git: Git,
    agents: AgentsConfig,
    claude: FakeClaude | ClaudeCli,
    sandbox: Sandboxer | None,
) -> tuple[Action, str | None]:
    decision, launched, _, _ = gate(
        git,
        REPO,
        lambda: agents,
        claude,
        Reads(),
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=login,
        started=same(STARTED),
        new_session=lambda: SESSION,
        sandbox=sandbox,
    )
    return decision.action, launched


def started_settings(spawned: Spawned) -> tuple[list[str], dict[str, object]]:
    """The one headless command spawned, and its one --settings JSON"""
    [(cmd, _, _)] = spawned.commands
    assert cmd.count("--settings") == 1
    settings: dict[str, object] = json.loads(cmd[cmd.index("--settings") + 1])
    return cmd, settings


def filesystem(settings: dict[str, object]) -> dict[str, list[str]]:
    sandbox = settings["sandbox"]
    assert isinstance(sandbox, dict)
    found: dict[str, list[str]] = sandbox["filesystem"]
    return found


def deny_rules(settings: dict[str, object]) -> list[str]:
    permissions = settings["permissions"]
    assert isinstance(permissions, dict)
    rules: list[str] = permissions["deny"]
    return rules


def sandboxed_launch(
    git: Git, home: Path, config: SandboxConfig = NONE_DECLARED
) -> tuple[list[str], dict[str, object]]:
    spawned = Spawned()
    claude = ClaudeCli([], run=spawned.runner, spawn=spawned)
    assert tick(git, headless(), claude, sandboxer(git, home, config)) == (Action.LAUNCH, str(SESSION))
    return started_settings(spawned)


# S-087-2


def test_s087_2_a_sandboxed_launch_passes_one_settings_json_with_the_env_and_the_sandbox(
    checkout: Git, home: Path
) -> None:
    cmd, settings = sandboxed_launch(checkout, home)
    sandbox = settings["sandbox"]
    assert isinstance(sandbox, dict)
    assert sandbox["enabled"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["failIfUnavailable"] is True
    assert "excludedCommands" not in sandbox
    env = settings["env"]
    assert isinstance(env, dict)
    assert env[GATE_SESSION] == "1" and env[MAINTAINER] == LOGIN
    assert set(settings) == {"env", "sandbox", "permissions"}
    assert cmd[-1] == prompt("/t", REPO, [ISSUES], NOW) + "\n\n" + headless_paragraph(LOGIN)


def test_s087_2_with_an_app_the_env_is_the_sessions_and_holds_no_more_than_the_two_folders(
    checkout: Git, home: Path, tmp_path: Path
) -> None:
    spawned = Spawned()
    claude = ClaudeCli([], run=spawned.runner, spawn=spawned)
    session_env = {"PATH": "/helpers:/usr/bin", "SHIPMILL_APP_KEY": str(home / ".config" / "shipmill" / KEY)}
    sandbox = sandboxer(checkout, home)
    built = sandbox(session_env)
    started = claude.start(
        checkout.root, NAME, "x", SESSION, tmp_path / "s.log", session_env, maintainer=LOGIN, sandbox=built
    )
    assert started == 4242
    _, settings = started_settings(spawned)
    assert settings["env"] == {
        **session_env,
        "UV_CACHE_DIR": str(home / ".cache" / "shipmill" / "romamo-demo" / "uv"),
        "GH_CONFIG_DIR": str(state_dir(checkout).resolve() / "gh-config"),
        GATE_SESSION: "1",
        MAINTAINER: LOGIN,
    }


def test_s087_2_an_interactive_launch_is_unchanged_and_never_builds_a_sandbox(checkout: Git) -> None:
    spawned = Spawned()
    claude = ClaudeCli(["--permission-mode=auto"], run=spawned.runner, spawn=spawned)

    def unbuilt(env: object) -> object:
        raise AssertionError("an interactive launch builds no sandbox")

    assert tick(checkout, interactive(), claude, unbuilt) == (Action.LAUNCH, "s9")  # type: ignore[arg-type]
    text = prompt("/t", REPO, [ISSUES], NOW) + "\n\n" + gate_paragraph(LOGIN)
    assert spawned.run[1] == ["claude", "--bg", "-n", NAME, "--permission-mode=auto", text]
    assert spawned.commands == []


def test_s087_2_no_launch_writes_a_settings_file(checkout: Git, home: Path) -> None:
    sandboxed_launch(checkout, home)
    for folder in (checkout.root, home):
        written = [p for p in folder.rglob("*") if p.name in ("settings.json", "settings.local.json", ".mcp.json")]
        assert written == []


# S-087-3


def test_s087_3_every_path_a_session_cant_read_is_denied_existing_or_not(checkout: Git, home: Path) -> None:
    (home / ".ssh").mkdir()
    _, settings = sandboxed_launch(checkout, home)
    denied = filesystem(settings)["denyRead"]
    expected = [str(home / p) for p in DENIED]
    assert expected == denied[: len(DENIED)]
    for path in expected:
        assert not path.startswith("~") and Path(path).is_absolute()
        assert {f"Read(/{path})", f"Read(/{path}/**)", f"Edit(/{path})", f"Edit(/{path}/**)"} <= set(
            deny_rules(settings)
        )
    assert {
        str(home / p) for p in (".ssh", ".aws", "Library/Keychains", ".config/gh/hosts.yml", ".claude.json")
    } <= set(denied)


def test_s087_3_the_list_is_the_specs() -> None:
    assert DENIED == (
        ".ssh",
        ".gnupg",
        ".netrc",
        ".git-credentials",
        ".pypirc",
        ".npmrc",
        ".docker/config.json",
        ".kube",
        ".aws",
        ".azure",
        ".config/gcloud",
        ".password-store",
        "Library/Keychains",
        ".config/gh/hosts.yml",
        ".claude.json",
        ".claude/.credentials.json",
        ".claude/history.jsonl",
    )


def test_s087_3_a_declared_read_entry_is_taken_out_of_the_list(checkout: Git, home: Path, tmp_path: Path) -> None:
    (home / ".config" / "shipmill").mkdir(parents=True)
    (home / ".config" / "shipmill" / "some-tool").write_text("x", encoding="utf-8")
    config = SandboxConfig(
        read=(SandboxPath("~/.aws"), SandboxPath(str(home / ".kube")), SandboxPath("~/.config/shipmill"))
    )
    _, settings = sandboxed_launch(checkout, home, config)
    denied = filesystem(settings)["denyRead"]
    for kept in (home / ".aws", home / ".kube", home / ".config" / "shipmill" / "some-tool"):
        assert str(kept) not in denied
        assert f"Read(/{kept})" not in deny_rules(settings)
    assert str(home / ".ssh") in denied


# S-087-4


def test_s087_4_the_app_key_and_the_sessions_project_stay_readable_and_the_rest_is_denied(
    checkout: Git, home: Path
) -> None:
    config = home / ".config" / "shipmill"
    config.mkdir(parents=True)
    for name in (KEY, "app-99.pem", "claude-token"):
        (config / name).write_text("x", encoding="utf-8")
    projects = home / ".claude" / "projects"
    own = project_folder(checkout.root.resolve())
    for name in (own, "-Users-amy-other"):
        (projects / name).mkdir(parents=True)
    (home / ".claude" / "plugins").mkdir()
    built = sandboxer(checkout, home)({"SHIPMILL_APP_KEY": str(config / KEY)})
    denied = filesystem(dict(built.settings))["denyRead"]
    assert str(config / "app-99.pem") in denied and str(config / "claude-token") in denied
    assert str(config / KEY) not in denied
    assert str(projects / "-Users-amy-other") in denied
    assert str(projects / own) not in denied
    assert not any(p.startswith(str(home / ".claude" / "plugins")) for p in denied)
    assert str(home / ".claude") not in denied


def test_s087_4_without_an_app_every_entry_of_the_config_folder_is_denied(checkout: Git, home: Path) -> None:
    config = home / ".config" / "shipmill"
    config.mkdir(parents=True)
    (config / KEY).write_text("x", encoding="utf-8")
    denied = filesystem(dict(sandboxer(checkout, home)(None).settings))["denyRead"]
    assert str(config / KEY) in denied


def test_s087_4_an_entry_created_after_one_launch_is_denied_at_the_next(checkout: Git, home: Path) -> None:
    sandbox = sandboxer(checkout, home)
    config = home / ".config" / "shipmill"
    projects = home / ".claude" / "projects"
    first = filesystem(dict(sandbox(None).settings))["denyRead"]
    config.mkdir(parents=True)
    (config / "app-5.pem").write_text("x", encoding="utf-8")
    (projects / "-Users-amy-new").mkdir(parents=True)
    second = filesystem(dict(sandbox(None).settings))["denyRead"]
    for added in (config / "app-5.pem", projects / "-Users-amy-new"):
        assert str(added) not in first and str(added) in second


# S-087-5


def test_s087_5_the_write_scope_is_exactly_the_specs_and_the_env_names_the_two_folders(
    checkout: Git, home: Path
) -> None:
    config = SandboxConfig(write=(SandboxPath("~/.cache/pnpm"), SandboxPath("/opt/cache")))
    _, settings = sandboxed_launch(checkout, home, config)
    root = checkout.root.resolve()
    common = root / ".git"
    uv = home / ".cache" / "shipmill" / "romamo-demo" / "uv"
    assert filesystem(settings)["allowWrite"] == [
        str(root),
        str(root / ".claude" / "worktrees"),
        str(common),
        str(uv),
        str(home / ".cache" / "pnpm"),
        "/opt/cache",
    ]
    env = settings["env"]
    assert isinstance(env, dict)
    assert env["UV_CACHE_DIR"] == str(uv) and uv.is_dir()
    gh = common / "shipmill" / "gh-config"
    assert env["GH_CONFIG_DIR"] == str(gh) and gh.is_dir() and list(gh.iterdir()) == []
    assert str(home / ".config" / "gh" / "hosts.yml") in filesystem(settings)["denyRead"]


def test_s087_5_gh_config_is_created_empty_before_each_launch(checkout: Git, home: Path) -> None:
    gh = state_dir(checkout) / "gh-config"
    gh.mkdir(parents=True)
    (gh / "config.yml").write_text("aliases: {}\n", encoding="utf-8")
    sandboxer(checkout, home)(None)
    assert gh.is_dir() and list(gh.iterdir()) == []


def test_s087_5_in_a_linked_worktree_the_common_dir_is_gits_and_the_main_trees_worktrees_are_writable(
    checkout: Git, home: Path, tmp_path: Path
) -> None:
    linked = tmp_path / "gate"
    checkout.run("worktree", "add", "-q", "--detach", str(linked))
    built = sandboxer(Git(linked), home)(None)
    main = checkout.root.resolve()
    scope = filesystem(dict(built.settings))["allowWrite"]
    assert scope[:3] == [str(linked.resolve()), str(main / ".claude" / "worktrees"), str(main / ".git")]
    assert built.env["GH_CONFIG_DIR"] == str(main / ".git" / "shipmill" / "gh-config")
    deny = filesystem(dict(built.settings))["denyWrite"]
    for tree in (linked.resolve(), main):
        assert str(tree / ".claude" / "settings.json") in deny


# S-087-6


def test_s087_6_deny_write_names_the_git_config_hooks_state_and_settings_files(home: Path, tmp_path: Path) -> None:
    root, common, state = tmp_path / "demo", tmp_path / "demo" / ".git", tmp_path / "demo" / ".git" / "shipmill"
    state.mkdir(parents=True)
    for name in ("app-token.json", "app-token-product-romamo.json", "gate.json", "extra.json"):
        (state / name).write_text("{}", encoding="utf-8")
    (state / "gh-config").mkdir()
    built = launch(Where(home, root, common, root, state, REPO), SandboxConfig(), None, ("tick.json", "gate.json"))
    assert filesystem(dict(built.settings))["denyWrite"] == [
        str(common / "config"),
        str(common / "hooks"),
        str(state / "extra.json"),
        str(state / "gate.json"),
        str(state / "tick.json"),  # the gate writes it, so it is denied before it exists
        str(root / ".claude" / "settings.json"),
        str(root / ".claude" / "settings.local.json"),
        str(root / ".mcp.json"),
    ]


def test_s087_6_the_gate_denies_its_own_state_files_and_keeps_the_token_caches_writable(
    checkout: Git, home: Path
) -> None:
    state = state_dir(checkout).resolve()
    state.mkdir(parents=True)
    for name in ("app-token.json", "app-token-product-romamo.json"):
        (state / name).write_text("{}", encoding="utf-8")
    _, settings = sandboxed_launch(checkout, home)
    deny = filesystem(settings)["denyWrite"]
    assert {str(state / n) for n in STATE_FILES} <= set(deny)
    assert {"gate.json", "tick.json", "handed.json", "cursor.json", "bin", "sessions"} <= set(STATE_FILES)
    for writable in ("app-token.json", "app-token-product-romamo.json", "gh-config"):
        assert str(state / writable) not in deny


def test_s087_6_a_linked_worktree_denies_the_main_trees_settings_files_too(home: Path, tmp_path: Path) -> None:
    where = Where(home, tmp_path / "gate", tmp_path / "main" / ".git", tmp_path / "main", tmp_path / "state", REPO)
    built = launch(where, SandboxConfig(), None, ())
    deny = filesystem(dict(built.settings))["denyWrite"]
    for tree in (tmp_path / "gate", tmp_path / "main"):
        for name in (".claude/settings.json", ".claude/settings.local.json", ".mcp.json"):
            assert str(tree / name) in deny


# S-087-7


def test_s087_7_edit_and_write_are_narrowed_to_the_write_scope_and_the_memory_folder(checkout: Git, home: Path) -> None:
    cmd, settings = sandboxed_launch(checkout, home)
    allowed = cmd[cmd.index("--allowedTools") + 1]
    scope = filesystem(settings)["allowWrite"]
    memory = home / ".claude" / "projects" / project_folder(checkout.root.resolve()) / "memory"
    paths = [*scope, str(memory)]
    edits = " ".join(f"Edit(/{p}/**)" for p in paths)
    writes = " ".join(f"Write(/{p}/**)" for p in paths)
    assert allowed == (
        f"Read {edits} {writes} Glob Grep Skill Agent SendMessage ListAgents TodoWrite"
        " Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *)"
    )
    entries = allowed.split(" ")
    assert "Edit" not in entries and "Write" not in entries
    assert HEADLESS_TOOLS.endswith(" Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *)")
    assert allowed.endswith(" Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *)")


# S-087-8


def test_s087_8_allowed_domains_are_exactly_the_defaults_and_the_declared(checkout: Git, home: Path) -> None:
    config = SandboxConfig(domains=(Domain("registry.npmjs.org"), Domain("*.example.com")))
    _, settings = sandboxed_launch(checkout, home, config)
    sandbox = settings["sandbox"]
    assert isinstance(sandbox, dict)
    assert sandbox["network"] == {
        "allowedDomains": [
            "github.com",
            "*.github.com",
            "*.githubusercontent.com",
            "pypi.org",
            "files.pythonhosted.org",
            "astral.sh",
            "*.astral.sh",
            "registry.npmjs.org",
            "*.example.com",
        ]
    }
    assert len(DEFAULT_DOMAINS) == 7


def commit_config(git: Git, text: str) -> None:
    """Commit .github/shipmill.toml holding text to the checkout's main and push it to origin"""
    config = git.root / ".github" / "shipmill.toml"
    config.parent.mkdir(exist_ok=True)
    config.write_text(text, encoding="utf-8")
    subprocess.run([*GIT, "-C", str(git.root), "add", ".github/shipmill.toml"], check=True)
    subprocess.run([*GIT, "-C", str(git.root), "commit", "-q", "-m", "config"], check=True)
    subprocess.run([*GIT, "-C", str(git.root), "push", "-q", "origin", "HEAD:main"], check=True)


TRUSTED = '[agents]\nprompt = "/t"\n\n[agents.sandbox]\ndomains = ["registry.npmjs.org"]\n'


def test_s087_8_the_domains_are_read_from_origins_default_branch_not_the_working_tree(checkout: Git) -> None:
    commit_config(checkout, TRUSTED)
    widened = TRUSTED.replace('["registry.npmjs.org"]', '["registry.npmjs.org", "evil.example.com"]')
    (checkout.root / ".github" / "shipmill.toml").write_text(widened, encoding="utf-8")
    assert trusted_sandbox(checkout).domains == (Domain("registry.npmjs.org"),)


def test_s087_8_no_config_or_no_table_at_origin_declares_nothing(checkout: Git) -> None:
    assert trusted_sandbox(checkout) == SandboxConfig()
    commit_config(checkout, '[agents]\nprompt = "/t"\n')
    assert trusted_sandbox(checkout) == SandboxConfig()


def test_s087_8_a_malformed_key_at_origin_is_dropped(checkout: Git) -> None:
    commit_config(checkout, TRUSTED.replace('"registry.npmjs.org"', '"https://registry.npmjs.org"'))
    assert trusted_sandbox(checkout) == SandboxConfig()


def test_s087_26_origins_local_ports_and_tunnels_open_on_macos_and_drop_on_linux(checkout: Git) -> None:
    tunnel = '\n[[agents.sandbox.grant.tunnels]]\nssh = "db.example.com"\nlocal = 15432\nremote = "db:5432"\n'
    commit_config(checkout, TRUSTED + "local_ports = true\n\n[agents.sandbox.grant]\nlocal_ports = true\n" + tunnel)
    on_mac, on_linux = trusted_sandbox(checkout, "darwin"), trusted_sandbox(checkout, "linux")
    assert on_mac.local_ports and on_mac.grant is not None and on_mac.grant.local_ports and on_mac.grant.tunnels
    assert on_linux == SandboxConfig(domains=(Domain("registry.npmjs.org"),), grant=SandboxConfig())


# S-087-12


def test_s087_12_the_refused_flags_are_the_specs() -> None:
    assert SANDBOX_REFUSED == ("--settings", "--add-dir")


@pytest.mark.parametrize("arg", ["--settings", "--settings={}", "--add-dir", "--add-dir=/tmp"])
def test_s087_12_with_the_sandbox_on_settings_or_add_dir_exits_2_and_stops_and_starts_nothing(
    checkout: Git, home: Path, arg: str
) -> None:
    claude = FakeClaude([bg("old", "idle", "done")], args=("--allowedTools", "Bash(npm *)", arg))
    with pytest.raises(ReleaseError) as caught:
        tick(checkout, headless(), claude, sandboxer(checkout, home))
    flag = arg.split("=", 1)[0]
    assert str(caught.value).startswith(f"--claude-arg {flag} is refused with --sandbox")
    assert "[agents.sandbox]" in (caught.value.fix or "")
    assert (claude.started, claude.launched, claude.stopped) == ([], [], [])
    assert not (state_dir(checkout) / RECORD).exists()


@pytest.mark.parametrize("args", [("--allowedTools", "Bash(npm *)"), ("--disallowedTools", "WebFetch")])
def test_s087_12_allowed_and_disallowed_tools_pass(checkout: Git, home: Path, args: tuple[str, ...]) -> None:
    claude = FakeClaude([bg("old", "idle", "done")], args=args)
    assert tick(checkout, headless(), claude, sandboxer(checkout, home)) == (Action.LAUNCH, str(SESSION))
    assert claude.stopped == ["old"] and claude.sandboxes[0] is not None


@pytest.mark.parametrize("arg", ["--settings", "--add-dir=/tmp"])
def test_s087_12_without_the_sandbox_the_flags_pass_as_before(checkout: Git, arg: str) -> None:
    claude = FakeClaude(args=(arg,))
    assert tick(checkout, headless(), claude, None) == (Action.LAUNCH, str(SESSION))
    assert claude.sandboxes == [None]


# S-087-19


def test_s087_19_without_sandbox_a_headless_launch_is_the_one_before_this_spec(checkout: Git) -> None:
    spawned = Spawned()
    claude = ClaudeCli(["--allowedTools", "Bash(npm *)"], run=spawned.runner, spawn=spawned)
    assert tick(checkout, headless(), claude, None) == (Action.LAUNCH, str(SESSION))
    [(cmd, _, _)] = spawned.commands
    text = prompt("/t", REPO, [ISSUES], NOW) + "\n\n" + headless_paragraph(LOGIN)
    assert cmd == [
        "claude",
        "-p",
        "--permission-prompts",
        "none",
        "--output-format",
        "stream-json",
        "--verbose",
        "--allowedTools",
        "Read Edit Write Glob Grep Skill Agent SendMessage ListAgents TodoWrite"
        " Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *)",
        "--disallowedTools",
        "AskUserQuestion",
        "--session-id",
        str(SESSION),
        "--settings",
        json.dumps({"env": {GATE_SESSION: "1", MAINTAINER: LOGIN}}),
        "-n",
        NAME,
        "--allowedTools",
        "Bash(npm *)",
        "--",
        text,
    ]


def test_s087_19_gate_sandbox_turns_the_sandbox_on(checkout: Git, home: Path) -> None:
    parser = _parser()
    assert parser.parse_args(["gate", REPO, "--sandbox"]).sandbox is True
    assert parser.parse_args(["gate", REPO]).sandbox is False
    claude = FakeClaude()
    tick(checkout, headless(), claude, sandboxer(checkout, home))
    [sandbox] = claude.sandboxes
    assert sandbox is not None and sandbox.settings["sandbox"]["enabled"] is True  # type: ignore[index]


def test_s087_19_launchd_sandbox_writes_the_flag_into_the_job(tmp_path: Path) -> None:
    path = str(tools(tmp_path / "bin", "claude", "uvx", "gh", "git"))
    job = build(REPO, tmp_path / "gate", 15, "shipmill@latest", [], tmp_path, path, nothing, sandbox=True)
    args = plistlib.loads(job.document)["ProgramArguments"]
    assert args[args.index("--refresh") + 1] == "--sandbox"
    parsed = _parser().parse_args(args[args.index("--repo") :])
    assert parsed.command == "gate" and parsed.sandbox is True
    plain = build(REPO, tmp_path / "gate", 15, "shipmill@latest", [], tmp_path, path, nothing)
    assert "--sandbox" not in plistlib.loads(plain.document)["ProgramArguments"]
    assert _parser().parse_args(["launchd", REPO, "--sandbox"]).sandbox is True
    pinned = build(REPO, tmp_path / "gate", 15, "shipmill==0.1.0", [], tmp_path, path, nothing, sandbox=True)
    pinned.plist.parent.mkdir(parents=True)
    pinned.plist.write_bytes(pinned.document)
    fix = cli_fix(read_job(REPO, tmp_path), REPO)  # a rewrite keeps the sandbox
    assert fix.endswith(f"launchd {REPO} --sandbox")
