"""Spec 050: `shipmill gh` ends every body it creates with the agent marker, as the App and as
the host's login, and refuses a create it can't mark; GhCli's own writes end with it too. No
test reaches the network: gh is a Runner, GitHub is MintApi and openssl FakeSigner"""

import io
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import BODY_LIMIT, MARKER, carries, marked, stripped, unmarked
from shipmill.app_gh import BodyEdit, BodyRead, body_edit, body_reader, current_body, marked_args
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import CUT_MARK, PROPOSAL_LABEL
from shipmill.policy import Lane
from shipmill.propose import Outcome, marker, upsert

from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_units import TestLongBodies

HOST_IDENTITY = '[agents]\nprompt = "/t"\nidentity = "host"\n'
AGENTS_NO_APP = '[agents]\nprompt = "/t"\n'


def sent(args: list[str]) -> list[str]:
    """args as `shipmill gh` hands them to gh: the last --body/-b moved to the end, before any
    `--`, as one --body holding its text marked"""
    end = args.index("--") if "--" in args else len(args)
    head = args[:end]
    at = max(i for i, arg in enumerate(head) if arg in ("--body", "-b"))
    return [*head[:at], *head[at + 2 :], "--body", marked(head[at + 1]), *args[end:]]


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


def no_read(flag: str, path: str) -> str:
    raise AssertionError(f"read {flag} {path}")


def run(root: Path, args: list[str], host: Host, stdin: str = "") -> Runner:
    runner = Runner()
    assert (
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(stdin),
        )
        == 7
    )
    return runner


def refused(root: Path, args: list[str], host: Host, match: str) -> None:
    """exit 2 (cli.run prints a ReleaseError and exits 2), gh never ran"""
    runner = Runner()
    with pytest.raises(ReleaseError, match=match):
        main(
            ["--repo", str(root), "gh", *args],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(""),
        )
    assert runner.calls == []


# -- the marker ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "carried"),
    [
        (f"text\n\n{MARKER}", True),
        (f"  {MARKER}  \ntext", True),
        ("text\n<!-- shipmill:agent via=gh -->", True),
        ("text <!-- shipmill:agent -->", False),  # not a line of its own
        ("<!-- shipmill:agents -->", False),
        ("<!-- shipmill:needs-decision -->\ntext", False),
    ],
)
def test_a_body_carries_the_marker_on_a_line_of_its_own(body: str, carried: bool) -> None:
    assert carries(body) is carried


def test_marking_keeps_the_first_line_and_ends_with_the_marker() -> None:
    assert marked("Triage: implement\n\nbody\n") == f"Triage: implement\n\nbody\n\n{MARKER}"
    assert marked(f"x\n\n{MARKER}") == f"x\n\n{MARKER}"  # no second marker
    assert marked("  \n") == MARKER
    assert unmarked(marked("a\nb\n")) == "a\nb"
    assert unmarked("a\nb\n") == "a\nb\n"


# -- S-050-1 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "body"),
    [
        (["issue", "create", "--title", "t", "--body", "Triage: x\n\nbody"], "Triage: x\n\nbody"),
        (["issue", "create", "-t", "t", "-b", "b"], "b"),
        (["issue", "new", "-t", "t", "--body=b"], "b"),
        (["issue", "comment", "250", "-bb", "-R", REPO], "b"),
        (["issue", "comment", "250", "--body", "--title"], "--title"),  # a value is never a flag
        (["issue", "create", "--title", "-h", "--body", "b"], "b"),  # nor a help flag
        (["pr", "create", "-B", "main", "-H", "x", "--title", "t", "--body", "b", "--label", "l"], "b"),
        (["pr", "comment", "7", "-b", "first", "-b", "last"], "last"),  # the last, as gh takes it
        (["pr", "review", "7", "--comment", "--body", "b"], "b"),
        (["pr", "review", "7", "-r", "-b", "b"], "b"),
    ],
)
def test_s050_1_a_create_hands_gh_one_marked_body(args: list[str], body: str) -> None:
    out = marked_args(args, no_read)
    assert out[-2:] == ["--body", f"{body}\n\n{MARKER}"]
    assert [a for a in out if a in ("--body", "-b") or a.startswith(("--body=", "-bb"))] == ["--body"]


