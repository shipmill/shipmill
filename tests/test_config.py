# ruff: noqa: E501 (each message is pinned whole, as the user reads it)
"""Every refusal of the config file, byte for byte: each section is read through one
strict Table, and these messages are what a user sees when their config is wrong"""

import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig
from shipmill.config import Table
from shipmill.errors import ReleaseError
from shipmill.policy import HooksConfig, NoticesConfig, Policy

from .conftest import POLICY

TOP = 'name = "demo"\n'
CHANGELOG = '[changelog]\nstyle = "keep-a-changelog"\n'
BUMP = '[bump]\nfrom = "headings"\n'
HEADINGS = 'major = ["Breaking"]\nminor = ["Added", "Changed"]\npatch = ["Fixed"]\n'
VERSION_LINE = '[[version_lines]]\nfile = "README.md"\npattern = \'demo \\S+$\'\nreplace = "demo {version}"\n'
STAGING = '\n[environments.staging]\nlane = "rc"\nworkflow = "deploy.yml"\n'

type Change = tuple[str, str]  # (old, new): replace old, which occurs once; an empty old appends new


def top(line: str) -> list[Change]:
    return [(TOP, TOP + line + "\n")]


def add(text: str) -> list[Change]:
    return [("", text)]


def apply(text: str, changes: list[Change]) -> str:
    for old, new in changes:
        if old:
            assert text.count(old) == 1, old
            text = text.replace(old, new)
        else:
            text += new
    return text


