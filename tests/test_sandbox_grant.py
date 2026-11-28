"""Spec 087's amendment (#1616, #1649): `local_ports` and the [agents.sandbox.grant] table.

S-087-9 reads both under [agents.sandbox] and [agents.sandbox.grant] and drops a malformed key
(a grant read or write entry that reaches a credential store, a tunnel's local repeated across
both tables); S-087-26 opens every local port on a macOS gate only, and names the drop on
Linux; S-087-27 keeps Unix sockets and unsandboxed commands out of every headless launch"""

import json
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from shipmill import refused
from shipmill.agents import AgentsConfig
from shipmill.autonomy import Hold
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.gate import TICK, Action, ClaudeCli, gate, load_tick, state_dir, tick_lines
from shipmill.sandbox import (
    CREDENTIALS,
    DEFAULT_DOMAINS,
    GRANT_TABLE,
    LINUX_PROBE,
    Domain,
    GrantKind,
    LocalPort,
    RemoteAddress,
    SandboxConfig,
    SandboxPath,
    SshDestination,
    Tunnel,
    Where,
    launch,
)
from tests.test_gate import ISSUES, NO_PRUNE, NOW, FakeClaude, FakeNotifier, host
from tests.test_gate_headless import LOGIN, NAME, SESSION, Spawned
from tests.test_gate_refused import REPO, checkout, tick_json

AGENTS = '[agents]\nprompt = "/t"\n'
GRANTED = """\
[agents.sandbox]
domains = ["registry.npmjs.org"]
local_ports = false

[agents.sandbox.grant]
domains = ["api.staging.example.com"]
read = ["~/.config/some-tool"]
write = ["~/data/fixtures"]
local_ports = true

[[agents.sandbox.grant.tunnels]]
ssh = "readonly@db.example.com"
local = 15432
remote = "127.0.0.1:5432"
"""
TUNNEL = Tunnel(SshDestination("readonly@db.example.com"), LocalPort(15432), RemoteAddress("127.0.0.1:5432"))


def parse(text: str, platform: str = "darwin") -> AgentsConfig:
    return AgentsConfig.parse(Table(tomllib.loads(AGENTS + text), "shipmill.toml").table("agents"), platform)


def sandbox(text: str, home: Path) -> tuple[SandboxConfig, tuple[refused.Refusal, ...]]:
    raw = tomllib.loads(AGENTS + text)["agents"]["sandbox"]
    return SandboxConfig.parse(raw, "shipmill.toml [agents]", home)


# S-087-9: local_ports and the grant table


def test_s087_9_parse_reads_local_ports_and_the_grant_table() -> None:
    agents = parse(GRANTED)
    assert agents.refused == ()
    assert agents.sandbox == SandboxConfig(
        domains=(Domain("registry.npmjs.org"),),
        grant=SandboxConfig(
            domains=(Domain("api.staging.example.com"),),
            read=(SandboxPath("~/.config/some-tool"),),
            write=(SandboxPath("~/data/fixtures"),),
            local_ports=True,
            tunnels=(TUNNEL,),
        ),
    )
    assert parse("[agents.sandbox]\nlocal_ports = true\n").sandbox == SandboxConfig(local_ports=True)


def test_s087_9_without_local_ports_or_a_grant_nothing_opens() -> None:
    assert parse("[agents.sandbox]\n").sandbox == SandboxConfig(local_ports=False, grant=None)
    assert parse("[agents.sandbox.grant]\n").sandbox == SandboxConfig(grant=SandboxConfig())


@pytest.mark.parametrize("table", ["[agents.sandbox]", GRANT_TABLE])
@pytest.mark.parametrize("value", ['"true"', "1", "[true]"])
def test_s087_9_a_local_ports_that_isnt_a_boolean_is_dropped(table: str, value: str) -> None:
    agents = parse(f"{table}\nlocal_ports = {value}\n")
    [refusal] = agents.refused
    assert (refusal.table, refusal.key, refusal.spec) == (table, "local_ports", "087")
    assert refusal.why.startswith("must be a boolean, got ") and refusal.off == "local ports"
    assert "local_ports = true or local_ports = false" in refusal.fix
    assert agents.sandbox.local_ports is False
    assert agents.sandbox.grant is None or agents.sandbox.grant.local_ports is False