@pytest.mark.parametrize("flag", [["--body-file", "{path}"], ["-F", "{path}"], ["--body-file={path}"], ["-F{path}"]])
def test_s050_1_a_body_file_is_read_and_marked(tmp_path: Path, flag: list[str]) -> None:
    path = tmp_path / "comment.md"
    path.write_text("Triage: implement\n\nwhy\n", encoding="utf-8")
    args = ["issue", "comment", "250", *(f.format(path=path) for f in flag)]
    out = marked_args(args, body_reader(io.StringIO("")))
    assert out == ["issue", "comment", "250", "--body", f"Triage: implement\n\nwhy\n\n{MARKER}"]


def test_s050_1_a_body_file_on_stdin_is_read_and_marked() -> None:
    out = marked_args(
        ["pr", "create", "-t", "t", "--body-file", "-", "--draft"], body_reader(io.StringIO("from stdin"))
    )
    assert out == ["pr", "create", "-t", "t", "--draft", "--body", f"from stdin\n\n{MARKER}"]


def test_s050_1_a_body_file_that_cant_be_read_exits_2(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="--body-file .*missing.md can't be read: No such file"):
        marked_args(["issue", "comment", "1", "--body-file", str(tmp_path / "missing.md")], body_reader(io.StringIO()))


@pytest.mark.parametrize(
    ("args", "flag"),
    [
        (["issue", "close", "5", "--comment", "Released.", "--reason", "completed"], "--comment"),
        (["issue", "reopen", "5", "-c", "Released."], "--comment"),
        (["pr", "close", "5", "-dc", "Released."], "--comment"),
        (["pr", "reopen", "5", "--comment=Released."], "--comment"),
    ],
)
def test_s050_1_a_closing_or_reopening_comment_is_marked(args: list[str], flag: str) -> None:
    out = marked_args(args, no_read)
    assert out[-2:] == [flag, f"Released.\n\n{MARKER}"]
    assert ("-d" in out) is ("-dc" in args)  # a switch bundled with -c is kept


def test_s050_1_a_close_without_a_comment_and_a_marked_body_reach_gh_unchanged() -> None:
    assert marked_args(["issue", "close", "5", "--reason", "not planned"], no_read) == [
        "issue",
        "close",
        "5",
        "--reason",
        "not planned",
    ]
    body = f"text\n\n{MARKER}"
    assert marked_args(["issue", "comment", "1", "--body", body], no_read) == ["issue", "comment", "1", "--body", body]


def test_s050_1_an_approval_without_a_body_gets_the_marker_alone() -> None:
    assert marked_args(["pr", "review", "7", "--approve"], no_read) == [
        "pr",
        "review",
        "7",
        "--approve",
        "--body",
        MARKER,
    ]
    assert marked_args(["pr", "review", "-a", "7"], no_read) == ["pr", "review", "-a", "7", "--body", MARKER]


@pytest.mark.parametrize("kind", ["--comment", "-r", None])
def test_s050_1_a_review_other_than_an_approval_needs_a_body(kind: str | None) -> None:
    """gh would ask for it in an editor, or refuse it blank: never an unmarked review"""
    with pytest.raises(ReleaseError, match="--body-file"):
        marked_args(["pr", "review", "7", *([kind] if kind else [])], no_read)


def test_s050_1_past_dashes_nothing_is_read_as_a_body() -> None:
    out = marked_args(["pr", "create", "--title", "t", "--body", "", "--", "--body", "x"], no_read)
    assert out == ["pr", "create", "--title", "t", "--body", MARKER, "--", "--body", "x"]


@pytest.mark.parametrize(
    ("config", "leading"), [(WITH_APP, ["--app-key", "{key}"]), (HOST_IDENTITY, []), (AGENTS_NO_APP, ["--as-host"])]
)
def test_s050_1_as_the_app_and_as_the_host_gh_gets_the_marked_body(
    tmp_path: Path, host: Host, config: str, leading: list[str]
) -> None:
    root = checkout(tmp_path, config)
    key = key_file(tmp_path)
    args = ["issue", "comment", "250", "--body-file", "-"]
    runner = run(root, [*(a.format(key=key) for a in leading), *args], host, stdin="Triage: implement\n")
    [(argv, _)] = runner.calls
    assert argv == [host.gh, "issue", "comment", "250", "--body", f"Triage: implement\n\n{MARKER}"]


