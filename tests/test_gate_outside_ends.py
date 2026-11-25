"""Spec 095: a session that ended ok after an outside failure records that failure, not idle:
GitHub's rate limit (github_limit) and a full disk (disk) pause the host, a network failure
ends error (D-112), and a denied permission ends nothing and notifies once per tool (D-113)"""

import dataclasses
import datetime as dt
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.agents import Mode
from shipmill.autonomy import Autonomy, AutonomyPolicy
from shipmill.errors import ReleaseError
from shipmill.gate import (
    DEAD_STREAK,
    DENIED_RECORD,
    RECORD,
    Action,
    Decision,
    input_command,
    load_launch,
    session_end,
    state_dir,
)
from shipmill.gitrepo import Git
from shipmill.host_pause import (
    DISK_FLOOR,
    GITHUB_WINDOW,
    HostPause,
    HostSeams,
    Rate,
    host_dir,
    load_host_pause,
    rate_of,
    save_host_pause,
)
from shipmill.item_status import Who
from shipmill.status import Pull, Row, Verdict, report
from shipmill.walk import HANDED, End, Hand, Handed

from .test_gate import FakeClaude, FakeNotifier, checkout
from .test_gate_ends import INIT, OK, SAID, SESSION, launch, logged
from .test_gate_pause import SESSION as LAUNCHED
from .test_gate_walk import INCIDENT, NOW, Source, cfg, handed, tick
from .test_gate_walk import REPO as GATE_REPO
from .test_status_item import whos
from .test_status_picture import REPO, facts, gate, job
from .test_watch_gate_idle import ws

__all__ = ["checkout", "ws"]  # the fixtures, imported for the tests below

RESET = 1795633200  # 2026-11-25T13:00:00Z


def failed(text: object, tool_use_id: str = "t1") -> dict[str, object]:
    """A user event carrying one failed tool result whose content is text"""
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": text, "is_error": True}
    return {"type": "user", "message": {"content": [block]}}


def used(tool: str, command: str, tool_use_id: str = "t1") -> dict[str, object]:
    block = {"type": "tool_use", "id": tool_use_id, "name": tool, "input": {"command": command}}
    return {"type": "assistant", "message": {"content": [block]}}


GH_LIMIT = failed("gh: API rate limit already exceeded for user ID 1. (HTTP 403)")
DISK_FULL = failed([{"type": "text", "text": "error: unable to write file: No space left on device"}])
DENIED = failed("Permission for this tool use was denied: this session has no approval surface")
NETWORK = failed("fatal: unable to access 'https://github.com/': Could not resolve host: github.com")
DENIALS = {
    **OK,
    "permission_denials": [
        {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "rm -rf tmp"}},
        {"tool_name": "Bash", "tool_use_id": "t2", "tool_input": {"command": "ls"}},
        {"tool_name": "WebFetch", "tool_use_id": "t3", "tool_input": {"url": "https://example.com"}},
    ],
}


# -- S-095-1: the cause, read from the failed tool results before ok


@pytest.mark.parametrize(
    ("lines", "end"),
    [
        ((INIT, used("Bash", "gh pr list"), GH_LIMIT, SAID, OK), End.GITHUB_LIMIT),
        ((INIT, failed("You have exceeded a secondary rate limit"), OK), End.GITHUB_LIMIT),
        ((INIT, DISK_FULL, OK), End.DISK),
        ((INIT, NETWORK, OK), End.ERROR),
        ((INIT, failed("dial tcp: connection timed out"), OK), End.ERROR),
        # the order: github_limit, disk, then the network; a denial beside them changes none
        ((INIT, NETWORK, DENIED, DISK_FULL, GH_LIMIT, OK), End.GITHUB_LIMIT),
        ((INIT, NETWORK, DENIED, DISK_FULL, OK), End.DISK),
        ((INIT, NETWORK, DENIED, OK), End.ERROR),
    ],
)
def test_s095_1_an_ok_session_whose_tool_calls_failed_on_an_outside_cause_records_it(
    tmp_path: Path, lines: tuple[object, ...], end: End
) -> None:
    logged(tmp_path, *lines)
    assert session_end(tmp_path, launch(), SESSION) is end