CASES: dict[str, list[Change]] = {
    # the top level
    "top unknown key": top("colour = 1"),
    "top name required": [(TOP, "")],
    "top name a string": [(TOP, "name = 1\n")],
    "top mode enum": [('mode = "release"', 'mode = "on"')],
    "top version_files enum": [('version_files = "pyproject"', 'version_files = "setup"')],
    "top after_stamp a list": top('after_stamp = "x"'),
    "top after_stamp non-empty strings": top('after_stamp = [""]'),
    "top after_stamp empty command": top('after_stamp = ["  "]'),
    # [changelog]
    "changelog unknown key": [(CHANGELOG, CHANGELOG + "colour = 1\n")],
    "changelog fragments a string": [(CHANGELOG, CHANGELOG + "fragments = 1\n")],
    "changelog fragments absolute": [(CHANGELOG, CHANGELOG + 'fragments = "/tmp/changelog.d"\n')],
    "changelog fragments outside": [(CHANGELOG, CHANGELOG + 'fragments = "../changelog.d"\n')],
    "changelog fragments trailing slash": [(CHANGELOG, CHANGELOG + 'fragments = "changelog.d/"\n')],
    "changelog fragments empty": [(CHANGELOG, CHANGELOG + 'fragments = ""\n')],
    "changelog style enum": [('style = "keep-a-changelog"', 'style = "plain"')],
    "changelog required": [(CHANGELOG, "")],
    "changelog a table": [(CHANGELOG, ""), (TOP, TOP + "changelog = 1\n")],
    "changelog path a string": [(CHANGELOG, CHANGELOG + "path = 1\n")],
    # [bump]
    "bump unknown key": [(BUMP, BUMP + "colour = 1\n")],
    "bump from enum": [('from = "headings"', 'from = "titles"')],
    "bump heading twice": [('patch = ["Fixed"]', 'patch = ["Added"]')],
    "bump no headings": [(HEADINGS, "")],
    "bump headings a list": [('patch = ["Fixed"]', 'patch = "Fixed"')],
    "bump paths unknown key": [('from = "headings"', 'from = "paths"\nminor_paths = ["src"]')],
    "bump paths required": [('from = "headings"', 'from = "paths"'), (HEADINGS, "")],
    "bump paths empty": [('from = "headings"', 'from = "paths"\nminor_paths = []'), (HEADINGS, "")],
    # [gates]
    "gates unknown key": add("\n[gates]\ncolour = 1\n"),
    "gates blocker_lanes enums": add('\n[gates]\nblocker_lanes = ["beta"]\n'),
    "gates freeze strings": add("\n[gates]\nfreeze = 1\n"),
    "gates a table": top("gates = 1"),
    # [publish], [bot]
    "publish unknown key": add("\n[publish]\ncolour = 1\n"),
    "publish tag_message a string": add("\n[publish]\ntag_message = 1\n"),
    "bot unknown key": add("\n[bot]\ncolour = 1\n"),
    "bot email a string": add("\n[bot]\nemail = 1\n"),
    # [lanes]
    "lanes unknown lane": [("[lanes.dev]", "[lanes.beta]")],
    "lanes stable promotes without rc": [('[lanes.rc]\nschedule = ["daily 07:00 UTC"]\ngithub_release = true\n', "")],
    "lanes none": [(POLICY[POLICY.index("[lanes.dev]") : POLICY.index("[[version_lines]]")], "[lanes]\n\n")],
    "lane hotfix unknown key": [("[lanes.hotfix]\n", "[lanes.hotfix]\nschedule = ['Mon 07:00 UTC']\n")],
    "lane dev unknown key": [("quiet_minutes = 30", "quiet_minutes = 30\nmarker = 'a'")],
    "lane quiet range": [("quiet_minutes = 30", "quiet_minutes = 301")],
    "lane quiet not a bool": [("quiet_minutes = 30", "quiet_minutes = true")],
    "lane promote_from": [('promote_from = "rc"', 'promote_from = "dev"')],
    "lane soak removed": [('promote_from = "rc"\n', 'promote_from = "rc"\nmin_soak_days = 3\n')],
    "lane marker": [("[lanes.rc]\n", "[lanes.rc]\nmarker = 'c'\n")],
    "lane dispatch": [('dispatch = ["publish.yml"]', 'dispatch = ["../x.yml"]')],
    "lane milestone a bool": [("quiet_minutes = 30", "quiet_minutes = 30\nmilestone = 1")],
    "lane a table": [("[lanes.dev]\nquiet_minutes = 30\n", ""), ("[lanes.rc]\n", "[lanes]\ndev = 1\n\n[lanes.rc]\n")],
    # [[version_lines]]
    "version_lines unknown key": [(VERSION_LINE, VERSION_LINE + "colour = 1\n")],
    "version_lines pattern": [("pattern = 'demo \\S+$'", "pattern = 'demo ('")],
    "version_lines array of tables": [(VERSION_LINE, ""), (TOP, TOP + "version_lines = [1]\n")],
    # [environments]
    "environments unknown key": add(STAGING + 'region = "eu"\n'),
    "environments a table": add("\n[environments]\nstaging = 1\n"),
    "environments the section a table": top("environments = 1"),
    # [operate]
    "operate unknown key": add(STAGING + "\n[operate]\nrollback = 3\n"),
    "operate range": add(STAGING + "\n[operate]\nrollback_after = 0\n"),
    "operate integer": add(STAGING + '\n[operate]\nrollback_after = "3"\n'),
    "operate empty label": add(STAGING + '\n[operate]\nincident_label = " "\n'),
    "operate a table": top("operate = 1"),
    # [autonomy]
    "autonomy unknown key": add('\n[autonomy]\nreleases = "act"\n'),
    "autonomy level": add('\n[autonomy]\nrelease = "auto"\n'),
    "autonomy level a string": add("\n[autonomy]\nrollback = true\n"),
    "autonomy deploy a table": add('\n[autonomy]\ndeploy = "propose"\n'),
    "autonomy deploy level": add(STAGING + '\n[autonomy]\ndeploy.staging = "yes"\n'),
    "autonomy deploy environment name": add('\n[autonomy]\ndeploy."pro duction" = "act"\n'),
    "autonomy deploy unknown environment": add(STAGING + '\n[autonomy]\ndeploy.qa = "act"\n'),
    "autonomy a table": top("autonomy = 1"),
    # [agents]
    "agents unknown key": add('\n[agents]\nprompt = "/t"\nwhen = 1\n'),
    "agents prompt required": add("\n[agents]\nprs = true\n"),
    "agents prompt empty": add('\n[agents]\nprompt = "  "\n'),
    "agents retry range": add('\n[agents]\nprompt = "/t"\nretry_hours = 0\n'),
    "agents prs a bool": add('\n[agents]\nprompt = "/t"\nprs = "yes"\n'),
    "agents a table": top("agents = 1"),
    # [roadmap]
    "roadmap unknown key": add("\n[roadmap]\nwip = 3\nvelocity = 2\n"),
    "roadmap wip range": add("\n[roadmap]\nwip = 0\n"),
    "roadmap cadence an integer": add('\n[roadmap]\ncadence = "2w"\n'),
    "roadmap cadence range": add("\n[roadmap]\ncadence = 27\n"),
    "roadmap a table": top("roadmap = 1"),
    # [notices]
    "notices unknown key": add("\n[notices]\nupgrade = 'uv add -U demo'\n"),
    "notices a string": add("\n[notices]\npin = 1\n"),
    "notices empty": add("\n[notices]\ninstall = ' '\n"),
    "notices placeholder": add("\n[notices]\npin = \"uv add 'demo=={semver}'\"\n"),
    "notices a table": top("notices = 1"),
    # [hooks]
    "hooks unknown key": add("\n[hooks]\nforce_push = false\n"),
    "hooks default_branch a bool": add('\n[hooks]\ndefault_branch = "false"\n'),
    "hooks default_branch not an integer": add("\n[hooks]\ndefault_branch = 0\n"),
    "hooks private a list": add('\n[hooks]\nprivate = "owner/**"\n'),
    "hooks private strings": add('\n[hooks]\nprivate = ["owner/**", 1]\n'),
    "hooks private non-empty": add('\n[hooks]\nprivate = [""]\n'),
    "hooks a table": top("hooks = 1"),
}


