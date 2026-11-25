"""Spec 090: `shipmill gh issue|pr comment <n> --status` writes the item's one status comment,
creating it once and editing it after (S-090-1 to S-090-5). No test reaches the network: GitHub
is MintApi, and gh a Thread that answers the reads and records the writes"""

import datetime as dt
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import BODY_LIMIT, MARKER
from shipmill.app_gh import STATUS_MARKER, bare_mention, own_status, status_body
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.leaks import PRIVATE_FILE, LeakRefused

from .conftest import guarded_home
from .test_app import BOT, REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import FAKE_GH, MintApi, executable

HOST_CONFIG = '[agents]\nprompt = "/t"\nidentity = "host"\n'
HOST_LOGIN = "romamo"
UPDATED = re.compile(r"Updated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
COMMENTS = f"repos/{REPO}/issues/5/comments"


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    return Host(fakes, record, guarded_home(tmp_path / "home"))


def status(text: str, login: str = BOT, when: str = "2026-11-24 10:15") -> str:
    """A status comment's body as shipmill gh writes it"""
    return f"{STATUS_MARKER}\nUpdated {when} UTC\n\n{text}\n\n{MARKER}"


@dataclass
class Thread:
    """Stands in for gh on item 5: its comments (id, author's login, body), oldest first, read a
    page of 100 at a time as `gh api --paginate --jq` prints them, one JSON line each; the host's
    login; a comment's current body; and the visibility of the repo. As the runner, it records
    each write and applies it, so the next call reads it. code fails every read"""

    comments: list[tuple[int, str, str]] = field(default_factory=list)
    code: int = 0
    reads: list[list[str]] = field(default_factory=list)
    writes: list[list[str]] = field(default_factory=list)
    login: str = BOT  # whom a create is written as

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.reads.append(args)
        if self.code != 0:
            return self.code, ""
        if args[:2] == ["api", "--paginate"] and args[2] == COMMENTS:
            pages = [self.comments[i : i + 100] for i in range(0, len(self.comments), 100)]
            return 0, "".join(json.dumps(list(c)) + "\n" for page in pages for c in page)
        if args == ["api", "user", "--jq", ".login"]:
            return 0, f"{HOST_LOGIN}\n"
        if args[-2:] == ["--jq", ".visibility"]:
            return 0, "public\n"
        found = re.fullmatch(rf"repos/{REPO}/issues/comments/([0-9]+)", args[1]) if len(args) == 2 else None
        if args[0] == "api" and found is not None:  # an edit's current body (spec 050)
            body = next(b for i, _, b in self.comments if i == int(found.group(1)))
            return 0, json.dumps({"body": body})
        raise AssertionError(f"unexpected gh read: {args}")

    def run(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        args = list(argv[1:])
        self.writes.append(args)
        if args[0] != "api":  # a plain comment, or gh's help
            return 0
        body = next(a.partition("=")[2] for a in args if a.startswith("body="))
        if args[:2] == ["api", COMMENTS]:
            self.comments.append((1000 + len(self.comments), self.login, body))
            return 0
        found = re.fullmatch(rf"repos/{REPO}/issues/comments/([0-9]+)", args[3])
        assert args[:3] == ["api", "-X", "PATCH"] and found is not None, args
        self.comments = [(i, a, body if i == int(found.group(1)) else b) for i, a, b in self.comments]
        return 0


def run(
    root: Path, host: Host, thread: Thread, args: list[str], stdin: str = "", app: Path | None = None
) -> tuple[int, MintApi]:
    api = MintApi()
    lead = ["--app-key", str(app)] if app is not None else []
    code = main(
        ["--repo", str(root), "gh", *lead, *args],
        api=api,
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=thread.run,
        gh_feed=lambda argv, env, fed: thread.run(argv, env),
        gh_capture=thread,
        stdin=io.StringIO(stdin),
    )
    return code, api


@pytest.fixture
def as_app(tmp_path: Path) -> tuple[Path, Path]:
    """A checkout whose config sets [agents] app_id, and the App's key"""
    root = checkout(tmp_path, WITH_APP)
    return root, key_file(tmp_path)


# -- S-090-1: one create, then edits of that comment


@pytest.mark.parametrize("group", ["issue", "pr"])
def test_s090_1_three_status_writes_run_one_create_then_two_edits(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path], group: str
) -> None:
    root, key = as_app
    thread = Thread(comments=[(1, "amy", "A first comment")])
    note = tmp_path / "status.md"
    for step in ("Rebased on main", "CI pending", "The fix is in #9"):
        note.write_text(step, encoding="utf-8")
        assert run(root, host, thread, [group, "comment", "5", "--status", "--body-file", str(note)], app=key)[0] == 0
    assert thread.writes[0][:2] == ["api", COMMENTS]
    created = thread.comments[-1][0]
    edit = ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/{created}"]
    assert [w[:4] for w in thread.writes[1:]] == [edit, edit]
    assert len(thread.writes) == 3  # and no other comment write
    assert all("--status" not in w for w in thread.writes)  # never reaches gh
    assert [c[0] for c in thread.comments] == [1, created]
    assert "The fix is in #9" in thread.comments[-1][2]


def test_s090_1_status_never_reaches_gh_and_reads_every_page(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread()
    run(root, host, thread, ["issue", "comment", "--status", "5", "--body", "Started"], app=key)
    assert ["api", "--paginate", COMMENTS, "--jq", '.[] | [.id, (.user.login // "ghost"), (.body // "")] | @json'] in (
        thread.reads
    )
    assert all("--status" not in w for w in [*thread.reads, *thread.writes])


def test_s090_1_a_url_names_the_item_and_its_repo(tmp_path: Path, host: Host, as_app: tuple[Path, Path]) -> None:
    root, key = as_app
    thread = Thread(comments=[(7, BOT, status("Rebased"))])
    url = f"https://github.com/{REPO}/pull/5"
    assert run(root, host, thread, ["pr", "comment", url, "--status", "-b", "CI pending"], app=key)[0] == 0
    assert thread.writes[0][:4] == ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/7"]


def test_s090_1_a_status_without_the_flag_still_posts_a_new_comment(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread(comments=[(7, BOT, status("Rebased"))])
    assert run(root, host, thread, ["issue", "comment", "5", "--body", "--status"], app=key)[0] == 0
    assert thread.writes[0][:4] == ["issue", "comment", "5", "--body"]  # --status was the body


# -- S-090-2: the body


def test_s090_2_the_body_is_the_marker_the_time_the_text_and_the_agent_marker() -> None:
    when = dt.datetime(2026, 11, 24, 12, 15, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert status_body("Rebased on main.\n\nCI pending.", when) == (
        f"{STATUS_MARKER}\nUpdated 2026-11-24 10:15 UTC\n\nRebased on main.\n\nCI pending.\n\n{MARKER}"
    )
    # a text carrying the agent marker keeps it once, last
    assert status_body(f"CI pending\n\n{MARKER}\n", when).count(MARKER) == 1


def test_s090_2_after_any_number_of_edits_one_updated_line_and_one_agent_marker(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread()
    for step in range(4):
        text = f"Step {step}\n\n{MARKER}" if step % 2 else f"Step {step}"
        assert run(root, host, thread, ["issue", "comment", "5", "--status", "--body", text], app=key)[0] == 0
    [(_, _, body)] = thread.comments
    lines = body.splitlines()
    assert lines[0] == STATUS_MARKER and UPDATED.fullmatch(lines[1]) and lines[2] == ""
    assert lines[3] == "Step 3" and lines[-1] == MARKER
    assert len(UPDATED.findall(body)) == 1 and body.count(MARKER) == 1
    now = dt.datetime.now(dt.UTC)
    written = dt.datetime.strptime(lines[1], "Updated %Y-%m-%d %H:%M UTC").replace(tzinfo=dt.UTC)
    assert dt.timedelta(0) <= now - written < dt.timedelta(minutes=2)  # the clock, in UTC


# -- S-090-3: which comment is edited


def test_s090_3_the_oldest_of_the_writers_own_is_edited_past_the_first_100(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    others = [(i, "amy", f"comment {i}") for i in range(1, 131)]
    thread = Thread(comments=[*others, (500, BOT, status("first")), (600, BOT, status("second"))])
    assert run(root, host, thread, ["issue", "comment", "5", "--status", "-b", "CI pending"], app=key)[0] == 0
    assert thread.writes[0][:4] == ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/500"]


@pytest.mark.parametrize(
    "theirs",
    [
        (40, "amy", status("a person's copy")),  # another login
        (41, BOT.upper(), status("first")[: -len(MARKER)].rstrip()),  # no agent marker
        (42, BOT, f"Progress\n{status('quoted')}"),  # the marker past its first line
        (43, BOT, f" {status('indented')}"),  # not exactly the marker
        (44, "other-app[bot]", status("another App's")),
    ],
)
def test_s090_3_a_marker_comment_not_the_writers_own_is_never_edited(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path], theirs: tuple[int, str, str]
) -> None:
    root, key = as_app
    thread = Thread(comments=[theirs])
    assert run(root, host, thread, ["issue", "comment", "5", "--status", "-b", "CI pending"], app=key)[0] == 0
    assert thread.writes[0][:2] == ["api", COMMENTS]  # the writer's own, created
    assert thread.comments[0] == theirs


def test_s090_3_the_author_is_matched_whatever_its_case() -> None:
    assert own_status([(3, BOT.upper(), status("x"))], BOT) == 3


def test_s090_3_as_the_host_its_login_writes_and_finds_the_comment(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_CONFIG)
    thread = Thread(comments=[(8, BOT, status("the App's")), (9, HOST_LOGIN, status("mine"))], login=HOST_LOGIN)
    assert run(root, host, thread, ["pr", "comment", "5", "--status", "-b", "CI pending"])[0] == 0
    assert ["api", "user", "--jq", ".login"] in thread.reads
    assert thread.writes[0][:4] == ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/9"]


def test_s090_3_with_as_host_the_hosts_login_writes(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, None)
    thread = Thread(comments=[(8, BOT, status("the App's"))], login=HOST_LOGIN)
    assert run(root, host, thread, ["--as-host", "issue", "comment", "5", "--status", "-b", "Started"])[0] == 0
    assert thread.writes[0][:2] == ["api", COMMENTS]
    assert run(root, host, thread, ["--as-host", "issue", "comment", "5", "--status", "-b", "CI pending"])[0] == 0
    assert thread.writes[1][:4] == ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/1001"]


# -- S-090-4: refusals, before any write


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (["issue", "comment", "5", "--status"], "no --body or --body-file"),
        (["issue", "comment", "5", "--status", "--edit-last", "-b", "x"], "--edit-last"),
        (["pr", "comment", "5", "--status", "--delete-last", "-b", "x"], "--delete-last"),
        (["pr", "comment", "5", "--status", "--create-if-none", "-b", "x"], "--create-if-none"),
        (["issue", "comment", "5", "--status", "--web"], "--web"),
        (["issue", "comment", "5", "--status", "-w"], "-w"),
        (["pr", "comment", "5", "--status", "--editor"], "--editor"),
        (["pr", "comment", "5", "--status", "-e"], "-e"),
        (["issue", "create", "--status", "-t", "x", "-b", "y"], "only `gh issue comment <n>`"),
        (["pr", "review", "5", "--status", "-b", "x"], "only `gh issue comment <n>`"),
        (["api", COMMENTS, "--status", "-f", "body=x"], "only `gh issue comment <n>`"),
        (["issue", "comment", "5", "--status", "-b", f"Rebased\n{STATUS_MARKER}"], "first"),
        (["issue", "comment", "5", "--status", "-b", "Thanks @romamo, rebased"], "@romamo bare"),
        (["issue", "comment", "5", "--status", "--status", "-b", "x"], "given 2 times"),
        (["issue", "comment", "5", "--status=true", "-b", "x"], "given a value"),
        (["issue", "comment", "--status", "-b", "x"], "names none"),
    ],
)
def test_s090_4_status_exits_2_with_no_write(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path], args: list[str], match: str
) -> None:
    root, key = as_app
    thread = Thread()
    with pytest.raises(ReleaseError, match=re.escape(match)):
        run(root, host, thread, args, app=key)
    assert (thread.reads, thread.writes) == ([], [])  # nothing read, no token, no write


def test_s090_4_the_bare_login_is_named_and_refused_before_any_token(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread()
    api = MintApi()
    with pytest.raises(ReleaseError, match="mentions @amy bare") as raised:
        main(
            ["--repo", str(root), "gh", "--app-key", str(key), "pr", "comment", "5", "--status", "-b", "Ask @amy"],
            api=api,
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=thread.run,
            gh_capture=thread,
        )
    assert "`@amy`" in str(raised.value) and "D-61" in str(raised.value)
    assert (api.posts, thread.writes) == ([], [])


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Waits on `@romamo`", None),
        ("```\n@romamo\n```", None),
        ("~~~~\n@romamo\n~~~~", None),
        ("mail romamo@example.com", None),
        ("the App, @demo-agent[bot], rebased", None),
        ("<!-- @romamo -->", None),
        ("``code `@a` here``", None),
        ("see https://example.com/@romamo", None),
        ("@romamo: rebased", "romamo"),
        ("(@amy) and `@bob`", "amy"),
        ("```\nfenced\n```\nthen @eve", "eve"),
        ("cc @org/team", "org"),
    ],
)
def test_s090_4_a_bare_mention_outside_a_code_span(text: str, found: str | None) -> None:
    assert bare_mention(text) == found


def test_s090_4_comments_that_cant_be_read_refuse_the_write(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread(code=1)
    with pytest.raises(ReleaseError, match="comments can't be read"):
        run(root, host, thread, ["issue", "comment", "5", "--status", "-b", "CI pending"], app=key)
    assert thread.writes == []


def test_s090_4_a_comments_read_that_isnt_comments_refuses(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app

    def garbled(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        return 0, '{"id": 1}\n'

    thread = Thread()
    with pytest.raises(ReleaseError, match="not a comment"):
        main(
            ["--repo", str(root), "gh", "--app-key", str(key), "issue", "comment", "5", "--status", "-b", "x"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=thread.run,
            gh_capture=garbled,
        )
    assert thread.writes == []


def test_s090_4_a_host_login_that_cant_be_read_refuses(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_CONFIG)
    thread = Thread()
    with pytest.raises(ReleaseError, match="host's gh login"):
        main(
            ["--repo", str(root), "gh", "issue", "comment", "5", "--status", "-b", "x"],
            environ=host.env(),
            home=host.home,
            gh_runner=thread.run,
            gh_capture=lambda argv, env: (1, ""),
        )
    assert thread.writes == []


def test_s090_4_with_product_it_is_refused(tmp_path: Path, host: Host, as_app: tuple[Path, Path]) -> None:
    root, key = as_app
    thread = Thread()
    with pytest.raises(ReleaseError, match="--product"):
        run(root, host, thread, ["--product", "romamo/other", "issue", "comment", "5", "--status", "-b", "x"])
    assert thread.writes == []


def test_s090_4_with_help_gh_prints_its_help_and_writes_no_status(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    thread = Thread()
    assert run(root, host, thread, ["issue", "comment", "--status", "--help"], app=key)[0] == 0
    assert thread.writes == [["issue", "comment", "--help"]]


# -- S-090-5: the leak check and the size limit


def test_s090_5_a_private_term_in_the_text_refuses_the_write(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path]
) -> None:
    root, key = as_app
    private = host.home / PRIVATE_FILE
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text('terms = ["Acme Rocket"]\n', encoding="utf-8")
    for comments in ([], [(7, BOT, status("Rebased"))]):  # a create, and an edit
        thread = Thread(comments=list(comments))
        with pytest.raises(LeakRefused):
            run(root, host, thread, ["issue", "comment", "5", "--status", "-b", "acme rocket is pending"], app=key)
        assert thread.writes == []


def test_s090_5_a_token_in_the_text_refuses_the_write_as_the_host(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_CONFIG)
    token = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    thread = Thread(comments=[(9, HOST_LOGIN, status("mine"))], login=HOST_LOGIN)
    with pytest.raises(LeakRefused):
        run(root, host, thread, ["issue", "comment", "5", "--status", "-b", f"used {token}"])
    assert thread.writes == []


@pytest.mark.parametrize("comments", [[], [(7, BOT, status("Rebased"))]])
def test_s090_5_a_whole_body_over_the_limit_refuses_the_write(
    tmp_path: Path, host: Host, as_app: tuple[Path, Path], comments: list[tuple[int, str, str]]
) -> None:
    root, key = as_app
    # the text alone fits; with the marker, the Updated line, and the agent marker it doesn't
    text = "x" * (BODY_LIMIT - len(STATUS_MARKER))
    note = tmp_path / "long.md"
    note.write_text(text, encoding="utf-8")
    thread = Thread(comments=list(comments))
    with pytest.raises(ReleaseError, match="over GitHub's limit"):
        run(root, host, thread, ["issue", "comment", "5", "--status", "--body-file", str(note)], app=key)
    assert thread.writes == []
