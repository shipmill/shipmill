"""Spec 052: where a refused key shows. doctor's FAIL row named refused beside a PASS policy row
(S-052-8), status's FAIL row with the entry's fix (S-052-9), and the "refused" list of every
command whose --json prints an object (S-052-11). Each refused key alone, and both together"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shipmill import factory, refused
from shipmill.cli import _app_install, _parser, _refused_or_none, _status, main
from shipmill.doctor import REFUSED, Check, doctor
from shipmill.refused import MIN_SOAK_DAYS, PLUGIN_UPDATE, Refusal
from shipmill.status import Verdict, report

from . import test_app, test_app_install
from .conftest import POLICY, Repo, at_day
from .test_decide_cli import FakePulls, commit
from .test_milestone_status import on_github
from .test_refused import AGENTS, soaked
from .test_status_picture import NOW, Fake, facts, host, lines, repo_with_release

PLUGIN = "plugin_update = true\n"
BOTH = (MIN_SOAK_DAYS, PLUGIN_UPDATE)
# each refused key alone and both together, then the config each reads as without them
CASES = [
    pytest.param(soaked(), POLICY, (MIN_SOAK_DAYS,), id="min_soak_days"),
    pytest.param(POLICY + AGENTS + PLUGIN, POLICY + AGENTS, (PLUGIN_UPDATE,), id="plugin_update"),
    pytest.param(soaked() + AGENTS + PLUGIN, POLICY + AGENTS, BOTH, id="both"),
]
SOAK_ROW = "refused: [lanes.stable] min_soak_days was removed (spec 029); the stable lane is off"
PLUGIN_ROW = (
    "refused: [agents] plugin_update was removed (spec 031); it turns off nothing: gate sessions load the"
    " installed plugin"
)


def fail_rows(refusals: tuple[Refusal, ...]) -> list[str]:
    """status's FAIL row for each refusal, then its fix, aligned under the row's value"""
    return [line for r in refusals for line in (f"  {'FAIL':<14} refused: {r.what}", f"  {'':<14} fix: {r.fix}")]


# -- S-052-8: doctor -----------------------------------------------------------------------------


@pytest.mark.parametrize(("config", "without", "refusals"), CASES)
def test_s052_8_doctor_prints_a_refused_fail_row_a_pass_policy_row_and_every_other_check(
    repo: Repo, config: str, without: str, refusals: tuple[Refusal, ...]
) -> None:
    repo.write(repo.policy_file, without)
    before = doctor(repo.root, repo.github)
    repo.write(repo.policy_file, config)
    after = doctor(repo.root, repo.github)
    assert [c for c in after if c.name == REFUSED] == [Check("FAIL", REFUSED, r.message) for r in refusals]
    assert [c.status for c in after if c.name == "policy"] == ["PASS"]
    assert after[1 : 1 + len(refusals)] == [c for c in after if c.name == REFUSED]  # right after the policy row
    # every other check still runs, as without the key, save the upgrade that takes min_soak_days out
    offered = [c for c in after if c.name != REFUSED and c not in before]
    assert all("stable-every-batch" in c.detail for c in offered), offered
    assert [c for c in before if c not in after] == []


def test_s052_8_the_rows_messages_are_the_catalogues(repo: Repo) -> None:
    repo.write(repo.policy_file, soaked() + AGENTS + PLUGIN)
    rows = [f"{c.status} {c.name}: {c.detail}" for c in doctor(repo.root, repo.github) if c.name == REFUSED]
    assert rows == [f"FAIL refused: {MIN_SOAK_DAYS.message}", f"FAIL refused: {PLUGIN_UPDATE.message}"]


def test_s052_8_a_config_without_a_refused_key_has_no_refused_row(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    assert [c for c in doctor(repo.root, repo.github) if c.name == REFUSED] == []


# -- S-052-9: status ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "refusals", [(MIN_SOAK_DAYS,), (PLUGIN_UPDATE,), BOTH], ids=["min_soak_days", "plugin", "both"]
)
def test_s052_9_status_prints_a_fail_row_for_each_refused_key_with_its_fix(refusals: tuple[Refusal, ...]) -> None:
    shown, plain = lines(facts(refused=refusals)), lines(facts())
    rows = fail_rows(refusals)
    assert [line for line in shown if line not in plain] == rows
    assert [line for line in shown if line not in rows] == plain  # the rest of the picture as without it
    assert report(facts(refused=refusals)).verdict is report(facts()).verdict is Verdict.IDLE


def test_s052_9_the_rows_read_as_the_catalogue_says() -> None:
    assert (MIN_SOAK_DAYS.what, PLUGIN_UPDATE.what) == (
        SOAK_ROW.removeprefix("refused: "),
        PLUGIN_ROW.removeprefix("refused: "),
    )
    assert fail_rows(BOTH) == [
        f"  FAIL           {SOAK_ROW}",
        "                 fix: delete it, or run shipmill upgrade --apply stable-every-batch",
        f"  FAIL           {PLUGIN_ROW}",
        "                 fix: delete it",
    ]


@pytest.mark.parametrize(("config", "without", "refusals"), CASES)
def test_s052_9_status_reads_the_refused_keys_of_the_checkouts_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, without: str, refusals: tuple[Refusal, ...]
) -> None:
    root = repo_with_release(tmp_path / "repo")
    (root / ".github").mkdir()

    def picture(text: str) -> tuple[int, str]:
        (root / ".github" / "shipmill.toml").write_text(text, encoding="utf-8")
        args = _parser().parse_args(["--repo", str(root), "status"])
        api, signer = test_app.FakeApi(), test_app.FakeSigner()
        code = _status(root, args, Fake(0), api, signer, host, home=tmp_path / "home", platform="linux", now=NOW)
        return code, capsys.readouterr().out

    code, plain = picture(without)
    assert "  FAIL " not in plain
    found, shown = picture(config)
    assert found == code
    rows = fail_rows(refusals)
    printed = shown.splitlines()
    at = printed.index(rows[0])
    assert printed[at : at + len(rows)] == rows


# -- S-052-11: the "refused" list of each --json object ------------------------------------------

Runner = Callable[[Repo, pytest.CaptureFixture[str], Path], dict[str, Any]]


def printed(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def decide_levels(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "decide", "levels", "--json"]) == 0
    return printed(capsys)


def decide_classify(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    argv = ["--repo", str(repo.root), "decide", "classify", "--files", "src/x.py", "--json"]
    assert main(argv, pulls=FakePulls()) == 0  # the levels, and the refusals, of the config at origin/HEAD
    return printed(capsys)


def autonomy(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "autonomy", "--json"], github=repo.github) == 0
    return printed(capsys)


def roles(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "roles", "--json"], login=host) == 0
    return printed(capsys)


def milestones(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    argv = ["--repo", str(repo.root), "milestones", "--now", at_day(5).isoformat(), "--json"]
    assert main(argv, github=repo.github) == 0
    return printed(capsys)


def app_install(repo: Repo, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> dict[str, Any]:
    key = tmp_path / "app.pem"
    key.write_text("not a real key\n", encoding="utf-8")
    key.chmod(0o600)
    args = test_app_install.args(repos=["acme/web"], app_key=key, json=True)
    app = test_app_install.FakeApp(covered={"acme/web"})
    assert _app_install(repo.root, args, app, test_app_install.FakeSigner(), out=None) == 0
    return printed(capsys)


COMMANDS: list[Runner] = [decide_levels, decide_classify, autonomy, roles, milestones, app_install]


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.__name__)
@pytest.mark.parametrize(("config", "without", "refusals"), CASES)
def test_s052_11_each_json_object_lists_the_refused_keys_and_none_without_one(
    repo: Repo,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: Runner,
    config: str,
    without: str,
    refusals: tuple[Refusal, ...],
) -> None:
    on_github(repo)  # milestones reads a GitHub origin; the others don't mind
    commit(repo, without)  # decide classify and autonomy read the config at origin/HEAD
    plain = command(repo, capsys, tmp_path)
    assert plain["refused"] == []
    commit(repo, config)
    found = command(repo, capsys, tmp_path)
    assert found["refused"] == [r.record() for r in refusals]
    assert found | {"refused": []} == plain  # additive: every other key as without the refused key


def test_s052_11_a_refusal_is_its_key_spec_what_it_turns_off_and_fix() -> None:
    assert refused.records(BOTH) == [
        {
            "key": "[lanes.stable] min_soak_days",
            "spec": "029",
            "off": "the stable lane",
            "fix": "delete it, or run shipmill upgrade --apply stable-every-batch",
        },
        {
            "key": "[agents] plugin_update",
            "spec": "031",
            "off": "nothing: gate sessions load the installed plugin",
            "fix": "delete it",
        },
    ]


@pytest.mark.parametrize(("config", "without", "refusals"), CASES)
def test_s052_11_factory_and_gate_json_list_the_checkouts_refused_keys(
    repo: Repo, config: str, without: str, refusals: tuple[Refusal, ...]
) -> None:
    repo.write(repo.policy_file, without)
    assert _refused_or_none(repo.root) == ()
    assert json.loads(factory.as_json([], _refused_or_none(repo.root))) == {"checks": [], "refused": []}
    repo.write(repo.policy_file, config)
    assert _refused_or_none(repo.root) == refusals
    found = json.loads(factory.as_json([], _refused_or_none(repo.root)))
    assert found == {"checks": [], "refused": [r.record() for r in refusals]}


def test_s052_11_factory_and_gate_json_list_none_for_a_config_they_cant_read(repo: Repo) -> None:
    # their own record names the config they can't read: the list is empty, never an exit 2 before it
    repo.write(repo.policy_file, "[lanes.stable\n")
    assert _refused_or_none(repo.root) == ()
    assert _refused_or_none(repo.root / "no-such-checkout") == ()


def test_s052_11_upgrade_apply_json_lists_what_the_edited_config_still_refuses(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    apply = ["--repo", str(repo.root), "upgrade", "--apply", "stable-every-batch", "--json"]
    repo.write(repo.policy_file, soaked() + AGENTS + PLUGIN)
    assert main(apply) == 0
    assert printed(capsys)["refused"] == [PLUGIN_UPDATE.record()]  # min_soak_days is gone, plugin_update not
    repo.write(repo.policy_file, soaked())
    assert main(apply) == 0
    assert printed(capsys)["refused"] == []


def test_s052_11_a_json_list_stays_a_list(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.write(repo.policy_file, soaked() + AGENTS + PLUGIN)
    assert main(["--repo", str(repo.root), "upgrade", "--json"], github=repo.github) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_s052_11_found_reads_the_raw_tables_and_skips_one_that_isnt_a_table() -> None:
    assert refused.found({"lanes": {"stable": {"min_soak_days": 3}}, "agents": {"plugin_update": False}}) == BOTH
    assert refused.found({"lanes": {"stable": {"min_soak_day": 3}}, "agents": {}}) == ()
    assert refused.found({"lanes": {"stable": 3}, "agents": "x"}) == ()
    assert refused.found({"lanes": {"rc": {"min_soak_days": 3}}}) == ()  # only the table the entry names
