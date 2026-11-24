"""S-030-25, D-104: `shipmill gh` refuses a decided comment on an item whose body or comments
name a CVE or GHSA id, so a decision on a known vulnerability is asked. No test reaches the
network: GitHub is MintApi, gh a Runner, and gh's reads a Thread"""

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import MARKER
from shipmill.cli import main
from shipmill.errors import ReleaseError

from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable

DECIDED = (
    "<!-- shipmill:decided zone=security until=2026-11-25T10:00:00Z -->\n@romamo Decided without waiting: keep it on"
)
HOST_CONFIG = '[agents]\nprompt = "/t"\nidentity = "host"\n'


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record = tmp_path / "record"
    record.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return Host(fakes, record, home)


@dataclass
class Thread:
    """Stands in for gh's reads: item 5's body and comments, pull request `fix/x`'s number, and
    comment 9's issue, each answered with code"""

    body: str = "A bug"
    comments: tuple[str, ...] = ()
    code: int = 0
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.calls.append(args)
        if self.code != 0:
            return self.code, ""
        if args[:2] == ["pr", "view"]:
            return 0, "5\n"
        if args[-2:] == ["--jq", ".issue_url"]:
            return 0, f"https://api.github.com/repos/{REPO}/issues/5\n"
        if args[:2] == ["api", "--paginate"]:
            return 0, "".join(f"{c}\n" for c in self.comments)
        if args == ["api", f"repos/{REPO}/issues/comments/9"]:  # an edit's current body (spec 050)
            return 0, f'{{"body": "old\\n\\n{MARKER}"}}'
        return 0, f"{self.body}\n"


def _args(tmp_path: Path, how: str, body: str) -> tuple[list[str], io.StringIO | None]:
    """A decided comment posting body on item 5, given as how says"""
    if how == "issue":
        return ["issue", "comment", "5", "--body", body], None
    if how == "file":
        path = tmp_path / "decided.md"
        path.write_text(body, encoding="utf-8")
        return ["pr", "comment", f"https://github.com/{REPO}/pull/5", "--body-file", str(path)], None
    if how == "stdin":
        return ["pr", "comment", "5", "-F", "-"], io.StringIO(body)
    if how == "branch":
        return ["pr", "comment", "fix/x", "--body", body], None
    if how == "close":
        return ["pr", "close", "5", "--comment", body], None
    if how == "edit":
        return ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/9", "-f", f"body={body}"], None
    return ["api", "repos/{owner}/{repo}/issues/5/comments", "-f", f"body={body}"], None


def _gh(root: Path, args: list[str], host: Host, runner: Runner, thread: Thread, stdin: io.StringIO | None) -> int:
    return main(
        ["--repo", str(root), "gh", *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        gh_capture=thread,
        gh_feed=lambda argv, env, fed: runner(argv, env),
        stdin=stdin,
    )


HOWS = ["issue", "file", "stdin", "branch", "close", "edit", "api"]


@pytest.mark.parametrize("how", HOWS)
@pytest.mark.parametrize(
    ("thread", "named"),
    [
        (Thread(body="Bumps x to fix CVE-2024-3094."), "CVE-2024-3094"),
        (Thread(comments=("ok", "see ghsa-jfh8-c2jp-5v3q")), "ghsa-jfh8-c2jp-5v3q"),
        (Thread(comments=("multi\nline cve-2023-44487 body",)), "cve-2023-44487"),
    ],
)
def test_s030_25_a_decided_comment_on_an_item_naming_an_advisory_exits_2_as_the_app(
    tmp_path: Path, host: Host, how: str, thread: Thread, named: str
) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    args, stdin = _args(tmp_path, how, DECIDED)
    runner = Runner(code=0)
    with pytest.raises(ReleaseError, match="D-104") as raised:
        _gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, runner, thread, stdin)
    assert f"{REPO}#5 names {named}" in str(raised.value)
    assert "<!-- shipmill:needs-decision -->" in str(raised.value)
    assert runner.calls == []
    assert ["api", f"repos/{REPO}/issues/5", "--jq", '.body // ""'] in thread.calls


