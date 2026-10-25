"""Spec 036, #638: [agents.roles] in .github/shipmill.toml and `shipmill roles`, which prints
who receives each step an agent can't do (S-036-1 to S-036-4)"""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, RolesConfig, app_id_of
from shipmill.cli import main
from shipmill.doctor import doctor
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\n'
SPEC = """
[agents.roles]
maintainer = ["octocat"]
infra = ["octocat", "hubot"]
legal = ["@example-org/legal"]
accounting = []
"""

Captured = pytest.CaptureFixture[str]


def host(login: str) -> Callable[[], str]:
    return lambda: login


HOST = host("hostuser")


def unreadable() -> str:
    raise ReleaseError("gh api user -q failed: HTTP 401: Bad credentials")


def roles(repo: Repo, capsys: Captured, *flags: str, login: Callable[[], str] = HOST) -> str:
    capsys.readouterr()
    assert main(["--repo", str(repo.root), "roles", *flags], login=login) == 0
    return capsys.readouterr().out


def roles_json(repo: Repo, capsys: Captured, login: Callable[[], str] = HOST) -> dict[str, object]:
    found: dict[str, object] = json.loads(roles(repo, capsys, "--json", login=login))["roles"]
    return found


def cli(repo: Repo, command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(repo.root), command],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


# -- S-036-1: the table loads, and `shipmill roles --json` prints each role --------------------


def test_s036_1_the_specs_table_loads_and_roles_json_prints_each_role(repo: Repo, capsys: Captured) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + SPEC)
    config = repo.policy.agents
    assert config is not None
    assert [str(r.name) for r in config.roles.roles] == ["maintainer", "infra", "legal", "accounting"]
    assert roles_json(repo, capsys) == {
        "maintainer": {"users": ["octocat"], "teams": [], "fallback": False},
        "infra": {"users": ["octocat", "hubot"], "teams": [], "fallback": False},
        "legal": {"users": [], "teams": ["@example-org/legal"], "fallback": False},
        "accounting": {"users": ["octocat"], "teams": [], "fallback": True},
    }


def test_s036_1_maintainer_is_present_when_the_table_doesnt_name_it(repo: Repo, capsys: Captured) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + '\n[agents.roles]\ninfra = ["hubot", "@acme/ops"]\n')
    assert roles_json(repo, capsys) == {
        "maintainer": {"users": ["hostuser"], "teams": [], "fallback": False},
        "infra": {"users": ["hubot"], "teams": ["@acme/ops"], "fallback": False},
    }


@pytest.mark.parametrize("config", [POLICY, POLICY + AGENTS], ids=["no-agents", "no-roles"])
def test_s036_1_a_config_without_roles_loads_as_before_with_only_the_maintainer(
    repo: Repo, capsys: Captured, config: str
) -> None:
    repo.write(repo.policy_file, config)
    if "[agents]" in config:
        assert AgentsConfig.load(repo.root).roles == RolesConfig()
    assert roles_json(repo, capsys) == {"maintainer": {"users": ["hostuser"], "teams": [], "fallback": False}}


def test_s036_1_roles_prints_one_line_per_role_maintainer_first(repo: Repo, capsys: Captured) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + SPEC.replace('maintainer = ["octocat"]\n', ""))
    assert roles(repo, capsys) == (
        "maintainer: @hostuser\ninfra: @octocat @hubot\nlegal: @example-org/legal\naccounting: @hostuser (fallback)\n"
    )


def test_s036_1_roles_flags_prints_the_role_arguments_triage_state_takes(repo: Repo, capsys: Captured) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + SPEC)
    assert roles(repo, capsys, "--flags") == (
        "--role maintainer=octocat --role infra=octocat,hubot --role legal=@example-org/legal"
        " --role accounting=octocat\n"
    )


def test_s036_1_shipmills_own_config_loads() -> None:
    AgentsConfig.load(ROOT)


# -- S-036-2: a malformed table exits 2 from doctor and roles, naming [agents.roles] and the key -


