"""Spec 036, #640: the resolved roles reach the state scripts through the gate, the watch, and
`shipmill status`, and a team-only person's item reads without error"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.agents import AgentsConfig, RolesConfig
from shipmill.autonomy import Autonomy, AutonomyPolicy, Hold
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gate import (
    Action,
    Finding,
    StateRead,
    decide,
    gate,
    headless_prompt,
    interactive_prompt,
    parse_findings,
    role_line,
    skills_dir,
    watch_command,
)
from shipmill.gitrepo import Git
from shipmill.roles import resolve
from shipmill.status import TEAM, Issue, parse_issues, read_issues, report

from .test_gate import DAY, ISSUES, NO_PRUNE, NOW, QUIET_ROWS, FakeClaude, FakeNotifier, bg
from .test_gate import checkout as checkout  # the fixture
from .test_status_picture import URL, Fake, facts, lines, repo_with_release
from .test_triage_human import handoff, person, run_script
from .test_triage_state import first_page

WATCH = skills_dir() / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE = skills_dir() / "github-issue-triage" / "scripts" / "triage_state.py"
HOST = "amy"
TABLE = {"infra": ["ann", "bo"], "legal": ["@acme/legal"], "accounting": []}
FLAGS = [
    "--role",
    f"maintainer={HOST}",
    "--role",
    "infra=ann,bo",
    "--role",
    "legal=@acme/legal",
    "--role",
    f"accounting={HOST}",
]


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    return load("watch_state_roles_wiring", WATCH)


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    return load("triage_state_roles_wiring", TRIAGE)


class Logins:
    """The host's gh login, counting each read; unreadable raises as host_login does"""

    def __init__(self, unreadable: bool = False) -> None:
        self.reads = 0
        self.unreadable = unreadable

    def __call__(self) -> str:
        self.reads += 1
        if self.unreadable:
            raise ReleaseError("gh api user failed: HTTP 401")
        return HOST


def agents(table: dict[str, list[str]] | None = None) -> AgentsConfig:
    roles = RolesConfig() if table is None else RolesConfig.parse(table)
    # land observe: QUIET_ROWS' open pull request is no work (S-040-9)
    observe = AutonomyPolicy(land=Autonomy.OBSERVE)
    return AgentsConfig(prompt="/triage {repo}", prs=None, retry_hours=24, roles=roles, autonomy=observe)


def tick(
    git: Git,
    config: AgentsConfig,
    login: Logins,
    rows: list[Finding],
    claude: FakeClaude | None = None,
) -> tuple[Action, list[StateRead], FakeClaude]:
    reads: list[StateRead] = []

    def findings(read: StateRead) -> list[Finding]:
        reads.append(read)
        return rows

    session = claude if claude is not None else FakeClaude()
    decision, _, _, _ = gate(
        git,
        "romamo/demo",
        lambda: config,
        session,
        findings,
        NOW,
        Hold,
        FakeNotifier(),
        NO_PRUNE,
        login=login,
        roles=resolve,
    )
    return decision.action, reads, session


# -- S-036-5: the gate ---------------------------------------------------------------------


def test_s036_5_the_gate_passes_one_role_flag_per_resolved_role_to_watch_state(checkout: Git) -> None:
    login = Logins()
    action, reads, claude = tick(checkout, agents(TABLE), login, [ISSUES], FakeClaude([bg("old", "idle", "done")]))
    assert action is Action.LAUNCH
    (read,) = reads
    assert read.flags() == FLAGS
    command = watch_command("romamo/demo", checkout.root, read)
    assert command[-len(FLAGS) :] == FLAGS  # each flag and value its own argv item, never a shell string
    assert login.reads == 1  # once a tick: for the roles and the prompt both
    _, text = claude.launched[0]
    assert role_line(read.roles) in text


def test_s036_5_a_gate_that_never_set_roles_passes_the_maintainer_only_and_ticks_as_before(checkout: Git) -> None:
    login = Logins()
    action, reads, claude = tick(checkout, agents(), login, QUIET_ROWS)
    assert action is Action.QUIET and claude.launched == []
    assert reads[0].flags() == ["--role", f"maintainer={HOST}"]
    assert login.reads == 1


