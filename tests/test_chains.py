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


@pytest.mark.parametrize("child", [True, False])
def test_s028_15_no_text_writes_the_relation_alone_and_leaves_the_body(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], child: bool
) -> None:
    # An accepted plan's body must stay as accepted: the relation, and no Depends on line
    plan = "<!-- shipmill:goal-plan G-1 rev 1 -->\n## Milestone\nv2\n"
    p, c = forge.add("o/r#1", plan), forge.add("o/r#2")
    how = "--child" if child else "--blocked-by"
    assert link(ch, forge, "o/r#1", how, "o/r#2", "--no-text") == 0
    assert (forge.parents.get(c) == p) if child else ((p, c) in forge.blocked)
    assert forge.body("o/r#1") == plan
    assert forge.writes() == ["addSubIssue" if child else "addBlockedBy"]
    relation = "o/r#2 is a sub-issue of o/r#1" if child else "o/r#1 is blocked by o/r#2"
    assert capsys.readouterr().out.strip() == f"linked: {relation}"

    forge.calls.clear()  # again: the relation is there, nothing is written
    assert link(ch, forge, "o/r#1", how, "o/r#2", "--no-text") == 0
    assert forge.writes() == []
    assert forge.body("o/r#1") == plan
    assert capsys.readouterr().out.strip() == "already linked"


@pytest.mark.parametrize(
    ("refuse", "named"),
    [
        ("write", "Issues must belong to the same owner"),
        ("read", "Field 'parent' doesn't exist on type 'Issue'"),
        ("forbidden", "Resource not accessible by integration"),
    ],
)
def test_s028_15_no_text_fails_when_the_forge_refuses_the_relation(
    ch: ModuleType, forge: Forge, capsys: pytest.CaptureFixture[str], refuse: str, named: str
) -> None:
    # No text fallback: a refusal exits 2 with the forge's error and writes nothing
    forge.add("o/r#1", "Plan\n")
    forge.add("someone/else#2")
    if refuse == "write":
        forge.refuse_write = named
    elif refuse == "read":
        forge.refuse_read = named
    else:
        forge.relation_error = ("write", error(named, "FORBIDDEN"))
    with pytest.raises(SystemExit) as exit_:
        link(ch, forge, "o/r#1", "--child", "someone/else#2", "--no-text")
    assert exit_.value.code == 2
    captured = capsys.readouterr()
    assert named in captured.err and "--no-text" in captured.err
    assert "text only" not in captured.out
    assert forge.body("o/r#1") == "Plan\n"
    assert "updateIssue" not in forge.writes()


def test_s028_15_no_text_with_product_writes_the_sub_issue_alone_through_the_product_token(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p, c = forge.add("acme/api#3", "The report\n"), forge.add("acme/web#7")
    argv = ("--product", "acme/api#3", "--child", "acme/web#7", "--no-text")
    code, git = run_link(ch, forge, tmp_path, COORDINATOR, "acme/product", *argv)
    assert code == 0
    assert forge.parents[c] == p and forge.body("acme/api#3") == "The report\n"
    top = (tmp_path / "repo").resolve()
    assert git.writes() == [[*UVX, "--repo", str(top), "gh", "--product", "acme/api"]]  # the sub-issue alone
    assert forge.writes() == ["addSubIssue"]
    assert capsys.readouterr().out.strip() == "linked: acme/web#7 is a sub-issue of acme/api#3"


@pytest.mark.parametrize("how", ["--child", "--blocked-by"])
def test_s028_15_no_text_in_a_component_still_refuses_another_repo_before_any_write(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], how: str
) -> None:
    # --no-text drops the Depends on line, never the component's same-repo rule (D-47)
    forge.add("acme/api#5", "Plan\n")
    forge.add("acme/web#4")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, COMPONENT, "acme/api", "acme/api#5", how, "acme/web#4", "--no-text")
    assert exit_.value.code == 2
    assert "a component of acme/product" in capsys.readouterr().err
    assert forge.calls == []


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


# -- spec 038: a component links within its repo; the coordinator links with --product (D-47)

PRODUCT_APP = '[agents]\nprompt = "Triage the repo"\napp_id = 123\n'
COMPONENT = PRODUCT_APP + '\n[product]\nhome = "acme/product"\n'
COORDINATOR = PRODUCT_APP + '\n[product]\nrepos = ["acme/api", "Acme/Web"]\n'


