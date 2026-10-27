"""`shipmill plugin-clean` (spec 039): the project- and local-scope installs of shipmill@shipmill
listed, deepest folder first, and with --apply, from a terminal, removed in their folders with
each folder's settings files restored byte for byte. Claude Code is a fake here: no real
`claude plugin` command runs"""

import io
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.plugin import INSTALLED, READ_MARKETPLACE, USER_INSTALL, USER_UPDATE

PLUGIN = "shipmill@shipmill"
LIST = ["claude", "plugin", "list", "--json"]
SETTINGS = '{\n  "permissions": {"allow": ["Bash(ls)"]},\n  "enabledPlugins": {"shipmill@shipmill": true}\n}\n'


def marketplace(ref: str) -> str:
    entry = {"name": "shipmill", "source": {"source": "github", "repo": "shipmill/shipmill", "ref": ref}}
    return json.dumps({"name": "shipmill", "plugins": [entry]})


def entry(scope: str, version: str, where: Path | None = None, plugin: str = PLUGIN) -> dict[str, str]:
    found = {"id": plugin, "scope": scope, "version": version}
    if where is not None:
        found["projectPath"] = str(where)
    return found


@dataclass
class FakeClaude:
    """`claude plugin list --json`, `claude plugin uninstall` in a folder, and the marketplace's
    gh api read. An uninstall removes the entry keyed on its cwd at its scope and, as Claude
    Code does, rewrites the folder's .claude/settings.json without the plugin; writes names
    more files it leaves there. keep leaves the entry listed; also removes another entry too
    (#233's nested-folder bug)"""

    entries: list[dict[str, str]]
    latest: str = "v0.82.0"
    keep: bool = False
    also: dict[str, str] | None = None
    writes: tuple[str, ...] = (".claude/settings.local.json",)
    calls: list[tuple[list[str], Path]] = field(default_factory=list)

    def __call__(self, cmd: list[str], cwd: Path) -> str:
        self.calls.append((cmd, cwd))
        if cmd == LIST:
            return json.dumps(self.entries)
        if cmd == READ_MARKETPLACE:
            return marketplace(self.latest)
        if cmd[:4] == ["claude", "plugin", "uninstall", PLUGIN] and cmd[4] == "--scope":
            assert cwd.is_dir(), f"uninstall ran in {cwd}, which doesn't exist"
            settings = cwd / ".claude" / "settings.json"
            settings.parent.mkdir(exist_ok=True)
            settings.write_text('{"enabledPlugins": {}}\n', encoding="utf-8")
            for name in self.writes:
                (cwd / name).write_text("{}\n", encoding="utf-8")
            target = {"id": PLUGIN, "scope": cmd[5], "projectPath": str(cwd)}
            if not self.keep:
                self.entries = [e for e in self.entries if any(e.get(k) != v for k, v in target.items())]
            if self.also is not None:
                self.entries = [e for e in self.entries if e != self.also]
            return ""
        raise AssertionError(f"unexpected command {cmd}")

    @property
    def uninstalls(self) -> list[tuple[str, Path]]:
        return [(cmd[5], cwd) for cmd, cwd in self.calls if cmd[2] == "uninstall"]

    @property
    def claude(self) -> list[list[str]]:
        return [cmd for cmd, _ in self.calls if cmd[0] == "claude"]


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def clean(fake: FakeClaude, home: Path, *args: str, terminal: bool = True) -> int:
    return main(["plugin-clean", *args], stdin=Tty() if terminal else io.StringIO(), claude=fake, home=home)


