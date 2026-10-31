"""watch_state.py's --tier, --sweep, and --known (spec 046): the reads the gate's walk makes,
run as the gate runs them, with a fake gh on PATH that logs every call"""

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.gate import StateRead, parse_findings, watch_command

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE = ROOT / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)  # noqa: UP017 (the script runs under 3.10 too)
HEAD = "a" * 40
BOT = "shipmill-app[bot]"
QUESTION = "<!-- shipmill:needs-decision -->\n@alice Decision needed: merge it?"
CONFIG = """mode = "release"

[lanes.rc]
schedule = ["Mon 07:00 UTC"]

[environments.staging]
lane = "rc"
workflow = "deploy.yml"

[agents]
prompt = "/triage {repo}"
"""
OPERATE = """on:
  schedule:
    - cron: "*/10 * * * *"
jobs:
  operate:
    uses: shipmill/shipmill/.github/workflows/operate.yml@v0
"""
# answers gh pr list and the batched GraphQL comment read; anything else fails the run
FAKE_GH = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["api", "graphql"]:
    query = next(a for a in args if a.startswith("query="))
    comments = json.loads(os.environ.get("FAKE_COMMENTS", "{}"))
    repository = {}
    for n in re.findall(r"n(\\d+): issueOrPullRequest", query):
        nodes = [
            {"author": {"__typename": "Bot" if who.endswith("[bot]") else "User", "login": who.replace("[bot]", "")},
             "authorAssociation": association, "body": body}
            for who, association, body in comments.get(n, [])
        ]
        repository["n" + n] = {"comments": {"pageInfo": {"hasPreviousPage": False}, "nodes": nodes}}
    print(json.dumps({"data": {"repository": repository}}))
elif args[:2] == ["pr", "list"]:
    print(os.environ.get("FAKE_PRS", "[]"))
else:
    sys.stderr.write("unexpected gh call: " + " ".join(args) + "\\n")
    sys.exit(1)
