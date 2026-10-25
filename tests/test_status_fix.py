"""Spec 011: every STUCK and WAITS ON YOU reason `shipmill status` gives carries a fix, and
the item lines say what acting on them needs"""

import dataclasses
import datetime as dt
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from shipmill import UVX, status
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.launchd import label
from shipmill.plugin import GateCli
from shipmill.status import (
    GH_PAUSE,
    STUCK_ROWS,
    YOURS_ROWS,
    Facts,
    Issue,
    Main,
    Pull,
    Reason,
    Row,
    Verdict,
    cli_update,
    parse_issues,
    parse_rows,
    read_branch,
    read_main,
    read_pulls,
    report,
)
from shipmill.version import Version
from tests.test_status_picture import AGENTS, FILES, NO_PRS, NOW, REPO, URL, facts, gate, job, lines

FIX = "                 fix: "
DECISION = "answer the needs-decision question on each item named"
LAND = (
    f"set prs = true under [agents] in .github/shipmill.toml, or land them by hand: /shipmill:github-pr-triage {REPO}"
)


def row(state: str) -> Row:
    return Row(state, "#3", "#3 x", False)


EVERY_REASON = [
    *(facts(row(s)) for s in STUCK_ROWS),
    *(facts(row(s)) for s in YOURS_ROWS),
    facts(gate=gate(job=job(loaded=False))),
    facts(gate=gate(job=job(last_exit="2"))),
    facts(gate=gate(job=job(last_run=NOW - dt.timedelta(hours=1)))),
    facts(gate=gate(job=job(last="shipmill: the gate needs a clean checkout", failed=True))),
    facts(gate=gate(job=job(last="UNCHANGED: same findings as session s1; retried after 2026-10-08T09:00"))),
    facts(gate=gate(job=job(last="WAITING: session s1 waits on you: claude attach s1"))),
    facts(gate=gate(job=job(last="PYPI_WAIT: plugin 0.32.2 waits for PyPI: the url answers 404"))),
    facts(gate=gate(job=None)),
    facts(gate=gate(app=None, app_error="the App isn't installed")),
    facts(gate=gate(agents=dataclasses.replace(AGENTS, app_id=None), app=None)),
    facts(issues=[Issue(6, "NEEDS_DECISION")]),
    facts(Row("NEEDS_DECISION", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")]),
    facts(cli="0.25.0"),
    facts(Row("PRS_OPEN", REPO, "#8", False), gate=gate(agents=NO_PRS)),
    facts(Row("PRS_OPEN", REPO, "#8", False), gate=gate(agents=None)),
]


@pytest.mark.parametrize("found", EVERY_REASON)
def test_s011_12_every_stuck_or_waiting_reason_has_a_fix_the_summary_shows(found: Facts) -> None:
    done = report(found)
    assert done.verdict in (Verdict.STUCK, Verdict.WAITS)
    assert done.reasons
    text = lines(found)
    for reason in done.reasons:
        assert reason.fix.strip()
        # on its own fix: line, or in the line it clears when that line already says it
        assert f"{FIX}{reason.fix}" in text or any(reason.fix in line for line in text), reason


def test_s011_12_a_reason_without_a_fix_cant_be_built() -> None:
    with pytest.raises(ValueError, match="without a fix"):
        Reason("the gate is down", " ")


def test_s011_12_a_group_sharing_a_fix_shows_it_once_after_its_last_item() -> None:
    found = facts(
        Row("NEEDS_DECISION", REPO, "#9", False),
        issues=[Issue(6, "NEEDS_DECISION")],
        pulls=[Pull(9, False, "CLEAN", "main")],
    )
    text = lines(found)
    at = text.index(f"  needs decision #6 {URL}/issues/6")
    assert text[at + 1 : at + 3] == [f"                 #9 {URL}/pull/9", f"{FIX}{DECISION}"]
    assert text.count(f"{FIX}{DECISION}") == 1


def test_s011_12_each_item_with_its_own_fix_shows_it_after_that_item() -> None:
    holds = (
        Row("HOLD", "#3", "freeze", False, f"gh issue close 3 -R {REPO}"),
        Row("HOLD", "#4", "freeze", False, f"gh issue close 4 -R {REPO}"),
    )
    assert lines(facts(*holds))[2:6] == [
        f"  hold           #3 {URL}/issues/3",
        f"{FIX}gh issue close 3 -R {REPO}",
        f"                 #4 {URL}/issues/4",
        f"{FIX}gh issue close 4 -R {REPO}",
    ]


def test_s011_12_a_row_under_other_shows_its_fix_and_rows_read_the_fix_field() -> None:
    printed = [
        {"state": "WORKTREE_STALE", "subject": "/w", "detail": "kept 9 days", "agent": False, "fix": "git -C /w log"},
        {"state": "BOT_OK", "subject": "rc", "detail": "", "agent": False, "fix": None},
        {"state": "BOT_OK", "subject": "dev", "detail": "", "agent": False},
    ]
    rows = parse_rows("".join(json.dumps(r) + "\n" for r in printed))
    assert [r.fix for r in rows] == ["git -C /w log", None, None]
    text = lines(facts(*rows))
    at = text.index("  other          WORKTREE_STALE /w kept 9 days")
    assert text[at + 1] == f"{FIX}git -C /w log"


def test_s011_12_a_stuck_row_takes_the_watchs_fix_or_names_the_watch_without_one() -> None:
    url = f"{URL}/actions/runs/12"
    failed = Row("BOT_FAILED", "stable", f"failure: {url}", True, f"gh run rerun 12 --failed -R {REPO}")
    text = lines(facts(failed))
    assert text[1:3] == [
        f"  repo           in sync at v0.26.0, BOT_FAILED {url}",
        f"{FIX}gh run rerun 12 --failed -R {REPO}",
    ]
    bare = report(facts(dataclasses.replace(failed, fix=None)))
    assert [r.fix for r in bare.reasons] == [f"/shipmill:github-ship-watch {REPO}"]


def test_s011_13_the_landing_line_carries_the_fix_only_when_no_gate_lands() -> None:
    off = lines(facts(Row("PRS_OPEN", REPO, "#8", False), gate=gate(agents=NO_PRS)))
    at = off.index("  landing        off: [agents] prs = false (the gate opens PRs but never lands them)")
    assert off[at + 1] == f"{FIX}{LAND}"
    on = lines(facts(Row("PRS_OPEN", REPO, "#8", False)))
    assert not any(line.startswith(FIX) for line in on)
    assert not any(line.startswith(FIX) for line in lines(facts(gate=gate(agents=NO_PRS))))
    bare = lines(facts(Row("PRS_OPEN", REPO, "#8", False), gate=gate(agents=None)))
    at = bare.index(f"  to land        #8 {URL}/pull/8")
    assert bare[at + 1] == f"{FIX}{LAND}"


@pytest.mark.parametrize(
    ("changed", "fix"),
    [
        (gate(job=job(loaded=False)), "launchctl bootstrap gui/501 /u/Library/LaunchAgents/web.plist"),
        (gate(job=job(last_run=NOW - dt.timedelta(hours=1))), f"launchctl kickstart gui/501/{label(REPO)}"),
        (gate(job=job(last_exit="2")), "tail -n 50 /u/gate.log"),
        (gate(job=job(last="shipmill: the gate needs a clean checkout", failed=True)), "tail -n 50 /u/gate.log"),
        (
            gate(job=job(last="UNCHANGED: same findings as session s1; retried after 2026-10-08T09:00")),
            "the same findings came back after session s1: read it (claude --resume s1), or wait for the retry",
        ),
        (gate(job=job(last="WAITING: session s1 waits on you: claude attach s1")), "claude attach s1"),
        (gate(job=None), f"shipmill launchd {REPO}"),
        (gate(app=None, app_error="the App isn't installed"), f"shipmill app-install {REPO}"),
        (
            gate(agents=dataclasses.replace(AGENTS, app_id=None), app=None),
            "shipmill app-create, then set app_id under [agents] in .github/shipmill.toml (shipmill-setup's App step)",
        ),
    ],
)
def test_s011_14_each_gate_problem_has_its_fix(changed: object, fix: str) -> None:
    found = facts(gate=changed)
    assert fix in [r.fix for r in report(found).reasons]
    assert any(fix in line for line in lines(found))


USER_FIX = "claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user"


def test_s031_15_a_lagging_install_is_a_row_with_its_fix_and_no_gate_pause() -> None:
    # spec 031: the install a session loads lags, which the gate reports and starts sessions on
    outdated = Row("SHIPMILL_OUTDATED", "plugin user", f"0.25.0, latest v0.26.0; {USER_FIX}", False, USER_FIX)
    found = facts(outdated)
    assert [(r.text, r.fix) for r in report(found).reasons] == [(outdated.text(), USER_FIX)]
    text = lines(found)
    assert text[-1] == f"  shipmill       0.26.0, update available: {USER_FIX}"
    assert not any("no session" in line or "paused" in line for line in text)
    # an older gate's last PLUGIN_STALE line no longer reads as a pause
    stale = "PLUGIN_STALE: a session here would load shipmill@shipmill 0.48.0 (user scope)"
    assert not any("paused" in line for line in lines(facts(gate=gate(job=job(last=stale)))))


def test_s031_16_status_names_the_unloaded_install_with_the_entry_to_delete() -> None:
    fix = (
        'delete the entry with "projectPath": "/w/r/tmp/shipmill-gate" under "shipmill@shipmill"'
        " in ~/.claude/plugins/installed_plugins.json"
    )
    detail = f"0.25.0, keyed on the gate's linked worktree /w/r/tmp/shipmill-gate, which no session loads; {fix}"
    found = facts(Row("SHIPMILL_OUTDATED", "plugin local", detail, False, fix))
    assert fix in [r.fix for r in report(found).reasons]
    assert lines(found)[-1] == f"  shipmill       0.26.0, update available: {fix}"


@pytest.mark.parametrize(
    "fix", ["uv tool upgrade shipmill", "uvx shipmill@latest --repo /w/r/tmp/shipmill-gate launchd acme/web"]
)
def test_s031_17_status_reports_the_gates_lagging_cli_with_its_fix(fix: str) -> None:
    lagging = facts(gate=gate(cli=GateCli(Version.parse("0.25.0"), fix)))
    reasons = report(lagging).reasons
    assert [(r.text, r.fix) for r in reasons] == [
        (f"the gate's CLI, shipmill 0.25.0, lags the latest release 0.26.0: {fix}", fix)
    ]
    assert lines(lagging)[-1] == f"  shipmill       0.26.0, gate 0.25.0, update available: {fix}"
    current = facts(gate=gate(cli=GateCli(Version.parse("0.26.0"), fix)))
    assert report(current).reasons == [] and lines(current)[-1].endswith("up to date")


def test_597_status_reports_a_current_gate_on_v0_with_its_rewrite() -> None:
    """#597: a job on the @v0 git source runs the newest commit, so it never lags, yet it runs a
    git tag rather than the release PyPI serves; status names the rewrite as for a lagging CLI"""
    fix = "uvx shipmill@latest --repo /w/r/tmp/shipmill-gate launchd acme/web"
    floating = facts(
        gate=gate(cli=GateCli(Version.parse("0.26.0"), fix, "git+https://github.com/shipmill/shipmill@v0"))
    )
    assert [r.fix for r in report(floating).reasons] == [fix]
    assert lines(floating)[-1] == f"  shipmill       0.26.0, gate 0.26.0 on @v0, update available: {fix}"


def test_s026_16_a_gate_paused_on_a_failed_hook_self_test_waits_on_you_with_the_fix() -> None:
    update = "claude plugin update shipmill@shipmill --scope user"
    last = (
        "HOOKS_FAILED: a session here would run without the delivery hooks: uv isn't on PATH:"
        f" no session starts until the self-test passes: {update}"
    )
    found = facts(gate=gate(job=job(last=last)))
    assert [(r.text, r.fix) for r in report(found).reasons] == [(f"the gate: {last}", update)]
    assert status.DECISION.match(last) is not None


def test_a_gate_paused_on_a_failed_claude_login_waits_on_you_with_the_login() -> None:
    # #500: an expired Claude Code login; the gate starts no session until it can authenticate
    last = (
        "CLAUDE_AUTH: Claude Code can't authenticate on this host (claude auth status says not logged in):"
        " no session starts; fix: claude auth login"
    )
    found = facts(gate=gate(job=job(last=last)))
    assert report(found).verdict is status.Verdict.WAITS
    assert [(r.text, r.fix) for r in report(found).reasons] == [(f"the gate: {last}", "claude auth login")]
    assert status.DECISION.match(last) is not None


def test_a_gate_held_until_pypi_serves_the_plugin_waits_on_you_with_the_publish_fix() -> None:
    # #569: a PYPI_WAIT tick starts no session; status reads it from the gate's last tick line
    last = (
        "PYPI_WAIT: plugin 0.32.2 waits for PyPI: https://pypi.org/pypi/shipmill/0.32.2/json answers 404;"
        " no session starts, the next tick retries"
    )
    fix = (
        "check the publish.yml run for v0.32.2: gh run list --repo shipmill/shipmill --workflow publish.yml;"
        " if none passed, publish it: gh workflow run publish.yml --repo shipmill/shipmill -f tag=v0.32.2"
    )
    found = facts(gate=gate(job=job(last=last)))
    assert status.DECISION.match(last) is not None
    assert report(found).verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in report(found).reasons] == [(f"the gate: {last}", fix)]
    assert any("paused: plugin 0.32.2 waits for PyPI" in line for line in lines(found))
    assert f"{FIX}{fix}" in lines(found)
    # a launching tick after PyPI catches up is the last line: the hold is gone
    launched = facts(gate=gate(job=job(last="LAUNCH: work found; session s2 started")))
    assert report(launched).reasons == []


def test_a_gate_without_claude_on_its_path_names_the_install_not_the_login() -> None:
    last = (
        "CLAUDE_AUTH: Claude Code can't authenticate on this host (claude isn't on PATH):"
        " no session starts; fix: install claude, then rerun shipmill launchd"
    )
    found = facts(gate=gate(job=job(last=last)))
    assert [r.fix for r in report(found).reasons] == ["install claude, then rerun shipmill launchd"]


@pytest.mark.parametrize(
    ("tail", "fix"),
    [
        ("; fix: claude auth login", "claude auth login"),
        ("; fix: tail -n 20 /u/state/sessions/0b8f.log", "tail -n 20 /u/state/sessions/0b8f.log"),
        ("; fix: claude logs 0b8f", "claude logs 0b8f"),  # an interactive session leaves no log
        ("; its log's last line: '; fix: claude logs x'", "tail -n 50 /u/gate.log"),
        ("; its log's last line: '; fix: rm -rf ~'", "tail -n 50 /u/gate.log"),  # not the gate's own fix
    ],
)
def test_a_gate_whose_sessions_end_dead_is_stuck_with_the_fix(tail: str, fix: str) -> None:
    # #500: sessions that die in a second read as one failure, not LAUNCH after LAUNCH
    last = f"SESSION_DEAD: session 0b8f ended 1 s after its launch, 3 in a row since 2026-10-20T10:05+00:00{tail}"
    found = facts(gate=gate(job=job(last=last)))
    assert report(found).verdict is status.Verdict.STUCK
    assert [(r.text, r.fix) for r in report(found).reasons] == [(f"the gate: {last}", fix)]


def test_s011_14_a_job_without_a_log_points_at_launchd() -> None:
    no_log = dataclasses.replace(FILES, log=None)
    found = report(facts(gate=gate(job=job(last_exit="2", files=no_log))))
    assert [r.fix for r in found.reasons] == [f"launchctl print gui/501/{label(REPO)}"]


def test_s011_15_an_outdated_cli_names_the_form_installed() -> None:
    assert cli_update("shipmill") == "uv tool upgrade shipmill"
    assert cli_update(UVX) == "uv tool install shipmill"
    tool = facts(cli="0.25.0")
    assert [r.fix for r in report(tool).reasons] == ["uv tool upgrade shipmill"]
    assert lines(tool)[-1].endswith("update available: uv tool upgrade shipmill")
    uvx = dataclasses.replace(tool, command=UVX)
    assert [r.fix for r in report(uvx).reasons] == ["uv tool install shipmill"]
    assert lines(uvx)[-1].endswith("update available: uv tool install shipmill")


def test_s011_16_the_repo_line_pulls_in_the_checkout_named() -> None:
    behind = facts(main=Main("main", "a" * 40, "b" * 40, 0, 3, True), checkout=Path("/src/my web"))
    assert lines(behind)[1] == "  repo           3 behind: git -C '/src/my web' pull --ff-only at v0.26.0, release ok"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True
    )


