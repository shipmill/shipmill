"""chains.py link: a dependency written as GitHub's native relation and as a Depends on line"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-issue-triage" / "scripts"


@pytest.fixture(scope="module")
def ch() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # chains imports triage_state, as when run from its folder
    try:
        spec = importlib.util.spec_from_file_location("chains", SCRIPTS / "chains.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def error(message: str, kind: str | None = None) -> dict[str, Any]:
    return {"message": message, **({"type": kind} if kind else {})}


class Forge:
    """A fake GitHub behind the GraphQL runner: issues, the native relations between them,
    and what it refuses. Every call is recorded"""

    def __init__(self, ch: ModuleType) -> None:
        self.ch = ch
        self.issues: dict[tuple[str, str, int], dict[str, str]] = {}
        self.blocked: set[tuple[str, str]] = set()  # (issue id, blocking issue id)
        self.parents: dict[str, str] = {}  # child id: parent id
        self.refuse_read: str | None = None  # the forge has no relation fields
        self.refuse_write: str | None = None  # the forge refuses the mutation
        self.rate_limited = False
        # ("read" or "write", the error) any relation query or mutation gets
        self.relation_error: tuple[str, dict[str, Any]] | None = None
        self.page = 100
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def add(self, ref: str, body: str = "", kind: str = "Issue") -> str:
        repo, _, number = ref.partition("#")
        owner, _, name = repo.partition("/")
        node_id = f"I_{ref}"
        self.issues[(owner.lower(), name.lower(), int(number))] = {"id": node_id, "body": body, "type": kind}
        return node_id

    def body(self, ref: str) -> str:
        return next(i["body"] for i in self.issues.values() if i["id"] == f"I_{ref}")

    def writes(self) -> list[str]:
        mutations = {self.ch.ADD_BLOCKED_BY: "addBlockedBy", self.ch.ADD_SUB_ISSUE: "addSubIssue"}
        mutations[self.ch.UPDATE_BODY] = "updateIssue"
        return [mutations[q] for q, _ in self.calls if q in mutations]

    def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, variables))
        ch = self.ch
        if self.rate_limited:
            return {"errors": [error("API rate limit exceeded", "RATE_LIMITED")]}
        if query == ch.RESOLVE:
            key = (str(variables["owner"]).lower(), str(variables["name"]).lower(), variables["number"])
            found = self.issues.get(key)
            if found is None:
                missing = f"Could not resolve to an issue or pull request with the number of {variables['number']}."
                return {"data": {"repository": {"issueOrPullRequest": None}}, "errors": [error(missing, "NOT_FOUND")]}
            node = {"__typename": found["type"]}
            if found["type"] == "Issue":
                node |= {"id": found["id"], "body": found["body"]}
            return {"data": {"repository": {"issueOrPullRequest": node}}}
        if query == ch.UPDATE_BODY:
            issue = next(i for i in self.issues.values() if i["id"] == variables["id"])
            issue["body"] = variables["body"]
            return {"data": {"updateIssue": {"issue": {"id": variables["id"]}}}}
        reads, writes = (ch.BLOCKED_BY, ch.PARENT), (ch.ADD_BLOCKED_BY, ch.ADD_SUB_ISSUE)
        if self.relation_error and query in {"read": reads, "write": writes}[self.relation_error[0]]:
            return {"data": None, "errors": [self.relation_error[1]]}
        if query in reads and self.refuse_read:
            # GitHub's shape for a field its schema doesn't have
            field = "blockedBy" if query == ch.BLOCKED_BY else "parent"
            undefined = {"code": "undefinedField", "typeName": "Issue", "fieldName": field}
            return {"errors": [{**error(self.refuse_read), "extensions": undefined}]}
        if query == ch.BLOCKED_BY:
            ids = sorted(b for a, b in self.blocked if a == variables["id"])
            start = int(variables.get("cursor") or 0)
            end = start + self.page
            more = end < len(ids)
            info = {"hasNextPage": more, "endCursor": str(end) if more else None}
            nodes = [{"id": i} for i in ids[start:end]]
            return {"data": {"node": {"blockedBy": {"pageInfo": info, "nodes": nodes}}}}
        if query == ch.PARENT:
            parent = self.parents.get(str(variables["id"]))
            return {"data": {"node": {"parent": {"id": parent} if parent else None}}}
        if query in (ch.ADD_BLOCKED_BY, ch.ADD_SUB_ISSUE) and self.refuse_write:
            return {"data": None, "errors": [error(self.refuse_write, "UNPROCESSABLE")]}
        if query == ch.ADD_BLOCKED_BY:
            self.blocked.add((str(variables["issue"]), str(variables["blocking"])))
            return {"data": {"addBlockedBy": {"issue": {"id": variables["issue"]}}}}
        if query == ch.ADD_SUB_ISSUE:
            self.parents[str(variables["sub"])] = str(variables["issue"])
            return {"data": {"addSubIssue": {"issue": {"id": variables["issue"]}}}}
        raise AssertionError(f"unexpected query {query}")


@pytest.fixture
def forge(ch: ModuleType) -> Forge:
    return Forge(ch)


def link(ch: ModuleType, forge: Forge, *argv: str) -> int:
    result: int = ch.main(["link", *argv], run=forge, write=forge)
    return result


def test_s017_6_blocked_by_writes_both_forms_and_again_changes_nothing(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    a = forge.add("o/r#5", "Build the page.\n")
    b = forge.add("o/r#4")
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert (a, b) in forge.blocked
    assert forge.body("o/r#5") == "Build the page.\n\nDepends on o/r#4"
    out = capsys.readouterr().out
    assert "linked: o/r#5 is blocked by o/r#4" in out and "added to o/r#5: Depends on o/r#4" in out

    forge.calls.clear()
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == []
    assert capsys.readouterr().out.strip() == "already linked"
    assert forge.body("o/r#5") == "Build the page.\n\nDepends on o/r#4"


def test_s017_6_the_body_is_kept_byte_for_byte(ch: ModuleType, forge: Forge) -> None:
    for body, expected in [
        ("", "Depends on o/r#4"),
        ("Text without a newline", "Text without a newline\n\nDepends on o/r#4"),
        ("Windows\r\nlines  \r\n", "Windows\r\nlines  \r\n\r\nDepends on o/r#4"),
        ("Steps\n\n- Depends on o/r#3\n", "Steps\n\n- Depends on o/r#3\nDepends on o/r#4"),
        ("Ends blank\n\n", "Ends blank\n\nDepends on o/r#4"),
    ]:
        forge = Forge(ch)
        forge.add("o/r#5", body)
        forge.add("o/r#4")
        forge.add("o/r#3")
        assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
        assert forge.body("o/r#5") == expected
        assert forge.body("o/r#5").startswith(body)


def test_s017_6_only_the_missing_half_is_written(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    # The relation is there (set in the UI), the line isn't: only the line is added
    a = forge.add("o/r#5", "Body")
    b = forge.add("o/r#4")
    forge.blocked.add((a, b))
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == ["updateIssue"]
    assert "already linked" not in capsys.readouterr().out

    # The line names it as a plain #4 of the same repo, the relation isn't there: only it is added
    forge = Forge(ch)
    a = forge.add("o/r#5", "Depends on #4 and #9\n")
    b = forge.add("O/R#4")
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == ["addBlockedBy"]
    assert forge.body("o/r#5") == "Depends on #4 and #9\n"
    out = capsys.readouterr().out
    assert "linked: o/r#5 is blocked by o/r#4" in out and "added to" not in out


def test_s017_6_a_plain_number_of_another_repo_or_a_mention_elsewhere_does_not_count(
    ch: ModuleType, forge: Forge
) -> None:
    forge.add("o/r#5", "Depends on #4\nSee other/r#4 too\n")
    forge.add("other/r#4")
    assert link(ch, forge, "o/r#5", "--blocked-by", "other/r#4") == 0
    assert forge.body("o/r#5") == "Depends on #4\nSee other/r#4 too\n\nDepends on other/r#4"


def test_s017_6_blocked_by_is_paged(ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]) -> None:
    forge.page = 2
    a = forge.add("o/r#5", "Depends on o/r#4")
    b = forge.add("o/r#4")
    for n in range(10, 15):
        forge.blocked.add((a, forge.add(f"o/r#{n}")))
    forge.blocked.add((a, b))
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == []
    assert capsys.readouterr().out.strip() == "already linked"


def test_s017_7_child_adds_a_sub_issue_and_a_depends_on_line(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    p = forge.add("o/r#1", "The feature\n")
    c = forge.add("o/other#2")
    assert link(ch, forge, "o/r#1", "--child", "o/other#2") == 0
    assert forge.parents[c] == p
    assert forge.body("o/r#1") == "The feature\n\nDepends on o/other#2"
    assert "linked: o/other#2 is a sub-issue of o/r#1" in capsys.readouterr().out

    assert link(ch, forge, "o/r#1", "--child", "o/other#2") == 0
    assert capsys.readouterr().out.strip() == "already linked"


def test_s017_8_a_forge_without_the_relation_still_gets_the_text_line(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.refuse_read = "Field 'blockedBy' doesn't exist on type 'Issue'\nmore detail"
    forge.add("o/r#5", "Body\n")
    forge.add("o/r#4")
    assert link(ch, forge, "o/r#5", "--blocked-by", "o/r#4") == 0
    assert forge.writes() == ["updateIssue"]
    assert forge.body("o/r#5") == "Body\n\nDepends on o/r#4"
    out = capsys.readouterr().out
    assert "text only: Field 'blockedBy' doesn't exist on type 'Issue'\n" in out + "\n"
    assert "more detail" not in out and "already linked" not in out


def test_s017_8_a_refused_cross_owner_link_still_gets_the_text_line(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.refuse_write = "Issues must belong to the same owner"
    forge.add("o/r#1")
    forge.add("someone/else#2")
    assert link(ch, forge, "o/r#1", "--child", "someone/else#2") == 0
    assert forge.parents == {}
    assert forge.body("o/r#1") == "Depends on someone/else#2"
    assert "text only: Issues must belong to the same owner" in capsys.readouterr().out

    # Again: the line is there, the forge still refuses; nothing is written twice
    forge.calls.clear()
    assert link(ch, forge, "o/r#1", "--child", "someone/else#2") == 0
    assert forge.writes() == ["addSubIssue"]
    assert forge.body("o/r#1") == "Depends on someone/else#2"
    assert capsys.readouterr().out.strip() == "text only: Issues must belong to the same owner"


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["o/r5", "--blocked-by", "o/r#4"], "'o/r5'"),
        (["o/r#5", "--blocked-by", "#4"], "'#4'"),
        (["o/r#5", "--child", "o/r#0"], "'o/r#0'"),
        (["o/r#5", "--blocked-by", "o/r#404"], "no issue o/r#404"),
        (["o/r#5", "--blocked-by", "o/r#7"], "o/r#7 is a pull request"),
        (["o/r#7", "--child", "o/r#4"], "o/r#7 is a pull request"),
        (["o/r#5", "--blocked-by", "O/R#5"], "o/r#5 can't be linked to itself"),
        (["o/r#5", "--child", "o/r#5"], "o/r#5 can't be linked to itself"),
    ],
)
def test_s017_9_bad_references_exit_2_naming_them_before_any_write(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], argv: list[str], named: str
) -> None:
    forge.add("o/r#5", "Body")
    forge.add("o/r#4")
    forge.add("o/r#7", kind="PullRequest")
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, *argv)
    assert exit_.value.code == 2
    assert named in capsys.readouterr().err
    assert forge.writes() == []
    assert forge.body("o/r#5") == "Body"


def test_a_rate_limit_is_a_gh_failure_not_a_refusal(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.add("o/r#5")
    forge.add("o/r#4")
    forge.rate_limited = True
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#5", "--blocked-by", "o/r#4")
    assert exit_.value.code == 2
    assert "rate limit" in capsys.readouterr().err
    assert forge.writes() == []


@pytest.mark.parametrize(
    "failure",
    [
        error("Something went wrong while executing your query. This may be the result of a timeout"),
        error("Could not resolve to a node with the global id of 'I_o/r#5'", "NOT_FOUND"),
        error("Internal server error", "INTERNAL"),
    ],
)
@pytest.mark.parametrize("on", ["read", "write"])
def test_a_transient_error_on_the_relation_is_a_gh_failure_not_a_refusal(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], failure: dict[str, Any], on: str
) -> None:
    # Only the forge refusing the relation goes text only; a timeout or an internal error
    # exits 2 with nothing written, so a rerun adds both halves
    forge.add("o/r#5", "Body")
    forge.add("o/r#4")
    forge.relation_error = (on, failure)
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#5", "--blocked-by", "o/r#4")
    assert exit_.value.code == 2
    assert failure["message"] in capsys.readouterr().err
    assert forge.writes() == ([] if on == "read" else ["addBlockedBy"])
    assert forge.body("o/r#5") == "Body"


def test_a_forbidden_relation_is_a_refusal(ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str]) -> None:
    forge.add("o/r#1")
    forge.add("someone/else#2")
    forge.relation_error = ("write", error("Resource not accessible by integration", "FORBIDDEN"))
    assert link(ch, forge, "o/r#1", "--child", "someone/else#2") == 0
    assert forge.body("o/r#1") == "Depends on someone/else#2"
    assert "text only: Resource not accessible by integration" in capsys.readouterr().out


def test_the_script_runs_from_its_folder_and_refuses_a_malformed_reference_before_gh(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "chains.py"), "link", "nope", "--blocked-by", "o/r#4"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": str(tmp_path)},  # no gh at all: it must not be reached
    )
    assert proc.returncode == 2
    assert "malformed reference 'nope'" in proc.stderr


# -- #526: with [agents] app_id set, link writes as the App (D-14)

APP_CONFIG = '[agents]\nprompt = "Triage the repo"\napp_id = 123\n'
# the plugin's pinned CLI, never a shipmill from PATH (spec 031, D-43)
UVX = [
    "uvx",
    f"shipmill=={json.loads((ROOT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']}",
]


def checkout(root: Path, config: str | None) -> Path:
    (root / ".git").mkdir(parents=True)
    if config is not None:
        (root / ".github").mkdir()
        (root / ".github" / "shipmill.toml").write_text(config, encoding="utf-8")
    return root


def gh_call(cmd: list[str]) -> tuple[str, dict[str, Any]]:
    """The query and variables of a `gh api graphql` command line as chains.py builds it"""
    assert cmd[:3] == ["api", "graphql", "-f"] and cmd[3].startswith("query="), cmd
    query, variables = cmd[3].removeprefix("query="), {}
    for flag, pair in zip(cmd[4::2], cmd[5::2], strict=True):
        key, _, value = pair.partition("=")
        variables[key] = int(value) if flag == "-F" else value
    return query, variables


class AppGh:
    """`shipmill gh` in front of the fake forge: each command it is given, and its exit code
    (gh's on success, 2 when the App's identity can't be had)"""

    def __init__(self, forge: Forge, prefix: list[str], code: int = 0) -> None:
        self.forge, self.prefix, self.code = forge, prefix, code
        self.ran: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.ran.append(cmd)
        assert cmd[: len(self.prefix)] == self.prefix, cmd
        if self.code == 2:
            return subprocess.CompletedProcess(cmd, 2, "", "error: the App's private key is missing\n")
        response = self.forge(*gh_call(cmd[len(self.prefix) :]))
        return subprocess.CompletedProcess(cmd, 1 if response.get("errors") else 0, json.dumps(response), "")


def test_526_the_writer_is_shipmill_gh_with_app_id_and_plain_gh_without(ch: ModuleType, tmp_path: Path) -> None:
    app = checkout(tmp_path / "app", APP_CONFIG)
    plain = checkout(tmp_path / "plain", '[agents]\nprompt = "Triage the repo"\n')
    bare = checkout(tmp_path / "bare", None)
    assert ch.writer(app) == [*UVX, "--repo", str(app.resolve()), "gh"]
    assert ch.writer(app / ".github") == [*UVX, "--repo", str(app.resolve()), "gh"]  # from a subfolder too
    assert ch.writer(plain) == ["gh"]
    assert ch.writer(bare) == ["gh"]


def test_526_a_config_with_app_id_it_cannot_read_exits_2(
    ch: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = checkout(tmp_path, "[agents]\napp_id = \n")
    with pytest.raises(SystemExit) as exit_:
        ch.writer(broken)
    assert exit_.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("child", [False, True])
def test_526_with_app_id_the_relation_and_the_body_edit_go_through_shipmill_gh(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], child: bool
) -> None:
    a = forge.add("o/r#5", "Build the page.\r\n")
    b = forge.add("o/r#4")
    prefix = ch.writer(checkout(tmp_path, APP_CONFIG))
    app = AppGh(forge, prefix)
    how = "--child" if child else "--blocked-by"
    assert ch.main(["link", "o/r#5", how, "o/r#4"], run=forge, write=ch.gh_runner(prefix, app)) == 0
    assert (forge.parents[b] == a) if child else ((a, b) in forge.blocked)
    assert forge.body("o/r#5") == "Build the page.\r\n\r\nDepends on o/r#4"  # byte for byte, then the line
    mutation = "addSubIssue" if child else "addBlockedBy"
    written = [gh_call(cmd[len(prefix) :])[0] for cmd in app.ran]
    assert written == [ch.ADD_SUB_ISSUE if child else ch.ADD_BLOCKED_BY, ch.UPDATE_BODY]
    assert forge.writes() == [mutation, "updateIssue"]
    reads = [q for q, _ in forge.calls if q not in written]
    assert reads and len(forge.calls) == len(reads) + 2  # the reads stayed on the plain runner
    assert "added to o/r#5: Depends on o/r#4" in capsys.readouterr().out


def test_526_a_refused_relation_still_writes_the_line_as_the_app(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.refuse_write = "Issues must belong to the same owner"
    forge.add("o/r#1")
    forge.add("someone/else#2")
    prefix = ch.writer(checkout(tmp_path, APP_CONFIG))
    app = AppGh(forge, prefix)
    assert ch.main(["link", "o/r#1", "--child", "someone/else#2"], run=forge, write=ch.gh_runner(prefix, app)) == 0
    assert forge.body("o/r#1") == "Depends on someone/else#2"
    assert len(app.ran) == 2
    assert "text only: Issues must belong to the same owner" in capsys.readouterr().out


def test_526_an_exit_2_from_shipmill_gh_stops_the_link_with_no_fallback(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.add("o/r#5", "Body")
    forge.add("o/r#4")
    prefix = ch.writer(checkout(tmp_path, APP_CONFIG))
    app = AppGh(forge, prefix, code=2)
    with pytest.raises(SystemExit) as exit_:
        ch.main(["link", "o/r#5", "--blocked-by", "o/r#4"], run=forge, write=ch.gh_runner(prefix, app))
    assert exit_.value.code == 2
    assert "the App's private key is missing" in capsys.readouterr().err
    assert len(app.ran) == 1  # the relation's mutation, not retried, and no body edit after it
    assert forge.writes() == []
    assert forge.body("o/r#5") == "Body"


FAKE_GH = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["gh", *args]) + "\\n")
query = args[3]
if "mutation" in query:
    print(json.dumps({{"data": {{"wrote": True}}}}))
elif "issueOrPullRequest" in query:
    number = next(a for a in args if a.startswith("number=")).partition("=")[2]
    print(json.dumps({{"data": {{"repository": {{"issueOrPullRequest": {{
        "__typename": "Issue", "id": "I_" + number, "body": "Body"}}}}}}}}))
else:
    print(json.dumps({{"data": {{"node": {{"blockedBy": {{
        "pageInfo": {{"hasNextPage": False, "endCursor": None}}, "nodes": []}}}}}}}}))
"""
FAKE_UVX = """#!{python}
import json, os, sys
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["uvx", *sys.argv[1:]]) + "\\n")
sys.stderr.write("error: the App's private key is missing\\n")
sys.exit({code})
"""


def run_script(tmp_path: Path, config: str | None, code: int = 2) -> tuple[subprocess.CompletedProcess[str], list[Any]]:
    """chains.py link run from a checkout, with a stand-in gh and uvx on PATH"""
    bin_dir, log = tmp_path / "bin", tmp_path / "log.jsonl"
    bin_dir.mkdir()
    for name, text in (("gh", FAKE_GH), ("uvx", FAKE_UVX)):
        (bin_dir / name).write_text(text.format(python=sys.executable, code=code), encoding="utf-8")
        (bin_dir / name).chmod(0o700)
    repo = checkout(tmp_path / "repo", config)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "chains.py"), "link", "o/r#5", "--blocked-by", "o/r#4"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env={"PATH": str(bin_dir), "FAKE_LOG": str(log)},
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return proc, calls


def test_526_run_from_a_checkout_with_app_id_the_script_writes_through_shipmill_gh(tmp_path: Path) -> None:
    proc, calls = run_script(tmp_path, APP_CONFIG)
    assert proc.returncode == 2
    assert "the App's private key is missing" in proc.stderr
    shipmill = [c for c in calls if c[0] == "uvx"]
    top = str((tmp_path / "repo").resolve())
    assert len(shipmill) == 1 and shipmill[0][1:7] == [UVX[1], "--repo", top, "gh", "api", "graphql"]
    assert "addBlockedBy" in shipmill[0][8]
    assert all("mutation" not in c[4] for c in calls if c[0] == "gh")  # reads only, never a plain-gh write


def test_526_run_from_a_checkout_without_app_id_the_script_writes_with_plain_gh(tmp_path: Path) -> None:
    proc, calls = run_script(tmp_path, '[agents]\nprompt = "Triage the repo"\n')
    assert proc.returncode == 0, proc.stderr
    assert [c[0] for c in calls] == ["gh"] * len(calls)
    assert sum("mutation" in c[4] for c in calls) == 2  # the relation and the body edit
