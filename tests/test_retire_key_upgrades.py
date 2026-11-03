"""Spec 047, Upgrades that retire a key: drop-agents-prs takes [agents] prs out and adds nothing,
drop-roadmap takes [roadmap] out and moves its wip to [agents] when [agents] sets none, and the
deprecations catalogue names each as its entry's migrating upgrade"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.deprecations import DeprecationId
from shipmill.deprecations import find as find_deprecation
from shipmill.deprecations_report import StateKind, upgrade_state
from shipmill.doctor import doctor
from shipmill.github import UPGRADE_LABEL
from shipmill.gitrepo import Git
from shipmill.policy import Policy
from shipmill.upgrades import Upgrade, UpgradeId, body, find, marked, marker

from .conftest import POLICY, FakeGitHub, Repo
from .test_gate import checkout
from .test_gate_upgrades import setup, swept_tick

__all__ = ["checkout"]  # the fixture, imported for the sweep's test

DROP_PRS = find(UpgradeId("drop-agents-prs"))
DROP_ROADMAP = find(UpgradeId("drop-roadmap"))
# changelog-fragments and agent-autonomy decided, so only the upgrades under test are pending
BASE = POLICY.replace("[changelog]\n", '[changelog]\nfragments = "changelog.d"\n').replace(
    "\n[[version_lines]]", '\n[autonomy]\nland = "propose"\n\n[[version_lines]]'
)


def write_config(root: Path, text: str) -> Path:
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def apply(root: Path, upgrade: Upgrade, *flags: str) -> None:
    assert main(["--repo", str(root), "upgrade", "--apply", str(upgrade.id), *flags]) == 0


def listed(root: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert main(["--repo", str(root), "upgrade", "--json"], github=FakeGitHub()) == 0
    return [u["id"] for u in json.loads(capsys.readouterr().out)]


def shipmill(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "shipmill", "--repo", str(root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


# -- drop-agents-prs (S-047-18) --------------------------------------------------------------

AGENTS_PRS = """\
# the agents  (two spaces, kept)
[agents]   # the gate
prompt = "triage {repo}"
prs = true            # the gate's open pull requests, before spec 040
wip = 2

