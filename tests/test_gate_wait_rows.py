"""Spec 089 (S-089-13): `shipmill status` and watch_state.py name why the gate waits. A paused
credential is one GATE_PAUSED row with its cause and when it ends; an item in backoff is a
GATE_RETRY row with the item, the time, and the run; `shipmill status --item N` says the pause
or the backoff for an item it holds, instead of "the gate takes it up on a coming tick\""""

import dataclasses
import datetime as dt
import hashlib
import json
import plistlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.autonomy import Autonomy, AutonomyPolicy
from shipmill.claude_pause import Pause, credential_id, pause_path, save_pause
from shipmill.claude_token import PREFIX, Token
from shipmill.item_status import Who
from shipmill.status import Pull, Row, Verdict, report
from shipmill.walk import HANDED, End, Hand, Handed, Head

from .test_status_item import whos
from .test_status_picture import REPO, facts, gate, job
from .test_watch_gate_idle import Host, host, rows, ws

__all__ = ["host", "ws"]  # the fixtures, imported for the tests below

UTC = dt.timezone.utc  # noqa: UP017 (the script runs under 3.10 too)
NOW = dt.datetime(2026, 11, 25, 6, 0, tzinfo=UTC)
TOKEN = f"{PREFIX}01-fake\n"  # built from the prefix, so no line holds a token-shaped string
RESETS = NOW + dt.timedelta(hours=2)


def token_at(path: Path) -> Path:
    path.write_text(TOKEN, encoding="utf-8")
    return path


# -- GATE_PAUSED


def test_s089_13_the_watch_names_the_credential_as_the_gate_does(ws: ModuleType, tmp_path: Path) -> None:
    path = token_at(tmp_path / "claude-token")
    assert ws.credential_name(path) == credential_id(Token(path, TOKEN.strip(), NOW))
    assert ws.credential_name(path) == hashlib.sha256(TOKEN.encode()).hexdigest()[:16]
    assert ws.credential_name(tmp_path / "none") == "login"
    assert ws.pauses_folder({"XDG_STATE_HOME": ""}, tmp_path) == tmp_path / ".local" / "state" / "shipmill" / "claude"
    assert ws.token_file(["shipmill", "--claude-token", "/x/t", "gate", REPO], tmp_path) == Path("/x/t")
    assert ws.token_file(["shipmill", "gate", REPO], tmp_path) == tmp_path / ".config" / "shipmill" / "claude-token"


def test_s089_13_a_limit_pause_is_one_gate_paused_row_with_its_end(ws: ModuleType, tmp_path: Path) -> None:
    token = token_at(tmp_path / "claude-token")
    named = ws.credential_name(token)
    save_pause(tmp_path, named, Pause(End.LIMIT, "s0", NOW, RESETS))
    (row,) = ws.paused_rows(tmp_path, token, 24, NOW)
    assert (row.state, row.subject, row.fix) == ("GATE_PAUSED", "limit", None)
    assert row.detail == "until 2026-11-25 08:00 UTC, or once /usage shows room: a usage limit stopped session s0"
    save_pause(tmp_path, named, Pause(End.LIMIT, "s0", NOW))  # no resetsAt: retry_hours after it began
    (row,) = ws.paused_rows(tmp_path, token, 24, NOW)
    assert row.detail.startswith("until 2026-11-26 06:00 UTC")
    assert ws.paused_rows(tmp_path, token, 24, NOW + dt.timedelta(hours=25)) == []  # it lifts on the next tick
    assert PREFIX not in json.dumps([r.json() for r in ws.paused_rows(tmp_path, token, 24, NOW)])


def test_s089_13_an_auth_pause_waits_for_a_new_token_or_a_login_with_its_fix(ws: ModuleType, tmp_path: Path) -> None:
    token = token_at(tmp_path / "claude-token")
    save_pause(tmp_path, ws.credential_name(token), Pause(End.AUTH, "s0", NOW))
    (row,) = ws.paused_rows(tmp_path, token, 24, NOW)
    assert (row.subject, row.detail.partition(":")[0]) == ("auth", "until the token changes")
    assert row.fix == f"the token in {token} was not accepted; run claude setup-token and save it to {token}"
    login = tmp_path / "none"
    save_pause(tmp_path, "login", Pause(End.AUTH, "s1", NOW))
    (row,) = ws.paused_rows(tmp_path, login, 24, NOW)
    assert row.detail.startswith("until claude auth status reports a login") and row.fix == "claude auth login"


