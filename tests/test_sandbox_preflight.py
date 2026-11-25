"""Before a sandboxed launch (spec 087, #1534): a settings file that would widen the session's
sandbox (S-087-13) or a Linux host that can't confine (S-087-17) fails the tick and starts no
session, and doctor's sandbox row says so, or what the sandbox opens (S-087-18)"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from shipmill.cli import _parser
from shipmill.doctor import REFUSED, SANDBOX_OFF, SANDBOX_ROW, Check, doctor
from shipmill.errors import ReleaseError
from shipmill.gate import RECORD, TICK, sandbox_for, state_dir
from shipmill.gitrepo import Git
from shipmill.sandbox import (
    BWRAP_PROBE,
    LINUX_PROBE,
    PACKAGES,
    USERNS_FIX,
    WIDENING_FIX,
    SandboxConfig,
    Unconfined,
    confinement,
    widening,
)

from .conftest import POLICY, Repo
from .test_app import REPO
from .test_gate import FakeClaude, bg
from .test_gate_headless import headless
from .test_sandbox_launch import checkout, home, sandboxer, tick

__all__ = ["checkout", "home"]  # the fixtures, shared with test_sandbox_launch

WIDENS = "which would widen a headless session's sandbox"


def settings(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


# S-087-13


def scope_of(root: Path) -> tuple[Path, ...]:
    return (root, root / ".git", Path("/opt/cache"))


@pytest.mark.parametrize("name", [".claude/settings.json", ".claude/settings.local.json"])
@pytest.mark.parametrize(
    ("value", "key"),
    [
        ({"sandbox": {"enabled": False}}, "sandbox"),
        ({"sandbox": {}}, "sandbox"),
        ({"permissions": {"additionalDirectories": ["/"]}}, "permissions.additionalDirectories"),
        ({"permissions": {"allow": ["Bash(npm *)", "Edit"]}}, 'permissions.allow "Edit"'),
        ({"permissions": {"allow": ["Write"]}}, 'permissions.allow "Write"'),
        ({"permissions": {"allow": ["Write(//etc/**)"]}}, 'permissions.allow "Write(//etc/**)"'),
        ({"permissions": {"allow": ["Edit(//**)"]}}, 'permissions.allow "Edit(//**)"'),
        ({"permissions": {"allow": ["Edit(~/notes/**)"]}}, 'permissions.allow "Edit(~/notes/**)"'),
        ({"permissions": {"allow": ["Edit(../outside/**)"]}}, 'permissions.allow "Edit(../outside/**)"'),
        ({"permissions": {"allow": ["Write()"]}}, 'permissions.allow "Write()"'),
        ({"permissions": "all"}, "permissions"),
        ({"permissions": {"allow": "Edit"}}, "permissions.allow"),
    ],
)
def test_s087_13_a_checkout_settings_key_that_widens_is_named(
    tmp_path: Path, name: str, value: object, key: str
) -> None:
    root, home = tmp_path / "demo", tmp_path / "home"
    path = settings(root / name, value)
    found = widening(root, home, scope_of(root))
    assert found is not None and (found.file, found.key) == (path, key)
    assert found.message == f"{path} sets {key}, {WIDENS}"
    error = found.error()
    assert str(error) == found.message and "[agents.sandbox]" in (error.fix or "") and error.fix == WIDENING_FIX


def test_s087_13_the_users_settings_count_too(tmp_path: Path) -> None:
    root, home = tmp_path / "demo", tmp_path / "home"
    path = settings(home / ".claude" / "settings.json", {"permissions": {"allow": ["Write"]}})
    found = widening(root, home, scope_of(root))
    assert found is not None and found.message == f'{path} sets permissions.allow "Write", {WIDENS}'
    relative = settings(home / ".claude" / "settings.json", {"permissions": {"allow": ["Edit(/notes/**)"]}})
    found = widening(root, home, scope_of(root))  # relative to the home's settings: outside the scope
    assert found is not None and found.file == relative


@pytest.mark.parametrize(
    "rules",
    [
        ["Bash(npm *)", "Read", "WebFetch(domain:example.com)", "Edit(src/**)", "Write(./docs/*.md)"],
        ["Edit(/src/**)"],  # relative to the project's settings: the checkout
        ["Edit(//{root}/**)", "Write(//{root}/.git/x)", "Write(//opt/cache/**)"],
    ],
)
def test_s087_13_rules_inside_the_write_scope_and_other_keys_pass(tmp_path: Path, rules: list[str]) -> None:
    root, home = tmp_path / "demo", tmp_path / "home"
    allow = [r.replace("//{root}", f"/{root}") for r in rules]
    settings(root / ".claude" / "settings.json", {"permissions": {"allow": allow, "deny": ["Read(.env)"]}, "env": {}})
    settings(home / ".claude" / "settings.json", {"model": "opus", "permissions": {"allow": ["Bash(ls *)"]}})
    assert widening(root, home, scope_of(root)) is None


def test_s087_13_no_settings_files_widen_nothing(tmp_path: Path) -> None:
    assert widening(tmp_path / "demo", tmp_path / "home", scope_of(tmp_path / "demo")) is None


def test_s087_13_a_settings_file_that_isnt_json_fails(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "settings.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ReleaseError, match="doesn't parse as JSON"):
        widening(root, tmp_path / "home", scope_of(root))


def test_s087_13_a_widening_settings_file_fails_the_tick_and_starts_no_session(checkout: Git, home: Path) -> None:
    path = settings(home / ".claude" / "settings.json", {"permissions": {"allow": ["Write"]}})
    claude = FakeClaude([bg("old", "idle", "done")])
    with pytest.raises(ReleaseError) as caught:
        tick(checkout, headless(), claude, sandboxer(checkout, home))
    assert str(caught.value) == f'{path} sets permissions.allow "Write", {WIDENS}'
    assert "[agents.sandbox]" in (caught.value.fix or "")
    assert (claude.started, claude.launched, claude.stopped) == ([], [], [])
    assert not (state_dir(checkout) / RECORD).exists()
    record = json.loads((state_dir(checkout) / TICK).read_text(encoding="utf-8"))
    assert record["action"] == "ERROR" and record["reason"] == str(caught.value) and record["fix"] == WIDENING_FIX


def test_s087_13_the_checkouts_sandbox_key_fails_the_tick(checkout: Git, home: Path) -> None:
    settings(checkout.root / ".claude" / "settings.local.json", {"sandbox": {"enabled": False}})
    claude = FakeClaude()
    with pytest.raises(ReleaseError, match=rf"settings.local.json sets sandbox, {WIDENS}$"):
        tick(checkout, headless(), claude, sandboxer(checkout, home))
    assert claude.started == []


def test_s087_13_without_the_sandbox_the_settings_files_arent_read(checkout: Git, home: Path) -> None:
    settings(checkout.root / ".claude" / "settings.json", {"sandbox": {"enabled": False}})
    claude = FakeClaude()
    tick(checkout, headless(), claude, None)
    assert len(claude.started) == 1


# S-087-17


class Host:
    """A host's PATH and its bwrap's answer, as the probe asks them"""

    def __init__(self, missing: Sequence[str] = (), code: int = 0, stderr: str = "") -> None:
        self.missing, self.code, self.stderr = set(missing), code, stderr
        self.ran: list[Sequence[str]] = []

    def which(self, name: str) -> str | None:
        return None if name in self.missing else f"/usr/bin/{name}"

    def run(self, cmd: Sequence[str]) -> tuple[int, str]:
        self.ran.append(cmd)
        return self.code, self.stderr


def probe(host: Host, platform: str = "linux") -> Unconfined | None:
    return confinement(platform, host.run, host.which)


def test_s087_17_a_linux_host_with_bwrap_and_socat_confines() -> None:
    host = Host()
    assert probe(host) is None
    assert host.ran == [BWRAP_PROBE] and BWRAP_PROBE == ("bwrap", "--ro-bind", "/", "/", "--unshare-user", "true")


def test_s087_17_macos_runs_no_probe() -> None:
    host = Host(missing=("bwrap", "socat"))
    assert probe(host, "darwin") is None and host.ran == []


def test_s087_17_a_user_namespace_refusal_names_the_sysctl() -> None:
    err = "bwrap: setting up uid map: Permission denied\n"
    found = probe(Host(code=1, stderr=err))
    assert found is not None
    assert found.message == (
        "the sandbox can't start on this host: `bwrap --ro-bind / / --unshare-user true` exited 1:"
        " bwrap: setting up uid map: Permission denied"
    )
    assert found.fix == USERNS_FIX and "kernel.apparmor_restrict_unprivileged_userns" in found.fix


@pytest.mark.parametrize(
    ("host", "failed"),
    [
        (Host(missing=("bwrap",)), "bwrap is not on PATH"),
        (Host(missing=("socat",)), "socat is not on PATH"),
        (Host(missing=("bwrap", "socat")), "bwrap is not on PATH; socat is not on PATH"),
    ],
)
def test_s087_17_a_missing_package_names_the_install(host: Host, failed: str) -> None:
    found = probe(host)
    assert found is not None and found.message == f"the sandbox can't start on this host: {failed}"
    assert found.fix == PACKAGES


def test_s087_17_a_host_that_cant_confine_fails_the_tick_and_starts_no_session(checkout: Git, home: Path) -> None:
    unconfined = probe(Host(missing=("socat",)))
    assert unconfined is not None
    claude = FakeClaude([bg("old", "idle", "done")])
    sandbox = sandbox_for(checkout, REPO, home, lambda git: SandboxConfig(), lambda: unconfined)
    with pytest.raises(ReleaseError) as caught:
        tick(checkout, headless(), claude, sandbox)
    assert str(caught.value) == "the sandbox can't start on this host: socat is not on PATH"
    assert caught.value.fix == PACKAGES
    assert (claude.started, claude.stopped) == ([], [])


# S-087-18

HEADLESS = '\n[agents]\nprompt = "/t"\nmode = "headless"\n'
DECLARED = """
[agents.sandbox]
domains = ["registry.npmjs.org", "*.example.com"]
read = ["~/.config/tool"]
write = ["~/.cache/pnpm", "/opt/cache"]
local_ports = true