# the next table, kept
[autonomy]
land = "propose"
"""


def test_s047_18_apply_deletes_the_prs_line_keeps_every_other_byte_and_adds_none(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    text = BASE.replace('\n[autonomy]\nland = "propose"\n', "\n" + AGENTS_PRS)
    path = write_config(repo.root, text)
    repo.write("changelog.d/README.md", "fragments\n")  # the folder [changelog] fragments names
    assert [c for c in doctor(repo.root, repo.github) if "[agents] prs" in c.detail]  # warned before
    assert listed(repo.root, capsys) == ["drop-agents-prs"]
    apply(repo.root, DROP_PRS)
    assert capsys.readouterr().out.startswith(
        "removed prs from [agents] in .github/shipmill.toml\nadded no line to .github/shipmill.toml\n"
    )
    after = path.read_bytes()
    assert (
        after == text.replace("prs = true            # the gate's open pull requests, before spec 040\n", "").encode()
    )
    raw = tomllib.loads(after.decode())
    assert DROP_PRS.decided(raw) and not DROP_PRS.applies(raw)
    assert listed(repo.root, capsys) == []
    policy = Policy.load(path)
    assert policy.agents is not None and policy.agents.prs is None and policy.agents.wip == 2
    # doctor gives no agents-prs warning any more
    assert find_deprecation(DeprecationId("agents-prs")).warn(policy) is None
    assert not [c for c in doctor(repo.root, repo.github) if "[agents] prs" in c.detail]


def test_s047_18_the_json_and_a_crlf_last_line_without_a_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = '[agents]\r\nprompt = "/t"\r\nprs = false # off'
    path = write_config(tmp_path, text)
    apply(tmp_path, DROP_PRS, "--json")
    record = json.loads(capsys.readouterr().out)
    assert (record["line"], record["lines"], record["removed"]) == (None, [], "prs")
    assert (record["removed_lines"], record["dropped"], record["into"]) == (["prs = false # off"], None, "agents")
    assert path.read_bytes() == b'[agents]\r\nprompt = "/t"\r\n'


def test_s047_18_listing_and_the_issue_show_the_line_it_takes_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = BASE + '\n[agents]\nprompt = "/t"\nprs = true\n'
    write_config(tmp_path, text)
    assert main(["--repo", str(tmp_path), "upgrade"], github=FakeGitHub()) == 0
    out = capsys.readouterr().out
    assert out.startswith("drop-agents-prs (shipmill 0.113.0): ")
    assert "  removes: [agents] prs\n  adds: nothing\n" in out
    assert main(["--repo", str(tmp_path), "upgrade", "--json"], github=FakeGitHub()) == 0
    (record,) = json.loads(capsys.readouterr().out)
    assert (record["lines"], record["removes"], record["removed_lines"]) == ([], "prs", ["prs = true"])
    text_body = body(DROP_PRS, tomllib.loads(text))
    assert text_body.startswith(marker(DROP_PRS) + "\n")
    assert "It deletes the `prs` line from `[agents]` in `.github/shipmill.toml`" in text_body
    assert "and adds none." in text_body
    assert "```diff\n [agents]\n-prs = true\n```" in text_body
    assert "```toml" not in text_body
    assert (
        "won't propose drop-agents-prs again. `[agents] prs` stays, doctor keeps warning, and"
        " `shipmill deprecations` keeps listing this repo under `agents-prs` (D-63)."
    ) in text_body
    assert "closes it once `[agents]` no longer sets `prs`." in text_body


def test_s047_18_closing_its_issue_unaccepted_keeps_the_key_and_the_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = BASE + '\n[agents]\nprompt = "/t"\nprs = true\n'
    path = write_config(tmp_path, text)
    github = FakeGitHub()
    github.close_issue(github.create_issue("t", f"{marker(DROP_PRS)}\n", (UPGRADE_LABEL,)), "")
    assert main(["--repo", str(tmp_path), "upgrade", "--json"], github=github) == 0
    assert json.loads(capsys.readouterr().out) == []  # declined: never proposed again
    assert path.read_text(encoding="utf-8") == text
    policy = Policy.load(path)
    assert find_deprecation(DeprecationId("agents-prs")).relies(policy)  # the warning stays
    state = upgrade_state(DROP_PRS, tomllib.loads(text), github.labelled_issues(UPGRADE_LABEL), [])
    assert state.kind is StateKind.DECLINED  # listed under agents-prs, declined


def test_s047_18_refuses_a_config_without_prs_and_writes_nothing(tmp_path: Path) -> None:
    text = '[agents]\nprompt = "/t"\n'
    path = write_config(tmp_path, text)
    done = shipmill(tmp_path, "upgrade", "--apply", "drop-agents-prs")
    assert done.returncode == 2
    assert "upgrade drop-agents-prs doesn't apply: [agents] in .github/shipmill.toml sets no prs" in done.stderr
    assert path.read_text(encoding="utf-8") == text


# -- drop-roadmap (S-047-19) -----------------------------------------------------------------

ROADMAP = """\
# the release policy  (kept)
name = "demo"

# the roadmap, deprecated
[roadmap]
wip = 3          # issues at once
cadence = 2

[agents]   # the gate
prompt = "triage {repo}"
mode = "headless"
# a comment after the last key, kept

[agents.roles]
release = ["@octo"]