MESSAGES: dict[str, str] = {
    "top unknown key": "shipmill.toml: unknown keys ['colour']; allowed: ['after_stamp', 'agents', 'autonomy', 'bot', 'branch', 'bump', 'changelog', 'downstream', 'environments', 'gates', 'hooks', 'lanes', 'mode', 'name', 'notices', 'operate', 'publish', 'roadmap', 'version_files', 'version_lines']",
    "top name required": "shipmill.toml: name is required",
    "top name a string": "shipmill.toml: name must be a string, got 1",
    "top mode enum": "shipmill.toml: mode must be one of ['off', 'dry-run', 'release'], got 'on'",
    "top version_files enum": "shipmill.toml: version_files must be one of ['pyproject', 'none'], got 'setup'",
    "top after_stamp a list": "shipmill.toml: after_stamp must be a list of strings, got 'x'",
    "top after_stamp non-empty strings": "shipmill.toml: after_stamp must be a list of non-empty strings",
    "top after_stamp empty command": "shipmill.toml: after_stamp holds an empty command",
    "changelog unknown key": "shipmill.toml [changelog]: unknown keys ['colour']; allowed: ['fragments', 'path', 'style']",
    "changelog fragments a string": "shipmill.toml [changelog]: fragments must be a string, got 1",
    "changelog fragments absolute": "shipmill.toml [changelog]: fragments is a folder relative to the repo root, such as 'changelog.d'; got '/tmp/changelog.d'",
    "changelog fragments outside": "shipmill.toml [changelog]: fragments is a folder relative to the repo root, such as 'changelog.d'; got '../changelog.d'",
    "changelog fragments trailing slash": "shipmill.toml [changelog]: fragments is a folder relative to the repo root, such as 'changelog.d'; got 'changelog.d/'",
    "changelog fragments empty": "shipmill.toml [changelog]: fragments is a folder relative to the repo root, such as 'changelog.d'; got ''",
    "changelog style enum": "shipmill.toml [changelog]: style must be one of ['keep-a-changelog', 'dash'], got 'plain'",
    "changelog required": "shipmill.toml: changelog is required",
    "changelog a table": "shipmill.toml: changelog must be a table, got 1",
    "changelog path a string": "shipmill.toml [changelog]: path must be a string, got 1",
    "bump unknown key": "shipmill.toml [bump]: unknown keys ['colour']; allowed: ['from', 'major', 'minor', 'patch']",
    "bump from enum": "shipmill.toml [bump]: from must be one of ['headings', 'paths'], got 'titles'",
    "bump heading twice": "shipmill.toml: [bump] lists heading 'Added' twice",
    "bump no headings": "shipmill.toml: [bump] from = 'headings' needs major, minor, or patch lists",
    "bump headings a list": "shipmill.toml [bump]: patch must be a list of strings, got 'Fixed'",
    "bump paths unknown key": "shipmill.toml [bump]: unknown keys ['major', 'minor', 'patch']; allowed: ['from', 'minor_paths']",
    "bump paths required": "shipmill.toml [bump]: minor_paths is required",
    "bump paths empty": "shipmill.toml: [bump] from = 'paths' needs a non-empty minor_paths",
    "gates unknown key": "shipmill.toml [gates]: unknown keys ['colour']; allowed: ['blocker_label', 'blocker_lanes', 'freeze', 'freeze_lanes']",
    "gates blocker_lanes enums": "shipmill.toml [gates]: blocker_lanes holds values outside ['dev', 'rc', 'stable', 'hotfix']",
    "gates freeze strings": "shipmill.toml [gates]: freeze must be a list of strings, got 1",
    "gates a table": "shipmill.toml: gates must be a table, got 1",
    "publish unknown key": "shipmill.toml [publish]: unknown keys ['colour']; allowed: ['release_title', 'tag_message']",
    "publish tag_message a string": "shipmill.toml [publish]: tag_message must be a string, got 1",
    "bot unknown key": "shipmill.toml [bot]: unknown keys ['colour']; allowed: ['email', 'name']",
    "bot email a string": "shipmill.toml [bot]: email must be a string, got 1",
    "lanes unknown lane": "shipmill.toml [lanes]: unknown keys ['beta']; allowed: ['dev', 'hotfix', 'rc', 'stable']",
    "lanes stable promotes without rc": "shipmill.toml: lanes.stable promotes from rc, but lanes.rc is not enabled",
    "lanes none": "shipmill.toml: [lanes] enables no lane",
    "lane hotfix unknown key": "shipmill.toml [lanes] [hotfix]: unknown keys ['schedule']; allowed: ['dispatch', 'github_release']",
    "lane dev unknown key": "shipmill.toml [lanes] [dev]: unknown keys ['marker']; allowed: ['dispatch', 'github_release', 'milestone', 'quiet_minutes', 'schedule']",
    "lane quiet range": "shipmill.toml [lanes] [dev]: quiet_minutes must be in 0..300, got 301",
    "lane quiet not a bool": "shipmill.toml [lanes] [dev]: quiet_minutes must be an integer, got True",
    "lane promote_from": "shipmill.toml [lanes] [stable]: promote_from is 'rc' or absent, got 'dev'",
    "lane soak removed": (
        "[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply"
        " stable-every-batch"
    ),
    "lane marker": "shipmill.toml [lanes] [rc]: marker is a, b, or rc, got 'c'",
    "lane dispatch": "shipmill.toml [lanes] [stable]: dispatch names a file in .github/workflows, got '../x.yml'",
    "lane milestone a bool": "shipmill.toml [lanes] [dev]: milestone must be true or false, got 1",
    "lane a table": "shipmill.toml [lanes]: dev must be a table, got 1",
    "version_lines unknown key": "shipmill.toml [[version_lines]][0]: unknown keys ['colour']; allowed: ['file', 'pattern', 'replace']",
    "version_lines pattern": "shipmill.toml [[version_lines]][0].pattern: missing ), unterminated subpattern at position 5",
    "version_lines array of tables": "shipmill.toml: version_lines must be an array of tables, [[version_lines]]",
    "environments unknown key": "shipmill.toml [environments] [staging]: unknown keys ['region']; allowed: ['bake_minutes', 'from', 'health', 'lane', 'workflow']",
    "environments a table": "shipmill.toml [environments]: staging must be a table, got 1",
    "environments the section a table": "shipmill.toml: environments must be a table, got 1",
    "operate unknown key": "shipmill.toml [operate]: unknown keys ['rollback']; allowed: ['incident_label', 'rollback_after']",
    "operate range": "shipmill.toml [operate]: rollback_after must be in 1..20, got 0",
    "operate integer": "shipmill.toml [operate]: rollback_after must be an integer, got '3'",
    "operate empty label": "shipmill.toml [operate]: incident_label must not be empty",
    "operate a table": "shipmill.toml: operate must be a table, got 1",
    "autonomy unknown key": "shipmill.toml [autonomy]: unknown keys ['releases']; allowed: ['deploy', 'intake', 'release', 'rollback', 'upgrade']",
    "autonomy level": "shipmill.toml [autonomy]: release must be one of ['observe', 'propose', 'act'], got 'auto'",
    "autonomy level a string": "shipmill.toml [autonomy]: rollback must be one of ['observe', 'propose', 'act'], got True",
    "autonomy deploy a table": "shipmill.toml [autonomy]: deploy is a table of environments, such as deploy.production = 'propose'",
    "autonomy deploy level": "shipmill.toml [autonomy] [deploy]: staging must be one of ['observe', 'propose', 'act'], got 'yes'",
    "autonomy deploy environment name": "an environment name is letters, digits, '.', '_', or '-'; got 'pro duction'",
    "autonomy deploy unknown environment": "shipmill.toml [autonomy]: deploy.qa names no environment in [environments]; known: staging",
    "autonomy a table": "shipmill.toml: autonomy must be a table, got 1",
    "agents unknown key": "shipmill.toml [agents]: unknown keys ['when']; allowed: ['app_id', 'max_wait_minutes', 'mode', 'notify', 'plugin_update', 'prompt', 'prs', 'remind_hours', 'retry_hours', 'wip']",
    "agents prompt required": "shipmill.toml [agents]: prompt is required",
    "agents prompt empty": "shipmill.toml [agents]: prompt must not be empty",
    "agents retry range": "shipmill.toml [agents]: retry_hours must be in 1..168, got 0",
    "agents prs a bool": "shipmill.toml [agents]: prs must be true or false, got 'yes'",
    "agents a table": "shipmill.toml: agents must be a table, got 1",
    "roadmap unknown key": "shipmill.toml [roadmap]: unknown keys ['velocity']; allowed: ['cadence', 'wip']",
    "roadmap wip range": "shipmill.toml [roadmap]: wip must be in 1..100, got 0",
    "roadmap cadence an integer": "shipmill.toml [roadmap]: cadence must be an integer, got '2w'",
    "roadmap cadence range": "shipmill.toml [roadmap]: cadence must be in 1..26, got 27",
    "roadmap a table": "shipmill.toml: roadmap must be a table, got 1",
    "notices unknown key": "shipmill.toml [notices]: unknown keys ['upgrade']; allowed: ['install', 'pin']",
    "notices a string": "shipmill.toml [notices]: pin must be a string, got 1",
    "notices empty": "shipmill.toml [notices]: install must not be empty",
    "notices placeholder": "shipmill.toml [notices]: pin takes {version}, {tag}, and {name}; got ['semver']",
    "notices a table": "shipmill.toml: notices must be a table, got 1",
    "hooks unknown key": "shipmill.toml [hooks]: unknown keys ['force_push']; allowed: ['default_branch', 'private']",
    "hooks default_branch a bool": "shipmill.toml [hooks]: default_branch must be true or false, got 'false'",
    "hooks default_branch not an integer": "shipmill.toml [hooks]: default_branch must be true or false, got 0",
    "hooks private a list": "shipmill.toml [hooks]: private must be a list of strings, got 'owner/**'",
    "hooks private strings": "shipmill.toml [hooks]: private must be a list of non-empty strings",
    "hooks private non-empty": "shipmill.toml [hooks]: private must be a list of non-empty strings",
    "hooks a table": "shipmill.toml: hooks must be a table, got 1",
}