def test_s011_16_the_repo_lines_fix_catches_up_off_the_default_branch_too(tmp_path: Path) -> None:
    """Regression: with another branch checked out, `git pull --ff-only` pulls that branch (or
    fails without an upstream) and leaves the default branch behind; the fix must catch it up"""
    origin, pusher, work = tmp_path / "origin.git", tmp_path / "pusher", tmp_path / "work"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(pusher), cwd=tmp_path)
    _git("commit", "-q", "--allow-empty", "-m", "one", cwd=pusher)
    _git("push", "-q", "origin", "main", cwd=pusher)
    _git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    _git("switch", "-q", "-c", "feat/x", cwd=work)
    _git("commit", "-q", "--allow-empty", "-m", "two", cwd=pusher)
    _git("push", "-q", "origin", "main", cwd=pusher)
    _git("fetch", "-q", "origin", cwd=work)
    main = read_main(Git(work), "main")
    assert main.behind == 1
    line = lines(facts(main=main, checkout=work))[1]
    fix = line.partition("1 behind: ")[2].partition(" at v")[0]
    subprocess.run(shlex.split(fix), check=True, capture_output=True)
    assert read_main(Git(work), "main").behind == 0, line


@pytest.mark.parametrize(
    ("merge", "shown"),
    [
        ("BEHIND", f" behind main: gh pr update-branch 8 -R {REPO}"),
        ("DIRTY", " conflicts with main: needs a rebase"),
        ("UNKNOWN", ""),
        ("CLEAN", ""),
        ("BLOCKED", ""),
    ],
)
def test_s011_17_a_pull_request_to_land_says_what_keeps_it(merge: str, shown: str) -> None:
    found = facts(Row("PRS_OPEN", REPO, "#8", False), pulls=[Pull(8, False, merge, "main")])
    assert f"  to land        #8 {URL}/pull/8{shown}" in lines(found)