@pytest.mark.parametrize(
    ("key", "value", "fault"),
    [
        ("domains", '["https://api.example.com"]', "has a scheme"),
        ("read", '["relative/tool"]', "is relative"),
        ("write", '["~/a/../b"]', "holds .."),
        ("tunnels", '[{ ssh = "h", local = 15432 }]', "a tunnel lacks remote"),
        ("tunnels", "1", "must be an array of tables, [[agents.sandbox.grant.tunnels]], got 1"),
    ],
)
def test_s087_9_a_malformed_grant_key_is_dropped_alone(key: str, value: str, fault: str) -> None:
    agents = parse(f"{GRANT_TABLE}\n{key} = {value}\nlocal_ports = true\n")
    [refusal] = agents.refused
    assert (refusal.table, refusal.key) == (GRANT_TABLE, key)
    assert fault in refusal.why and refusal.message.startswith(f"{GRANT_TABLE} {key} ")
    assert agents.sandbox.grant == SandboxConfig(local_ports=True)  # the rest of the grant stands
    assert agents.sandbox.domains == ()


@pytest.mark.parametrize("key", ["read", "write"])
@pytest.mark.parametrize(
    ("entry", "store"),
    [
        ("~/.ssh", "~/.ssh"),
        ("~/.ssh/id_ed25519", "~/.ssh"),
        ("~/.SSH/config", "~/.ssh"),  # another spelling of the same folder on macOS
        ("~/", "~/.ssh"),  # it holds every store
        ("/", "~/.ssh"),
        ("~/.config", "~/.config/gcloud"),
        ("~/.config/gh", "~/.config/gh/hosts.yml"),
        ("~/.config/gh/hosts.yml", "~/.config/gh/hosts.yml"),
        ("~/.docker/config.json", "~/.docker/config.json"),
        ("~/Library/Keychains/login.keychain-db", "~/Library/Keychains"),
        ("~/.aws/credentials", "~/.aws"),
        ("~/.password-store", "~/.password-store"),
    ],
)
def test_s087_9_a_grant_entry_that_reaches_a_credential_store_is_dropped(
    tmp_path: Path, key: str, entry: str, store: str
) -> None:
    found, refusals = sandbox(f'{GRANT_TABLE}\n{key} = ["/opt/ok", "{entry}"]\nlocal_ports = true\n', tmp_path)
    [refusal] = refusals
    assert (refusal.table, refusal.key) == (GRANT_TABLE, key)
    assert refusal.why == f"is malformed: {entry!r} reaches {store}, a credential store a grant can't open"
    assert "outside the credential stores and ~/.config/gh/hosts.yml" in refusal.fix
    assert found.grant == SandboxConfig(local_ports=True)