[[version_lines]]
file = "README.md"
pattern = 'x'
replace = "{version}"
"""


def test_s047_19_apply_deletes_the_table_and_moves_wip_into_agents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path, ROADMAP)
    apply(tmp_path, DROP_ROADMAP)
    assert capsys.readouterr().out.startswith(
        "removed [roadmap] from .github/shipmill.toml, these lines:\n"
        "  [roadmap]\n"
        "  wip = 3          # issues at once\n"
        "  cadence = 2\n"
        "  \n"
        "added wip = 3 to [agents] in .github/shipmill.toml\n"
    )
    assert path.read_text(encoding="utf-8") == ROADMAP.replace(
        "[roadmap]\nwip = 3          # issues at once\ncadence = 2\n\n", ""
    ).replace('mode = "headless"\n', 'mode = "headless"\nwip = 3\n')
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    assert "roadmap" not in raw and raw["agents"]["wip"] == 3
    assert raw["agents"]["roles"] == {"release": ["@octo"]}  # wip went into [agents], not [agents.roles]
    assert DROP_ROADMAP.decided(raw) and not DROP_ROADMAP.applies(raw)


def test_s047_19_the_json_names_the_lines_taken_out_and_the_one_moved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(tmp_path, ROADMAP)
    apply(tmp_path, DROP_ROADMAP, "--json")
    record = json.loads(capsys.readouterr().out)
    assert (record["dropped"], record["removed"], record["into"]) == ("roadmap", None, "agents")
    assert record["removed_lines"] == ["[roadmap]", "wip = 3          # issues at once", "cadence = 2", ""]
    assert (record["line"], record["lines"]) == ("wip = 3", ["wip = 3"])


@pytest.mark.parametrize(
    ("agents", "why"),
    [
        ('[agents]\nprompt = "/t"\nwip = 7\n', "`[agents]` already sets `wip`, which stays as it is"),
        ("", "the config has no `[agents]` table to move `wip` to"),
    ],
)
def test_s047_19_with_agents_wip_set_or_no_agents_it_adds_no_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], agents: str, why: str
) -> None:
    text = f'name = "demo"\n\n[roadmap]\nwip = 3\n\n{agents}'
    path = write_config(tmp_path, text)
    raw = tomllib.loads(text)
    assert not DROP_ROADMAP.adds(raw) and DROP_ROADMAP.lines(raw) == ()
    issue = body(DROP_ROADMAP, raw)
    assert f"It adds no line: {why}." in issue
    assert "```diff\n-[roadmap]\n-wip = 3\n```" in issue
    apply(tmp_path, DROP_ROADMAP)
    assert "added no line to .github/shipmill.toml\n" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == text.replace("[roadmap]\nwip = 3\n\n", "")
    after = tomllib.loads(path.read_text(encoding="utf-8"))
    assert after.get("agents", {}).get("wip") == raw.get("agents", {}).get("wip")


def test_s047_19_a_roadmap_without_wip_moves_nothing(tmp_path: Path) -> None:
    text = '[agents]\nprompt = "/t"\n\n[roadmap]\ncadence = 2\n'  # at the end of the file
    path = write_config(tmp_path, text)
    assert "It adds no line: `[roadmap]` sets no `wip`." in body(DROP_ROADMAP, tomllib.loads(text))
    apply(tmp_path, DROP_ROADMAP)
    assert path.read_text(encoding="utf-8") == '[agents]\nprompt = "/t"\n\n'


def test_s047_19_a_roadmap_before_an_array_of_tables_keeps_it(tmp_path: Path) -> None:
    text = (
        '[agents]\nprompt = "/t"\n\n[roadmap]\nwip = 3\n[[version_lines]]\nfile = "a"\npattern = "x"\nreplace = "y"\n'
    )
    path = write_config(tmp_path, text)
    apply(tmp_path, DROP_ROADMAP)
    assert path.read_text(encoding="utf-8") == text.replace("[roadmap]\nwip = 3\n", "").replace(
        'prompt = "/t"\n', 'prompt = "/t"\nwip = 3\n'
    )


def test_s047_19_the_issue_names_the_limit_it_turns_on(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = BASE + '\n[agents]\nprompt = "/t"\n\n[roadmap]\nwip = 3\ncadence = 2\n'
    write_config(tmp_path, text)
    issue = body(DROP_ROADMAP, tomllib.loads(text))
    assert (
        "It deletes the `[roadmap]` table from `.github/shipmill.toml` (its header, its keys, and its lines up to"
        " the next table's header) and keeps every other line. It moves `wip = 3` into `[agents]`, which turns it"
        " on, since nothing reads `[roadmap]`'s `wip` today: triage keeps at most 3 issues in progress at once."
    ) in issue
    assert "```diff\n-[roadmap]\n-wip = 3\n-cadence = 2\n [agents]\n+wip = 3\n```" in issue
    assert "closes it once `.github/shipmill.toml` has no `[roadmap]` table." in issue
    assert main(["--repo", str(tmp_path), "upgrade"], github=FakeGitHub()) == 0
    out = capsys.readouterr().out
    assert "  removes: [roadmap], the whole table\n  adds: [agents] wip = 3\n" in out
    assert main(["--repo", str(tmp_path), "upgrade", "--json"], github=FakeGitHub()) == 0
    (record,) = json.loads(capsys.readouterr().out)
    assert (record["drops"], record["into"], record["lines"]) == ("roadmap", "agents", ["wip = 3"])
    assert record["removed_lines"] == ["[roadmap]", "wip = 3", "cadence = 2"]


def test_s047_19_a_decided_config_closes_its_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github = FakeGitHub()
    write_config(tmp_path, BASE + "\n[roadmap]\nwip = 3\n")
    assert main(["--repo", str(tmp_path), "upgrade", "--propose"], github=github) == 0
    [(number, _)] = github.issues.items()
    apply(tmp_path, DROP_ROADMAP)
    capsys.readouterr()
    assert main(["--repo", str(tmp_path), "upgrade", "--propose"], github=github) == 0
    assert github.closed[number] == (
        "`.github/shipmill.toml` has no `[roadmap]` table: drop-roadmap is decided, so this issue is done."
    )


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("roadmap = { wip = 3 }\n", "no [roadmap] header line"),
        ("roadmap.wip = 3\n", "no [roadmap] header line"),  # dotted
        ("[roadmap]\nwip = 3\n\n[roadmap.x]\ny = 1\n", "can't take [roadmap] out of .github/shipmill.toml"),
        ('[roadmap]\nwip = 3\n\n[agents.roles]\nrelease = ["@o"]\n', "can't take [roadmap] out of"),
    ],
)
def test_s047_19_refuses_a_table_it_cannot_take_out_and_writes_nothing(tmp_path: Path, text: str, error: str) -> None:
    path = write_config(tmp_path, text)
    done = shipmill(tmp_path, "upgrade", "--apply", "drop-roadmap")
    assert done.returncode == 2
    assert error in done.stderr
    assert path.read_text(encoding="utf-8") == text


# -- the deprecations catalogue and the sweep (S-047-20) -------------------------------------


def test_s047_20_the_deprecations_name_the_two_upgrades() -> None:
    upgrades = {i: find_deprecation(DeprecationId(i)).upgrade for i in ("agents-prs", "roadmap")}
    assert upgrades == {"agents-prs": DROP_PRS.id, "roadmap": DROP_ROADMAP.id}
    # the prompt's land reading stays agent-autonomy's; [agents] credit has no upgrade (spec 051)
    assert find_deprecation(DeprecationId("agents-prompt-land")).upgrade == UpgradeId("agent-autonomy")
    assert find_deprecation(DeprecationId("agents-credit")).upgrade is None


def test_s047_20_a_sweep_opens_an_issue_for_each(checkout: Git) -> None:
    text = BASE + '\n[agents]\nprompt = "/t"\nprs = true\n\n[roadmap]\nwip = 3\n'
    source, seams = setup(text)
    swept_tick(checkout, source, seams)
    opened = seams.github.open_labelled_issues(UPGRADE_LABEL)
    assert sorted(str(marked(i)) for i in opened) == ["drop-agents-prs", "drop-roadmap"]
    raw = tomllib.loads(text)
    for upgrade in (DROP_PRS, DROP_ROADMAP):  # shipmill deprecations reads each as open
        state = upgrade_state(upgrade, raw, opened, [])
        assert state.kind is StateKind.ISSUE_OPEN
