"""S-087-9: `AgentsConfig.parse` reads [agents.sandbox] domains, read, write and tunnels, and a
malformed key is dropped with its refusal (D-64) named by doctor, the tick and stderr, while
the config loads and the session starts without that key. A key shipmill never knew under
[agents.sandbox] fails the load (D-63)"""

import tomllib
from pathlib import Path

import pytest

from shipmill import refused
from shipmill.agents import AgentsConfig
from shipmill.cli import main
from shipmill.config import Table
from shipmill.doctor import REFUSED, Check, doctor
from shipmill.errors import ReleaseError
from shipmill.gate import TICK, Action, load_tick, state_dir, tick_lines
from shipmill.refused import Refusal
from shipmill.sandbox import (
    Domain,
    LocalPort,
    RemoteAddress,
    SandboxConfig,
    SandboxPath,
    SshDestination,
    Tunnel,
)
from tests.test_gate import FakeClaude
from tests.test_gate_refused import checkout, run, tick_json

from .conftest import POLICY, Repo

AGENTS = '[agents]\nprompt = "/t"\n'
DECLARED = """\
[agents.sandbox]
domains = ["registry.npmjs.org", "*.example.com"]
read = ["~/.config/some-tool", "/opt/tool"]
write = ["~/.cache/pnpm"]

[[agents.sandbox.tunnels]]
ssh = "readonly@db.example.com"
local = 15432
remote = "127.0.0.1:5432"

[[agents.sandbox.tunnels]]
ssh = "db2.example.com"
local = 1024
remote = "localhost:65535"
"""
TUNNEL = 'ssh = "readonly@db.example.com"\nlocal = 15432\nremote = "127.0.0.1:5432"\n'
BAD_DOMAIN = '[agents.sandbox]\ndomains = ["https://registry.npmjs.org"]\nwrite = ["~/.cache/pnpm"]\n'


def parse(text: str, platform: str = "darwin") -> AgentsConfig:
    return AgentsConfig.parse(Table(tomllib.loads(AGENTS + text), "shipmill.toml").table("agents"), platform)


def test_s087_9_parse_reads_each_key_as_declared() -> None:
    agents = parse(DECLARED)
    assert agents.refused == ()
    assert agents.sandbox == SandboxConfig(
        domains=(Domain("registry.npmjs.org"), Domain("*.example.com")),
        read=(SandboxPath("~/.config/some-tool"), SandboxPath("/opt/tool")),
        write=(SandboxPath("~/.cache/pnpm"),),
        tunnels=(
            Tunnel(SshDestination("readonly@db.example.com"), LocalPort(15432), RemoteAddress("127.0.0.1:5432")),
            Tunnel(SshDestination("db2.example.com"), LocalPort(1024), RemoteAddress("localhost:65535")),
        ),
    )


def test_s087_9_no_table_and_an_empty_one_declare_nothing() -> None:
    assert parse("").sandbox == parse("[agents.sandbox]\n").sandbox == SandboxConfig()
    assert parse("[agents.sandbox]\ndomains = []\ntunnels = []\n").sandbox == SandboxConfig()
    assert parse("").refused == ()