class Checkout:
    """git and the writes' gh in front of the fake forge, for a checkout whose origin is origin
    (None: no origin remote): every command run, and each write's gh prefix"""

    def __init__(self, forge: Forge, origin: str | None, code: int = 0) -> None:
        self.forge, self.origin, self.code = forge, origin, code
        self.ran: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.ran.append(cmd)
        if cmd[0] == "git":
            assert cmd[3:] == ["remote", "get-url", "origin"], cmd
            if self.origin is None:
                return subprocess.CompletedProcess(cmd, 2, "", "error: No such remote 'origin'\n")
            return subprocess.CompletedProcess(cmd, 0, f"git@github.com:{self.origin}.git\n", "")
        if self.code == 2:  # `shipmill gh` without the App's identity
            return subprocess.CompletedProcess(cmd, 2, "", "error: the App's private key is missing\n")
        response = self.forge(*gh_call(cmd[cmd.index("api") :]))
        return subprocess.CompletedProcess(cmd, 1 if response.get("errors") else 0, json.dumps(response), "")

    def gh(self, mutations: bool) -> list[list[str]]:
        """The prefix of each gh call run here that is a write (mutations) or a read"""
        calls = [cmd for cmd in self.ran if cmd[0] != "git"]
        return [
            cmd[: cmd.index("api")] for cmd in calls if ("mutation" in gh_call(cmd[cmd.index("api") :])[0]) is mutations
        ]

    def writes(self) -> list[list[str]]:
        return self.gh(mutations=True)

    def reads(self) -> list[list[str]]:
        """The reads run here, not on the plain runner: a listed repo's, through the product token"""
        return self.gh(mutations=False)


def run_link(
    ch: ModuleType, forge: Forge, tmp_path: Path, config: str | None, origin: str | None, *argv: str
) -> tuple[int, Checkout]:
    """chains.py link from a checkout (from its .github subfolder when it has a config)"""
    git = Checkout(forge, origin)
    top = checkout(tmp_path / "repo", config)
    here = top / ".github" if config is not None else top
    code: int = ch.main(["link", *argv], run=forge, checkout=here, execute=git)
    return code, git


def prepare(forge: Forge, parent: str, other: str, state: str, child: bool) -> None:
    """Two issues, linked already in both forms, or with the forge refusing the relation"""
    p, o = forge.add(parent, "Body"), forge.add(other)
    if state == "already linked":
        if child:
            forge.parents[o] = p
        else:
            forge.blocked.add((p, o))
        next(i for i in forge.issues.values() if i["id"] == p)["body"] = f"Depends on {other}"
    if state == "text only":
        forge.refuse_write = "Issues must belong to the same owner"


STATES = ["new", "already linked", "text only"]


@pytest.mark.parametrize(
    "argv",
    [
        ["acme/api#5", "--blocked-by", "acme/web#4"],
        ["acme/api#5", "--blocked-by", "acme/product#4"],  # waits on its home's item
        ["acme/product#4", "--blocked-by", "acme/api#5"],  # the other way round
        ["acme/api#5", "--child", "acme/web#4"],
        ["Acme/API#5", "--child", "acme/api-old#4"],
    ],
)
@pytest.mark.parametrize("state", STATES)
def test_s038_11_a_component_refuses_another_repo_s_reference_before_any_write(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], state: str
) -> None:
    prepare(forge, argv[0], argv[2], state, argv[1] == "--child")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, COMPONENT, "acme/api", *argv)
    assert exit_.value.code == 2
    err = capsys.readouterr().err
    assert "a component of acme/product" in err and "D-47" in err and "upstream" in err
    assert forge.calls == []  # not one read, so not one write


def test_s038_11_a_component_without_a_known_origin_refuses_every_link(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge.add("acme/api#5")
    forge.add("acme/api#4")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, COMPONENT, None, "acme/api#5", "--blocked-by", "acme/api#4")
    assert exit_.value.code == 2
    assert "the checkout's origin, which can't be told" in capsys.readouterr().err
    assert forge.calls == []