class GhAnswers:
    """Each gh call's (exit, stdout, stderr), in order, as status's injected runner"""

    def __init__(self, *answers: tuple[int, str, str]) -> None:
        self.answers = list(answers)
        self.ran: list[list[str]] = []
        self.paused: list[float] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.ran.append(cmd)
        code, out, err = self.answers.pop(0)
        return subprocess.CompletedProcess(cmd, code, out, err)

    def pause(self, seconds: float) -> None:
        self.paused.append(seconds)


BAD_GATEWAY = "HTTP 502: Bad Gateway (https://api.github.com/graphql)"


@pytest.mark.parametrize("read", ["pulls", "branch"])
def test_s011_11_status_reruns_a_transient_gh_read_once(read: str) -> None:
    out = "[]" if read == "pulls" else "main\n"
    answers = GhAnswers((1, "", BAD_GATEWAY), (0, out, ""))
    got = read_pulls(REPO, answers, answers.pause) if read == "pulls" else read_branch(REPO, answers, answers.pause)
    assert got == ([] if read == "pulls" else "main")
    assert len(answers.ran) == 2 and answers.ran[0] == answers.ran[1]
    assert answers.paused == [GH_PAUSE]


@pytest.mark.parametrize("read", ["pulls", "branch"])
def test_s011_11_status_says_rerun_after_a_second_transient_failure(read: str) -> None:
    answers = GhAnswers((1, "", BAD_GATEWAY), (1, "", "read: connection reset by peer"))
    with pytest.raises(ReleaseError, match=r"connection reset by peer; transient GitHub API error: rerun$"):
        read_pulls(REPO, answers, answers.pause) if read == "pulls" else read_branch(REPO, answers, answers.pause)
    assert len(answers.ran) == 2