MALFORMED = [
    # domains: a scheme, a port, a path, and what isn't a host name
    ("domains", '["https://registry.npmjs.org"]', "'https://registry.npmjs.org' has a scheme"),
    ("domains", '["registry.npmjs.org:443"]', "'registry.npmjs.org:443' has a port"),
    ("domains", '["registry.npmjs.org/simple"]', "'registry.npmjs.org/simple' has a path"),
    ("domains", '["*"]', "'*' is not a host name"),
    ("domains", '["*."]', "'*.' is not a host name"),
    ("domains", '["a.*.org"]', "'a.*.org' is not a host name"),
    ("domains", '["-x.org"]', "'-x.org' is not a host name"),
    ("domains", '["a b.org"]', "'a b.org' is not a host name"),
    ("domains", '["user@x.org"]', "'user@x.org' is not a host name"),
    ("domains", '[""]', "'' is empty"),
    ("domains", "[3]", "3 is not a string"),
    ("domains", '"registry.npmjs.org"', "must be a list of host names, got 'registry.npmjs.org'"),
    # read and write: a relative path, one with .., an empty one, and what isn't a list of strings
    ("read", '["relative/tool"]', "'relative/tool' is relative"),
    ("read", '["~"]', "'~' is relative"),
    ("read", '["~user/x"]', "'~user/x' is relative"),
    ("read", '["~/a/../.ssh"]', "'~/a/../.ssh' holds .."),
    ("read", '["/a/.."]', "'/a/..' holds .."),
    ("read", '[""]', "'' is empty"),
    ("read", "[true]", "True is not a string"),
    ("write", '["cache"]', "'cache' is relative"),
    ("write", '["~/../x"]', "'~/../x' holds .."),
    ("write", "{ a = 1 }", "must be a list of paths, got {'a': 1}"),
    # tunnels: a missing, an extra, or an invalid field, a repeated local, and what isn't a table
    ("tunnels", '[{ ssh = "h", local = 15432 }]', "a tunnel lacks remote"),
    ("tunnels", "[{}]", "a tunnel lacks ssh, local, remote"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = "h:1", user = "x" }]', "a tunnel sets user, beyond"),
    ("tunnels", '[{ ssh = "-oProxyCommand=x", local = 15432, remote = "h:1" }]', "ssh '-oProxyCommand=x' is not"),
    ("tunnels", '[{ ssh = "u@h -p 22", local = 15432, remote = "h:1" }]', "ssh 'u@h -p 22' is not [user@]host"),
    ("tunnels", '[{ ssh = "u@h:22", local = 15432, remote = "h:1" }]', "ssh 'u@h:22' is not [user@]host"),
    ("tunnels", '[{ ssh = "-u@h", local = 15432, remote = "h:1" }]', "ssh '-u@h' is not [user@]host"),
    ("tunnels", '[{ ssh = 3, local = 15432, remote = "h:1" }]', "ssh 3 is not [user@]host"),
    ("tunnels", '[{ ssh = "h", local = 1023, remote = "h:1" }]', "local 1023 is not a port from 1024 to 65535"),
    ("tunnels", '[{ ssh = "h", local = 65536, remote = "h:1" }]', "local 65536 is not a port"),
    ("tunnels", '[{ ssh = "h", local = "15432", remote = "h:1" }]', "local '15432' is not a port"),
    ("tunnels", '[{ ssh = "h", local = true, remote = "h:1" }]', "local True is not a port"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = "5432" }]', "remote '5432' is not host:port"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = "h:0" }]', "remote 'h:0' is not host:port"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = "h:99999" }]', "remote 'h:99999' is not host:port"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = "h:" }]', "remote 'h:' is not host:port"),
    ("tunnels", '[{ ssh = "h", local = 15432, remote = 5432 }]', "remote 5432 is not host:port"),
    (
        "tunnels",
        '[{ ssh = "h", local = 15432, remote = "h:1" }, { ssh = "g", local = 15432, remote = "g:1" }]',
        "local 15432 is given twice",
    ),
    ("tunnels", "[1]", "1 is not a table of ssh, local, remote"),
    ("tunnels", "1", "must be an array of tables, [[agents.sandbox.tunnels]], got 1"),
]


@pytest.mark.parametrize(("key", "value", "fault"), MALFORMED)
def test_s087_9_a_malformed_key_is_dropped_alone_with_its_refusal(key: str, value: str, fault: str) -> None:
    """Every other key still reads as declared; the malformed one is empty, never wider"""
    lines = DECLARED.splitlines(keepends=True)
    if key == "tunnels":  # the array of tables goes, the inline value takes its place
        text = "".join(lines[: lines.index("[[agents.sandbox.tunnels]]\n")]).rstrip("\n") + f"\ntunnels = {value}\n"
    else:
        text = "".join(f"{key} = {value}\n" if line.startswith(f"{key} = ") else line for line in lines)
    agents, declared = parse(text), parse(DECLARED)
    [refusal] = agents.refused
    assert (refusal.table, refusal.key, refusal.spec) == ("[agents.sandbox]", key, "087")
    assert fault in refusal.why and refusal.turns_off
    assert refusal.message.startswith(f"[agents.sandbox] {key} ")
    assert getattr(agents.sandbox, key) == ()
    for other in {"domains", "read", "write", "tunnels"} - {key}:
        assert getattr(agents.sandbox, other) == getattr(declared.sandbox, other)