def test_s038_11_a_component_links_within_its_own_repo_as_before(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = forge.add("acme/api#5", "Body\n")
    r = forge.add("acme/api#9")
    code, git = run_link(ch, forge, tmp_path, COMPONENT, "Acme/Api", "ACME/api#5", "--blocked-by", "acme/API#9")
    assert code == 0  # GitHub ignores case, and so does the check
    assert (a, r) in forge.blocked and forge.body("acme/api#5") == "Body\n\nDepends on acme/API#9"
    top = str((tmp_path / "repo").resolve())
    assert git.writes() == [[*UVX, "--repo", top, "gh"]] * 2  # the session's App, as before
    assert "added to ACME/api#5" in capsys.readouterr().out


def through(top: Path, repo: str) -> list[str]:
    """The gh prefix a coordinator's call on repo runs with: the session's `shipmill gh` for
    the home repo (acme/product), `shipmill gh --product <repo>` for a listed one"""
    session = [*UVX, "--repo", str(top), "gh"]
    return session if repo.lower() == "acme/product" else [*session, "--product", repo]


@pytest.mark.parametrize(
    ("parent", "child"),
    [
        ("acme/api#3", "acme/web#7"),
        ("ACME/Web#3", "acme/product#7"),
        ("acme/api#3", "acme/api#7"),
        ("acme/product#3", "acme/web#7"),  # a report in the home repo itself (#596)
        ("Acme/Product#3", "acme/product#7"),
    ],
)
def test_s038_29_product_child_writes_through_the_session_or_the_product_token_and_reads_a_listed_repo_with_it(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], parent: str, child: str
) -> None:
    p, c = forge.add(parent, "The report\n"), forge.add(child)
    code, git = run_link(ch, forge, tmp_path, COORDINATOR, "acme/product", "--product", parent, "--child", child)
    assert code == 0
    assert forge.parents[c] == p and forge.body(parent) == f"The report\n\nDepends on {child}"
    top = (tmp_path / "repo").resolve()
    p_repo, c_repo = parent.partition("#")[0], child.partition("#")[0]
    assert git.writes() == [through(top, p_repo)] * 2  # the sub-issue, the line: never --product for the home
    assert forge.writes() == ["addSubIssue", "updateIssue"]
    # resolving P, resolving C, C's parent: a listed repo's through the product token, never plain gh
    reads = [through(top, p_repo), through(top, c_repo), through(top, c_repo)]
    listed = [r for r in reads if "--product" in r]
    assert git.reads() == listed
    on_plain_gh = len(forge.calls) - len(git.reads()) - len(git.writes())  # the runner main was given
    assert on_plain_gh == len(reads) - len(listed)  # the home repo's reads alone
    assert f"linked: {child} is a sub-issue of {parent}" in capsys.readouterr().out

    git.ran.clear()  # again: already linked, nothing written, the same reads
    assert ch.main(["link", "--product", parent, "--child", child], run=forge, checkout=top, execute=git) == 0
    assert git.writes() == [] and git.reads() == listed
    assert capsys.readouterr().out.strip() == "already linked"


@pytest.mark.parametrize("parent", ["acme/api#3", "acme/product#3"])
def test_s038_29_a_shipmill_gh_exit_2_stops_the_link_with_no_plain_gh_fallback(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], parent: str
) -> None:
    # a listed parent fails its first read; a home parent reads with plain gh, then the
    # child's read through the product token fails: nothing is read again with plain gh
    forge.add(parent, "The report\n")
    forge.add("acme/web#7")
    git = Checkout(forge, "acme/product", code=2)
    top = checkout(tmp_path / "repo", COORDINATOR).resolve()
    with pytest.raises(SystemExit) as exit_:
        ch.main(["link", "--product", parent, "--child", "acme/web#7"], run=forge, checkout=top, execute=git)
    assert exit_.value.code == 2
    assert "the App's private key is missing" in capsys.readouterr().err
    assert forge.writes() == [] and forge.body(parent) == "The report\n"
    home = parent.startswith("acme/product")
    assert [q for q, _ in forge.calls] == ([ch.RESOLVE] if home else [])  # the home's own read alone
    assert [cmd[: cmd.index("api")] for cmd in git.ran if cmd[0] != "git"] == [
        through(top, "acme/web" if home else "acme/api")
    ]


@pytest.mark.parametrize(
    ("config", "origin", "argv", "named"),
    [
        (None, "acme/product", ["acme/api#3", "--child", "acme/web#7"], "needs [product] repos"),
        (PRODUCT_APP, "acme/product", ["acme/api#3", "--child", "acme/web#7"], "needs [product] repos"),
        (COMPONENT, "acme/api", ["acme/api#3", "--child", "acme/api#7"], "needs [product] repos"),
        (COORDINATOR, "acme/product", ["acme/api#3", "--child", "acme/sdk#7"], "acme/sdk#7 is in neither"),
        (COORDINATOR, "acme/product", ["other/api#3", "--child", "acme/web#7"], "other/api#3 is in neither"),
        (COORDINATOR, None, ["acme/product#3", "--child", "acme/web#7"], "acme/product#3 is in neither"),
        (COORDINATOR, "acme/product", ["acme/api#3", "--blocked-by", "acme/web#7"], "never --blocked-by"),
    ],
)
@pytest.mark.parametrize("state", STATES)
def test_s038_29_product_exits_2_before_any_read_or_write_outside_the_product(
    ch: ModuleType,
    forge: Forge,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    config: str | None,
    origin: str | None,
    argv: list[str],
    named: str,
    state: str,
) -> None:
    prepare(forge, argv[0], argv[2], state, argv[1] == "--child")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, config, origin, "--product", *argv)
    assert exit_.value.code == 2
    assert named in capsys.readouterr().err
    assert forge.calls == []


