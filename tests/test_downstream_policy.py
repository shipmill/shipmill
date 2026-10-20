"""Spec 032: the [downstream] section of .github/shipmill.toml"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.downstream import Downstream, DownstreamConfig
from shipmill.errors import ReleaseError
from shipmill.policy import Policy

from .conftest import POLICY

APP = "\n[downstream]\napp_id = 123456\n"
CONSUMER = '\n[downstream.consumer-app]\nrepo = "example-org/consumer-app"\nworkflow = "library-tests.yml"\n'
WHERE = "shipmill.toml [downstream]"
TABLE_KEYS = "['ref', 'repo', 'report_only', 'timeout_minutes', 'workflow']"
WORKFLOW_RULE = "workflow names a file in the downstream's .github/workflows"
NAME_RULE = "a downstream's name matches [a-z0-9][a-z0-9-]{0,38}, since it becomes a check's name"


def downstream(text: str) -> DownstreamConfig | None:
    return Policy.parse(tomllib.loads(POLICY + text), "shipmill.toml").downstream


def test_s032_1_a_policy_without_the_section_has_no_downstreams() -> None:
    assert downstream("") is None


def test_s032_1_the_policy_reads_downstream_with_its_defaults() -> None:
    assert downstream(APP + CONSUMER) == DownstreamConfig(
        app_id=123456,
        timeout_minutes=30,
        downstreams=(
            Downstream(
                name="consumer-app",
                repo="example-org/consumer-app",
                workflow="library-tests.yml",
                ref=None,
                report_only=False,
                timeout_minutes=30,
            ),
        ),
    )


def test_s032_1_the_policy_reads_every_downstream_key_in_config_order() -> None:
    text = (
        "\n[downstream]\napp_id = 7\ntimeout_minutes = 20\n"
        '\n[downstream.zeta]\nrepo = "o/zeta"\nworkflow = "t.yaml"\nref = "release/2"\n'
        "report_only = true\ntimeout_minutes = 45\n"
        '\n[downstream.alpha]\nrepo = "o/alpha.py"\nworkflow = "t.yml"\n'
    )
    assert downstream(text) == DownstreamConfig(
        app_id=7,
        timeout_minutes=20,
        downstreams=(
            Downstream("zeta", "o/zeta", "t.yaml", "release/2", True, 45),
            Downstream("alpha", "o/alpha.py", "t.yml", None, False, 20),
        ),
    )


def test_s032_1_the_timeout_bounds_are_inclusive() -> None:
    text = (
        "\n[downstream]\napp_id = 1\ntimeout_minutes = 300\n"
        '\n[downstream.low]\nrepo = "o/low"\nworkflow = "t.yml"\ntimeout_minutes = 1\n'
        '\n[downstream.high]\nrepo = "o/high"\nworkflow = "t.yml"\n'
    )
    config = downstream(text)
    assert config is not None
    assert [d.timeout_minutes for d in config.downstreams] == [1, 300]


def test_s032_1_a_name_may_be_39_characters() -> None:
    name = "a" + "-" * 37 + "z"
    config = downstream(APP + CONSUMER.replace("consumer-app]", f"{name}]"))
    assert config is not None
    assert config.downstreams[0].name == name


def table(key: str, line: str) -> str:
    return APP + CONSUMER + line + "\n" if key == "table" else APP + line + "\n" + CONSUMER


REFUSALS: dict[str, tuple[str, str]] = {
    "unknown scalar key": (
        APP + "colour = 1\n" + CONSUMER,
        f"{WHERE}: unknown keys ['colour']; allowed: ['app_id', 'timeout_minutes']",
    ),
    "no downstream table": (APP, f"{WHERE} names no downstream repository"),
    "empty section": ("\n[downstream]\n", f"{WHERE} names no downstream repository"),
    "missing app_id": ("\n[downstream]\n" + CONSUMER, f"{WHERE}: app_id is required"),
    "app_id zero": ("\n[downstream]\napp_id = 0\n" + CONSUMER, f"{WHERE}: app_id must be 1 or more, got 0"),
    "app_id a string": ('\n[downstream]\napp_id = "1"\n' + CONSUMER, f"{WHERE}: app_id must be an integer, got '1'"),
    "app_id a bool": ("\n[downstream]\napp_id = true\n" + CONSUMER, f"{WHERE}: app_id must be an integer, got True"),
    "section timeout a bool": (
        table("section", "timeout_minutes = true"),
        f"{WHERE}: timeout_minutes must be an integer, got True",
    ),
    "table timeout a bool": (
        table("table", "timeout_minutes = true"),
        f"{WHERE} [consumer-app]: timeout_minutes must be an integer, got True",
    ),
    "section timeout zero": (
        table("section", "timeout_minutes = 0"),
        f"{WHERE}: timeout_minutes must be in 1..300, got 0",
    ),
    "section timeout over": (
        table("section", "timeout_minutes = 301"),
        f"{WHERE}: timeout_minutes must be in 1..300, got 301",
    ),
    "unknown table key": (
        table("table", "branch = 'main'"),
        f"{WHERE} [consumer-app]: unknown keys ['branch']; allowed: {TABLE_KEYS}",
    ),
    "missing repo": (
        APP + '\n[downstream.consumer-app]\nworkflow = "t.yml"\n',
        f"{WHERE} [consumer-app]: repo is required",
    ),
    "missing workflow": (
        APP + '\n[downstream.consumer-app]\nrepo = "o/r"\n',
        f"{WHERE} [consumer-app]: workflow is required",
    ),
    "repo no slash": (
        (APP + CONSUMER).replace('"example-org/consumer-app"', '"consumer-app"'),
        f"{WHERE} [consumer-app]: repo is owner/name, such as example-org/consumer-app; got 'consumer-app'",
    ),
    "repo two slashes": (
        (APP + CONSUMER).replace('"example-org/consumer-app"', '"a/b/c"'),
        f"{WHERE} [consumer-app]: repo is owner/name, such as example-org/consumer-app; got 'a/b/c'",
    ),
    "repo empty owner": (
        (APP + CONSUMER).replace('"example-org/consumer-app"', '"/c"'),
        f"{WHERE} [consumer-app]: repo is owner/name, such as example-org/consumer-app; got '/c'",
    ),
    "repo dot dot": (
        (APP + CONSUMER).replace('"example-org/consumer-app"', '"o/.."'),
        f"{WHERE} [consumer-app]: repo is owner/name, such as example-org/consumer-app; got 'o/..'",
    ),
    "repo a string": (
        (APP + CONSUMER).replace('"example-org/consumer-app"', "1"),
        f"{WHERE} [consumer-app]: repo must be a string, got 1",
    ),
    "workflow with a slash": (
        (APP + CONSUMER).replace('"library-tests.yml"', '".github/workflows/t.yml"'),
        f"{WHERE} [consumer-app]: {WORKFLOW_RULE}, got '.github/workflows/t.yml'",
    ),
    "workflow without the suffix": (
        (APP + CONSUMER).replace('"library-tests.yml"', '"library-tests.json"'),
        f"{WHERE} [consumer-app]: {WORKFLOW_RULE}, got 'library-tests.json'",
    ),
    "empty ref": (
        table("table", 'ref = ""'),
        f"{WHERE} [consumer-app]: ref must be a branch name; omit it for the downstream's default branch",
    ),
    "blank ref": (
        table("table", 'ref = "  "'),
        f"{WHERE} [consumer-app]: ref must be a branch name; omit it for the downstream's default branch",
    ),
    "ref a string": (table("table", "ref = 1"), f"{WHERE} [consumer-app]: ref must be a string, got 1"),
    "report_only a bool": (
        table("table", 'report_only = "true"'),
        f"{WHERE} [consumer-app]: report_only must be true or false, got 'true'",
    ),
    "report_only not an integer": (
        table("table", "report_only = 1"),
        f"{WHERE} [consumer-app]: report_only must be true or false, got 1",
    ),
    "table timeout zero": (
        table("table", "timeout_minutes = 0"),
        f"{WHERE} [consumer-app]: timeout_minutes must be in 1..300, got 0",
    ),
    "table timeout over": (
        table("table", "timeout_minutes = 301"),
        f"{WHERE} [consumer-app]: timeout_minutes must be in 1..300, got 301",
    ),
    "name upper case": (
        (APP + CONSUMER).replace("consumer-app]", "Consumer]"),
        f"{WHERE} [Consumer]: {NAME_RULE}",
    ),
    "name leading dash": (
        (APP + CONSUMER).replace("consumer-app]", '"-app"]'),
        f"{WHERE} [-app]: {NAME_RULE}",
    ),
    "name underscore": (
        (APP + CONSUMER).replace("consumer-app]", "consumer_app]"),
        f"{WHERE} [consumer_app]: {NAME_RULE}",
    ),
    "name 40 characters": (
        (APP + CONSUMER).replace("consumer-app]", "a" * 40 + "]"),
        f"{WHERE} [{'a' * 40}]: {NAME_RULE}",
    ),
    "same repo and workflow twice": (
        APP + CONSUMER + CONSUMER.replace("consumer-app]", "again]"),
        f"{WHERE}: [consumer-app] and [again] both name library-tests.yml in example-org/consumer-app; keep one",
    ),
}


@pytest.mark.parametrize("name", REFUSALS)
def test_s032_2_a_bad_downstream_section_is_refused_naming_the_key(name: str) -> None:
    text, message = REFUSALS[name]
    with pytest.raises(ReleaseError) as caught:
        downstream(text)
    assert str(caught.value) == message


def test_s032_2_a_downstream_key_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(ReleaseError) as caught:
        Policy.parse(tomllib.loads("downstream = 1\n" + POLICY), "shipmill.toml")
    assert str(caught.value) == "shipmill.toml: downstream must be a table, got 1"


def test_s032_2_the_same_repo_with_another_workflow_is_two_downstreams() -> None:
    config = downstream(
        APP + CONSUMER + CONSUMER.replace("consumer-app]", "nightly]").replace("library-tests", "nightly")
    )
    assert config is not None
    assert [d.name for d in config.downstreams] == ["consumer-app", "nightly"]


@pytest.mark.parametrize("name", REFUSALS)
def test_s032_2_a_bad_downstream_section_exits_2(name: str, tmp_path: Path) -> None:
    text, message = REFUSALS[name]
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + text, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "settle-minutes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr == f"shipmill: {message}\n"
