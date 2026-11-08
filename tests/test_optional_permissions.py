"""D-77 (#968): the App asks for deployments: read as an optional permission. A session's token
asks for it only where the installation grants it, an installation without it still launches
sessions, and doctor and the gate's GitHub preflight warn naming what the owner accepts"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from shipmill.agents import Mode
from shipmill.app import OPTIONAL_PERMISSIONS, PERMISSIONS, Answer, mint
from shipmill.cli import _gate_exit
from shipmill.doctor import APP, doctor, optional_permission_checks, session_app_on_host
from shipmill.downstream import DISPATCH_PERMISSIONS
from shipmill.gate import Action, tick_lines
from shipmill.github_auth import github_auth
from shipmill.gitrepo import Git

from .conftest import POLICY, Repo
from .test_app import APP_ID, GRANTED, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP
from .test_gate import NOW, FakeClaude
from .test_gate_github_auth import ACCESS, ReachApi, auth_of, checkout, config, no_host, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

WITH_DEPLOYMENTS = {**GRANTED, "deployments": "read"}
PAGE = "https://github.com/organizations/romamo/settings/installations/77"
SESSION = {p.key: str(p.access) for p in PERMISSIONS}


@dataclass
class Granting(ReachApi):
    """ReachApi whose installation grants permissions and names its page; posts records each
    token request's body"""

    granted: dict[str, str] = field(default_factory=lambda: dict(GRANTED))
    posts: list[Mapping[str, object]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        if path == f"/repos/{REPO}/installation" and self.installed and self.found is None:
            self.calls.append((path, token))
            return Answer(200, json.dumps({"id": 77, "permissions": self.granted, "html_url": PAGE}))
        return super().get(path, token)

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.posts.append(body)
        return super().post(path, token, body)


def test_d77_an_installation_with_deployments_mints_a_token_that_asks_for_it(tmp_path: Path) -> None:
    api = Granting(granted=dict(WITH_DEPLOYMENTS))
    token = mint(APP_ID, REPO, key_file(tmp_path), NOW, FakeSigner(), api, PERMISSIONS, OPTIONAL_PERMISSIONS)
    [body] = api.posts
    assert body == {"repositories": ["demo"], "permissions": {**SESSION, "deployments": "read"}}
    assert token.notices == ()


def test_d77_an_installation_without_deployments_never_asks_for_it_and_names_what_to_accept(tmp_path: Path) -> None:
    api = Granting()
    token = mint(APP_ID, REPO, key_file(tmp_path), NOW, FakeSigner(), api, PERMISSIONS, OPTIONAL_PERMISSIONS)
    [body] = api.posts
    assert body == {"repositories": ["demo"], "permissions": SESSION}  # GitHub would refuse it otherwise
    [notice] = token.notices
    assert notice.startswith(f"app demo-agent on {REPO} lacks the optional permission Deployments: read")
    assert notice.endswith(f"the owner accepts it on the App's installation page {PAGE}")
    assert "sessions start without it" in notice


def test_d77_another_table_asks_for_no_optional_permission(tmp_path: Path) -> None:
    """A downstream's token keeps its own table: granted or not, deployments isn't asked for"""
    api = Granting(granted={**WITH_DEPLOYMENTS, "actions": "write"})
    token = mint(APP_ID, REPO, key_file(tmp_path), NOW, FakeSigner(), api, DISPATCH_PERMISSIONS)
    [body] = api.posts
    assert "deployments" not in body["permissions"]  # type: ignore[operator]
    assert token.notices == ()


def test_d77_a_gate_whose_installation_lacks_deployments_still_launches_and_warns(
    checkout: Git, tmp_path: Path
) -> None:
    events: list[str] = []
    api = Granting(events=events)
    preflight = github_auth(REPO, checkout.root, FakeSigner(), api, run=no_host, clock=lambda: NOW)
    claude = FakeClaude()
    decision = tick(checkout, tmp_path, config(Mode.HEADLESS, APP_ID), claude, preflight, auth_of(events), api)
    assert decision.action is Action.LAUNCH and len(claude.started) == 1
    assert _gate_exit(decision) == 0
    assert events[-2] == f"POST {ACCESS}"
    assert api.posts[-1] == {"repositories": ["demo"], "permissions": SESSION}
    shown = tick_lines(decision, "s1", (), (), False)
    [warning] = [line for line in shown if line.startswith("  warning: ")]
    assert "lacks the optional permission Deployments: read" in warning and PAGE in warning


def test_d77_a_gate_whose_installation_grants_deployments_asks_for_it_and_warns_nothing(
    checkout: Git, tmp_path: Path
) -> None:
    api = Granting(granted=dict(WITH_DEPLOYMENTS))
    preflight = github_auth(REPO, checkout.root, FakeSigner(), api, run=no_host, clock=lambda: NOW)
    decision = tick(checkout, tmp_path, config(Mode.HEADLESS, APP_ID), FakeClaude(), preflight, auth_of([]), api)
    assert decision.action is Action.LAUNCH
    assert api.posts[-1] == {"repositories": ["demo"], "permissions": {**SESSION, "deployments": "read"}}
    assert not [line for line in tick_lines(decision, "s1", (), (), False) if "warning:" in line]


def test_d77_doctor_warns_naming_the_permission_and_the_installation_page(tmp_path: Path) -> None:
    probe = session_app_on_host(key_file(tmp_path), tmp_path, FakeSigner(), Granting(), lambda: NOW)
    [row] = optional_permission_checks(probe, APP_ID, REPO)
    assert (row.status, row.name) == ("WARN", APP)
    assert "lacks the optional permission Deployments: read" in row.detail
    assert f"the owner accepts it on the App's installation page {PAGE}" in row.detail


def test_d77_doctor_passes_an_installation_that_grants_it(tmp_path: Path) -> None:
    api = Granting(granted=dict(WITH_DEPLOYMENTS))
    probe = session_app_on_host(key_file(tmp_path), tmp_path, FakeSigner(), api, lambda: NOW)
    assert [(c.status, c.detail) for c in optional_permission_checks(probe, APP_ID, REPO)] == [
        ("PASS", f"app demo-agent on {REPO} is granted the optional Deployments: read")
    ]
    assert api.posts == []  # doctor reads the installation and mints nothing


def test_d77_doctor_without_the_key_on_the_host_has_no_row(tmp_path: Path) -> None:
    api = Granting()
    probe = session_app_on_host(None, tmp_path, FakeSigner(), api, lambda: NOW)
    assert optional_permission_checks(probe, APP_ID, REPO) == []
    assert api.calls == []


def test_d77_a_failed_read_is_a_warn_never_a_fail(tmp_path: Path) -> None:
    probe = session_app_on_host(key_file(tmp_path), tmp_path, FakeSigner(), Granting(installed=False), lambda: NOW)
    [row] = optional_permission_checks(probe, APP_ID, REPO)
    assert row.status == "WARN" and row.detail.startswith(f"can't check the App {APP_ID}'s optional permissions")


def test_d77_doctor_adds_the_warn_without_a_fail(repo: Repo, tmp_path: Path) -> None:
    repo.write(".github/shipmill.toml", POLICY + "\n" + WITH_APP)
    probe = session_app_on_host(key_file(tmp_path), tmp_path, FakeSigner(), Granting(), lambda: NOW)
    with_probe = doctor(repo.root, repo.github, repo=REPO, session_app=probe)
    without = doctor(repo.root, repo.github, repo=REPO)
    [row] = [c for c in with_probe if c.name == APP]
    assert row.status == "WARN"
    assert [c for c in with_probe if c.name != APP] == without  # every other row, and so the exit code, unchanged