"""


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_tiers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def checkout(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / ".github" / "workflows").mkdir(parents=True)
    (work / ".github" / "shipmill.toml").write_text(CONFIG, encoding="utf-8")
    (work / ".github" / "workflows" / "ops.yml").write_text(OPERATE, encoding="utf-8")
    return work


def pr(
    number: int, *labels: str, draft: bool = False, fork: bool = False, assignees: tuple[str, ...] = ()
) -> dict[str, object]:
    return {
        "number": number,
        "isDraft": draft,
        "isCrossRepository": fork,
        "labels": [{"name": label} for label in labels],
        "headRefOid": HEAD,
        "assignees": [{"login": login} for login in assignees],
    }


def known(**given: object) -> dict[str, object]:
    found: dict[str, object] = {"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}
    return found | given


def tier(
    tmp_path: Path, number: int, data: dict[str, object], *flags: str, comments: object = None
) -> tuple[list[dict[str, object]], list[list[str]]]:
    """One --tier read, its rows and every gh call it made"""
    work = checkout(tmp_path)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(FAKE_GH.replace("{python}", sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    log = tmp_path / "gh.log"
    log.touch()
    path = tmp_path / "known.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_COMMENTS": json.dumps(comments or {}),
    }
    cmd = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(work), "--json", "--tier", str(number)]
    proc = subprocess.run([*cmd, "--known", str(path), *flags], capture_output=True, text=True, env=env, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return [json.loads(line) for line in proc.stdout.splitlines()], calls


def test_s046_7_tier_1_prints_its_rows_alone(tmp_path: Path) -> None:
    incident = {
        "number": 9,
        "title": "staging is down",
        "createdAt": "2026-10-27T10:00:00Z",
        "author": "alice",
        "labels": ["incident"],
        "closing_prs": [],
    }
    failed = {
        "workflow": "ops.yml",
        "status": "completed",
        "conclusion": "failure",
        "createdAt": "2026-10-27T11:50:00Z",
        "url": "https://github.com/o/r/actions/runs/7",
    }
    release = {**failed, "workflow": "release.yml", "url": "https://github.com/o/r/actions/runs/8"}
    rows, calls = tier(tmp_path, 1, known(incidents=[incident], runs=[failed, release], prs=[pr(3)]))
    assert sorted((r["state"], r["subject"]) for r in rows) == [("INCIDENT_OPEN", "#9"), ("OPERATE_FAILED", "ops.yml")]
    assert calls == []  # the change check read the incidents and the runs already


def test_s046_7_tier_3_prints_open_and_waiting_pull_requests_alone(tmp_path: Path) -> None:
    prs = [pr(3), pr(4, draft=True), pr(5, "needs-decision"), pr(6, fork=True), pr(7, "decided")]
    comments = {"5": [[BOT, "NONE", QUESTION]], "7": []}
    rows, calls = tier(tmp_path, 3, known(prs=prs), "--trusted-only", "--bot-login", BOT, comments=comments)
    assert [(r["state"], r["detail"]) for r in rows] == [("PRS_OPEN", "#3 #7"), ("NEEDS_DECISION", "#5")]
    assert rows[0]["heads"] == {"3": HEAD, "7": HEAD}
    # the one batched comment read, of the pull requests labelled needs-decision or decided
    assert len(calls) == 1 and calls[0][:2] == ["api", "graphql"]
    assert "n5: issueOrPullRequest" in calls[0][3] and "n7: issueOrPullRequest" in calls[0][3]


def test_853_a_persons_assigned_pull_request_is_no_tier_3_item(tmp_path: Path) -> None:
    # "hold it: I merge it by hand", taken up: labelled role:maintainer and assigned; one labelled
    # without an assignee (human reads as role:maintainer, in any case) stays for a session to assign
    held = pr(160, "role:maintainer", assignees=("romamo",))
    prs = [pr(3), held, pr(161, "Human"), pr(162, "ROLE:Infra", draft=True, assignees=("amy",))]
    rows, _ = tier(tmp_path, 3, known(prs=prs))
    assert [(r["state"], r["detail"]) for r in rows] == [("PRS_OPEN", "#3 #161")]
    only, _ = tier(tmp_path / "held", 3, known(prs=[held]))
    assert only == []  # no row in tier 3 at all, so the gate's walk hands no session for it


def test_853_the_full_report_lists_a_persons_pull_request_as_with_person(ws: ModuleType) -> None:
    prs = [pr(3), pr(160, "role:maintainer", assignees=("romamo",)), pr(158, "human", assignees=("ann", "bo-b"))]
    rows = ws.intake("o/r", 0, "", [*prs, pr(161, "role:maintainer")], lambda n: [])
    assert [(r.state, r.detail) for r in rows] == [
        ("PRS_OPEN", "#3 #161"),
        ("PRS_PARKED", "WITH_PERSON #158 (@ann @bo-b) #160 (@romamo)"),
    ]
    assert "PRS_PARKED" not in ws.AGENT | ws.ACTION and rows[1].fix is None  # report only
    malformed = {**prs[1], "assignees": [{"name": "Rom"}]}
    with pytest.raises(ws.Refused, match="#160's assignees"):
        ws.intake("o/r", 0, "", [malformed], lambda n: [])


def test_853_known_needs_each_pull_requests_assignees(tmp_path: Path) -> None:
    without = {k: v for k, v in pr(3).items() if k != "assignees"}
    path = tmp_path / "known.json"
    path.write_text(json.dumps(known(prs=[without])), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(checkout(tmp_path)), "--json", "--tier", "3"]
    proc = subprocess.run([*cmd, "--known", str(path)], capture_output=True, text=True, check=False)
    assert proc.returncode == 2 and "gh pr list's fields" in proc.stderr


@pytest.mark.parametrize(
    ("cmd", "shown"),
    [
        (
            ["gh", "api", "-X", "GET", "repos/o/r/actions/runs", "-f", "per_page=100"],
            "gh api -X GET repos/o/r/actions/runs -f per_page=...",
        ),
        (
            ["gh", "api", "graphql", "-f", "query=query { viewer { login } }", "-F", "owner=o", "-Hx:y"],
            "gh api graphql -f query=... -F owner=... -Hx:...",
        ),
        (
            ["gh", "api", "--paginate", f"repos/o/r/{'x' * 300}", "--field=token=ghs_secret", "--jq", ".[]"],
            f"gh api --paginate repos/o/r/{'x' * 300} ...",
        ),
        (["git", "-C", "/tmp/a b", "fetch"], "git -C '/tmp/a b' fetch"),
    ],
    ids=["get", "graphql", "long", "git"],
)
def test_853_the_error_line_names_the_whole_command_and_no_field_value(
    ws: ModuleType, capsys: pytest.CaptureFixture[str], cmd: list[str], shown: str
) -> None:
    failed = subprocess.CompletedProcess(cmd, 1, "", "HTTP 403: Resource not accessible by integration")
    with pytest.raises(SystemExit):
        ws.checked(cmd, failed)
    err = capsys.readouterr().err
    assert err == f"error: {shown}: HTTP 403: Resource not accessible by integration\n"
    assert "ghs_secret" not in err and "viewer" not in err


@pytest.mark.parametrize(("closed", "queries"), [(2, 1), (60, 2)])
def test_842_the_full_report_reads_the_pull_requests_comments_in_batches(
    ws: ModuleType, closed: int, queries: int
) -> None:
    # #842: the comments of every pull request intake may ask about are one GraphQL query per
    # COMMENTS_CHUNK items, never one REST read each; this pins the full report's intake reads
    prs = [pr(3), pr(5, "needs-decision"), pr(6, "decided", fork=True), pr(7, "decided")]
    decided = [{"number": 100 + n, "isCrossRepository": n == 1} for n in range(closed)]
    comments = {5: [(BOT, "NONE", QUESTION)]}
    ran: list[list[str]] = []

    def read(cmd: list[str]) -> str:
        ran.append(cmd)
        if cmd[1:3] == ["api", "graphql"]:
            query = next(a for a in cmd if a.startswith("query="))
            repository = {}
            for n in map(int, re.findall(r"n(\d+): issueOrPullRequest", query)):
                nodes = [
                    {
                        "author": {"__typename": "Bot", "login": who.removesuffix("[bot]")},
                        "authorAssociation": a,
                        "body": b,
                    }
                    for who, a, b in comments.get(n, [])
                ]
                repository[f"n{n}"] = {"comments": {"pageInfo": {"hasPreviousPage": False}, "nodes": nodes}}
            return json.dumps({"data": {"repository": repository}})
        assert cmd[1:3] == ["pr", "list"], cmd
        return json.dumps(decided if "closed" in cmd else prs)

    rows = ws.intake_rows("o/r", 0, "", BOT, True, None, None, frozenset(), NOW, read=read)
    assert [(r.state, r.detail) for r in rows] == [
        ("PRS_OPEN", "#3 #7"),
        ("NEEDS_DECISION", "#5"),
        ("UNTRUSTED", "#6"),
    ]
    assert len(ran) == 2 + queries  # the open and the closed pull requests, then the batched comments
    asked = sorted(int(n) for c in ran[2:] for n in re.findall(r"n(\d+): issueOrPullRequest", c[4]))
    # a fork's pull request is never read under --trusted-only: neither #6 nor #101
    assert asked == sorted([5, 7, *(100 + n for n in range(closed) if n != 1)])


def test_s046_7_the_rows_a_tier_prints_read_as_the_gates_findings(tmp_path: Path) -> None:
    rows, _ = tier(tmp_path, 3, known(prs=[pr(3)]))
    (found,) = parse_findings("\n".join(json.dumps(r) for r in rows))
    assert (found.state, found.detail, found.heads) == ("PRS_OPEN", "#3", ((3, HEAD),))


def test_s046_7_no_tier_prints_a_host_or_report_only_row(ws: ModuleType) -> None:
    printed = {state for states in ws.TIERS.values() for state in states}
    assert printed - ws.ACTION == {"PRS_OPEN"}  # the one non-action row, the gate's work under land
    assert not printed & {"AGENT_SESSION", "HOST_UNKNOWN", "SHIPMILL_VERSION", "LOOP", "BOT_OK", "ISSUES_OPEN"}
    assert set(ws.SWEPT) <= ws.AGENT
    # every state that needs an agent has its tier, so the gate's walk reads it (S-046-12)
    assert printed >= ws.AGENT


@pytest.mark.parametrize(
    "flags",
    [
        ["--tier", "3", "--sweep"],
        ["--tier", "3", "--no-host"],
        ["--sweep", "--host", "sessions"],
        ["--known", "k.json"],
        ["--tier", "9"],
    ],
)
def test_s046_7_a_tier_or_sweep_read_refuses_the_host_flags(flags: list[str]) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "o/r", *flags], capture_output=True, text=True, check=False)
    assert proc.returncode == 2 and proc.stdout == ""


def test_s046_12_the_issues_row_splits_by_triage_state(ws: ModuleType) -> None:
    fix = "run github-issue-triage on o/r"
    issues = ws.Row("ISSUES", "o/r", "DECIDED #4; NEEDS_PR #9; NEW #5 #6", fix)
    other = ws.Row("VETOED", "o/r", "#2", fix)
    assert [(r.state, r.detail) for r in ws.split_issues([issues, other], decided=True)] == [
        ("ISSUES", "DECIDED #4"),
        ("VETOED", "#2"),
    ]
    assert [r.detail for r in ws.split_issues([issues], decided=False)] == ["NEEDS_PR #9", "NEW #5 #6"]


def test_a_malformed_known_file_is_refused(ws: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "known.json"
    path.write_text(json.dumps({"default_branch": "main"}), encoding="utf-8")
    with pytest.raises(ws.Refused, match="expected exactly"):
        ws.read_known(path)
    path.write_text(json.dumps(known(prs=[{"number": 3}])), encoding="utf-8")
    with pytest.raises(ws.Refused, match="gh pr list's fields"):
        ws.read_known(path)


@pytest.mark.parametrize(
    "given",
    [
        {"prs": {}},  # an object, not a list: read as no pull request at all
        {"incidents": ""},
        {"runs": {}},
        {"prs": [{**pr(3), "labels": ["needs-decision"]}]},  # gh pr list's labels are objects
        {"prs": [{**pr(3), "number": "3"}]},
        {"prs": [{**pr(3), "isDraft": "false"}]},
        {
            "incidents": [
                {
                    "number": 9,
                    "title": "t",
                    "createdAt": NOW.isoformat(),
                    "author": "a",
                    "labels": "incident",
                    "closing_prs": [],
                }
            ]
        },
    ],
)
def test_a_known_file_of_the_wrong_shape_is_refused(ws: ModuleType, tmp_path: Path, given: dict[str, object]) -> None:
    path = tmp_path / "known.json"
    path.write_text(json.dumps(known(**given)), encoding="utf-8")
    with pytest.raises(ws.Refused):
        ws.read_known(path)


@pytest.mark.parametrize("level", ["observe", "propose", "act"])
def test_s046_7_tier_4_waits_on_the_upgrade_questions_the_full_report_does(ws: ModuleType, level: str) -> None:
    body = "<!-- shipmill-upgrade: lanes v1 -->\nupgrade the config"

    def issue(number: int, *labels: str, closing: tuple[int, ...] = ()) -> object:
        upgrade = ("shipmill-upgrade", "needs-decision", *labels)
        return ws.Issue(number, "upgrade", body, NOW, "github-actions[bot]", upgrade, closing)

    issues = [issue(1), issue(2, "shipmill-upgrade-later"), issue(3, closing=(8,))]
    full = ws.upgrade_rows(issues, level, False, lambda n: [], lambda name: [], "o/r")
    # with no reply yet, every upgrade question the full report reads waits, and no other
    assert ws.asked_upgrades(issues, level) == full.waiting == ([] if level == "observe" else [1])


def test_known_runs_fall_back_only_when_the_workflow_has_none(ws: ModuleType) -> None:
    older = ws.Run("completed", "success", NOW - dt.timedelta(hours=2), "https://github.com/o/r/actions/runs/1")
    newer = ws.Run("completed", "failure", NOW, "https://github.com/o/r/actions/runs/2")
    found = ws.Known("main", False, [], [], [("release.yml", older), ("ops.yml", newer), ("release.yml", newer)])
    assert ws.known_runs(found, "release.yml", "o/r") == [newer, older]


def test_a_graphql_query_is_a_read_and_a_mutation_is_not(ws: ModuleType) -> None:
    assert ws.gh_read(["gh", "api", "graphql", "-f", "query=query { viewer { login } }"])
    assert not ws.gh_read(["gh", "api", "graphql", "-f", "query=mutation { addComment }"])
    assert not ws.gh_read(["gh", "api", "graphql", "-f", "owner=o"])


def test_comment_logins_read_as_the_rest_api_shows_them(ws: ModuleType) -> None:
    assert ws.comment_login({"__typename": "Bot", "login": "shipmill-app"}) == BOT
    assert ws.comment_login({"__typename": "User", "login": "alice"}) == "alice"
    assert ws.comment_login(None) == "ghost"


def test_triage_state_reads_only_the_labelled_open_issues_with_label() -> None:
    spec = importlib.util.spec_from_file_location("triage_state_tiers", TRIAGE)
    assert spec is not None and spec.loader is not None
    triage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = triage
    spec.loader.exec_module(triage)
    narrowed = triage.first_query(True, ("needs-decision", 'a"b'))
    assert 'open: issues(states: OPEN, labels: ["needs-decision", "a\\"b"], first: $size' in narrowed
    assert "labels: [" not in triage.first_query(True).split("closed:")[0]
    assert 'labels: ["decided"], first: $size, after: $cursor' in triage.open_page(False, ("decided",))


def test_s046_20_status_reads_every_section_without_a_tier_or_sweep(tmp_path: Path) -> None:
    for host in (True, False):
        cmd = watch_command("o/r", tmp_path, StateRead(), json=False, host=host)
        assert not {"--tier", "--sweep", "--known"} & set(cmd)


def test_s046_20_the_full_report_still_reads_the_host_rows(ws: ModuleType) -> None:
    # main reads report_rows unless --tier or --sweep is given, with the host's rows
    assert ws.report_rows.__defaults__ == (True,)
    args = ws.arguments().parse_args(["o/r"])
    assert (args.tier, args.sweep, args.known) == (None, False, None)