def test_s036_5_an_unreadable_login_for_the_maintainer_reads_no_state_and_exits_2(checkout: Git) -> None:
    # S-036-4's rule for the gate: the maintainer lists nobody and the login can't be read
    with pytest.raises(ReleaseError, match=r"\[agents\.roles\] maintainer lists nobody.*HTTP 401"):
        tick(checkout, agents(TABLE), Logins(unreadable=True), [ISSUES])


def test_s036_5_a_listed_maintainer_reads_no_login_on_a_quiet_tick(checkout: Git) -> None:
    login = Logins(unreadable=True)
    action, reads, _ = tick(checkout, agents({"maintainer": ["maria", "@acme/ops"]}), login, QUIET_ROWS)
    assert action is Action.QUIET
    assert reads[0].flags() == ["--role", "maintainer=maria,@acme/ops"]
    assert login.reads == 0


def test_s036_5_the_session_prompt_carries_the_role_line_in_both_modes() -> None:
    roles = resolve(RolesConfig.parse(TABLE), lambda: HOST)
    line = (
        "Pass the same role flags to triage_state.py and watch_state.py when you read the state again:"
        f" --role maintainer={HOST} --role infra=ann,bo --role legal=@acme/legal --role accounting={HOST}"
    )
    assert role_line(roles) == line
    for build in (headless_prompt, interactive_prompt):
        text = build("/t {repo}", "romamo/demo", [ISSUES], NOW, HOST, None, roles)
        assert f"\n\n{line}\n\n" in text
        assert role_line(roles) not in build("/t {repo}", "romamo/demo", [ISSUES], NOW, HOST)


# -- S-036-5: watch_state.py ---------------------------------------------------------------


def test_s036_5_watch_state_passes_its_role_flags_to_triage_state(ws: ModuleType) -> None:
    args = ws.arguments().parse_args(["o/r", "--role", "maintainer=amy", "--role", "legal=@acme/legal"])
    assert args.role == ["maintainer=amy", "legal=@acme/legal"]
    command = ws.triage_command("o/r", "x[bot]", True, None, args.role)
    assert command[-4:] == ["--role", "maintainer=amy", "--role", "legal=@acme/legal"]
    assert "--role" not in ws.triage_command("o/r")  # no flags, as an older gate passes


@pytest.mark.parametrize("flags", [["--role", "infra=ann"], ["--role", "maintainer="], ["--role", "Bad=ann"]])
def test_s036_5_watch_state_refuses_role_flags_triage_state_would_refuse(flags: list[str]) -> None:
    proc = subprocess.run(
        [sys.executable, str(WATCH), "o/r", *flags], capture_output=True, text=True, check=False, env={"PATH": ""}
    )
    assert proc.returncode == 2
    assert "--role" in proc.stderr and proc.stdout == ""


# -- S-036-5: shipmill status --------------------------------------------------------------


def status_repo(tmp_path: Path, roles: str = "") -> Path:
    root = repo_with_release(tmp_path / "repo")
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(f'[agents]\nprompt = "/t"\n{roles}', encoding="utf-8")
    return root


def test_s036_5_status_passes_the_role_flags_to_both_reads(tmp_path: Path) -> None:
    root = status_repo(tmp_path, '[agents.roles]\ninfra = ["ann"]\n')
    fake = Fake(0)
    assert main(["--repo", str(root), "status"], state=fake, login=lambda: HOST) == 0
    # the host sections' reads (#745) read no issue, so they pass no role flags
    reads = [c for c in fake.seen if c[1].endswith(("watch_state.py", "triage_state.py")) and "--host" not in c]
    assert len(reads) == 2
    for cmd in reads:
        assert cmd[-4:] == ["--role", f"maintainer={HOST}", "--role", "infra=ann"]


def test_s036_5_read_issues_passes_the_flags_before_the_bot_login() -> None:
    fake = Fake(0)
    roles = resolve(RolesConfig(), lambda: HOST)
    read_issues("acme/web", fake, "x[bot]", roles)
    assert fake.seen[0][-4:] == ["--role", f"maintainer={HOST}", "--bot-login", "x[bot]"]


