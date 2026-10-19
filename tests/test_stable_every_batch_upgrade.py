"""Spec 029: the stable lane `shipmill init` writes (S-029-11) and the stable-every-batch
upgrade for a config on a time soak (S-029-12)"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import CALLER
from shipmill.github import UPGRADE_LABEL
from shipmill.policy import Lane, Policy
from shipmill.ticks import crons
from shipmill.upgrades import UpgradeId, body, find, marker

from .conftest import POLICY, FakeGitHub, Repo

UPGRADE = find(UpgradeId("stable-every-batch"))
FRAGMENTS = '[changelog]\nfragments = "changelog.d"\n'  # changelog-fragments decided, so it stays out of the lists


def write_config(root: Path, text: str) -> Path:
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def listed(root: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert main(["--repo", str(root), "upgrade", "--json"], github=FakeGitHub()) == 0
    return [u["id"] for u in json.loads(capsys.readouterr().out)]


def apply(root: Path) -> None:
    assert main(["--repo", str(root), "upgrade", "--apply", "stable-every-batch"]) == 0


def shipmill(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "shipmill", "--repo", str(root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


# -- init (S-029-11) -------------------------------------------------------------------------


def test_s029_11_init_writes_a_stable_lane_on_quiet_minutes_and_no_schedule(repo: Repo) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    text = (repo.root / CONFIG_PATH).read_text(encoding="utf-8")
    stable = tomllib.loads(text)["lanes"]["stable"]
    assert stable == {"quiet_minutes": 30, "github_release": True}
    assert not {"promote_from", "min_soak_days", "schedule", "milestone"} & stable.keys()
    assert (
        "[lanes.stable]                      # X.Y.Z after every batch of merges; a breaking change waits for you\n"
        "quiet_minutes = 30\n"
        "github_release = true\n"
    ) in text
    # the rc lane only as comments, as the dev lane is
    assert (
        "# [lanes.rc]                        # X.Y.ZrcN for people who try a change first, by hand or on a schedule\n"
    ) in text
    assert "\n[lanes.rc]" not in text
    assert set(Policy.load(repo.root / CONFIG_PATH).lanes) == {Lane.STABLE, Lane.HOTFIX}
    workflow = (repo.root / CALLER).read_text(encoding="utf-8")
    assert "schedule:" not in workflow and crons(workflow) == ()
    assert "  push:\n" in workflow and "  workflow_dispatch:\n" in workflow


def test_s029_11_init_writes_no_soak_whatever_the_changelog_style(repo: Repo) -> None:
    repo.write("CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n## 1.0.0 - 2026-09-01\n\n- The first release\n")
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    raw = tomllib.loads((repo.root / CONFIG_PATH).read_text(encoding="utf-8"))
    assert raw["lanes"]["stable"] == {"quiet_minutes": 30, "github_release": True}


# -- listing (S-029-12) ----------------------------------------------------------------------


def test_s029_12_lists_the_upgrade_only_while_the_stable_lane_sets_min_soak_days(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    soaked = POLICY.replace("[changelog]\n", FRAGMENTS)
    write_config(repo.root, soaked)
    assert listed(repo.root, capsys) == ["stable-every-batch"]
    write_config(repo.root, soaked.replace("min_soak_days = 3", "min_soak_days = 0"))  # whatever its value
    assert listed(repo.root, capsys) == ["stable-every-batch"]
    write_config(repo.root, soaked.replace("min_soak_days = 3\n", ""))  # edited out by hand: decided
    assert listed(repo.root, capsys) == []
    no_stable = soaked.split("[lanes.stable]")[0] + "[lanes.hotfix]\n"
    write_config(repo.root, no_stable)
    assert listed(repo.root, capsys) == []


def test_s029_12_lists_for_people_what_it_removes_and_adds(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(repo.root, POLICY.replace("[changelog]\n", FRAGMENTS))
    assert main(["--repo", str(repo.root), "upgrade"], github=FakeGitHub()) == 0
    out = capsys.readouterr().out
    assert out.startswith("stable-every-batch (shipmill ")
    assert "  removes: [lanes.stable] min_soak_days\n" in out
    assert "  adds:" not in out  # the fixture's stable lane has a schedule
    assert "upgrade --apply stable-every-batch`" in out


def test_s029_12_the_text_for_people_and_the_decline(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(repo.root, POLICY.replace("[changelog]\n", FRAGMENTS))
    assert main(["--repo", str(repo.root), "upgrade", "--json"], github=FakeGitHub()) == 0
    (record,) = json.loads(capsys.readouterr().out)
    assert (record["table"], record["line"], record["removes"]) == (
        "lanes.stable",
        "quiet_minutes = 30",
        "min_soak_days",
    )
    assert record["changes"] == (
        "stable releases ship every batch of merges whose CI passed, instead of an rc three days old that"
        " nobody ran; a breaking change still waits for the maintainer's hand start; the rc lane stays for"
        " people who pin pre-releases and can be deleted along with promote_from when no milestone gates"
        " the stable lane"
    )
    text = body(UPGRADE)
    assert text.startswith(marker(UPGRADE) + "\n")
    assert "It deletes the `min_soak_days` line from `[lanes.stable]`" in text
    assert "the table sets none of `quiet_minutes`, `schedule`, `milestone`" in text
    assert "```toml\n[lanes.stable]\nquiet_minutes = 30\n```" in text
    assert (
        "close this issue: shipmill won't propose stable-every-batch again. The next minor release refuses"
        " `min_soak_days`, so a decline means deleting it from `[lanes.stable]` by hand before then."
    ) in text
    assert "closes it once `[lanes.stable]` no longer sets `min_soak_days`." in text


def test_s029_12_proposing_opens_one_issue_and_a_decided_config_closes_it(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    write_config(repo.root, POLICY.replace("[changelog]\n", FRAGMENTS))
    assert main(["--repo", str(repo.root), "upgrade", "--propose"], github=github) == 0
    [(number, issue)] = github.issues.items()
    assert capsys.readouterr().out == f"opened #{number}: stable-every-batch\n"
    assert github.labels[number] == (UPGRADE_LABEL,) and issue.title == "shipmill upgrade: turn on stable-every-batch"
    apply(repo.root)
    capsys.readouterr()
    assert main(["--repo", str(repo.root), "upgrade", "--propose"], github=github) == 0
    assert github.closed[number] == (
        "`[lanes.stable]` in `.github/shipmill.toml` no longer sets `min_soak_days`: stable-every-batch is"
        " decided, so this issue is done."
    )


def test_s029_12_a_closed_issue_declines_it(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    github = FakeGitHub()
    write_config(repo.root, POLICY.replace("[changelog]\n", FRAGMENTS))
    github.close_issue(github.create_issue("t", f"{marker(UPGRADE)}\n", (UPGRADE_LABEL,)), "")
    assert main(["--repo", str(repo.root), "upgrade", "--json"], github=github) == 0
    assert json.loads(capsys.readouterr().out) == []


# -- applying (S-029-12) ---------------------------------------------------------------------


def test_s029_12_apply_removes_the_line_and_keeps_promote_from_and_the_schedule(repo: Repo) -> None:
    path = write_config(repo.root, POLICY)
    before = path.read_bytes()
    apply(repo.root)
    after = path.read_bytes()
    assert after == before.replace(b"min_soak_days = 3\n", b"")
    stable = tomllib.loads(after.decode())["lanes"]["stable"]
    assert stable["promote_from"] == "rc" and stable["schedule"] == ["Mon 07:00 UTC"] and "quiet_minutes" not in stable
    assert Policy.load(path).rule(Lane.STABLE).min_soak_days == 0


SOAKED = """\
# the release policy  (two spaces, kept)
name = "demo"
mode = "release"
version_files = "none"