def test_s050_1_through_the_real_gh_the_marked_body_is_one_argument(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    key_file(tmp_path)
    code = main(
        ["--repo", str(root), "gh", "--app-key", str(tmp_path / "app.pem"), "pr", "comment", "1", "-b", "it's -R x"],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
    )
    assert code == 7
    expected = ["pr", "comment", "1", "--body", f"it's -R x\n\n{MARKER}"]
    assert (host.record / "gh-args").read_text() == "".join(f"{a}\n" for a in expected)


# -- S-050-2 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "create", "--title", "t"],
        ["issue", "comment", "1"],
        ["pr", "create", "--fill"],
        ["pr", "comment", "1", "-R", REPO],
        ["issue", "create", "--title", "t", "--body", "b", "--web"],
        ["issue", "comment", "1", "-e"],
        ["pr", "create", "-wt", "t"],
        ["pr", "comment", "1", "--editor", "--body", "b"],
    ],
)
def test_s050_2_a_create_it_cant_mark_exits_2_naming_body_file(args: list[str]) -> None:
    with pytest.raises(ReleaseError, match="--body-file"):
        marked_args(args, no_read)


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_s050_2_edit_last_names_the_api_edit(command: str) -> None:
    with pytest.raises(ReleaseError, match=r"gh api -X PATCH repos/<owner>/<repo>/issues/comments/<id>"):
        marked_args([command, "comment", "1", "--edit-last", "--body", "b"], no_read)


def test_s050_2_a_switch_turned_off_is_no_refusal() -> None:
    out = marked_args(["issue", "comment", "1", "--web=false", "--body", "b"], no_read)
    assert out == ["issue", "comment", "1", "--web=false", "--body", f"b\n\n{MARKER}"]


@pytest.mark.parametrize("config", [WITH_APP, HOST_IDENTITY])
def test_s050_2_the_refusal_runs_no_gh(tmp_path: Path, host: Host, config: str) -> None:
    root = checkout(tmp_path, config)
    key_file(tmp_path)
    leading = ["--app-key", str(tmp_path / "app.pem")] if config == WITH_APP else []
    refused(root, [*leading, "issue", "create", "-t", "t", "--editor"], host, "--body-file")


def test_s050_2_the_refusal_exits_2(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "gh", "issue", "comment", "1", "--web"],
        capture_output=True,
        text=True,
        check=False,
        env={**host.env(), "HOME": str(host.home)},
    )
    assert done.returncode == 2
    assert "--body-file" in done.stderr
    assert not (host.record / "gh-args").exists()


# -- S-050-3 -------------------------------------------------------------------------------------


@dataclass
class Current:
    """Stands in for the gh that reads an edit's current body: records each argv and env, and
    answers code with out, or with a REST record holding body"""

    body: object = ""
    code: int = 0
    out: str | None = None
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env)))
        return self.code, json.dumps({"id": 1, "body": self.body}) if self.out is None else self.out


def edit_of(args: list[str], read: BodyRead = no_read) -> BodyEdit:
    found = body_edit(args, read)
    assert found is not None
    return found


AGENTS = f"Filed by an agent.\n\n{MARKER}"


@pytest.mark.parametrize(
    ("args", "path", "body"),
    [
        (["issue", "edit", "5", "--body", "new"], "issues/5", "new"),
        (["issue", "edit", "#5", "-b", "new", "--add-label", "ready"], "issues/5", "new"),
        (["issue", "edit", "-R", REPO, "--body=new", "5"], "issues/5", "new"),
        (["issue", "edit", f"https://github.com/{REPO}/issues/5", "-bnew"], "issues/5", "new"),
        (["pr", "edit", "7", "--title", "t", "--body", "new"], "pulls/7", "new"),
        (["pr", "edit", "7", "-B", "main", "-b", "first", "-b", "new"], "pulls/7", "new"),  # the last, as gh takes it
    ],
)
def test_s050_3_an_edit_names_its_record_and_its_new_body(args: list[str], path: str, body: str) -> None:
    edit = edit_of(args)
    assert (edit.record(REPO), edit.body) == (f"repos/{REPO}/{path}", body)
    marked_out, plain = edit.args(carried=True), edit.args(carried=False)
    assert marked_out[-2:] == ["--body", f"{body}\n\n{MARKER}"]
    assert [a for a in marked_out if a in ("--body", "-b") or a.startswith(("--body=", "-bn"))] == ["--body"]
    assert not any(carries(a) for a in plain)
    assert plain == args or plain[-2:] == ["--body", body]  # one body flag needing no change: as given