def test_s089_13_a_lifted_pause_or_another_credentials_gives_no_row(ws: ModuleType, tmp_path: Path) -> None:
    token = token_at(tmp_path / "claude-token")
    save_pause(tmp_path, ws.credential_name(token), Pause(End.LIMIT, "s0", NOW, RESETS, None, NOW))
    save_pause(tmp_path, "login", Pause(End.AUTH, "s1", NOW))
    assert ws.paused_rows(tmp_path, token, 24, NOW) == []


def test_s089_13_a_pause_file_shipmill_doesnt_write_is_refused(ws: ModuleType, tmp_path: Path) -> None:
    pause_path(tmp_path, "login").write_text(json.dumps({"cause": "dead", "session": "s", "at": NOW.isoformat()}))
    with pytest.raises(ws.Refused, match="cause must be limit or auth"):
        ws.paused_rows(tmp_path, tmp_path / "none", 24, NOW)


# -- GATE_RETRY


def test_s089_13_each_hand_in_backoff_is_a_gate_retry_row_soonest_first(ws: ModuleType, tmp_path: Path) -> None:
    head = Head("a" * 40, "SUCCESS")
    hands = {
        "PRS_OPEN #3": Hand("s0", NOW, head, ended=End.ERROR, errors=2, until=NOW + dt.timedelta(hours=1)),
        "f00dfacecafe1234": Hand("s1", NOW, ended=End.ERROR, errors=1, until=NOW + dt.timedelta(minutes=15)),
        "PRS_OPEN #4": Hand("s2", NOW, head, ended=End.ERROR, errors=1, until=NOW - dt.timedelta(minutes=1)),
        "ISSUES NEW #5": Hand("s3", NOW),
    }
    Handed(hands).save(tmp_path / HANDED)
    record = tmp_path / "gate.json"
    record.write_text(json.dumps({"fingerprint": "f00dfacecafe1234", "item": "INCIDENT_OPEN #9"}), encoding="utf-8")
    rows = ws.retry_rows(tmp_path / HANDED, record, NOW)
    assert [(r.state, r.subject, r.detail) for r in rows] == [
        ("GATE_RETRY", "INCIDENT_OPEN #9", "after 2026-11-25 06:15 UTC: 1 error ends in a row"),
        ("GATE_RETRY", "PRS_OPEN #3", "after 2026-11-25 07:00 UTC: 2 error ends in a row"),
    ]  # #4's backoff ended: the gate hands it on its next tick
    assert not any(r.json()["agent"] for r in rows)


# -- shipmill status


def test_s089_13_shipmill_status_prints_both_rows_with_the_pauses_fix() -> None:
    paused = Row("GATE_PAUSED", "auth", "until the token changes: its token was refused for session s0", False, "x")
    retry = Row("GATE_RETRY", "PRS_OPEN #3", "after 2026-11-25 07:00 UTC: 2 error ends in a row", False)
    text = "\n".join(report(facts(paused, retry)).lines)
    assert "GATE_PAUSED auth until the token changes" in text and "x" in text
    assert "GATE_RETRY PRS_OPEN #3 after 2026-11-25 07:00 UTC: 2 error ends in a row" in text


@pytest.mark.parametrize(
    "fix", ["claude auth login", "the token in /u/t was not accepted; run claude setup-token and save it to /u/t"]
)
def test_s089_13_an_auth_pause_waits_on_you_in_shipmill_status(fix: str) -> None:
    # the tick's PAUSED replaces the SESSION_DEAD that read STUCK before spec 089: a refused
    # credential still waits on a person, never "nothing to do"
    last = (
        f"PAUSED: auth: a refused credential stopped session s0; no session starts until the token changes; fix: {fix}"
    )
    paused = Row("GATE_PAUSED", "auth", "until the token changes: its token was refused for session s0", False, fix)
    found = report(facts(paused, gate=gate(job=job(last=last))))
    assert found.verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in found.reasons] == [(f"the gate: {last}", fix)]
    limit = "PAUSED: limit: a usage limit stopped session s0; no session starts until 2026-11-25T08:00+00:00"
    assert report(facts(gate=gate(job=job(last=limit)))).verdict is not Verdict.WAITS  # it lifts by itself