@pytest.mark.parametrize("how", ["issue", "file", "api"])
def test_s030_25_the_decided_comment_naming_an_advisory_itself_exits_2(tmp_path: Path, host: Host, how: str) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    args, stdin = _args(tmp_path, how, f"{DECIDED}\n\nWhy: CVE-2024-3094 is not reachable")
    runner = Runner(code=0)
    with pytest.raises(ReleaseError, match="names CVE-2024-3094"):
        _gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, runner, Thread(), stdin)
    assert runner.calls == []


@pytest.mark.parametrize("how", ["issue", "file", "close"])
def test_s030_25_it_is_refused_as_the_host_too(tmp_path: Path, host: Host, how: str) -> None:
    root = checkout(tmp_path, HOST_CONFIG)
    args, stdin = _args(tmp_path, how, DECIDED)
    runner = Runner(code=0)
    with pytest.raises(ReleaseError, match="D-104"):
        _gh(root, args, host, runner, Thread(body="GHSA-JFH8-C2JP-5V3Q"), stdin)
    assert runner.calls == []


@pytest.mark.parametrize("how", HOWS)
def test_s030_25_a_thread_that_cant_be_read_refuses(tmp_path: Path, host: Host, how: str) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    args, stdin = _args(tmp_path, how, DECIDED)
    runner = Runner(code=0)
    with pytest.raises(ReleaseError, match="can't be"):
        _gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, runner, Thread(code=1), stdin)
    assert runner.calls == []


@pytest.mark.parametrize("how", HOWS)
def test_s030_25_a_decided_comment_on_an_item_naming_neither_posts(tmp_path: Path, host: Host, how: str) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    args, stdin = _args(tmp_path, how, DECIDED)
    runner = Runner(code=0)
    thread = Thread(body="CVE-24-1 and GHSA-aaaa-bbbb-cccc are no ids", comments=("CVE-2024-12",))
    assert _gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, runner, thread, stdin) == 0
    assert len(runner.calls) == 1
    assert [c[2] for c in thread.calls if c[:2] == ["api", "--paginate"]] == [f"repos/{REPO}/issues/5/comments"]


def test_s030_25_a_comment_without_the_decided_marker_reads_nothing(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    runner = Runner(code=0)
    thread = Thread(body="CVE-2024-3094")
    args = ["issue", "comment", "5", "--body", "Triage: implement, CVE-2024-3094"]
    assert _gh(root, ["--app-key", str(tmp_path / "app.pem"), *args], host, runner, thread, None) == 0
    assert (len(runner.calls), thread.calls) == (1, [])


def test_s030_25_a_pull_request_comment_naming_no_item_is_refused(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    runner = Runner(code=0)
    with pytest.raises(ReleaseError, match="name it by its number or URL"):
        _gh(
            root,
            ["--app-key", str(tmp_path / "app.pem"), "pr", "comment", "--body", DECIDED],
            host,
            runner,
            Thread(),
            None,
        )
    assert runner.calls == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("CVE-2024-3094", "CVE-2024-3094"),
        ("(cve-2021-44228)", "cve-2021-44228"),
        ("https://nvd.nist.gov/vuln/detail/CVE-2024-3094", "CVE-2024-3094"),
        ("GHSA-jfh8-c2jp-5v3q", "GHSA-jfh8-c2jp-5v3q"),
        ("CVE-24-3094", None),
        ("CVE-2024-123", None),
        ("GHSA-abcd-efgh-ijkl", None),  # a, b, d, e, i, k, l: no GHSA letters
        ("xCVE-2024-3094", None),
    ],
)
def test_s030_25_the_id_grammar(tmp_path: Path, host: Host, text: str, found: str | None) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    runner = Runner(code=0)
    args = ["--app-key", str(tmp_path / "app.pem"), "issue", "comment", "5", "--body", DECIDED]
    if found is None:
        assert _gh(root, args, host, runner, Thread(body=text), None) == 0
        assert len(runner.calls) == 1
        return
    with pytest.raises(ReleaseError, match=f"names {found}"):
        _gh(root, args, host, runner, Thread(body=text), None)
    assert runner.calls == []