def test_s087_9_an_absolute_grant_path_into_the_homes_store_is_dropped_too(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    _, refusals = sandbox(f'{GRANT_TABLE}\nwrite = ["{home / ".ssh" / "authorized_keys"}"]\n', home)
    assert [r.key for r in refusals] == ["write"]
    linked = tmp_path / "linked"
    linked.symlink_to(home)  # a home reached through a link places the stores at its target too
    _, through = sandbox(f'{GRANT_TABLE}\nread = ["{home / ".aws"}"]\n', linked)
    assert [r.key for r in through] == ["read"]


def test_s087_9_a_grant_entry_beside_the_stores_stays(tmp_path: Path) -> None:
    text = f'{GRANT_TABLE}\nread = ["~/.config/some-tool", "~/.sshd-notes", "/opt/x"]\nwrite = ["~/data"]\n'
    found, refusals = sandbox(text, tmp_path)
    assert refusals == ()
    assert found.grant is not None and [str(p) for p in found.grant.read] == [
        "~/.config/some-tool",
        "~/.sshd-notes",
        "/opt/x",
    ]


def test_s087_9_the_stores_are_the_first_two_items_of_what_a_session_cant_read() -> None:
    assert CREDENTIALS[-1] == ".config/gh/hosts.yml" and len(CREDENTIALS) == 14
    assert {".ssh", ".gnupg", ".netrc", ".aws", "Library/Keychains"} <= set(CREDENTIALS)
    assert ".claude.json" not in CREDENTIALS


def test_s087_9_the_top_tables_read_may_still_name_a_store(tmp_path: Path) -> None:
    """Only a grant's entry is refused: the repo's declared exception stays as #1528 built it"""
    found, refusals = sandbox('[agents.sandbox]\nread = ["~/.aws"]\n', tmp_path)
    assert refusals == () and found.read == (SandboxPath("~/.aws"),)


def test_s087_9_a_tunnel_local_repeated_across_both_tables_drops_the_grants_tunnels() -> None:
    text = GRANTED.replace(
        "local_ports = false\n",
        "local_ports = false\n\n[[agents.sandbox.tunnels]]\n"
        'ssh = "db2.example.com"\nlocal = 15432\nremote = "localhost:5432"\n',
    )
    agents = parse(text)
    [refusal] = agents.refused
    assert (refusal.table, refusal.key) == (GRANT_TABLE, "tunnels")
    assert refusal.why == "is malformed: local 15432 is given in [agents.sandbox] tunnels too"
    assert agents.sandbox.tunnels == (
        Tunnel(SshDestination("db2.example.com"), LocalPort(15432), RemoteAddress("localhost:5432")),
    )
    assert agents.sandbox.grant is not None and agents.sandbox.grant.tunnels == ()
    assert agents.sandbox.grant.domains == (Domain("api.staging.example.com"),)


def test_s087_9_a_grant_that_isnt_a_table_grants_nothing() -> None:
    agents = parse('[agents.sandbox]\ndomains = ["a.org"]\ngrant = ["b.org"]\n')
    [refusal] = agents.refused
    assert (refusal.table, refusal.key) == ("[agents.sandbox]", "grant")
    assert "must be a table, [agents.sandbox.grant]" in refusal.why
    assert agents.sandbox == SandboxConfig(domains=(Domain("a.org"),))


@pytest.mark.parametrize("key", ["domain", "grant", "allowUnixSockets"])
def test_s087_9_a_key_shipmill_never_knew_in_the_grant_fails_the_load(key: str) -> None:
    with pytest.raises(ReleaseError, match=rf"unknown keys \['{key}'\]"):
        parse(f"{GRANT_TABLE}\n{key} = []\n")


# S-087-26


def test_s087_26_local_ports_opens_every_local_port_on_a_macos_gate(tmp_path: Path) -> None:
    for declared in (
        SandboxConfig(local_ports=True),
        SandboxConfig(grant=SandboxConfig(local_ports=True)),
    ):
        kinds = (GrantKind.LOCAL_PORTS,) if declared.grant is not None else ()
        network = built(tmp_path, declared, kinds, "darwin")["network"]
        assert network == {"allowedDomains": list(DEFAULT_DOMAINS), "allowLocalBinding": True}


def test_s087_26_a_grant_opens_local_ports_only_when_granted(tmp_path: Path) -> None:
    declared = SandboxConfig(grant=SandboxConfig(local_ports=True, domains=(Domain("api.example.com"),)))
    others = tuple(k for k in GrantKind if k is not GrantKind.LOCAL_PORTS)
    for kinds in ((), others):
        assert "allowLocalBinding" not in built(tmp_path, declared, kinds, "darwin")["network"]
    assert GrantKind.LOCAL_PORTS.label == "sandbox:local-ports"
    undeclared = SandboxConfig(grant=SandboxConfig(domains=(Domain("api.example.com"),)))
    assert "allowLocalBinding" not in built(tmp_path, undeclared, (GrantKind.LOCAL_PORTS,), "darwin")["network"]


def test_s087_26_no_local_entry_reaches_allowed_domains(tmp_path: Path) -> None:
    declared = SandboxConfig(local_ports=True, tunnels=(TUNNEL,), grant=SandboxConfig(tunnels=(TUNNEL,)))
    domains = built(tmp_path, declared, tuple(GrantKind), "darwin")["network"]["allowedDomains"]
    assert domains == list(DEFAULT_DOMAINS)
    assert not any("127.0.0.1" in d or "localhost" in d for d in domains)


def test_s087_26_a_linux_launch_never_binds_local_ports(tmp_path: Path) -> None:
    declared = SandboxConfig(local_ports=True, grant=SandboxConfig(local_ports=True))
    assert built(tmp_path, declared, tuple(GrantKind), "linux")["network"] == {"allowedDomains": list(DEFAULT_DOMAINS)}


def test_s087_26_on_linux_local_ports_and_every_tunnel_are_dropped_and_named() -> None:
    text = GRANTED.replace("local_ports = false", "local_ports = true") + (
        '\n[[agents.sandbox.tunnels]]\nssh = "db2.example.com"\nlocal = 15433\nremote = "localhost:5432"\n'
    )
    on_mac, on_linux = parse(text, "darwin"), parse(text, "linux")
    assert on_mac.refused == () and on_mac.sandbox.local_ports and on_mac.sandbox.tunnels
    assert [(r.table, r.key) for r in on_linux.refused] == [
        ("[agents.sandbox]", "local_ports"),
        ("[agents.sandbox]", "tunnels"),
        (GRANT_TABLE, "local_ports"),
        (GRANT_TABLE, "tunnels"),
    ]
    for refusal in on_linux.refused:
        assert LINUX_PROBE in refusal.message and refusal.turns_off
        assert refusal.why == "is dropped on linux: local ports wait for the Linux probe (S-087-29)"
    grant = on_linux.sandbox.grant
    assert not on_linux.sandbox.local_ports and on_linux.sandbox.tunnels == ()
    assert grant is not None and not grant.local_ports and grant.tunnels == ()
    assert on_linux.sandbox.domains == on_mac.sandbox.domains and grant.write == (SandboxPath("~/data/fixtures"),)


def test_s087_26_on_linux_nothing_is_named_without_local_ports_or_a_tunnel() -> None:
    assert parse('[agents.sandbox]\ndomains = ["a.org"]\nlocal_ports = false\n', "linux").refused == ()


def test_s087_26_on_linux_stderr_names_the_drop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git = checkout(tmp_path / "gate", AGENTS + "[agents.sandbox]\nlocal_ports = true\n")
    refused.begin()
    AgentsConfig.load(git.root, REPO, platform="linux")
    err = capsys.readouterr().err
    assert err == f"shipmill: refused: [agents.sandbox] local_ports is dropped on linux: {LINUX_PROBE} (spec 087);" + (
        " a macOS gate opens it; on this host, leave it for the probe or delete it; local ports is off\n"
    )


def test_s087_26_on_linux_the_tick_launches_without_it_and_names_it(tmp_path: Path) -> None:
    git = checkout(tmp_path / "gate", AGENTS + "[agents.sandbox]\nlocal_ports = true\n")
    decision, launched, _, _ = gate(
        git,
        REPO,
        lambda: AgentsConfig.load(git.root, REPO, platform="linux"),
        FakeClaude(),
        lambda _: [ISSUES],
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=host,
    )
    assert decision.action is Action.LAUNCH
    first = tick_lines(decision, launched, (), (), dry_run=False)[0]
    assert first.endswith("; refused: [agents.sandbox] local_ports (spec 087)")
    records = tick_json(git)["refused"]
    assert isinstance(records, list) and len(records) == 1 and LINUX_PROBE in records[0]["why"]
    loaded = load_tick(state_dir(git) / TICK)
    assert loaded is not None and [r.key for r in loaded.refused] == ["local_ports"]


# S-087-27


def keys_of(value: object) -> Iterator[str]:
    """Every key at every depth of a JSON value"""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from keys_of(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from keys_of(inner)


WIDEST = SandboxConfig(
    domains=(Domain("registry.npmjs.org"),),
    read=(SandboxPath("~/.aws"),),
    write=(SandboxPath("/"),),
    local_ports=True,
    tunnels=(TUNNEL,),
    grant=SandboxConfig(
        domains=(Domain("*.example.com"),),
        read=(SandboxPath("~/.config/some-tool"),),
        write=(SandboxPath("~/data"),),
        local_ports=True,
    ),
)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("kinds", [(), tuple(GrantKind)], ids=["no grant", "every kind granted"])
def test_s087_27_no_launch_opens_a_unix_socket_or_an_unsandboxed_command(
    tmp_path: Path, platform: str, kinds: tuple[GrantKind, ...]
) -> None:
    spawned = Spawned()
    args = ["--allowedTools", "Bash(docker *)", "--disallowedTools", "WebFetch"]
    claude = ClaudeCli(args, run=spawned.runner, spawn=spawned)
    confined = launch(where(tmp_path), WIDEST, None, (), kinds, platform)
    claude.start(tmp_path / "demo", NAME, "x", SESSION, tmp_path / "s.log", None, maintainer=LOGIN, sandbox=confined)
    [(cmd, _, _)] = spawned.commands
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert not {"allowUnixSockets", "allowAllUnixSockets", "excludedCommands"} & set(keys_of(settings))
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert settings["sandbox"]["enabled"] is True and settings["sandbox"]["failIfUnavailable"] is True


@pytest.mark.parametrize("table", ["[agents.sandbox]", GRANT_TABLE])
@pytest.mark.parametrize("key", ["allowUnixSockets", "allowAllUnixSockets", "allowUnsandboxedCommands"])
def test_s087_27_no_key_of_either_table_declares_a_socket_or_an_unsandboxed_command(table: str, key: str) -> None:
    with pytest.raises(ReleaseError, match=rf"unknown keys \['{key}'\]"):
        parse(f"{table}\n{key} = true\n")


def where(tmp_path: Path) -> Where:
    root = tmp_path / "demo"
    return Where(tmp_path / "home", root, root / ".git", root, tmp_path / "state", REPO)


def built(tmp_path: Path, declared: SandboxConfig, kinds: tuple[GrantKind, ...], platform: str) -> dict[str, Any]:
    sandbox = launch(where(tmp_path), declared, None, (), kinds, platform).settings["sandbox"]
    assert isinstance(sandbox, dict)
    return sandbox


def test_granting_adds_only_the_granted_kinds_entries() -> None:
    declared = SandboxConfig(domains=(Domain("a.org"),), grant=WIDEST.grant)
    assert declared.granting(()) == SandboxConfig(domains=(Domain("a.org"),))
    opened = declared.granting((GrantKind.DOMAINS, GrantKind.WRITE))
    assert opened == SandboxConfig(domains=(Domain("a.org"), Domain("*.example.com")), write=(SandboxPath("~/data"),))


def test_a_granted_write_reaches_the_settings(tmp_path: Path) -> None:
    home = tmp_path / "home"
    declared = SandboxConfig(grant=SandboxConfig(write=(SandboxPath("~/data"),)))
    plain = built(tmp_path, declared, (), "darwin")["filesystem"]
    opened = built(tmp_path, declared, (GrantKind.WRITE,), "darwin")["filesystem"]
    assert str(home / "data") not in plain["allowWrite"] and str(home / "data") in opened["allowWrite"]
