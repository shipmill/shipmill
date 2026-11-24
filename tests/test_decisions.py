"""The decisions log script shared by github-issue-triage and github-pr-triage"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "decisions.py"


def decisions(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, check=False)


def add(cwd: Path, title: str, applies: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return decisions(
        cwd,
        "add",
        "--title", title,
        "--rule", f"{title}, always",
        "--why", "the user said so",
        "--applies", applies,
        "--enforced", "review",
        "--source", "romamo/demo#12",
        "--date", "2026-10-03",
        *extra,
    )  # fmt: skip


def test_add_creates_the_log_and_numbers_entries(tmp_path: Path) -> None:
    assert add(tmp_path, "Representation is --format", "src/cli/*, CLI flags").stdout == "D-1\n"
    assert add(tmp_path, "One handler catch", "src/handler.py").stdout == "D-2\n"
    log = (tmp_path / "docs" / "decisions.md").read_text()
    assert "## D-2: One handler catch\n\n- Decided: 2026-10-03, in romamo/demo#12\n" in log
    assert decisions(tmp_path, "check").returncode == 0


def test_supersede_links_both_ways_and_hides_the_old_rule(tmp_path: Path) -> None:
    add(tmp_path, "Old rule", "src/a.py")
    add(tmp_path, "Unrelated", "src/b.py")
    assert add(tmp_path, "New rule", "src/a.py", "--supersedes", "D-1").stdout == "D-3\n"
    log = (tmp_path / "docs" / "decisions.md").read_text()
    assert "- Enforced by: review\n- Superseded by: D-3\n\n## D-2" in log
    assert decisions(tmp_path, "check").returncode == 0
    assert decisions(tmp_path, "find", "src/a.py").stdout.startswith("D-3: New rule")
    assert "D-1" in decisions(tmp_path, "find", "--all", "src/a.py").stdout
    assert add(tmp_path, "Again", "src/a.py", "--supersedes", "D-1").returncode == 2


def test_find_matches_globs_prefixes_and_words(tmp_path: Path) -> None:
    add(tmp_path, "Flags", "src/cli/*, CLI flags")
    add(tmp_path, "Docs", "docs/")
    assert decisions(tmp_path, "find", "src/cli/main.py").stdout.startswith("D-1")
    assert decisions(tmp_path, "find", "docs/guide/intro.md").stdout.startswith("D-2")
    assert decisions(tmp_path, "find", "flags").stdout.startswith("D-1")
    assert decisions(tmp_path, "find", "src/other.py").returncode == 1


def test_check_reports_each_problem(tmp_path: Path) -> None:
    (tmp_path / "DECISIONS.md").write_text(
        "# Decisions\n\n## D-1: First\n\n- Decided: yesterday\n- Rule: r\n- Rule: again\n"
        "- Why: w\n- Applies to: x\n\n## D-3: Gap\n\n- Decided: 2026-10-03, in o/r#1\n- Rule: r\n"
        "- Why: w\n- Applies to: x\n- Enforced by: review\n- Supersedes: D-1\n## Notes\n"
    )
    out = decisions(tmp_path, "check")
    assert out.returncode == 1
    for problem in (
        "repeats 'Rule'",
        "D-1 (line 3): missing 'Enforced by'",
        "Decided must read",
        "expected D-2",
        "lacks 'Superseded by: D-3'",
        "a heading that isn't",
    ):
        assert problem in out.stdout, problem
    assert add(tmp_path, "Blocked", "x").returncode == 2


def test_no_log_is_an_input_error(tmp_path: Path) -> None:
    assert decisions(tmp_path, "check").returncode == 2


# -- zoned decisions (spec 030) -----------------------------------------------------------------


def zoned(cwd: Path, title: str, zone: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return add(cwd, title, "src/a.py", "--zone", zone, "--decided-at", "2026-10-03T14:00:00+02:00", *extra)


def test_s030_17_add_zone_writes_the_zone_line_and_check_accepts_it(tmp_path: Path) -> None:
    out = zoned(tmp_path, "Read S-001-2 as per item", "interpretation")
    assert (out.returncode, out.stdout) == (0, "D-1\n"), out.stderr
    log = (tmp_path / "docs" / "decisions.md").read_text()
    # veto_hours defaults to 24 without a config; the time is in UTC
    assert "- Enforced by: review\n- Zone: interpretation (notify, veto until 2026-10-04T12:00:00Z)\n" in log
    assert decisions(tmp_path, "check").returncode == 0


def test_s030_17_the_veto_window_is_the_configs_veto_hours(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    config = tmp_path / ".github" / "shipmill.toml"
    config.write_text('[decisions]\nveto_hours = 48\ncontract-addition = "act"\n', encoding="utf-8")
    assert zoned(tmp_path, "A reading", "interpretation").returncode == 0
    assert (
        "- Zone: interpretation (notify, veto until 2026-10-05T12:00:00Z)"
        in (tmp_path / "docs/decisions.md").read_text()
    )
    # a zone the config doesn't keep at notify carries no Zone line
    refused = zoned(tmp_path, "An addition", "contract-addition")
    assert refused.returncode == 2 and "at act" in refused.stderr
    assert zoned(tmp_path, "A scope call", "scope").returncode == 2
    assert zoned(tmp_path, "Nowhere", "release").returncode == 2  # no agent zone
    config.write_text('[decisions]\ndirection = "act"\n', encoding="utf-8")
    below = zoned(tmp_path, "Below the floor", "interpretation")
    assert below.returncode == 2 and "below its floor ask" in below.stderr


def test_s030_17_check_fails_a_zone_that_names_no_zone_id(tmp_path: Path) -> None:
    assert zoned(tmp_path, "A reading", "interpretation").returncode == 0
    log = tmp_path / "docs" / "decisions.md"
    log.write_text(log.read_text().replace("Zone: interpretation", "Zone: interpretations"))
    out = decisions(tmp_path, "check")
    assert out.returncode == 1
    assert "D-1 (line 7): Zone names no zone id 'interpretations'; zone ids: direction," in out.stdout
    log.write_text(log.read_text().replace("Zone: interpretations (notify, ", "Zone: interpretation (ask, "))
    assert "Zone must read" in decisions(tmp_path, "check").stdout


def test_s030_17_the_repos_own_log_passes_check() -> None:
    repo = Path(__file__).resolve().parents[1]
    assert decisions(repo, "check").returncode == 0


def test_s030_17_the_decisions_table_reads_the_same_without_tomllib(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("decisions_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    text = "[agents]\nmode = \"headless\"\n\n[decisions]  # levels\nveto_hours = 12\ntriage-verdict = 'ask'\n"
    path = tmp_path / "shipmill.toml"
    assert module.decisions_table_310(text, path) == {"veto_hours": 12, "triage-verdict": "ask"}
    path.write_text(text, encoding="utf-8")
    found = module.policy(path)
    assert (found.veto_hours, found.levels["triage-verdict"], found.levels["scope"]) == (12, "ask", "ask")
    for unreadable in ("[decisions]\nscope = { a = 1 }\n", 'decisions.scope = "ask"\n', "[decisions.sub]\n"):
        with pytest.raises(module.LogError, match=r"can't read \[decisions\] on Python 3.10"):
            module.decisions_table_310(unreadable, path)


def test_s030_17_the_310_reader_refuses_what_tomllib_refuses(tmp_path: Path) -> None:
    """An array of tables, a table declared twice, a spaced dotted subtable, and a leading-zero
    integer are invalid or no plain table to tomllib, so the 3.10 reader refuses them too"""
    spec = importlib.util.spec_from_file_location("decisions_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    path = tmp_path / "shipmill.toml"
    for unreadable in (
        '[[decisions]]\nscope = "ask"\n',
        '[decisions]\nscope = "ask"\n[agents]\n[decisions]\nsecurity = "ask"\n',
        '[ decisions . sub ]\nx = "ask"\n',
        "[decisions]\nveto_hours = 012\n",
    ):
        with pytest.raises(module.LogError, match=r"can't read \[decisions\] on Python 3.10"):
            module.decisions_table_310(unreadable, path)
    assert module.decisions_table_310("[ decisions ]\nveto_hours = 0\n", path) == {"veto_hours": 0}


def script_module() -> object:
    spec = importlib.util.spec_from_file_location("decisions_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EARNED = (
    '[decisions]\nclean_releases = 2\n\n[decisions.earned]\nprotected = "act"\nsecurity = "notify"\nmax_lines = 200\n'
)


def test_s083_2_policy_reads_earned_and_clean_releases_with_every_level_unchanged(tmp_path: Path) -> None:
    module: Any = script_module()
    path = tmp_path / "shipmill.toml"
    path.write_text(EARNED, encoding="utf-8")
    found = module.policy(path)
    assert found.levels == {zone: default for zone, (default, _) in module.ZONES.items()}
    assert (found.earned, found.max_lines, found.clean_releases) == ({"protected": "act", "security": "notify"}, 200, 2)
    path.write_text('[decisions]\nprotected = "notify"\n', encoding="utf-8")
    plain = module.policy(path)
    assert (plain.earned, plain.max_lines, plain.clean_releases) == (None, 200, 3)  # D-63: as before


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[decisions.earned]\nscope = "act"\n',
            "[decisions.earned] scope takes no earned level: only protected and security do",
        ),
        ('[decisions.earned]\nprotected = "maybe"\n', "[decisions.earned] protected = 'maybe': a level is one of"),
        ('[decisions.earned]\nsecurity = "act"\n', "[decisions.earned] security = 'act' is below its floor notify"),
        ("[decisions.earned]\nmax_lines = 0\n", "[decisions.earned] max_lines must be an integer from 1 to 10000"),
        ("[decisions.earned]\nmax_lines = 10001\n", "[decisions.earned] max_lines must be an integer from 1 to 10000"),
        ('[decisions.earned]\nmax_lines = "200"\n', "[decisions.earned] max_lines must be an integer from 1 to 10000"),
        ("[decisions]\nclean_releases = 0\n", "[decisions] clean_releases must be an integer from 1 to 20"),
        ("[decisions]\nclean_releases = 21\n", "[decisions] clean_releases must be an integer from 1 to 20"),
        ("[decisions]\nclean_releases = true\n", "[decisions] clean_releases must be an integer from 1 to 20"),
        ('[decisions]\nearned = "act"\n', "[decisions] earned must be a table"),
    ],
)
def test_s083_2_policy_refuses_each_malformed_value(tmp_path: Path, text: str, message: str) -> None:
    module: Any = script_module()
    path = tmp_path / "shipmill.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(module.LogError) as caught:
        module.policy(path)
    assert message in str(caught.value)


def test_s083_2_the_310_reader_asks_for_311_for_a_config_holding_earned(tmp_path: Path) -> None:
    """policy() reads [decisions] with decisions_table_310 on Python 3.10, which has no tomllib"""
    module: Any = script_module()
    path = tmp_path / "shipmill.toml"
    for text in (EARNED, '[decisions.earned]\nprotected = "act"\n', '[decisions]\nearned = { protected = "act" }\n'):
        with pytest.raises(module.LogError, match=r"can't read \[decisions\] on Python 3.10: use 3.11\+"):
            module.decisions_table_310(text, path)
    assert module.decisions_table_310("[decisions]\nclean_releases = 2\n", path) == {"clean_releases": 2}


def test_s083_3_the_script_lists_area_record_after_protected_at_act(tmp_path: Path) -> None:
    module: Any = script_module()
    zones = list(module.ZONES)
    assert zones[zones.index("protected") + 1] == "area-record"
    assert module.ZONES["area-record"] == ("act", None)
    path = tmp_path / "shipmill.toml"
    assert module.policy(path).levels["area-record"] == "act"  # no file
    path.write_text('[decisions]\nscope = "ask"\n', encoding="utf-8")
    assert module.policy(path).levels["area-record"] == "act"  # no key
    path.write_text('[decisions]\narea-record = "ask"\n', encoding="utf-8")
    assert module.policy(path).levels["area-record"] == "ask"