def test_s087_9_several_malformed_keys_each_refused() -> None:
    agents = parse('[agents.sandbox]\ndomains = ["x.org:1"]\nread = ["rel"]\nwrite = ["/ok"]\n')
    assert [r.key for r in agents.refused] == ["domains", "read"]
    assert agents.sandbox == SandboxConfig(write=(SandboxPath("/ok"),))


def test_s087_9_a_sandbox_that_isnt_a_table_is_dropped_whole() -> None:
    agents = parse('sandbox = ["registry.npmjs.org"]\n')
    [refusal] = agents.refused
    assert (refusal.table, refusal.key) == ("[agents]", "sandbox")
    assert "must be a table, [agents.sandbox]" in refusal.why
    assert agents.sandbox == SandboxConfig()


def test_s087_9_a_key_shipmill_never_knew_fails_the_load() -> None:
    """D-63: a typo fails fast; it is not a malformed escape key"""
    with pytest.raises(ReleaseError, match=r"unknown keys \['domain'\]"):
        parse('[agents.sandbox]\ndomain = ["registry.npmjs.org"]\n')


def test_s087_9_the_refusals_message_names_the_key_its_fault_the_fix_and_what_is_off() -> None:
    [refusal] = parse(BAD_DOMAIN).refused
    assert refusal.message == (
        "[agents.sandbox] domains is malformed: 'https://registry.npmjs.org' has a scheme (spec 087); write each"
        " entry as a host name, or *. and a name, such as registry.npmjs.org; each declared domain is off"
    )
    assert refusal.named == "[agents.sandbox] domains (spec 087)"
    assert refusal.record() == {
        "key": "[agents.sandbox] domains",
        "spec": "087",
        "off": "each declared domain",
        "fix": "write each entry as a host name, or *. and a name, such as registry.npmjs.org",
        "why": "is malformed: 'https://registry.npmjs.org' has a scheme",
    }


def _refusal() -> Refusal:
    [refusal] = parse(BAD_DOMAIN).refused
    return refusal


def test_s087_9_doctor_prints_the_refusal_as_a_fail_row_and_the_policy_still_passes(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + "\n" + AGENTS + BAD_DOMAIN)
    checks = doctor(repo.root, repo.github)
    assert [c for c in checks if c.name == REFUSED] == [Check("FAIL", REFUSED, _refusal().message)]
    assert [c.status for c in checks if c.name == "policy"] == ["PASS"]


def test_s087_9_every_command_that_loads_the_config_says_it_once_on_stderr(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write(repo.policy_file, POLICY + "\n" + AGENTS + BAD_DOMAIN)
    refused.begin()
    assert main(["--repo", str(repo.root), "settle-minutes"], github=repo.github) == 0
    captured = capsys.readouterr()
    assert captured.err == f"shipmill: refused: {_refusal().message}\n"
    assert captured.out == "30\n"


def test_s087_9_a_tick_launches_without_the_key_and_names_it(tmp_path: Path) -> None:
    plain = checkout(tmp_path / "plain", AGENTS + '[agents.sandbox]\nwrite = ["~/.cache/pnpm"]\n')
    malformed = checkout(tmp_path / "malformed", AGENTS + BAD_DOMAIN)
    plain_claude, malformed_claude = FakeClaude(), FakeClaude()
    without, launched_without = run(plain, plain_claude)
    with_key, launched_with = run(malformed, malformed_claude)

    assert with_key.action is Action.LAUNCH  # the session starts, without the key
    assert launched_with == launched_without and malformed_claude.launched == plain_claude.launched
    assert with_key.refused == (_refusal(),)
    first = tick_lines(with_key, launched_with, (), (), dry_run=False)[0]
    assert first.endswith("; refused: [agents.sandbox] domains (spec 087)")
    assert tick_json(malformed)["refused"] == [_refusal().record()]
    loaded = load_tick(state_dir(malformed) / TICK)
    assert loaded is not None and loaded.refused == (_refusal(),)