MALFORMED = {
    "not-a-table": ('roles = "octocat"', "[agents.roles] must be a table"),
    "role-name": ('[agents.roles]\nInfra = ["octocat"]', "[agents.roles] 'Infra': a role name is"),
    "role-name-long": (f'[agents.roles]\n{"a" * 46} = ["octocat"]', f"[agents.roles] '{'a' * 46}'"),
    "a-string": ('[agents.roles]\ninfra = "octocat"', "[agents.roles] infra must be an array"),
    "a-number": ("[agents.roles]\ninfra = 3", "[agents.roles] infra must be an array"),
    "a-number-in-array": ('[agents.roles]\ninfra = ["octocat", 3]', "[agents.roles] infra must be an array"),
    "inline-table": (
        '[agents.roles]\ninfra = { agent = "ops" }',
        "[agents.roles] infra: agent-filled roles aren't supported yet",
    ),
    "filler": ('[agents.roles]\ninfra = ["octo cat"]', "[agents.roles] infra: 'octo cat' is neither a GitHub login"),
    "trailing-hyphen": ('[agents.roles]\ninfra = ["octocat-"]', "[agents.roles] infra: 'octocat-' is neither"),
    "bad-team": ('[agents.roles]\nlegal = ["@example-org"]', "[agents.roles] legal: '@example-org' is neither"),
    "team-dot": ('[agents.roles]\nlegal = ["@acme/le.gal"]', "[agents.roles] legal: '@acme/le.gal' is neither"),
    "bot": (
        '[agents.roles]\ninfra = ["shipmill-bot[bot]"]',
        "[agents.roles] infra: 'shipmill-bot[bot]' is an App's bot",
    ),
    "twice": ('[agents.roles]\ninfra = ["octocat", "OctoCat"]', "[agents.roles] infra lists OctoCat twice"),
    "team-twice": (
        '[agents.roles]\nlegal = ["@acme/legal", "@ACME/Legal"]',
        "[agents.roles] legal lists @ACME/Legal twice",
    ),
    "maintainer-teams-only": (
        '[agents.roles]\nmaintainer = ["@acme/core"]',
        "[agents.roles] maintainer lists only teams",
    ),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_s036_2_doctor_and_roles_exit_2_naming_agents_roles_and_the_key(repo: Repo, case: str) -> None:
    table, message = MALFORMED[case]
    repo.write(repo.policy_file, POLICY + AGENTS + table + "\n")
    for command in ("doctor", "roles"):
        done = cli(repo, command)
        assert done.returncode == 2, (command, done.stdout, done.stderr)
        assert done.stderr.startswith(f"shipmill: {message}"), (command, done.stderr)


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_s036_2_every_reader_of_agents_refuses_it(repo: Repo, case: str) -> None:
    table, message = MALFORMED[case]
    repo.write(repo.policy_file, POLICY + AGENTS + table + "\n")
    readers = (
        lambda: AgentsConfig.load(repo.root),
        lambda: app_id_of(repo.root),
        lambda: doctor(repo.root),
        lambda: repo.policy,
    )
    for read in readers:
        with pytest.raises(ReleaseError) as caught:
            read()
        assert str(caught.value).startswith(message)


def test_s036_2_well_formed_fillers_are_accepted(repo: Repo, capsys: Captured) -> None:
    table = '[agents.roles]\nmaintainer = ["a", "a-b-c", "@acme/core"]\nops = ["@my-org/team_1-x", "Z9"]\n'
    repo.write(repo.policy_file, POLICY + AGENTS + table)
    assert roles_json(repo, capsys) == {
        "maintainer": {"users": ["a", "a-b-c"], "teams": ["@acme/core"], "fallback": False},
        "ops": {"users": ["Z9"], "teams": ["@my-org/team_1-x"], "fallback": False},
    }


# -- S-036-3: an empty role falls back to the maintainer ---------------------------------------


def test_s036_3_an_empty_role_resolves_to_the_maintainers_fillers_marked_fallback(repo: Repo, capsys: Captured) -> None:
    table = '[agents.roles]\nmaintainer = ["octocat", "@acme/core"]\naccounting = []\n'
    repo.write(repo.policy_file, POLICY + AGENTS + table)
    assert roles_json(repo, capsys)["accounting"] == {"users": ["octocat"], "teams": ["@acme/core"], "fallback": True}
    assert roles(repo, capsys).splitlines()[1] == "accounting: @octocat @acme/core (fallback)"
    assert "--role accounting=octocat,@acme/core\n" in roles(repo, capsys, "--flags")


# -- S-036-4: an unset or empty maintainer is the host's gh login --------------------------------


@pytest.mark.parametrize("maintainer", ["", "maintainer = []\n"], ids=["unset", "empty"])
def test_s036_4_the_maintainer_is_the_hosts_gh_login(repo: Repo, capsys: Captured, maintainer: str) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + "[agents.roles]\n" + maintainer + "infra = []\n")
    assert roles_json(repo, capsys, login=host("monalisa")) == {
        "maintainer": {"users": ["monalisa"], "teams": [], "fallback": False},
        "infra": {"users": ["monalisa"], "teams": [], "fallback": True},
    }


def test_s036_4_a_listed_maintainer_never_reads_the_login(repo: Repo, capsys: Captured) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + SPEC)
    assert roles_json(repo, capsys, login=unreadable)["maintainer"] == {
        "users": ["octocat"],
        "teams": [],
        "fallback": False,
    }


@pytest.mark.parametrize("maintainer", ["", "maintainer = []\n"], ids=["unset", "empty"])
def test_s036_4_an_unreadable_login_exits_2(repo: Repo, maintainer: str) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + "[agents.roles]\n" + maintainer)
    with pytest.raises(ReleaseError) as caught:
        main(["--repo", str(repo.root), "roles"], login=unreadable)
    assert "the maintainer is the host's gh login, which can't be read" in str(caught.value)
    assert "HTTP 401" in str(caught.value)


def test_s036_4_roles_exits_2_without_gh_when_the_maintainer_is_unset(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    done = cli(repo, "roles", env={"PATH": "/nonexistent"})
    assert done.returncode == 2, done.stderr
    assert done.stderr.startswith("shipmill: [agents.roles] maintainer lists nobody"), done.stderr
    assert "gh is not on PATH" in done.stderr