[[agents.sandbox.tunnels]]
ssh = "readonly@db.example.com"
local = 15432
remote = "127.0.0.1:5432"
"""
GRANT = """
[agents.sandbox.grant]
domains = ["api.staging.example.com"]
write = ["~/data/fixtures"]
local_ports = true

[[agents.sandbox.grant.tunnels]]
ssh = "db.example.com"
local = 15433
remote = "localhost:5432"
"""


def row(
    repo: Repo,
    tmp_path: Path,
    config: str,
    sandboxed: bool = True,
    platform: str = "darwin",
    confines: Unconfined | None = None,
) -> list[Check]:
    repo.write(repo.policy_file, POLICY + config)
    checks = doctor(
        repo.root,
        repo.github,
        repo=REPO,
        home=tmp_path / "home",
        sandboxed=sandboxed,
        platform=platform,
        confines=lambda: confines,
    )
    return [c for c in checks if c.name == SANDBOX_ROW]


def test_s087_18_no_row_without_headless_mode(repo: Repo, tmp_path: Path) -> None:
    assert row(repo, tmp_path, '\n[agents]\nprompt = "/t"\n') == []
    assert row(repo, tmp_path, "") == []


def test_s087_18_off_warns(repo: Repo, tmp_path: Path) -> None:
    assert row(repo, tmp_path, HEADLESS + DECLARED, sandboxed=False) == [Check("WARN", SANDBOX_ROW, SANDBOX_OFF)]
    assert SANDBOX_OFF == "off: headless sessions run unconfined; pass --sandbox"


def test_s087_18_on_passes_listing_what_it_opens_and_grants_none_without_the_table(repo: Repo, tmp_path: Path) -> None:
    assert row(repo, tmp_path, HEADLESS + DECLARED) == [
        Check(
            "PASS",
            SANDBOX_ROW,
            "on: 7 default domains, registry.npmjs.org, *.example.com, 1 read and 2 write exceptions, 1 tunnels,"
            " local ports on; grants: none",
        )
    ]
    assert row(repo, tmp_path, HEADLESS) == [
        Check(
            "PASS",
            SANDBOX_ROW,
            "on: 7 default domains, 0 read and 0 write exceptions, 0 tunnels, local ports off; grants: none",
        )
    ]


def test_s087_18_grants_name_each_kind_the_table_declares_with_its_entries(repo: Repo, tmp_path: Path) -> None:
    [check] = row(repo, tmp_path, HEADLESS + GRANT)
    assert check.status == "PASS"
    assert check.detail.endswith(
        "; grants: domains (api.staging.example.com), write (~/data/fixtures), local-ports,"
        " tunnels (db.example.com 15433:localhost:5432)"
    )
    [empty] = row(repo, tmp_path, HEADLESS + "\n[agents.sandbox.grant]\n")
    assert empty.detail.endswith("; grants: none")


def test_s087_18_a_linux_host_that_cant_confine_fails_with_the_ticks_text(repo: Repo, tmp_path: Path) -> None:
    unconfined = probe(Host(missing=("bwrap",)))
    assert unconfined is not None
    [check] = row(repo, tmp_path, HEADLESS, platform="linux", confines=unconfined)
    failed = "the sandbox can't start on this host: bwrap is not on PATH"
    assert check == Check("FAIL", SANDBOX_ROW, f"{failed}; fix: {PACKAGES}")


def test_s087_18_a_widening_settings_file_fails_with_the_ticks_text(repo: Repo, tmp_path: Path) -> None:
    path = settings(tmp_path / "home" / ".claude" / "settings.json", {"permissions": {"additionalDirectories": ["/"]}})
    [check] = row(repo, tmp_path, HEADLESS)
    assert check == Check(
        "FAIL", SANDBOX_ROW, f"{path} sets permissions.additionalDirectories, {WIDENS}; fix: {WIDENING_FIX}"
    )


def test_s087_18_off_never_reads_the_settings_or_probes(repo: Repo, tmp_path: Path) -> None:
    settings(tmp_path / "home" / ".claude" / "settings.json", {"sandbox": {}})
    unconfined = Unconfined("socat is not on PATH", PACKAGES)
    assert row(repo, tmp_path, HEADLESS, sandboxed=False, confines=unconfined)[0].status == "WARN"


def test_s087_18_doctor_takes_sandbox_for_a_gate_that_isnt_a_launchd_job() -> None:
    assert _parser().parse_args(["doctor", "--sandbox"]).sandbox is True
    assert _parser().parse_args(["doctor"]).sandbox is False


def test_s087_26_on_linux_doctor_names_the_dropped_local_ports(repo: Repo, tmp_path: Path) -> None:
    repo.write(repo.policy_file, POLICY + HEADLESS + "\n[agents.sandbox]\nlocal_ports = true\n")
    checks = doctor(repo.root, repo.github, repo=REPO, home=tmp_path / "home", platform="linux", confines=lambda: None)
    [refused] = [c for c in checks if c.name == REFUSED]
    assert refused.status == "FAIL" and LINUX_PROBE in refused.detail
    assert [c.detail for c in checks if c.name == SANDBOX_ROW] == [SANDBOX_OFF]