@pytest.mark.parametrize(
    ("config", "named"),
    [
        ('[agents]\nprompt = "x"\n\n[product]\nrepos = ["acme/api"]\n', "repos needs [agents] app_id"),
        (PRODUCT_APP + '\n[product]\nrepos = ["acme/api", "acme/product"]\n', "this checkout's own repo"),
        (PRODUCT_APP + '\n[product]\nhome = "ACME/product"\n', "this checkout's own repo"),
        (PRODUCT_APP + '\n[product]\nhome = "acme/x"\nrepos = ["acme/api"]\n', "can't both be set"),
        (PRODUCT_APP + "\n[product]\nrepos = []\n", "at least one repo"),
        (PRODUCT_APP + '\n[product]\nrepos = ["acme/api", "Acme/API"]\n', "twice"),
        (PRODUCT_APP + '\n[product]\nrepos = ["acme"]\n', "owner/name"),
        (PRODUCT_APP + '\n[product]\nrepo = ["acme/api"]\n', "'repo'"),
        (PRODUCT_APP + "\n[product]\n", "neither home"),
    ],
)
def test_s038_29_a_product_table_shipmill_refuses_is_refused_before_any_read(
    ch: ModuleType, forge: Forge, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, named: str
) -> None:
    forge.add("acme/product#3")
    forge.add("acme/product#7")
    with pytest.raises(SystemExit) as exit_:
        run_link(ch, forge, tmp_path, config, "acme/product", "acme/product#3", "--child", "acme/product#7")
    assert exit_.value.code == 2
    assert named in capsys.readouterr().err
    assert forge.calls == []


def test_s038_29_the_310_reader_reads_repos_as_tomllib_does(ch: ModuleType, tmp_path: Path) -> None:
    ws = ch.watch_module()
    policy = tmp_path / "shipmill.toml"
    for text, repos in [
        (COORDINATOR, ("acme/api", "Acme/Web")),
        ("[product]\nrepos = ['acme/api', \"other/sdk\",]  # the components\n", ("acme/api", "other/sdk")),
        (COMPONENT, None),
        (PRODUCT_APP, None),
    ]:
        assert ws.product_repos(text, policy) == repos
        assert ws.product_repos_310(text, policy) == repos
    refused = ['[product]\nrepos = "acme/api"\n', "[product]\nrepos = [1]\n", '[product]\nx = "y"\n']
    for text in refused:
        with pytest.raises(ws.Refused):
            ws.product_repos(text, policy)
        with pytest.raises(ws.Refused, match=r"\[product\]"):
            ws.product_repos_310(text, policy)


def test_s038_29_the_310_reader_refuses_a_product_table_declared_twice(ch: ModuleType, tmp_path: Path) -> None:
    ws = ch.watch_module()
    policy = tmp_path / "shipmill.toml"
    text = '[product]\nrepos = ["acme/api"]\n\n[agents]\napp_id = 1\n\n[ "product" ]\nrepos = ["acme/web"]\n'
    with pytest.raises(ws.Refused):
        ws.product_repos(text, policy)  # tomllib: "Cannot declare ('product',) twice"
    with pytest.raises(ws.Refused, match=r"\[product\] is declared twice"):
        ws.product_repos_310(text, policy)  # never the last table's repos alone


def test_s038_4_without_a_product_table_link_reads_no_origin_and_links_any_repo(
    ch: ModuleType, forge: Forge, tmp_path: Path
) -> None:
    p, c = forge.add("o/r#1"), forge.add("someone/else#2")
    code, git = run_link(ch, forge, tmp_path, PRODUCT_APP, "o/r", "o/r#1", "--child", "someone/else#2")
    assert code == 0 and forge.parents[c] == p
    assert all(cmd[0] != "git" for cmd in git.ran)  # no [product]: the origin is never asked
    top = str((tmp_path / "repo").resolve())
    assert git.writes() == [[*UVX, "--repo", top, "gh"]] * 2