@pytest.mark.parametrize(
    "endpoint",
    [
        f"repos/{REPO}/issues/5",
        f"repos/{REPO}/pulls/7",
        f"repos/{REPO}/issues/comments/9",
        f"repos/{REPO}/pulls/comments/9",
        f"repos/{REPO}/pulls/7/reviews/3",
    ],
)
@pytest.mark.parametrize(
    "method", [["-X", "PATCH"], ["--method", "PATCH"], ["--method=patch"], ["-XPATCH"]], ids=lambda m: "".join(m)
)
def test_s050_3_an_api_patch_on_a_body_endpoint_is_an_edit(endpoint: str, method: list[str]) -> None:
    args = ["api", *method, endpoint, "-f", "body=new", "-f", "title=t"]
    edit = edit_of(args)
    assert edit.record(None) == endpoint  # the endpoint names its repo: no default needed
    assert edit.args(carried=True) == ["api", *method, endpoint, "-f", "title=t", "-f", f"body=new\n\n{MARKER}"]
    assert edit.args(carried=False) == args  # nothing to change: the args as given


@pytest.mark.parametrize(
    ("field_flag", "value"),
    [("-f", "body=new"), ("-F", "body=new"), ("--field", "body=new"), ("--raw-field", "body=new")],
)
def test_s050_3_every_body_field_form_is_read(field_flag: str, value: str) -> None:
    edit = edit_of(["api", "-X", "PATCH", f"repos/{REPO}/issues/5", field_flag, value])
    assert edit.body == "new"


def test_s050_3_a_body_file_and_stdin_are_read_once(tmp_path: Path) -> None:
    path = tmp_path / "body.md"
    path.write_text("from a file\r\n\r\nDepends on o/r#4", encoding="utf-8")
    endpoint = f"repos/{REPO}/issues/5"
    edit = edit_of(["api", "-X", "PATCH", endpoint, "-F", f"body=@{path}"], body_reader(io.StringIO()))
    # a person's record: the file goes to gh as given, byte for byte
    assert edit.args(carried=False) == ["api", "-X", "PATCH", endpoint, "-F", f"body=@{path}"]
    assert edit.args(carried=True) == [  # an agent's: read as text, as a create's file is
        "api",
        "-X",
        "PATCH",
        endpoint,
        "-f",
        f"body=from a file\n\nDepends on o/r#4\n\n{MARKER}",
    ]
    stdin = edit_of(["issue", "edit", "5", "--body-file", "-"], body_reader(io.StringIO("from stdin")))
    assert stdin.args(carried=False) == ["issue", "edit", "5", "--body", "from stdin"]  # gh can't read stdin again
    filed = edit_of(["pr", "edit", "7", "-F", str(path)], body_reader(io.StringIO()))
    assert filed.args(carried=False) == ["pr", "edit", "7", "-F", str(path)]


def test_s050_3_an_edit_never_marks_a_persons_record_nor_unmarks_an_agents() -> None:
    """the new body carries the marker exactly when the current one does, whatever the new text"""
    session_marked = edit_of(["issue", "edit", "5", "--body", f"{MARKER}\n\nDepends on o/r#4"])
    assert session_marked.args(carried=False) == ["issue", "edit", "5", "--body", "Depends on o/r#4"]
    assert session_marked.args(carried=True) == ["issue", "edit", "5", "--body", f"Depends on o/r#4\n\n{MARKER}"]
    appended = edit_of(["issue", "edit", "5", "--body", f"{AGENTS}\n\nDepends on o/r#4"])  # link's append
    assert appended.args(carried=True)[-1] == f"Filed by an agent.\n\nDepends on o/r#4\n\n{MARKER}"
    assert stripped("text\n<!-- shipmill:agent via=gh -->\n") == "text"
    assert stripped("no marker\n") == "no marker\n"