def tree(root: Path) -> dict[str, bytes | None]:
    """Every path under root, a file's bytes, None for a folder"""
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def linked_worktree(main_dir: Path, path: Path) -> Path:
    run = ["git", "-C", str(main_dir), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "maintenance.auto=false"]
    subprocess.run(["git", "init", "-q", str(main_dir)], check=True)
    subprocess.run([*run, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    subprocess.run([*run, "worktree", "add", "-q", "--detach", str(path)], check=True)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    found = tmp_path / "home"
    (found / ".claude" / "plugins").mkdir(parents=True)
    (found / ".claude" / "plugins" / "installed_plugins.json").write_text('{"version": 2}\n', encoding="utf-8")
    return found


@pytest.fixture
def host(tmp_path: Path) -> dict[str, Path]:
    """A repo, its nested gate checkout (a linked worktree), another repo, and a gone folder"""
    repo = tmp_path / "w" / "repo-a"
    repo.mkdir(parents=True)
    gate = linked_worktree(repo, repo / "tmp" / "shipmill-gate")
    other = tmp_path / "w" / "repo-b"
    (other / ".claude").mkdir(parents=True)
    (other / ".claude" / "settings.json").write_text(SETTINGS, encoding="utf-8")
    return {"repo": repo, "gate": gate, "other": other, "gone": tmp_path / "w" / "gone" / "deeper"}


def test_s039_8_the_dry_run_lists_each_keyed_install_deepest_first_and_changes_nothing(
    host: dict[str, Path], home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClaude(
        [
            entry("user", "0.82.0"),
            entry("project", "0.25.0", host["repo"]),
            entry("local", "0.70.0", host["gate"]),
            entry("local", "0.58.0", host["gone"]),
            entry("project", "0.73.1", host["other"]),
        ]
    )
    before = tree(tmp_path)
    assert clean(fake, home, terminal=False) == 0  # no terminal needed for a dry run
    assert tree(tmp_path) == before  # wrote no file, created no folder
    assert fake.claude == [LIST]  # no claude command but the list
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[:4] for line in out] == [
        ["manual", "local", "0.70.0", str(host["gate"])],
        ["remove", "local", "0.58.0", str(host["gone"])],
        ["remove", "project", "0.25.0", str(host["repo"])],
        ["remove", "project", "0.73.1", str(host["other"])],
    ]
    assert out[0].endswith(
        f'a linked worktree: delete the entry with "projectPath": "{host["gate"]}" under "{PLUGIN}" in {INSTALLED}'
    )
    assert out[1].endswith("missing: created for the uninstall, then removed")
    assert out[3].endswith("restores .claude/settings.json")


def test_s039_8_no_keyed_install_says_so(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeClaude([entry("user", "0.82.0")])
    assert clean(fake, home) == 0
    assert capsys.readouterr().out == f"no project- or local-scope install of {PLUGIN} on this host\n"


def test_s039_9_apply_without_a_terminal_refuses_before_any_change(host: dict[str, Path], home: Path) -> None:
    fake = FakeClaude([entry("user", "0.82.0"), entry("project", "0.25.0", host["other"])])
    with pytest.raises(ReleaseError, match="only from a person's terminal"):
        clean(fake, home, "--apply", terminal=False)
    assert fake.uninstalls == [] and fake.calls == []


def test_s039_9_apply_without_a_user_install_refuses_naming_it(host: dict[str, Path], home: Path) -> None:
    fake = FakeClaude([entry("project", "0.25.0", host["other"])])
    with pytest.raises(ReleaseError) as refused:
        clean(fake, home, "--apply")
    assert USER_INSTALL == "claude plugin install shipmill@shipmill --scope user"
    assert USER_INSTALL in str(refused.value)
    assert fake.uninstalls == []
    assert (host["other"] / ".claude" / "settings.json").read_text(encoding="utf-8") == SETTINGS


def test_s039_10_each_removal_runs_in_its_folder_and_restores_the_settings_byte_for_byte(
    host: dict[str, Path], home: Path
) -> None:
    bare = host["repo"].parent / "repo-c"  # a folder with no .claude/ at all
    bare.mkdir()
    fake = FakeClaude(
        [entry("user", "0.82.0"), entry("project", "0.73.1", host["other"]), entry("local", "0.60.0", bare)]
    )
    assert clean(fake, home, "--apply") == 0
    assert sorted(fake.uninstalls) == sorted([("project", host["other"]), ("local", bare)])
    assert (host["other"] / ".claude" / "settings.json").read_bytes() == SETTINGS.encode()
    assert not (host["other"] / ".claude" / "settings.local.json").exists()  # the uninstall created it
    assert not (bare / ".claude").exists()  # absent before, absent after
    assert [e["scope"] for e in fake.entries] == ["user"]


@pytest.mark.parametrize("broken", ["keep", "also"])
def test_s039_11_an_unexpected_listing_stops_the_run_after_restoring_the_folder(
    host: dict[str, Path], home: Path, broken: str
) -> None:
    bystander = entry("project", "1.0.0", host["repo"], plugin="other@mine")
    shallow = host["other"].parent  # removed after the deeper one, if ever
    fake = FakeClaude(
        [
            entry("user", "0.82.0"),
            bystander,
            entry("project", "0.73.1", host["other"]),
            entry("project", "0.2", shallow),
        ],
        keep=broken == "keep",
        also=bystander if broken == "also" else None,
    )
    with pytest.raises(ReleaseError) as stopped:
        clean(fake, home, "--apply")
    said = str(stopped.value)
    assert ("it is still listed" in said) if broken == "keep" else ('gone: ["other@mine", "project"' in said)
    assert "no further uninstall" in said
    assert fake.uninstalls == [("project", host["other"])]  # the shallower entry was never reached
    assert (host["other"] / ".claude" / "settings.json").read_bytes() == SETTINGS.encode()
    assert not (host["other"] / ".claude" / "settings.local.json").exists()


def test_s039_12_a_missing_folder_is_created_for_the_uninstall_and_removed_again(
    host: dict[str, Path], home: Path, tmp_path: Path
) -> None:
    fake = FakeClaude([entry("user", "0.82.0"), entry("local", "0.58.0", host["gone"])])
    assert clean(fake, home, "--apply") == 0
    assert fake.uninstalls == [("local", host["gone"])]
    assert not (tmp_path / "w" / "gone").exists()  # the folder and the parent it created


def test_s039_12_a_created_folder_holding_more_is_left_named_and_exits_1(
    host: dict[str, Path], home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClaude([entry("user", "0.82.0"), entry("local", "0.58.0", host["gone"])], writes=("notes.txt",))
    assert clean(fake, home, "--apply") == 1
    assert (host["gone"] / "notes.txt").is_file()
    assert f"left {host['gone']}" in capsys.readouterr().out


def test_s039_13_a_linked_worktree_is_manual_never_uninstalled_and_installed_plugins_is_never_written(
    host: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = home / ".claude" / "plugins" / "installed_plugins.json"
    before = record.read_bytes()
    fake = FakeClaude([entry("user", "0.82.0"), entry("local", "0.70.0", host["gate"])])
    assert clean(fake, home, "--apply") == 1  # it is left
    assert fake.uninstalls == []
    assert record.read_bytes() == before
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("manual  local") and line.endswith(
        f'"projectPath": "{host["gate"]}" under "{PLUGIN}" in {INSTALLED}'
    )


@pytest.mark.parametrize(("user", "last"), [("0.80.0", f"then: {USER_UPDATE}"), ("0.82.0", None)])
def test_s039_14_only_the_plugins_keyed_installs_are_removed_and_the_last_line_updates_a_lagging_user_install(
    host: dict[str, Path], home: Path, capsys: pytest.CaptureFixture[str], user: str, last: str | None
) -> None:
    others = [
        entry("user", user),
        entry("managed", "0.82.0"),
        entry("project", "1.0.0", host["other"], plugin="other@mine"),
        entry("user", "2.0.0", plugin="other@mine"),
    ]
    fake = FakeClaude([*others, entry("project", "0.73.1", host["other"])])
    assert clean(fake, home, "--apply") == 0  # no keyed shipmill@shipmill install is left
    assert fake.uninstalls == [("project", host["other"])]
    assert all(cmd[3] == PLUGIN for cmd in fake.claude if cmd[2] == "uninstall")
    assert fake.entries == others
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if line.startswith("then:")] == ([] if last is None else [last])
    assert last is None or out[-1] == last
    assert USER_UPDATE == (
        "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user"
    )