@pytest.mark.parametrize(
    "lines",
    [
        (INIT, failed("FAILED tests/test_x.py::test_y - AssertionError"), OK),  # any other failure
        # the same words in a tool result that didn't fail, or in the assistant's text, are no cause
        (
            INIT,
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "No space left on device"}]}},
            OK,
        ),
        (
            INIT,
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "API rate limit exceeded"}]}},
            OK,
        ),
        (INIT, {**OK, "permission_denials": []}, OK),
        # a denied permission is no end (D-113), listed or read in a failed tool result
        (INIT, used("Bash", "rm -rf tmp"), DENIED, OK),
        (INIT, failed("Permission to use Bash has been denied."), OK),
        (INIT, DENIALS),
    ],
)
def test_s095_1_a_session_whose_failed_tool_calls_read_no_outside_cause_ends_ok(
    tmp_path: Path, lines: tuple[object, ...]
) -> None:
    logged(tmp_path, *lines)
    assert session_end(tmp_path, launch(), SESSION) is End.OK


def test_s095_1_spec_089s_ends_come_first(tmp_path: Path) -> None:
    limited = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429}
    logged(tmp_path, INIT, GH_LIMIT, limited)
    assert session_end(tmp_path, launch(), SESSION) is End.LIMIT
    logged(tmp_path, INIT, GH_LIMIT, {"type": "result", "subtype": "error_during_execution", "is_error": True})
    assert session_end(tmp_path, launch(), SESSION) is End.ERROR


@pytest.mark.parametrize(
    "event",
    [
        {**OK, "permission_denials": "Bash"},
        {**OK, "permission_denials": [{"tool_input": {}}]},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": "yes"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": 7, "is_error": True}]}},
    ],
)
def test_s095_1_a_malformed_tool_result_or_denial_fails_fast(tmp_path: Path, event: object) -> None:
    logged(tmp_path, INIT, event, OK)
    with pytest.raises(ReleaseError, match="malformed"):
        session_end(tmp_path, launch(), SESSION)


# -- S-095-2: handed.json records the new ends; their hands drop and count no attempt


