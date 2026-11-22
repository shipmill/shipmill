"""#1469 part 4: `status --item` reads the bot's login beside the item's own state, and its
other reads beside each other, and a closed item's exit waits on none of them"""

import datetime as dt
import re
import subprocess
import threading
from pathlib import Path

import pytest

from shipmill.app import default_key
from shipmill.autonomy import AutonomyPolicy
from shipmill.cli import _status_item
from shipmill.errors import ReleaseError
from shipmill.item_status import Ref
from tests import test_app
from tests.test_status_item import ITEM, Fake
from tests.test_status_picture import repo_with_release

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
REPO = test_app.REPO


class Login:
    """The App's bot login, which says when it starts and, held, waits for release"""

    def __init__(self, held: bool) -> None:
        self.started, self.release, self.finished = threading.Event(), threading.Event(), threading.Event()
        self.held = held

    def __call__(self, app_id: int, key: Path) -> str | None:
        self.started.set()
        if self.held:
            self.release.wait(10)
        self.finished.set()
        return test_app.BOT


class Beside(Fake):
    """The item Fake whose read of the item's own state answers only once the login started"""

    def __init__(self, login: Login) -> None:
        super().__init__()
        self.login = login

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["gh", "api"] and ITEM.fullmatch(cmd[2]) is not None:
            assert self.login.started.wait(5), "the bot's login was not read beside the item's state"
        return super().__call__(cmd)


def checkout(tmp_path: Path) -> tuple[Path, Path]:
    root = repo_with_release(tmp_path / "repo", REPO)
    (root / ".github").mkdir()
    config = f'[agents]\nprompt = "/t"\napp_id = {test_app.APP_ID}\n'
    (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    home = tmp_path / "home"
    key = default_key(test_app.APP_ID, home)
    key.parent.mkdir(parents=True)
    key.write_text("not a real key\n", encoding="utf-8")
    key.chmod(0o600)
    return root, home


def item(root: Path, home: Path, number: int, run: Fake, login: Login) -> int:
    ref = Ref(str(number), number, None)
    return _status_item(root, REPO, ref, False, run, (), AutonomyPolicy(), (), home, "linux", NOW, login)


def test_a_closed_items_exit_waits_on_no_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, home = checkout(tmp_path)
    login = Login(held=True)
    run = Beside(login)
    try:
        with pytest.raises(ReleaseError, match=re.escape(f"#7 is no open issue or pull request of {REPO}")):
            item(root, home, 7, run, login)
        assert not login.finished.is_set()  # still held: the exit didn't wait on it
    finally:
        login.release.set()
    assert run.seen == [["gh", "api", f"repos/{REPO}/issues/7", "--jq", ".state"]]
    assert capsys.readouterr() == ("", "")


def test_an_open_pull_request_reads_its_own_detail_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, home = checkout(tmp_path)
    login = Login(held=False)
    run = Beside(login)
    assert item(root, home, 9, run, login) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{REPO}#9 (https://github.com/{REPO}/pull/9): ") and "  why:  check check failed\n" in out
    assert [c for c in run.seen if c[:3] == ["gh", "pr", "view"]] == [
        ["gh", "pr", "view", "9", "-R", REPO, "--json", "statusCheckRollup,reviewDecision,labels"]
    ]
    watch = [c for c in run.seen if c[1].endswith(("watch_state.py", "triage_state.py"))]
    assert len(watch) == 2 and all(c[-2:] == ["--bot-login", test_app.BOT] for c in watch)


def test_an_open_issue_reads_no_pull_request_detail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, home = checkout(tmp_path)
    login = Login(held=False)
    run = Beside(login)
    assert item(root, home, 4, run, login) == 0
    assert capsys.readouterr().out.startswith(f"{REPO}#4 (https://github.com/{REPO}/issues/4): parked\n")
    assert not any(c[:3] == ["gh", "pr", "view"] for c in run.seen)