[changelog]
style = "keep-a-changelog"
fragments = "changelog.d"

[bump]
from = "headings"
minor = ["Added"]

[lanes.rc]                          # X.Y.ZrcN
schedule = ["Mon-Fri 07:00 UTC"]
github_release = true

# the stable lane, promoted from an rc
[lanes.stable]   # stable
promote_from = "rc"
min_soak_days = 3                   # three days, as init wrote it
{extra}
github_release = true

[lanes.hotfix]
github_release = true
"""


def test_s029_12_apply_adds_quiet_minutes_in_its_place_when_the_table_has_no_trigger(tmp_path: Path) -> None:
    text = SOAKED.format(extra="# no trigger: promoted by hand")
    path = write_config(tmp_path, text)
    apply(tmp_path)
    assert path.read_text(encoding="utf-8") == text.replace(
        "min_soak_days = 3                   # three days, as init wrote it\n", "quiet_minutes = 30\n"
    )
    assert Policy.load(path).rule(Lane.STABLE).quiet_minutes == 30


@pytest.mark.parametrize("trigger", ["quiet_minutes = 60", 'schedule = ["Mon 07:00 UTC"]', "milestone = true"])
def test_s029_12_apply_adds_no_trigger_beside_one(tmp_path: Path, trigger: str) -> None:
    text = SOAKED.format(extra=trigger)
    path = write_config(tmp_path, text)
    apply(tmp_path)
    assert path.read_text(encoding="utf-8") == text.replace(
        "min_soak_days = 3                   # three days, as init wrote it\n", ""
    )


def test_s029_12_apply_keeps_crlf_and_a_last_line_without_a_newline(tmp_path: Path) -> None:
    text = '[lanes.rc]\r\n\r\n[lanes.stable]\r\npromote_from = "rc"\r\nmin_soak_days = 2'
    path = write_config(tmp_path, text)
    apply(tmp_path)
    assert path.read_bytes() == b'[lanes.rc]\r\n\r\n[lanes.stable]\r\npromote_from = "rc"\r\nquiet_minutes = 30'


def test_s029_12_apply_prints_what_it_did(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(tmp_path, SOAKED.format(extra=""))
    apply(tmp_path)
    out = capsys.readouterr().out
    assert out.startswith(
        "removed min_soak_days from [lanes.stable] in .github/shipmill.toml\n"
        "added quiet_minutes = 30 to [lanes.stable] in .github/shipmill.toml\n"
    )
    write_config(tmp_path, SOAKED.format(extra="milestone = true"))
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "stable-every-batch", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert (record["line"], record["removed"]) == (None, "min_soak_days")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('[lanes.stable]\npromote_from = "rc"\n', "upgrade stable-every-batch doesn't apply: [lanes.stable] in"),
        ('lanes = "stable"\n', "lanes must be a table"),
        ('[lanes]\nstable = "x"\n', "lanes.stable must be a table"),
        ('[lanes]\nstable = { promote_from = "rc", min_soak_days = 3 }\n', "no [lanes.stable] header line"),
        ("[lanes]\nstable.min_soak_days = 3\n", "no [lanes.stable] header line"),
        ('[lanes.stable]\n"min_soak_days" = 3\n', "no min_soak_days line under [lanes.stable]"),
    ],
)
def test_s029_12_apply_refuses_a_table_it_cannot_edit_and_writes_nothing(tmp_path: Path, text: str, error: str) -> None:
    path = write_config(tmp_path, text)
    done = shipmill(tmp_path, "upgrade", "--apply", "stable-every-batch")
    assert done.returncode == 2
    assert error in done.stderr
    assert path.read_text(encoding="utf-8") == text