@pytest.mark.parametrize(
    "error", ["HTTP 401: Bad credentials (https://api.github.com/graphql)", "gh: Not Found (HTTP 404)"]
)
def test_s011_11_status_never_reruns_an_auth_or_not_found_failure(error: str) -> None:
    answers = GhAnswers((1, "", error))
    with pytest.raises(ReleaseError) as failed:
        read_branch(REPO, answers, answers.pause)
    assert (len(answers.ran), answers.paused) == (1, [])
    assert "transient" not in str(failed.value)


def test_s011_17_the_pull_request_read_asks_for_the_merge_state() -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        out = [{"number": 8, "isDraft": False, "mergeStateStatus": "BEHIND", "baseRefName": "main"}]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    assert read_pulls(REPO, run) == [Pull(8, False, "BEHIND", "main")]
    assert "number,isDraft,mergeStateStatus,baseRefName" in seen[0]


def test_s011_18_in_progress_names_its_pull_requests_and_parked_says_why() -> None:
    issues = [
        Issue(389, "IN_PROGRESS", "#409:open #410:merged(part) #411:open(part)"),
        Issue(30, "BLOCKED", "acme/web#5:open"),
        Issue(29, "BLOCKED", "acme/web#5:open other/lib#7:closed"),
        Issue(28, "BLOCKED", "labelled blocked"),
        Issue(27, "POSTPONED"),
        Issue(26, "TRIAGED"),
    ]
    text = lines(facts(issues=issues))
    assert f"  in progress    #389 {URL}/issues/389 → #409 {URL}/pull/409, #411 {URL}/pull/411" in text
    at = text.index(
        f"  parked         #30 {URL}/issues/30 waits on acme/web#5 (open); unblocks when it closes or merges"
    )
    assert text[at + 1 : at + 5] == [
        f"                 #29 {URL}/issues/29 waits on acme/web#5 (open), other/lib#7 (closed); "
        "unblocks when they close or merge",
        f"                 #28 {URL}/issues/28 labelled blocked: gh issue edit 28 -R {REPO} --remove-label blocked "
        "once it can go on",
        f"                 #27 {URL}/issues/27 postponed",
        f"                 #26 {URL}/issues/26 triaged",
    ]