def test_each_case_has_its_message() -> None:
    assert CASES.keys() == MESSAGES.keys()


@pytest.mark.parametrize("name", CASES)
def test_the_config_refuses_with_the_same_words(name: str) -> None:
    with pytest.raises(ReleaseError) as caught:
        Policy.parse(tomllib.loads(apply(POLICY, CASES[name])), "shipmill.toml")
    assert str(caught.value) == MESSAGES[name]


def refusal(load: Callable[[], object]) -> str:
    with pytest.raises(ReleaseError) as caught:
        load()
    return str(caught.value)


def test_the_file_is_read_with_the_same_words(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "shipmill.toml"
    assert refusal(lambda: Policy.load(path)) == f"no release policy at {path}"
    path.parent.mkdir()
    path.write_text("name demo\n", encoding="utf-8")
    assert (
        refusal(lambda: Policy.load(path))
        == f"{path}: Expected '=' after a key in a key/value pair (at line 1, column 6)"
    )


def test_the_agents_section_alone_is_read_with_the_same_words(tmp_path: Path) -> None:
    assert refusal(lambda: AgentsConfig.load(tmp_path)) == (
        f"no .github/shipmill.toml in {tmp_path}; add an [agents] section with a prompt to use the gate"
    )
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text("name demo\n", encoding="utf-8")
    assert refusal(lambda: AgentsConfig.load(tmp_path)) == (
        f"{path}: Expected '=' after a key in a key/value pair (at line 1, column 6)"
    )
    path.write_text('name = "demo"\n', encoding="utf-8")
    assert refusal(lambda: AgentsConfig.load(tmp_path)) == (
        f"{path} has no [agents] section; add one with a prompt to use the gate"
    )
    path.write_text("agents = 1\n", encoding="utf-8")
    assert refusal(lambda: AgentsConfig.load(tmp_path)) == "shipmill.toml: agents must be a table, got 1"
    path.write_text('[agents]\nprompt = "/t"\nwhen = 1\n', encoding="utf-8")
    assert refusal(lambda: AgentsConfig.load(tmp_path)) == (
        "shipmill.toml [agents]: unknown keys ['when']; allowed: ['app_id', 'max_wait_minutes', 'mode', 'notify', 'plugin_update', 'prompt', 'prs', 'remind_hours', 'retry_hours', 'wip']"
    )


def agents(text: str) -> AgentsConfig:
    return AgentsConfig.parse(Table(tomllib.loads('[agents]\nprompt = "/t"\n' + text), "shipmill.toml").table("agents"))


def test_s003_1_the_wait_keys_default_and_read_what_is_given() -> None:
    omitted = agents("")
    assert (omitted.notify, omitted.remind_hours, omitted.max_wait_minutes) == (True, 4, 15)
    given = agents("notify = false\nremind_hours = 1\nmax_wait_minutes = 10080\n")
    assert (given.notify, given.remind_hours, given.max_wait_minutes) == (False, 1, 10080)
    edges = agents("notify = true\nremind_hours = 168\nmax_wait_minutes = 0\n")
    assert (edges.notify, edges.remind_hours, edges.max_wait_minutes) == (True, 168, 0)
    assert agents("remind_hours = 24\nmax_wait_minutes = 120\n").remind_hours == 24  # larger than the stop is allowed


def test_the_wip_limit_is_read_from_agents_and_is_none_when_omitted() -> None:
    """D-32 (#377): the work-in-progress limit triage reads is [agents] wip, 1..100"""
    assert agents("").wip is None
    assert (agents("wip = 1\n").wip, agents("wip = 100\n").wip) == (1, 100)


@pytest.mark.parametrize(
    ("line", "refused"),
    [
        ("wip = 0", "wip must be in 1..100, got 0"),
        ("wip = 101", "wip must be in 1..100, got 101"),
        ('wip = "3"', "wip must be an integer, got '3'"),
        ("wip = true", "wip must be an integer, got True"),
    ],
)
def test_a_bad_wip_limit_is_refused_naming_it(line: str, refused: str) -> None:
    assert refusal(lambda: agents(line + "\n")) == f"shipmill.toml [agents]: {refused}"


def test_no_doc_or_skill_still_names_the_removed_roadmap_plan() -> None:
    """D-32 (#377): outside the history (CHANGELOG, fragments, decisions), nothing points at
    roadmap_state.py or a [roadmap] wip limit"""
    root = Path(__file__).resolve().parents[1]
    history = {root / "CHANGELOG.md", root / "docs" / "decisions.md"}
    found = [
        f"{path.relative_to(root)}: {stale}"
        for folder in ("docs", "skills", "src", ".claude-plugin")
        for path in sorted((root / folder).rglob("*"))
        if path.is_file() and path.suffix in {".md", ".py", ".json", ".toml"} and path not in history
        for stale in ("roadmap_state", "[roadmap] wip")
        if stale in path.read_text(encoding="utf-8")
    ]
    assert found == []


WAIT_REFUSALS = {
    "notify = 1": "notify must be true or false, got 1",
    'notify = "yes"': "notify must be true or false, got 'yes'",
    "remind_hours = 0": "remind_hours must be in 1..168, got 0",
    "remind_hours = 169": "remind_hours must be in 1..168, got 169",
    "remind_hours = true": "remind_hours must be an integer, got True",
    "remind_hours = 1.5": "remind_hours must be an integer, got 1.5",
    "max_wait_minutes = -1": "max_wait_minutes must be in 0..10080, got -1",
    "max_wait_minutes = 10081": "max_wait_minutes must be in 0..10080, got 10081",
    "max_wait_minutes = false": "max_wait_minutes must be an integer, got False",
    'max_wait_minutes = "4"': "max_wait_minutes must be an integer, got '4'",
    "max_wait_hours = 4": (
        "unknown keys ['max_wait_hours']; allowed: "
        "['app_id', 'max_wait_minutes', 'mode', 'notify', 'plugin_update', 'prompt', 'prs', 'remind_hours', 'retry_hours', 'wip']"
    ),
    "wait_hours = 4": (
        "unknown keys ['wait_hours']; allowed: "
        "['app_id', 'max_wait_minutes', 'mode', 'notify', 'plugin_update', 'prompt', 'prs', 'remind_hours', 'retry_hours', 'wip']"
    ),
}


@pytest.mark.parametrize("line", WAIT_REFUSALS)
def test_s003_2_a_bad_wait_key_is_refused_naming_it(line: str) -> None:
    assert refusal(lambda: agents(line + "\n")) == f"shipmill.toml [agents]: {WAIT_REFUSALS[line]}"


def test_s003_2_a_bad_wait_key_exits_2(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + '\n[agents]\nprompt = "/t"\nremind_hours = 0\n', encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr == "shipmill: shipmill.toml [agents]: remind_hours must be in 1..168, got 0\n"


def test_s021_5_the_policy_reads_notices_and_an_unknown_key_exits_2(tmp_path: Path) -> None:
    text = POLICY + "\n[notices]\npin = \"uv add 'demo=={version}'\"\ninstall = 'uv add {name}'\n"
    notices = Policy.parse(tomllib.loads(text), "shipmill.toml").notices
    assert (notices.pin, notices.install) == ("uv add 'demo=={version}'", "uv add {name}")
    assert Policy.parse(tomllib.loads(POLICY), "shipmill.toml").notices == NoticesConfig()
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + "\n[notices]\ninstall = 'uv add demo'\nupgrade = 'uv add -U demo'\n", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr == "shipmill: shipmill.toml [notices]: unknown keys ['upgrade']; allowed: ['install', 'pin']\n"


def hooks(text: str) -> HooksConfig:
    return Policy.parse(tomllib.loads(POLICY + text), "shipmill.toml").hooks


def test_s026_14_the_policy_reads_hooks_with_its_defaults() -> None:
    assert hooks("") == HooksConfig(default_branch=True, private=())
    assert hooks("\n[hooks]\n") == HooksConfig(default_branch=True, private=())
    given = hooks('\n[hooks]\ndefault_branch = false\nprivate = ["owner/**", "notes/*.md"]\n')
    assert given == HooksConfig(default_branch=False, private=("owner/**", "notes/*.md"))
    assert hooks("\n[hooks]\nprivate = []\n").private == ()


@pytest.mark.parametrize("name", [name for name in CASES if name.startswith("hooks ")])
def test_s026_14_a_bad_hooks_key_exits_2_naming_it(name: str, tmp_path: Path) -> None:
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(apply(POLICY, CASES[name]), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr == f"shipmill: {MESSAGES[name]}\n"