def test_s089_13_status_item_names_the_backoff_or_the_pause_instead_of_a_coming_tick() -> None:
    pulls = facts(Row("PRS_OPEN", REPO, "#9", False), pulls=[Pull(9, False, "CLEAN", "main")])
    pulls = dataclasses.replace(pulls, autonomy=AutonomyPolicy(land=Autonomy.ACT))
    retry = Row("GATE_RETRY", "PRS_OPEN #9", "after 2026-11-25 07:00 UTC: 2 error ends in a row", False)
    held = dataclasses.replace(pulls, rows=[*pulls.rows, retry])
    assert whos(held, 9)[-1] == ("the gate hands it again after 2026-11-25 07:00 UTC: 2 error ends in a row", Who.AGENT)
    limit = Row("GATE_PAUSED", "limit", "until 2026-11-25 08:00 UTC, or once /usage shows room: a usage limit", False)
    paused = dataclasses.replace(pulls, rows=[*pulls.rows, limit])
    assert whos(paused, 9)[-1] == (
        "the gate starts no session until 2026-11-25 08:00 UTC, or once /usage shows room, paused by a usage limit",
        Who.EVENT,
    )
    auth = Row("GATE_PAUSED", "auth", "until the token changes: its token was refused", False, "claude setup-token")
    refused = dataclasses.replace(pulls, rows=[*pulls.rows, auth])
    assert whos(refused, 9)[-1] == (
        "the gate starts no session until the token changes, paused by a refused credential",
        Who.MAINTAINER,
    )


def test_s089_13_status_item_reads_the_pause_whatever_it_names(ws: ModuleType) -> None:
    assert ws.item_row(ws.Row("GATE_PAUSED", "limit", "until ..."), 9)
    assert ws.item_row(ws.Row("GATE_RETRY", "PRS_OPEN #9", "after ..."), 9)
    assert not ws.item_row(ws.Row("GATE_RETRY", "PRS_OPEN #10", "after ..."), 9)


def test_s089_13_an_unreadable_token_file_gives_no_row_not_a_crash(ws: ModuleType, tmp_path: Path) -> None:
    # the gate refuses a file its user can't read (CLAUDE_AUTH) and starts no session with it,
    # so no pause names it; the watch reads the rest of its report
    token = token_at(tmp_path / "claude-token")
    save_pause(tmp_path, "login", Pause(End.AUTH, "s1", NOW))
    token.chmod(0o000)
    try:
        assert ws.paused_rows(tmp_path, token, 24, NOW) == []
    finally:
        token.chmod(0o600)


@pytest.mark.skipif(sys.platform != "darwin", reason="the gate's launchd job is a Mac's")
def test_s089_13_the_watch_reads_the_pause_where_the_launchd_gate_writes_it(host: Host) -> None:
    # launchd gives the gate's tick only its job's EnvironmentVariables, none of them
    # XDG_STATE_HOME, so its pauses are under ~/.local/state whatever the person's shell sets
    agents = host.tmp / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    job = {
        "Label": "dev.shipmill.gate.o.r",
        "ProgramArguments": ["uvx", "shipmill", "--repo", str(host.work), "gate", "o/r"],
        "WorkingDirectory": str(host.work),
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin"},
    }
    (agents / "dev.shipmill.gate.o.r.plist").write_bytes(plistlib.dumps(job))
    save_pause(host.tmp / ".local" / "state" / "shipmill" / "claude", "login", Pause(End.AUTH, "s1", NOW))
    host.env["XDG_STATE_HOME"] = str(host.tmp / "shell-state")
    paused = [r for r in rows(host.watch()) if r["state"] == "GATE_PAUSED"]
    assert [(r["subject"], r["fix"]) for r in paused] == [("auth", "claude auth login")]