def test_s050_3_placeholders_and_a_missing_repo_take_the_repo_gh_works_on() -> None:
    edit = edit_of(["api", "-X", "PATCH", "repos/{owner}/{repo}/issues/5", "-f", "body=x"])
    assert edit.record("o/r") == "repos/o/r/issues/5"
    assert edit_of(["issue", "edit", "5", "-b", "x"]).record("o/r") == "repos/o/r/issues/5"
    assert edit_of(["issue", "edit", "5", "-b", "x", "-R", "a/b"]).record("o/r") == "repos/a/b/issues/5"
    with pytest.raises(ReleaseError, match="can't tell its repo here; name it with -R owner/name"):
        edit_of(["issue", "edit", "5", "-b", "x"]).record(None)


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (["issue", "edit", "--body", "x"], "gh issue edit with a body flag names none"),
        (["issue", "edit", "5", "6", "--body", "x"], "names 5 6.*one issue by its number or URL"),
        (["pr", "edit", "my-branch", "--body", "x"], "names my-branch.*one pull request"),
        (["pr", "edit", "-b", "x"], "names none"),
        (["issue", "edit", "5", "--body", "x", "--body-file", "f"], "--body or --body-file, not both"),
        (["api", "-X", "PATCH", f"repos/{REPO}/issues/5", "--input", "b.json"], "--input is refused.*-F body=@<file>"),
        (["api", "-X", "PATCH", f"repos/{REPO}/pulls/7", "--input", "-", "-f", "x=y"], "--input is refused"),
    ],
)
def test_s050_3_an_edit_whose_record_cant_be_named_exits_2(args: list[str], match: str) -> None:
    with pytest.raises(ReleaseError, match=match):
        body_edit(args, no_read)


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "edit", "5", "--add-label", "ready"],
        ["pr", "edit", "7", "--title", "t", "--milestone", "m"],
        ["issue", "edit", "5", "--title", "--body"],  # a value is never a flag
        ["issue", "edit", "--help", "--body", "x"],
        ["api", "-X", "PATCH", f"repos/{REPO}/issues/5", "-f", "state=closed"],
        ["api", "-X", "PATCH", f"repos/{REPO}/milestones/3", "-f", "title=1.1.1"],
        ["api", f"repos/{REPO}/issues/5"],
        ["api", "-X", "POST", f"repos/{REPO}/issues/5/comments", "-f", "body=b"],  # a create: S-050-4
        ["issue", "comment", "5", "--body", "b"],
    ],
)
def test_s050_3_other_calls_are_no_edit(args: list[str]) -> None:
    assert body_edit(args, no_read) is None


@pytest.mark.parametrize(
    ("current", "match"),
    [
        (Current(code=1, out=""), "exited 1"),
        (Current(out="not json"), "isn't JSON"),
        (Current(out="[]"), "has no body"),
        (Current(out='{"id": 1}'), "has no body"),
        (Current(body=7), "its body is int, not text"),
        (Current(body={"text": "x"}), "its body is dict"),
    ],
)
def test_s050_3_a_current_body_that_cant_be_read_exits_2(current: Current, match: str) -> None:
    with pytest.raises(ReleaseError, match=f"current body of repos/o/r/issues/5 can't be read.*{match}"):
        current_body(current, Path("/gh"), {}, "repos/o/r/issues/5", "gh issue edit")


def test_s050_3_a_record_written_with_no_body_reads_empty() -> None:
    """GitHub gives null for it: a person's issue filed with no body stays theirs"""
    assert current_body(Current(body=None), Path("/gh"), {}, "repos/o/r/issues/5", "gh issue edit") == ""
    assert current_body(Current(body=AGENTS), Path("/gh"), {"GH_TOKEN": "t"}, "repos/o/r/issues/5", "x") == AGENTS