def test_s036_5_status_with_an_unreadable_login_exits_2_before_any_read(tmp_path: Path) -> None:
    root = status_repo(tmp_path)
    fake = Fake(0)
    with pytest.raises(ReleaseError, match=r"maintainer lists nobody"):
        main(["--repo", str(root), "status", "--rows"], state=fake, login=Logins(unreadable=True))
    assert fake.seen == []


# -- S-036-13: the watch and status read ASSIGN_DUE and teams ------------------------------


def line(number: int, state: str, **extra: object) -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": "", **extra})


def no_comments(number: int) -> list[tuple[str, str, str]]:
    raise AssertionError(f"read the comments of #{number}")


def test_s036_13_the_watch_counts_assign_due_as_a_triage_action(ws: ModuleType) -> None:
    assert "ASSIGN_DUE" in ws.TRIAGE_ACTION
    (row,) = ws.intake("o/r", 1, line(7, "ASSIGN_DUE", assign=["ann"]), [], no_comments)
    assert (row.state, row.detail, row.json()["agent"]) == ("ISSUES", "ASSIGN_DUE #7", True)
    assert decide(parse_findings(json.dumps(row.json())), [], None, NOW, DAY).action is Action.LAUNCH


def test_s036_13_the_watch_lists_a_with_person_items_teams(ws: ModuleType) -> None:
    out = "\n".join(
        [
            line(7, "WITH_PERSON", assignees=["ann"], teams=["@acme/legal"]),
            line(9, "WITH_PERSON", assignees=[], teams=["@acme/legal", "@acme/ops"]),
            line(5, "WITH_PERSON", assignees=["cy"]),  # read without --role flags: no teams key
        ]
    )
    (row,) = ws.intake("o/r", 0, out, [], no_comments)
    assert (row.state, row.detail) == (
        "ISSUES_OPEN",
        "WITH_PERSON #7 (@ann @acme/legal) #9 (@acme/legal @acme/ops) #5 (@cy)",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"assignees": [], "teams": []},
        {"assignees": [], "teams": ["acme/legal"]},
        {"assignees": ["ann"], "teams": "@acme/legal"},
        {"assignees": [], "teams": ["@acme/legal x"]},
        {"teams": ["@acme/legal"]},
    ],
)
def test_s036_13_a_with_person_line_without_anyone_valid_is_refused(ws: ModuleType, extra: dict[str, object]) -> None:
    with pytest.raises(ws.Refused, match="WITH_PERSON line without its assignees or teams"):
        ws.intake("o/r", 0, line(7, "WITH_PERSON", **extra), [], no_comments)
    with pytest.raises(ReleaseError, match="WITH_PERSON line without its assignees or teams"):
        parse_issues(line(7, "WITH_PERSON", **extra) + "\n")


def test_s036_13_status_lists_assign_due_to_triage() -> None:
    found = facts(issues=[Issue(7, "ASSIGN_DUE", "assign @ann (role:infra)")])
    assert f"  to triage      #7 {URL}/issues/7" in lines(found)


def test_s036_13_status_reads_a_team_only_with_person_line(ts: ModuleType, tmp_path: Path, ws: ModuleType) -> None:
    # triage_state.py's own line for a team-only role's item, read by the watch and by status
    waiting = person([handoff()], people=(), labels=("role:legal",))
    proc = run_script(
        tmp_path, first_page([waiting]), "--role", "maintainer=maria", "--role", "legal=@example-org/legal"
    )
    assert proc.returncode == 0, proc.stderr
    printed = "\n".join(entry for entry in proc.stdout.splitlines() if '"number"' in entry)
    (issue,) = parse_issues(printed + "\n")
    assert (issue.state, issue.assignees, issue.teams) == ("WITH_PERSON", (), ("@example-org/legal",))
    text = lines(facts(issues=[issue]))
    assert f"  parked         #7 {URL}/issues/7 (@example-org/legal)" in text
    assert report(facts(issues=[issue])).reasons == []
    (row,) = ws.intake("o/r", 0, printed, [], no_comments)
    assert row.detail == "WITH_PERSON #7 (@example-org/legal)"
    assert TEAM.pattern == ts.TEAM.pattern  # status reads teams by triage_state.py's rule
