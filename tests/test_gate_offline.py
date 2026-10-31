"""#848: a tick whose uvx couldn't reach PyPI (the first tick after a FileVault login, before
DNS is back) is offline, not STUCK: the gate line says so, names the next run, and keeps
`launchctl kickstart` as its fix. Any other failed run stays STUCK"""

import datetime as dt

import pytest

from shipmill.status import Gate, Job, Verdict, parse_job, report
from tests.test_gate_tick_report import LOG, gate_line
from tests.test_status_picture import FILES, NOW, facts, gate

KICK = "launchctl kickstart gui/501/dev.shipmill.gate.acme.web"
FETCH = "  Caused by: Failed to fetch: `https://pypi.org/simple/shipmill/`"
SENDING = "  Caused by: error sending request for url (https://pypi.org/simple/shipmill/)"
DNS = [
    "error: Request failed after 3 retries",
    FETCH,
    SENDING,
    "  Caused by: client error (Connect)",
    "  Caused by: dns error: failed to lookup address information: nodename nor servname provided, or not known",
    "  Caused by: failed to lookup address information: nodename nor servname provided, or not known",
]
CONNECT = ["error: Request failed after 3 retries", FETCH, SENDING, "  Caused by: client error (Connect)"]
EARLIER = "QUIET: nothing needs an agent"


def read(log: list[str], exit_code: str = "2", ran: dt.timedelta = dt.timedelta(minutes=4)) -> Job:
    printed = f"\tstate = not running\n\tlast exit code = {exit_code}\n"
    return parse_job({"StartInterval": 900}, printed, "\n".join(log) + "\n", NOW - ran, FILES)


def offline(job: Job) -> Gate:
    return gate(job=job)


@pytest.mark.parametrize("tail", [DNS, CONNECT], ids=["dns", "connect"])
def test_848_uvs_network_error_is_offline_not_stuck(tail: list[str]) -> None:
    found = offline(read([EARLIER, *tail]))
    check = gate_line(found)
    assert check.value == "offline at last tick, next in 11 min, launchd every 15 min"
    assert check.fixes == (KICK,)  # S-011: the line keeps a fix
    assert check.ok
    assert report(facts(gate=found)).verdict is not Verdict.STUCK


@pytest.mark.parametrize(
    "tail",
    [
        ["error: Request failed after 3 retries", FETCH, "  Caused by: HTTP status server error (503)"],  # PyPI is down
        ["shipmill: gh api failed: dns error: lookup api.github.com", FETCH],  # shipmill's own failure
        ["Traceback (most recent call last):", '  File "x.py"', "OSError: dns error: client error (Connect)"],
        [*DNS, "Traceback (most recent call last):", '  File "x.py"', "KeyError: 'x'"],  # a later crash
        [*DNS, "error: the checkout is gone"],  # a later failure of another kind
    ],
    ids=["503", "shipmill", "traceback", "later-crash", "later-error"],
)
def test_848_any_other_failed_run_is_still_stuck(tail: list[str]) -> None:
    found = offline(read([EARLIER, *tail]))
    check = gate_line(found)
    assert check.value.startswith("failed: exit 2; failed: ")
    assert "offline" not in check.value
    assert check.fixes == (LOG, LOG)
    assert report(facts(gate=found)).verdict is Verdict.STUCK


def test_848_a_later_tick_clears_offline() -> None:
    check = gate_line(offline(read([*DNS, EARLIER], exit_code="0")))
    assert check.value == "OK, launchd every 15 min"


def test_848_an_offline_exit_0_isnt_offline() -> None:
    # launchctl's exit is the last run's: 0 is another run since, whatever the log's last lines
    check = gate_line(offline(read([EARLIER, *DNS], exit_code="0")))
    assert check.value.startswith("failed: error: Request failed after 3 retries")


def test_848_a_machine_offline_past_two_intervals_is_still_stale() -> None:
    found = offline(read([EARLIER, *DNS], ran=dt.timedelta(minutes=40)))
    check = gate_line(found)
    assert check.value == "stale: last run 40 min ago; offline at last tick, next run due now, launchd every 15 min"
    assert check.fixes == (KICK, KICK)
    assert report(facts(gate=found)).verdict is Verdict.STUCK