def test_s095_2_handed_json_and_the_watch_read_the_new_ends(ws: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / HANDED
    hands = {f"ISSUES VERIFY_DUE #{n}": Hand("s", NOW, ended=e) for n, e in enumerate(End, start=1)}
    Handed(hands).save(path)
    assert Handed.load(path) == Handed(hands)
    assert set(ws.ENDS) == {e.value for e in End}
    assert ws.idle_rows(path, NOW + dt.timedelta(days=2)) == []


@pytest.mark.parametrize("end", [End.GITHUB_LIMIT, End.DISK])
def test_s095_2_a_hand_that_ended_on_an_outside_cause_drops_never_idle_and_keeps_no_backoff(end: End) -> None:
    hands = {
        "ISSUES VERIFY_DUE #1": Hand("a", NOW, ended=end, errors=2),
        "ISSUES VERIFY_DUE #2": Hand("b", NOW, ended=End.OK),
    }
    found = Handed(hands).settled(["ISSUES VERIFY_DUE #1"], lambda h: NOW, dt.timedelta(hours=24))
    assert found == Handed({"ISSUES VERIFY_DUE #2": Hand("b", NOW, ended=End.OK)})


class HostGate:
    """A headless gate whose host pauses live in folder, the rate probe and free space given"""

    def __init__(self, git: Git, folder: Path, **keys: Any) -> None:
        self.git, self.folder = git, folder
        self.claude, self.notifier = FakeClaude(), FakeNotifier()
        self.agents = cfg(Mode.HEADLESS, **keys)
        self.rate: Rate | None = Rate(False, dt.datetime.fromtimestamp(RESET, tz=dt.UTC))
        self.free = DISK_FLOOR * 10
        self.probed = 0

    def probe(self) -> Rate | None:
        self.probed += 1
        return self.rate

    def tick(self, now: dt.datetime, signature: str = "sig") -> Decision:
        seams = HostSeams(self.folder, self.probe, lambda _: self.free)
        source = Source({1: [INCIDENT]}, signature=signature)
        return tick(self.git, source, now, self.agents, self.claude, self.notifier, host_seams=seams)

    def ended(self, *events: object) -> None:
        """The launched session's log: these events, written a minute after NOW"""
        logged(state_dir(self.git), *events, session=LAUNCHED, seconds=60)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "state" / "shipmill" / "host"


def test_s095_2_a_session_that_was_denied_a_tool_keeps_its_ok_hand_and_is_not_handed_again(
    checkout: Git, folder: Path
) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    gate.ended(INIT, DENIALS)
    for round in range(DEAD_STREAK + 1):  # the unchanged subject waits, as any ok end's does (D-113)
        decision = gate.tick(NOW + dt.timedelta(minutes=10 * (round + 1)))
        assert decision.dead is None and len(gate.claude.started) == 1
    assert len(handed(checkout)) == 1  # its hand kept, not dropped as a caused end's is


# -- S-095-3: the host's record


def test_s095_3_the_host_pause_lives_beside_the_credentials(tmp_path: Path) -> None:
    assert host_dir({"XDG_STATE_HOME": str(tmp_path)}, Path("/home/u")) == tmp_path / "shipmill" / "host"
    assert host_dir({}, Path("/home/u")) == Path("/home/u/.local/state/shipmill/host")
    with pytest.raises(ReleaseError, match="absolute"):
        host_dir({"XDG_STATE_HOME": "rel"}, Path("/home/u"))


def test_s095_3_a_github_limit_end_writes_the_hosts_pause_with_the_spent_resets_reset(
    checkout: Git, folder: Path
) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    gate.ended(INIT, GH_LIMIT, OK)
    gate.tick(NOW + dt.timedelta(minutes=10))
    data = json.loads((folder / "github_limit.json").read_text())
    resets = dt.datetime.fromtimestamp(RESET, tz=dt.UTC)
    assert data == {
        "cause": "github_limit",
        "session": LAUNCHED,
        "at": (NOW + dt.timedelta(minutes=1)).isoformat(),
        "resets_at": resets.isoformat(),
    }


def test_s095_3_a_disk_end_writes_the_hosts_pause(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    gate.ended(INIT, DISK_FULL, OK)
    gate.free = 100
    gate.tick(NOW + dt.timedelta(minutes=10))
    assert json.loads((folder / "disk.json").read_text()) == {
        "cause": "disk",
        "session": LAUNCHED,
        "at": (NOW + dt.timedelta(minutes=1)).isoformat(),
    }


def test_s095_3_the_rate_reads_the_latest_reset_of_a_spent_resource() -> None:
    def text(core: int, graphql: int) -> str:
        res = {"core": {"remaining": core, "reset": RESET - 600}, "graphql": {"remaining": graphql, "reset": RESET}}
        return json.dumps({"resources": res})

    at = dt.datetime.fromtimestamp
    assert rate_of(text(0, 0)) == Rate(False, at(RESET, tz=dt.UTC))
    assert rate_of(text(0, 5)) == Rate(False, at(RESET - 600, tz=dt.UTC))
    assert rate_of(text(5, 5)) == Rate(True, None)
    for bad in ("not json", "{}", json.dumps({"resources": {"core": {"remaining": "1", "reset": 1}}})):
        assert rate_of(bad) is None


def test_s095_3_a_host_pause_file_shipmill_doesnt_write_is_refused(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "disk.json").write_text(json.dumps({"cause": "github_limit", "session": "s", "at": NOW.isoformat()}))
    with pytest.raises(ReleaseError, match="malformed"):
        load_host_pause(folder, End.DISK)


# -- S-095-4: a host pause starts nothing on any gate and counts no attempt


def test_s095_4_while_the_hosts_pause_holds_any_gate_starts_nothing_and_reads_paused(
    checkout: Git, folder: Path
) -> None:
    save_host_pause(folder, HostPause(End.GITHUB_LIMIT, "another-gates-session", NOW, NOW + dt.timedelta(hours=1)))
    gate = HostGate(checkout, folder)  # a gate that never launched: no dead session of its own
    for minutes in (0, 10, 20):
        decision = gate.tick(NOW + dt.timedelta(minutes=minutes))
        assert decision.action is Action.PAUSED and not gate.claude.started
        assert decision.reason == (
            "github_limit: GitHub's rate limit stopped session another-gates-session; "
            "no session starts until gh api rate_limit shows room"
        )


def test_s095_4_a_host_pause_counts_no_attempt_against_the_item_that_hit_it(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    for round in range(DEAD_STREAK + 1):
        gate.ended(INIT, GH_LIMIT, OK)
        at = NOW + dt.timedelta(days=round + 1)
        save_host_pause(folder, HostPause(End.GITHUB_LIMIT, LAUNCHED, at, None, at))  # as a lift leaves it
        decision = gate.tick(at)
        assert decision.action is Action.SESSION_DEAD and decision.work == (INCIDENT,)
        found = load_launch(state_dir(checkout) / RECORD)
        assert found is not None and found.deaths is None


# -- S-095-5: a github_limit pause lifts on the probe, else by the clock


def test_s095_5_the_first_tick_whose_probe_shows_room_lifts_it(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    gate.ended(INIT, GH_LIMIT, OK)
    assert gate.tick(NOW + dt.timedelta(minutes=10)).action is Action.PAUSED
    assert gate.tick(NOW + dt.timedelta(minutes=20)).action is Action.PAUSED  # past no clock: the probe reads none
    gate.rate = Rate(True, None)
    assert gate.tick(NOW + dt.timedelta(minutes=30)).action is not Action.PAUSED
    found = load_host_pause(folder, End.GITHUB_LIMIT)
    assert found is not None and found.lifted == NOW + dt.timedelta(minutes=30)


@pytest.mark.parametrize("resets", [True, False], ids=["at-its-reset", "an-hour-on"])
def test_s095_5_an_unread_probe_lifts_it_at_its_reset_or_an_hour_after_the_end(
    checkout: Git, folder: Path, resets: bool
) -> None:
    at = NOW + dt.timedelta(minutes=5)
    lifts = at + dt.timedelta(minutes=30) if resets else at + GITHUB_WINDOW
    save_host_pause(folder, HostPause(End.GITHUB_LIMIT, "s0", at, lifts if resets else None))
    gate = HostGate(checkout, folder)
    gate.rate = None
    before = gate.tick(lifts - dt.timedelta(minutes=1))
    assert before.action is Action.PAUSED and lifts.isoformat(timespec="minutes") in before.reason
    assert gate.tick(lifts).action is not Action.PAUSED


# -- S-095-6: a disk pause lifts once the floor is free


def test_s095_6_a_disk_pause_holds_below_the_floor_and_lifts_at_it(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder)
    gate.tick(NOW)
    gate.ended(INIT, DISK_FULL, OK)
    gate.free = DISK_FLOOR - 1
    decision = gate.tick(NOW + dt.timedelta(minutes=10))
    assert decision.action is Action.PAUSED
    assert decision.reason.startswith(f"disk: no space left on device stopped session {LAUNCHED}")
    assert f"until {checkout.root} has 2.0 GiB free, it has 2.0 GiB" in decision.reason
    assert decision.reason.endswith(
        f"fix: free space on the file system holding {checkout.root}: the gate launches again at 2.0 GiB free"
    )
    gate.free = DISK_FLOOR
    assert gate.tick(NOW + dt.timedelta(minutes=20)).action is not Action.PAUSED


def test_s095_6_shipmill_status_names_the_disk_pause_with_its_fix() -> None:
    fix = "free space on the file system holding /u/demo: the gate launches again at 2.0 GiB free"
    last = (
        "PAUSED: disk: no space left on device stopped session s0; no session starts until /u/demo "
        f"has 2.0 GiB free, it has 0.1 GiB; fix: {fix}"
    )
    found = report(facts(gate=gate(job=job(last=last))))
    assert found.verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in found.reasons] == [(f"the gate: {last}", fix)]
    limit = (
        "PAUSED: github_limit: GitHub's rate limit stopped session s0; "
        "no session starts until gh api rate_limit shows room"
    )
    assert report(facts(gate=gate(job=job(last=limit)))).verdict is not Verdict.WAITS  # it lifts by itself


# -- S-095-7: one notification per denied tool


def test_s095_7_a_denied_tool_notifies_once_and_the_session_keeps_its_end(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder, notify=True)
    gate.tick(NOW)
    gate.ended(INIT, DENIALS)
    decision = gate.tick(NOW + dt.timedelta(minutes=10))
    assert decision.dead is None and len(gate.claude.started) == 1  # ended ok: the tick is as without it
    assert gate.notifier.sent == [
        (
            f"shipmill {GATE_REPO}",
            f"session {LAUNCHED} was denied Bash (rm -rf tmp): allow it in the gate's allowlist or "
            "[agents.sandbox], or leave it denied",
        ),
        (
            f"shipmill {GATE_REPO}",
            f"session {LAUNCHED} was denied WebFetch (https://example.com): allow it in the gate's "
            "allowlist or [agents.sandbox], or leave it denied",
        ),
    ]
    assert decision.denied[0].startswith("notified: session")
    record = json.loads((state_dir(checkout) / DENIED_RECORD).read_text())
    assert set(record) == {"Bash", "WebFetch"}
    assert record["Bash"] == {
        "command": "rm -rf tmp",
        "session": LAUNCHED,
        "at": (NOW + dt.timedelta(minutes=10)).isoformat(),
        "notified": (NOW + dt.timedelta(minutes=10)).isoformat(),
    }
    gate.ended(INIT, used("Bash", "git push"), DENIED, OK)  # a later denial of a recorded tool
    assert gate.tick(NOW + dt.timedelta(minutes=20)).denied == ()
    assert len(gate.notifier.sent) == 2


def test_s095_7_a_denial_read_from_a_tool_result_names_its_tool_use(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder, notify=True)
    gate.tick(NOW)
    gate.ended(
        INIT,
        used("Bash", "uvx shipmill gh pr merge 3", "u9"),
        failed("Permission for this tool use was denied", "u9"),
        OK,
    )
    gate.tick(NOW + dt.timedelta(minutes=10))
    assert [body for _, body in gate.notifier.sent] == [
        f"session {LAUNCHED} was denied Bash (uvx shipmill gh pr merge 3): allow it in the gate's allowlist or "
        "[agents.sandbox], or leave it denied"
    ]


def test_s095_7_a_dead_session_that_was_denied_a_tool_notifies_too(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder, notify=True)
    gate.tick(NOW)
    gate.ended(INIT, {**DENIALS, "subtype": "error_during_execution", "is_error": True})
    decision = gate.tick(NOW + dt.timedelta(minutes=10))
    assert decision.dead is not None and decision.dead.end is End.ERROR
    assert [body.split(":")[0] for _, body in gate.notifier.sent] == [
        f"session {LAUNCHED} was denied Bash (rm -rf tmp)",
        f"session {LAUNCHED} was denied WebFetch (https",
    ]


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        ({"command": "rm -rf tmp"}, "rm -rf tmp"),
        ({"command": "cat > a <<'EOF'\nTOKEN=secret\nEOF"}, "cat > a <<'EOF'"),
        ({"command": "x" * 200}, "x" * 119 + "…"),
        ({"url": "https://example.com"}, "https://example.com"),
        ("not an input", ""),
    ],
)
def test_s095_7_a_denied_command_shows_its_first_line_cut_at_120_characters(given: object, shown: str) -> None:
    assert input_command(given) == shown


def test_s095_7_a_failed_send_is_tried_again_next_tick_and_notify_off_sends_none(checkout: Git, folder: Path) -> None:
    gate = HostGate(checkout, folder, notify=True)
    gate.tick(NOW)
    gate.ended(INIT, DENIALS)
    gate.notifier.fail = "no notifier"
    failed_tick = gate.tick(NOW + dt.timedelta(minutes=10))
    assert failed_tick.denied == (
        "notify failed for denied Bash: no notifier",
        "notify failed for denied WebFetch: no notifier",
    )
    gate.notifier.fail = None
    gate.ended(INIT, DENIALS)
    assert len(gate.tick(NOW + dt.timedelta(minutes=20)).denied) == 2 and len(gate.notifier.sent) == 2
    quiet = HostGate(checkout, folder, notify=False)  # notify off: recorded, nothing sent
    (state_dir(checkout) / DENIED_RECORD).unlink()
    quiet.ended(INIT, DENIALS)
    assert quiet.tick(NOW + dt.timedelta(minutes=30)).denied == () and not quiet.notifier.sent
    assert set(json.loads((state_dir(checkout) / DENIED_RECORD).read_text())) == {"Bash", "WebFetch"}


# -- S-095-8: status and the watch print GATE_PAUSED for the host's pause


def test_s095_8_the_watch_prints_gate_paused_for_a_host_pause(ws: ModuleType, folder: Path) -> None:
    resets = NOW + dt.timedelta(minutes=40)
    save_host_pause(folder, HostPause(End.GITHUB_LIMIT, "s1", NOW, resets))
    save_host_pause(folder, HostPause(End.DISK, "s2", NOW))
    rows = ws.host_paused_rows(folder)
    assert [(r.state, r.subject) for r in rows] == [("GATE_PAUSED", "github_limit"), ("GATE_PAUSED", "disk")]
    assert rows[0].detail == (
        f"until gh api rate_limit shows room, {resets:%Y-%m-%d %H:%M} UTC by the clock: "
        "GitHub's rate limit stopped session s1"
    )
    assert rows[1].detail == "until 2.0 GiB free: no space left on device stopped session s2" and rows[1].fix
    save_host_pause(folder, HostPause(End.DISK, "s2", NOW, None, NOW))  # lifted: no row
    assert [r.subject for r in ws.host_paused_rows(folder)] == ["github_limit"]
    (folder / "disk.json").write_text(json.dumps({"cause": "disk", "session": 1, "at": NOW.isoformat()}))
    with pytest.raises(ws.Refused):
        ws.host_paused_rows(folder)


def test_s095_8_status_item_names_the_hosts_pause_instead_of_a_coming_tick() -> None:
    pulls = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    pulls = dataclasses.replace(pulls, autonomy=AutonomyPolicy(land=Autonomy.ACT))
    limit = Row(
        "GATE_PAUSED", "github_limit", "until gh api rate_limit shows room, 2026-11-25 13:00 UTC by the clock: x", False
    )
    assert whos(dataclasses.replace(pulls, rows=[*pulls.rows, limit]), 9)[-1] == (
        "the gate starts no session until gh api rate_limit shows room, 2026-11-25 13:00 UTC by the clock, "
        "paused by GitHub's rate limit",
        Who.EVENT,
    )
    disk = Row("GATE_PAUSED", "disk", "until 2.0 GiB free: no space left on device", False, "free space")
    assert whos(dataclasses.replace(pulls, rows=[*pulls.rows, disk]), 9)[-1] == (
        "the gate starts no session until 2.0 GiB free, paused by a full disk",
        Who.MAINTAINER,
    )
    text = "\n".join(report(facts(disk)).lines)
    assert "GATE_PAUSED disk until 2.0 GiB free" in text