def test_a_parked_issues_native_marks_and_parent_progress_read_plainly() -> None:
    # triage_state.py's note marks a forge-only hold (native) and a sub-issue (child), and
    # a parent's starts with its children's progress (#340)
    issues = [
        Issue(31, "BLOCKED", "children 1/2 closed acme/web#4:closed(child) acme/web#5:open(child)"),
        Issue(32, "BLOCKED", "acme/web#2:open other/lib#7:not_planned(native)"),
    ]
    text = lines(facts(issues=issues))
    at = text.index(
        f"  parked         #32 {URL}/issues/32 waits on acme/web#2 (open), other/lib#7 (not_planned, native); "
        "unblocks when they close or merge"
    )
    assert text[at + 1] == (
        f"                 #31 {URL}/issues/31 waits on acme/web#4 (closed, child), acme/web#5 (open, child); "
        "children 1/2 closed; unblocks when they close or merge"
    )


def test_s011_18_no_title_reaches_the_summary() -> None:
    marker = "MARKER-TITLE"
    printed = [
        {"number": 3, "state": "IN_PROGRESS", "title": marker, "note": "#9:open"},
        {"number": 4, "state": "BLOCKED", "title": marker, "note": "labelled blocked"},
        {"number": 5, "state": "NEEDS_DECISION", "title": marker, "note": ""},
    ]
    issues = parse_issues("".join(json.dumps(r) + "\n" for r in printed))
    found = facts(Row("PRS_OPEN", REPO, "#9", False), issues=issues, pulls=[Pull(9, True, "BEHIND", "main")])
    assert marker not in report(found).text(REPO)
    assert all(marker not in r.fix for r in report(found).reasons)


def test_s011_19_each_draft_names_the_command_that_readies_it() -> None:
    found = facts(pulls=[Pull(12, True, "DRAFT", "main"), Pull(11, True, "DRAFT", "main")])
    text = lines(found)
    at = text.index(f"  drafts         #12 {URL}/pull/12: gh pr ready 12 -R {REPO} once it is ready")
    assert text[at + 1] == f"                 #11 {URL}/pull/11: gh pr ready 11 -R {REPO} once it is ready"
