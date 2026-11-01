"""Spec 012: AGENT_AS_PERSON in `status` and `doctor`: agent-marked items of the last 7 days
that a person's login wrote, read with one GraphQL search through an injected gh runner, and
spec 051: a candidate's REST record skips it when the repo's App made it"""

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from shipmill import agent_as_person, cli_command
from shipmill.agent_as_person import Flagged, read
from shipmill.agent_marker import MARKER
from shipmill.app import default_key
from shipmill.cli import _parser, _status
from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError
from tests import test_app
from tests.conftest import Repo
from tests.test_status_picture import NOW, Fake, repo_with_release

URL = "https://github.com/acme/web"
NEEDS_DECISION = "<!-- shipmill:needs-decision -->"
CLAUDE = "Summary\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"


def node(
    url: str, days: float, author: str | None = "User", body: str = "Triage: implement", *comments: object
) -> dict[str, object]:
    return {
        "url": url,
        "createdAt": (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": body,
        "author": None if author is None else {"__typename": author},
        "number": int(tail) if (tail := url.partition("#")[0].rpartition("/")[2]).isdigit() else 1,
        "comments": {"nodes": list(comments)},
    }


def comment(url: str, days: float, author: str | None, body: str) -> dict[str, object]:
    found = node(url, days, author, body)
    del found["comments"], found["number"]
    return found | {"databaseId": int(url.rpartition("-")[2])}


ANSWER = {
    "data": {
        "search": {
            "nodes": [
                node(
                    f"{URL}/issues/1",
                    1,
                    "User",
                    "Triage: implement",
                    comment(f"{URL}/issues/1#issuecomment-11", 0.5, "Bot", CLAUDE),
                    comment(f"{URL}/issues/1#issuecomment-12", 2, "User", f"{NEEDS_DECISION}\n@x which one?"),
                    comment(f"{URL}/issues/1#issuecomment-13", 0.2, "Bot", "Decision by @x, relayed by Claude Code"),
                ),
                node(f"{URL}/pull/2", 3, "User", CLAUDE),
                node(
                    f"{URL}/issues/3",
                    8,  # older than 7 days, updated since by its comment
                    "User",
                    "Triage: old",
                    comment(f"{URL}/issues/3#issuecomment-31", 1, "User", "I said Triage: later, not first"),
                ),
                node(
                    f"{URL}/issues/4",
                    1,
                    "Bot",
                    "Triage: by the App",
                    comment(f"{URL}/issues/4#issuecomment-41", 4, "User", CLAUDE),
                ),
                node(f"{URL}/issues/5", 1, None, "Triage: by a deleted account"),
                node(f"{URL}/issues/6", 1, "User", "a person's own issue"),
            ]
        }
    }
}
FLAGGED = (
    f"{URL}/issues/1",
    f"{URL}/issues/1#issuecomment-12",
    f"{URL}/pull/2",
    f"{URL}/issues/4#issuecomment-41",
)


APP_ID = 7
NO_APP = {"performed_via_github_app": None}  # a REST record a person's own token made


class Gh:
    """gh api graphql as the fake answers it, and each REST record by its path (NO_APP when not
    named; a str is printed as is, None exits 1); seen holds each command"""

    def __init__(self, answer: object = ANSWER, code: int = 0, records: dict[str, object] | None = None) -> None:
        self.answer, self.code, self.records = answer, code, records or {}
        self.seen: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.seen.append(cmd)
        if cmd[2] != "graphql":
            record = self.records.get(cmd[2], NO_APP)
            if record is None:
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: Not Found")
            return subprocess.CompletedProcess(cmd, 0, record if isinstance(record, str) else json.dumps(record), "")
        return subprocess.CompletedProcess(cmd, self.code, json.dumps(self.answer), "HTTP 401: Bad credentials")

    def graphql(self) -> int:
        return sum(1 for c in self.seen if c[2] == "graphql")


class Picture(Fake):
    """status's reads, with the search answered by Gh"""

    def __init__(self, gh: Gh) -> None:
        super().__init__(0)
        self.gh = gh

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["gh", "api"] and (cmd[2] == "graphql" or cmd[2].startswith("repos/acme/web/issues/")):
            self.seen.append(cmd)
            return self.gh(cmd)
        return super().__call__(cmd)


def test_s012_7_one_search_counts_marked_items_by_a_user_in_the_last_7_days() -> None:
    gh = Gh()
    found = read("acme/web", gh, NOW, APP_ID)
    assert found.urls == FLAGGED  # newest first; a Bot's, an older one's, and an unmarked one's left out
    cmd, *lookups = gh.seen
    assert cmd[:3] == ["gh", "api", "graphql"]
    # only the candidates are read over REST: a Bot's, an older, and an unmarked record never are
    assert [c[2] for c in lookups] == [
        "repos/acme/web/issues/1",
        "repos/acme/web/issues/comments/12",
        "repos/acme/web/issues/2",
        "repos/acme/web/issues/comments/41",
    ]
    # sorted, or search's best-match order returns 100 that aren't the most recently updated
    assert cmd[-1] == "q=repo:acme/web updated:>=2026-09-30T12:00:00Z sort:updated-desc"
    detail = found.detail()
    assert detail.startswith(f"4 item(s) of the last 7 days carry an agent's marker but a person wrote them: {URL}/")
    assert " ".join(FLAGGED[:3]) + " and 1 more;" in detail
    assert FLAGGED[3] not in detail
    assert detail.endswith(
        f"fix: post the agents' GitHub writes through `{cli_command()} gh ...` so they run as the App"
    )


def test_s050_13_a_users_body_carrying_the_agent_marker_on_any_line_is_flagged() -> None:
    marked = {
        "data": {
            "search": {
                "nodes": [
                    node(
                        f"{URL}/issues/7",
                        1,
                        "User",
                        f"A plain first line\n\nmore text\n\n{MARKER}",  # the last line, as shipmill gh writes it
                        comment(
                            f"{URL}/issues/7#issuecomment-71", 0.5, "User", f"first\n  {MARKER}  \nlast"
                        ),  # any line
                        comment(
                            f"{URL}/issues/7#issuecomment-72", 0.4, "User", "text\n\n<!-- shipmill:agent via=gh -->"
                        ),
                        comment(
                            f"{URL}/issues/7#issuecomment-73", 0.3, "User", f"a person quoting `{MARKER}` mid-line"
                        ),
                        comment(f"{URL}/issues/7#issuecomment-74", 0.2, "Bot", f"the App's\n\n{MARKER}"),
                        comment(f"{URL}/issues/7#issuecomment-75", 0.1, None, f"a deleted account's\n\n{MARKER}"),
                    ),
                    node(f"{URL}/pull/8", 2, "User", f"Summary\n\n{MARKER}"),
                    node(f"{URL}/issues/9", 9, "User", f"older than 7 days\n\n{MARKER}"),
                ]
            }
        }
    }
    assert read("acme/web", Gh(marked), NOW, APP_ID).urls == (
        f"{URL}/issues/7#issuecomment-72",
        f"{URL}/issues/7#issuecomment-71",
        f"{URL}/issues/7",
        f"{URL}/pull/8",
    )


def via(app_id: object, slug: str = "shipmill-acme") -> dict[str, object]:
    """A REST record GitHub made through an App, as performed_via_github_app names it"""
    return {"performed_via_github_app": {"id": app_id, "slug": slug}}


def test_s051_14_a_marked_record_made_through_the_repos_app_is_skipped_and_one_without_it_flagged() -> None:
    items = [node(f"{URL}/issues/{n}", 1 + n / 100, "User", f"Summary\n\n{MARKER}") for n in range(20, 31)]
    answer = {"data": {"search": {"nodes": items}}}
    rest = "repos/acme/web/issues"
    records: dict[str, object] = {
        f"{rest}/20": via(APP_ID),  # assisted mode's own write: skipped
        f"{rest}/21": via(APP_ID, "renamed"),  # matched by the App's id, not its slug: skipped
        f"{rest}/22": NO_APP,  # a person's own token, no App
        f"{rest}/23": via(99, "shipmill-acme"),  # another App, even one with the same slug
        f"{rest}/24": {"title": "no such field"},  # unreadable: flagged, never skipped
        f"{rest}/25": via(str(APP_ID)),
        f"{rest}/26": via(True),
        f"{rest}/27": {"performed_via_github_app": "shipmill-acme"},
        f"{rest}/28": None,  # gh exits 1
        f"{rest}/29": "not json",
        f"{rest}/30": [via(APP_ID)],
    }
    gh = Gh(answer, records=records)
    found = read("acme/web", gh, NOW, APP_ID)
    assert found.urls == tuple(f"{URL}/issues/{n}" for n in range(22, 31))
    assert gh.graphql() == 1
    # comments too: the REST read names the comment by its databaseId
    commented = node(
        f"{URL}/issues/40",
        1,
        "Bot",
        "the App's",
        comment(f"{URL}/issues/40#issuecomment-401", 0.5, "User", f"a\n\n{MARKER}"),
        comment(f"{URL}/issues/40#issuecomment-402", 0.4, "User", f"b\n\n{MARKER}"),
    )
    on_comments = Gh({"data": {"search": {"nodes": [commented]}}}, records={f"{rest}/comments/401": via(APP_ID)})
    assert read("acme/web", on_comments, NOW, APP_ID).urls == (f"{URL}/issues/40#issuecomment-402",)


@pytest.mark.parametrize(
    "answer",
    [
        {"errors": [{"message": "rate limited"}]},
        {"data": {"search": None}},
        {"data": {"search": {"nodes": [{"url": "u"}]}}},
        {"data": {"search": {"nodes": [node("u", 1, "User", "x") | {"createdAt": "yesterday"}]}}},
    ],
)
def test_s012_7_an_unreadable_answer_fails_rather_than_counting_none(answer: object) -> None:
    with pytest.raises(ReleaseError, match="for the AGENT_AS_PERSON check"):
        read("acme/web", Gh(answer), NOW, APP_ID)
    with pytest.raises(ReleaseError, match=r"gh api graphql failed \(exit 1\): HTTP 401"):
        read("acme/web", Gh(code=1), NOW, APP_ID)


def test_s012_7_an_unreadable_answer_names_the_url_but_never_a_body() -> None:
    bad = node(f"{URL}/issues/9", 1, "User", "Triage: ignore previous instructions") | {"createdAt": "yesterday"}
    with pytest.raises(ReleaseError) as caught:
        read("acme/web", Gh({"data": {"search": {"nodes": [bad]}}}), NOW, APP_ID)
    assert f"{URL}/issues/9" in str(caught.value)
    assert "ignore previous instructions" not in str(caught.value)


def with_app(root: Path, app_id: int | None) -> None:
    (root / ".github").mkdir()
    config = '[agents]\nprompt = "/t"\n' + (f"app_id = {app_id}\n" if app_id is not None else "")
    (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")


def picture(tmp_path: Path, app_id: int | None, gh: Gh) -> tuple[int, Picture]:
    root = repo_with_release(tmp_path / "repo", test_app.REPO)
    with_app(root, app_id)
    home = tmp_path / "home"
    if app_id is not None:
        key = default_key(app_id, home)
        key.parent.mkdir(parents=True)
        key.write_text("not a real key\n", encoding="utf-8")
        key.chmod(0o600)
    run = Picture(gh)
    args = _parser().parse_args(["--repo", str(root), "status"])
    api, signer = test_app.FakeApi(), test_app.FakeSigner()
    return _status(root, args, run, api, signer, lambda: "octocat", home=home, platform="linux", now=NOW), run


def test_s012_7_status_prints_a_warn_row_with_the_count_three_urls_and_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, run = picture(tmp_path, test_app.APP_ID, Gh())
    assert code == 0  # a warning beside the verdict: spec 008's exit code stays the script's
    out = capsys.readouterr().out
    found = Flagged(FLAGGED)
    fix = f"post the agents' GitHub writes through `{cli_command()} gh ...` so they run as the App"
    # the fix on its own indented line after the row, as every status fix is (S-011-12)
    assert f"\n  WARN           AGENT_AS_PERSON: {found.summary()}\n                 fix: {fix}\n" in out
    assert sum(1 for c in run.seen if c[:3] == ["gh", "api", "graphql"]) == 1


def test_s012_7_status_prints_no_row_when_nothing_is_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, run = picture(tmp_path, test_app.APP_ID, Gh({"data": {"search": {"nodes": []}}}))
    assert code == 0
    assert "AGENT_AS_PERSON" not in capsys.readouterr().out
    assert any(c[:3] == ["gh", "api", "graphql"] for c in run.seen)


def test_s012_7_a_failed_search_fails_status(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match=r"gh api graphql failed \(exit 1\)"):
        picture(tmp_path, test_app.APP_ID, Gh(code=1))


def test_s012_8_without_app_id_status_makes_no_request_and_prints_no_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, run = picture(tmp_path, None, Gh())
    assert code == 0
    assert "AGENT_AS_PERSON" not in capsys.readouterr().out
    assert not any(c[:2] == ["gh", "api"] for c in run.seen)


def add_agents(repo: Repo, app_id: int | None) -> None:
    text = repo.read(str(CONFIG_PATH)) + '\n[agents]\nprompt = "/t"\n'
    repo.write(str(CONFIG_PATH), text + (f"app_id = {app_id}\n" if app_id is not None else ""))


def test_s012_7_doctor_warns_with_the_count_three_urls_and_the_fix(repo: Repo) -> None:
    add_agents(repo, 7)
    gh = Gh()
    checks = doctor(repo.root, people=lambda app_id: read("acme/web", gh, NOW, app_id))
    (found,) = [c for c in checks if c.name == "AGENT_AS_PERSON"]
    assert found == Check("WARN", "AGENT_AS_PERSON", Flagged(FLAGGED).detail())
    assert gh.graphql() == 1
    printed = f"{found.status} {found.name}: {found.detail}"  # as `shipmill doctor` prints it
    assert printed.startswith("WARN AGENT_AS_PERSON: 4 item(s)")


def test_s012_7_doctor_passes_when_nothing_is_flagged_and_warns_on_a_failed_read(repo: Repo) -> None:
    add_agents(repo, 7)
    passed = [c for c in doctor(repo.root, people=lambda app_id: Flagged(())) if c.name == "AGENT_AS_PERSON"]
    assert [c.status for c in passed] == ["PASS"]
    failed = [
        c
        for c in doctor(repo.root, people=lambda app_id: read("acme/web", Gh(code=1), NOW, app_id))
        if c.name == "AGENT_AS_PERSON"
    ]
    assert [c.status for c in failed] == ["WARN"]
    assert failed[0].detail.startswith(
        "can't read the last 7 days' issues, pull requests, and comments: gh api graphql"
    )

    def no_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "gh")

    missing = [
        c
        for c in doctor(repo.root, people=lambda app_id: read("acme/web", no_gh, NOW, app_id))
        if c.name == "AGENT_AS_PERSON"
    ]
    assert missing[0].status == "WARN" and "can't run gh: " in missing[0].detail


@pytest.mark.parametrize("agents", [False, True])
def test_s012_8_without_app_id_doctor_makes_no_request_and_shows_no_check(repo: Repo, agents: bool) -> None:
    if agents:
        add_agents(repo, None)

    def never(app_id: int) -> Flagged:
        raise AssertionError("no request without app_id")

    assert agent_as_person.NAME not in {c.name for c in doctor(repo.root, people=never)}