def run_edit(root: Path, args: list[str], host: Host, current: Current, stdin: str = "") -> Runner:
    runner = Runner()
    code = main(
        ["--repo", str(root), "gh", *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
        stdin=io.StringIO(stdin),
        gh_capture=current,
    )
    assert code == 7
    return runner


@pytest.mark.parametrize(
    ("config", "leading"), [(WITH_APP, ["--app-key", "{key}"]), (HOST_IDENTITY, []), (AGENTS_NO_APP, ["--as-host"])]
)
@pytest.mark.parametrize(("was", "now"), [(AGENTS, f"new\n\n{MARKER}"), ("A person's issue.", "new")])
def test_s050_3_through_shipmill_gh_the_edit_reads_first_with_the_same_identity(
    tmp_path: Path, host: Host, config: str, leading: list[str], was: str, now: str
) -> None:
    root = checkout(tmp_path, config)
    key = key_file(tmp_path)
    current = Current(body=was)
    args = ["issue", "edit", "250", "--body-file", "-", "--add-label", "ready"]
    runner = run_edit(root, [*(a.format(key=key) for a in leading), *args], host, current, stdin="new")
    [(read, read_env)] = current.calls
    [(argv, env)] = runner.calls
    assert read == [host.gh, "api", f"repos/{REPO}/issues/250"]
    assert argv == [host.gh, "issue", "edit", "250", "--add-label", "ready", "--body", now]
    assert read_env == env  # the same token, or the same host login
    assert ("GH_TOKEN" in env) is (config == WITH_APP)


def test_s050_3_an_api_edit_through_shipmill_gh_fills_the_repo_from_the_checkout(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    current = Current(body=AGENTS)
    args = ["api", "-X", "PATCH", "repos/{owner}/{repo}/issues/comments/9", "-f", "body=fixed"]
    runner = run_edit(root, args, host, current)
    assert current.calls[0][0] == [host.gh, "api", f"repos/{REPO}/issues/comments/9"]
    assert runner.calls[0][0] == [host.gh, *args[:4], "-f", f"body=fixed\n\n{MARKER}"]


@pytest.mark.parametrize("current", [Current(code=1, out=""), Current(out="null")])
def test_s050_3_when_the_current_body_cant_be_read_the_edit_doesnt_run(
    tmp_path: Path, host: Host, current: Current
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    runner = Runner()
    with pytest.raises(ReleaseError, match="can't be read.*the edit didn't run"):
        main(
            ["--repo", str(root), "gh", "pr", "edit", "7", "--body", "x"],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            stdin=io.StringIO(""),
            gh_capture=current,
        )
    assert len(current.calls) == 1 and runner.calls == []


def test_s050_3_an_agents_edit_marked_past_the_limit_exits_2_and_runs_no_edit(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    runner = Runner()
    with pytest.raises(ReleaseError, match="over GitHub's limit"):
        main(
            ["--repo", str(root), "gh", "issue", "edit", "5", "--body", "x" * BODY_LIMIT],
            api=MintApi(),
            signer=FakeSigner(),
            environ=host.env(),
            home=host.home,
            gh_runner=runner,
            gh_capture=Current(body=AGENTS),
        )
    assert runner.calls == []


def test_s050_3_an_edit_without_a_body_flag_reads_nothing(tmp_path: Path, host: Host) -> None:
    """S-050-6: labels, a title, assignees reach gh as given, with no read before them"""
    current = Current()
    args = ["issue", "edit", "5", "--add-label", "ready", "--title", "t"]
    runner = run_edit(checkout(tmp_path, HOST_IDENTITY), args, host, current)
    assert current.calls == [] and runner.calls[0][0] == [host.gh, *args]


# -- S-050-4 -------------------------------------------------------------------------------------

COMMENTS = f"repos/{REPO}/issues/250/comments"


@pytest.mark.parametrize(
    ("args", "kept"),
    [
        (["api", COMMENTS, "-f", "body=b"], ["api", COMMENTS]),
        (["api", "-X", "POST", COMMENTS, "--raw-field", "body=b"], ["api", "-X", "POST", COMMENTS]),
        (["api", f"/{COMMENTS}", "--field=body=b"], ["api", f"/{COMMENTS}"]),
        (["api", f"https://api.github.com/{COMMENTS}", "-fbody=b"], ["api", f"https://api.github.com/{COMMENTS}"]),
        (
            ["api", "repos/{owner}/{repo}/issues", "-f", "title=t", "-F", "body=b"],
            ["api", "repos/{owner}/{repo}/issues", "-f", "title=t"],
        ),
        (
            ["api", f"repos/{REPO}/pulls", "-f", "head=x", "-f", "base=main", "-f", "body=b", "-f", "title=t"],
            ["api", f"repos/{REPO}/pulls", "-f", "head=x", "-f", "base=main", "-f", "title=t"],
        ),
        (["api", f"repos/{REPO}/pulls/7/comments", "-f", "body=b"], ["api", f"repos/{REPO}/pulls/7/comments"]),
        (
            ["api", f"repos/{REPO}/pulls/7/comments/9/replies", "-f", "body=b"],
            ["api", f"repos/{REPO}/pulls/7/comments/9/replies"],
        ),
        (
            ["api", "--method", "post", f"repos/{REPO}/pulls/7/reviews", "-f", "event=COMMENT", "-f", "body=b"],
            ["api", "--method", "post", f"repos/{REPO}/pulls/7/reviews", "-f", "event=COMMENT"],
        ),
    ],
)
def test_s050_4_an_api_create_gets_its_body_field_marked(args: list[str], kept: list[str]) -> None:
    assert marked_args(args, no_read) == [*kept, "-f", f"body=b\n\n{MARKER}"]


def test_s050_4_a_body_field_from_a_file_is_read_and_marked(tmp_path: Path) -> None:
    path = tmp_path / "body.md"
    path.write_text("from a file\n", encoding="utf-8")
    out = marked_args(["api", COMMENTS, "-F", f"body=@{path}"], body_reader(io.StringIO()))
    assert out == ["api", COMMENTS, "-f", f"body=from a file\n\n{MARKER}"]
    out = marked_args(["api", COMMENTS, "-F", "body=@-"], body_reader(io.StringIO("from stdin")))
    assert out == ["api", COMMENTS, "-f", f"body=from stdin\n\n{MARKER}"]
    with pytest.raises(ReleaseError, match="can't be read"):
        marked_args(["api", COMMENTS, "-F", f"body=@{tmp_path / 'missing'}"], body_reader(io.StringIO()))


def test_s050_4_a_create_without_a_body_field_gets_the_marker_alone() -> None:
    reviews = f"repos/{REPO}/pulls/7/reviews"
    assert marked_args(["api", reviews, "-f", "event=APPROVE"], no_read) == [
        "api",
        reviews,
        "-f",
        "event=APPROVE",
        "-f",
        f"body={MARKER}",
    ]
    assert marked_args(["api", "-X", "POST", reviews], no_read) == [
        "api",
        "-X",
        "POST",
        reviews,
        "-f",
        f"body={MARKER}",
    ]


def test_s050_4_an_api_create_with_input_exits_2() -> None:
    with pytest.raises(ReleaseError, match="--input is refused"):
        marked_args(["api", COMMENTS, "--input", "body.json"], no_read)


MUTATIONS = [
    "addComment",
    "updateIssueComment",
    "createIssue",
    "updateIssue",
    "createPullRequest",
    "updatePullRequest",
    "addPullRequestReview",
    "submitPullRequestReview",
    "updatePullRequestReview",
    "addPullRequestReviewComment",
    "addPullRequestReviewThread",
    "addDiscussionComment",
    "updateDiscussionComment",
    "createDiscussion",
    "updateDiscussion",
]


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_s050_4_a_graphql_mutation_writing_a_body_exits_2_naming_rest(tmp_path: Path, mutation: str) -> None:
    query = f"mutation {{ {mutation}(input: {{subjectId: $id, body: $b}}) {{ clientMutationId }} }}"
    with pytest.raises(ReleaseError, match=f"{mutation} is refused.*REST form"):
        marked_args(["api", "graphql", "-f", f"query={query}"], no_read)
    path = tmp_path / "q.graphql"
    path.write_text(query, encoding="utf-8")
    with pytest.raises(ReleaseError, match=f"{mutation} is refused"):
        marked_args(["api", "graphql", "-F", f"query=@{path}"], body_reader(io.StringIO()))
    with pytest.raises(ReleaseError, match="from stdin is refused"):
        marked_args(["api", "graphql", "-F", "query=@-"], body_reader(io.StringIO(query)))


def test_s050_4_the_api_refusals_run_no_gh(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    refused(root, ["api", COMMENTS, "--input", "-"], host, "--input is refused")
    refused(root, ["api", "graphql", "-f", "query=mutation { addComment(input: {}) { x } }"], host, "addComment")


@pytest.mark.parametrize(
    "args",
    [
        ["api", "graphql", "-f", "query={ viewer { login } }"],
        ["api", "graphql", "-f", "query=mutation { addLabelsToLabelable(input: {}) { x } }"],
        ["api", "graphql", "-f", "query=mutation { addBlockedBy(input: {}) { issue { id } } }"],  # chains.py's
        ["api", COMMENTS],  # a read
        ["api", "-X", "GET", COMMENTS, "-f", "per_page=100"],
        ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/9", "-f", "body=b"],  # an edit: body_edit's (S-050-3)
        ["api", "-X", "POST", f"repos/{REPO}/issues/7/labels", "-f", "labels[]=x"],
    ],
)
def test_s050_4_other_api_calls_reach_gh_as_given(args: list[str]) -> None:
    assert marked_args(args, no_read) == args


# -- S-050-5 -------------------------------------------------------------------------------------


def test_s050_5_a_marked_body_over_the_limit_exits_2_and_runs_no_gh(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    fits = "x" * (BODY_LIMIT - len(f"\n\n{MARKER}"))
    assert len(marked_args(["issue", "comment", "1", "--body", fits], no_read)[-1]) == BODY_LIMIT
    refused(root, ["issue", "comment", "1", "--body", fits + "x"], host, "over GitHub's limit of 65,536")
    refused(root, ["api", COMMENTS, "-f", f"body={fits}x"], host, "over GitHub's limit")


def test_s050_5_ghcli_writes_end_with_the_marker_a_cut_body_included(tmp_path: Path) -> None:
    bodies = TestLongBodies()
    gh = bodies.gh(tmp_path)
    gh.comment_issue(7, "Released v1.0.0.")
    assert bodies.sent(tmp_path) == f"Released v1.0.0.\n\n{MARKER}"
    gh.close_issue(7, "Closed.")
    assert bodies.sent(tmp_path) == f"Closed.\n\n{MARKER}"
    assert gh.create_issue("t", "Opened.", (PROPOSAL_LABEL,)) == 7
    assert bodies.sent(tmp_path) == f"Opened.\n\n{MARKER}"
    for edit in (True, False):
        long = bodies.big(BODY_LIMIT - 5)  # within GitHub's limit, but not with the marker after it
        if edit:
            gh.update_issue(7, "t", long)
        else:
            gh.comment_issue(7, long)
        cut = bodies.sent(tmp_path)
        assert CUT_MARK in cut
        assert cut.endswith(f"_\n\n{MARKER}")
        assert len(cut) <= BODY_LIMIT


def test_s050_5_a_proposal_stored_with_the_marker_reads_unchanged(tmp_path: Path) -> None:
    """upsert compares the stored body less the marker GhCli ended it with, cut or not"""
    bodies = TestLongBodies()
    mark = marker(Lane.STABLE)
    short = f"{mark}\nshort"
    assert upsert(bodies.gh(tmp_path, marked(short)), mark, "t", short, "fix") == (7, Outcome.UNCHANGED)
    long = f"{mark}\n{bodies.big(BODY_LIMIT * 2)}"
    assert upsert(bodies.gh(tmp_path), mark, "t", long, "fix") == (7, Outcome.OPENED)
    stored = bodies.sent(tmp_path)
    assert upsert(bodies.gh(tmp_path, stored), mark, "t", long, "fix") == (7, Outcome.UNCHANGED)
    changed = f"{mark}\n- changed\n{bodies.big(BODY_LIMIT * 2)}"
    assert upsert(bodies.gh(tmp_path, stored), mark, "t", changed, "fix") == (7, Outcome.UPDATED)


# -- S-050-6 -------------------------------------------------------------------------------------

PASSTHROUGH = [
    ["issue", "edit", "1", "--add-label", "ready", "--remove-label", "needs-decision"],
    ["pr", "edit", "7", "--add-assignee", "@me"],
    ["issue", "edit", "1", "--add-assignee", "someone"],
    ["label", "create", "ready", "--description", "x"],
    ["pr", "merge", "7", "--squash", "--body", "a commit message"],
    ["pr", "merge", "7", "--squash", "--body-file", "-"],
    ["release", "create", "v1.0.0", "--notes", "notes", "--title", "t"],
    ["issue", "view", "1", "--json", "body"],
    ["pr", "list", "--search", "--body x"],
    ["issue", "create", "--help"],
    ["pr", "review", "-h"],
    ["issue", "close", "1", "-c", "x", "--help"],
    ["issue", "comment", "1", "--delete-last", "--yes"],
    ["api", "user"],
    ["run", "rerun", "5"],
]


@pytest.mark.parametrize("args", PASSTHROUGH)
def test_s050_6_other_commands_reach_gh_exactly_as_given(args: list[str]) -> None:
    assert marked_args(args, no_read) == args


@pytest.mark.parametrize("args", [a for a in PASSTHROUGH if a[:2] != ["pr", "merge"]])
def test_s050_6_through_shipmill_gh_as_the_host(tmp_path: Path, host: Host, args: list[str]) -> None:
    runner = run(checkout(tmp_path, HOST_IDENTITY), args, host)
    assert runner.calls[0][0] == [host.gh, *args]


def test_s050_6_a_merge_body_stays_a_commit_message_as_the_host(tmp_path: Path, host: Host) -> None:
    args = ["pr", "merge", "7", "--squash", "--body-file", "-"]
    runner = run(checkout(tmp_path, HOST_IDENTITY), args, host, stdin="never read")
    assert runner.calls[0][0] == [host.gh, *args]


def test_sent_is_what_shipmill_gh_hands_gh() -> None:
    args = ["issue", "create", "-b", "b", "-t", "t", "--", "x"]
    assert marked_args(args, no_read) == sent(args)
