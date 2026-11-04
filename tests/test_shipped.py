"""github-pr-triage's shipped.py: which closed issues a release fixed, read and reported, never
commented on (D-69, #921), without gh"""

import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-pr-triage" / "scripts" / "shipped.py"


def closed(number: int = 5) -> dict[str, Any]:
    """A closed issue as shipped.py reads it"""
    return {"state": "CLOSED", "title": "a fix", "url": f"https://github.com/me/demo/issues/{number}"}


def variables(cmd: list[str]) -> dict[str, str]:
    """A gh api graphql call's -f and -F fields but the query"""
    pairs = (cmd[i + 1].partition("=") for i, a in enumerate(cmd) if a in ("-f", "-F"))
    return {k: v for k, _, v in pairs if k != "query"}


class Forge:
    """A fake gh answering shipped.py's aliased GraphQL reads as GitHub does, recording each call:
    prs by commit, issues by number (a number not among them resolves to nothing, as GitHub
    answers: null data and a NOT_FOUND error)"""

    def __init__(
        self, prs: dict[str, list[dict[str, Any]]] | None = None, issues: dict[int, dict[str, Any]] | None = None
    ) -> None:
        self.prs = prs or {}
        self.issues = issues or {}
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.calls.append(cmd)
        if cmd[:3] != ["gh", "api", "graphql"]:
            return ""
        repository: dict[str, Any] = {}
        errors = []
        for key, value in variables(cmd).items():
            if re.fullmatch(r"o\d+", key):
                repository[f"c{key[1:]}"] = {"associatedPullRequests": {"nodes": self.prs.get(value, [])}}
            elif re.fullmatch(r"n\d+", key):
                alias, number = f"i{key[1:]}", int(value)
                if number not in self.issues:
                    repository[alias] = None
                    errors.append({"type": "NOT_FOUND", "path": ["repository", alias], "message": f"no {number}"})
                elif "/pull/" in self.issues[number]["url"]:
                    repository[alias] = {"url": self.issues[number]["url"]}
                else:
                    repository[alias] = self.issues[number]
        out: dict[str, Any] = {"data": {"repository": repository}}
        return json.dumps({**out, "errors": errors} if errors else out)


@pytest.fixture(scope="module")
def sp() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shipped", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pr(
    body: str, title: str = "a change", links: tuple[tuple[int, str], ...] = (), merged: bool = True
) -> dict[str, Any]:
    nodes = [{"number": n, "repository": {"nameWithOwner": r}} for n, r in links]
    return {
        "number": 9,
        "title": title,
        "body": body,
        "mergedAt": "2026-10-01T00:00:00Z" if merged else None,
        "closingIssuesReferences": {"nodes": nodes},
    }


def test_368_a_closing_keyword_quoted_mid_line_or_in_backticks_names_nothing(sp: ModuleType) -> None:
    body = "\n".join(
        [
            'It quotes the bug ("... Closes #424.") mid-line, and `Fixes #425` too',
            "`Closes #426` in backticks at the start of a line",
            "> Closes #427, a quote",
            "```",
            "Fixes #428",
            "```",
            "Fixes #5",
            "- Closes #6",
            "resolves: #7",
        ]
    )
    found = sp.pr_closes("me/demo", pr(body, "Fix the thing (fixes #11, not `fixes #12`)"))
    assert found == {5, 6, 7, 11}


def test_368_github_s_closing_links_count_only_in_the_repo(sp: ModuleType) -> None:
    links = ((13, "me/demo"), (14, "Me/Demo"), (15, "other/repo"))
    assert sp.pr_closes("me/demo", pr("no keyword here", links=links)) == {13, 14}


def test_368_collect_reads_commit_trailers_and_merged_prs_once(sp: ModuleType) -> None:
    prs = [pr('quotes ("Closes #424.")\nFixes #5'), {**pr("Fixes #8", merged=False), "number": 10}]
    gh = Forge(prs={"a" * 40: prs, "b" * 40: prs})
    pairs = [("a" * 40, "a change\n\nFixes #3\nsee Fixes #4 mid-line"), ("b" * 40, "a second")]
    assert sp.collect("me/demo", pairs, gh) == {3: {"aaaaaaa"}, 5: {"PR #9"}}
    (call,) = gh.calls
    assert call[:3] == ["gh", "api", "graphql"]
    assert f"o1={'b' * 40}" in call


def test_368_an_unresolvable_number_is_skipped_and_the_rest_still_reported(
    sp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = Forge(issues={500: closed(500)})  # 424 resolves to nothing: null, and GitHub's NOT_FOUND
    sp.report("me/demo", {424: {"PR #365"}, 500: {"abc1234"}}, "v1.2.0", "stable", False, gh)
    out = capsys.readouterr()
    assert out.err == "note: #424 [PR #365] is no issue or pull request of me/demo, skipped\n"
    assert out.out == "#500   FIXED      a fix  [abc1234]\n"


def answer(errors: list[dict[str, Any]], data: dict[str, Any] | None = None) -> str:
    return json.dumps({"data": {"repository": {"i0": None}} if data is None else data, "errors": errors})


MISSING_I0 = {"type": "NOT_FOUND", "path": ["repository", "i0"], "message": "Could not resolve to an issue"}


@pytest.mark.parametrize(
    ("cmd", "stdout", "expected"),
    [
        (["gh", "api", "graphql", "-f", "query=x"], answer([MISSING_I0]), True),
        (["gh", "api", "graphql"], answer([MISSING_I0, {"type": "RATE_LIMITED", "message": "slow down"}]), False),
        (["gh", "api", "graphql"], json.dumps({"data": None, "errors": [MISSING_I0]}), False),  # no data at all
        (["gh", "api", "graphql"], json.dumps({"message": "Bad credentials"}), False),
        (["gh", "api", "graphql"], "", False),  # no answer at all: a network failure
        (["gh", "issue", "view", "424"], answer([MISSING_I0]), False),  # only a GraphQL read skips
    ],
)
def test_368_only_graphql_s_not_found_answer_passes_a_failed_gh(
    sp: ModuleType, cmd: list[str], stdout: str, expected: bool
) -> None:
    assert sp.partial(cmd, stdout) is expected


@pytest.mark.parametrize(
    "error",
    [
        {**MISSING_I0, "path": ["repository"]},  # the repository itself: never a skip
        {**MISSING_I0, "path": ["repository", "i7"]},  # an alias the query didn't ask for
        {**MISSING_I0, "type": "FORBIDDEN"},
        {"message": "Something went wrong"},
    ],
)
def test_368_any_other_graphql_error_stops_the_whole_batch(
    sp: ModuleType, error: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        sp.views("me/demo", [424], lambda cmd: answer([error]))
    assert exc.value.code == 2
    assert capsys.readouterr().err.startswith("error: gh api graphql...")


def test_368_a_numeric_repo_name_reaches_graphql_as_a_string(sp: ModuleType) -> None:
    # gh's -F turns "2048" into a number, and GraphQL refuses it for String!; -f keeps it a string
    gh = Forge()
    sp.prs_for("1984/2048", "1" * 40, gh)
    sp.views("1984/2048", [5], gh)
    flags = [{c[i + 1].partition("=")[0]: a for i, a in enumerate(c) if a in ("-f", "-F")} for c in gh.calls]
    assert flags == [
        {"query": "-f", "owner": "-f", "name": "-f", "o0": "-f"},
        {"query": "-f", "owner": "-f", "name": "-f", "n0": "-F"},  # an issue number is GraphQL's Int!
    ]


# -- #754: the reads batched in aliased GraphQL queries


def test_754_120_commits_are_read_in_ceil_120_over_the_batch_queries(sp: ModuleType) -> None:
    shas = [f"{i:040x}" for i in range(120)]
    linked = pr("Fixes #5")
    gh = Forge(prs={shas[77]: [linked]})
    pairs = [(sha, "a change") for sha in shas]
    assert sp.collect("me/demo", pairs, gh) == {5: {"PR #9"}}
    assert len(gh.calls) == math.ceil(120 / sp.COMMITS_PER_QUERY) > 1
    asked = [v for call in gh.calls for k, v in variables(call).items() if re.fullmatch(r"o\d+", k)]
    assert asked == shas  # each commit once, in order
    assert all("$o0: GitObjectID!" in call[4] for call in gh.calls)


def test_754_the_issues_are_read_in_one_query(sp: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    issues = {
        5: closed(5),
        6: closed(6),
        7: {**closed(7), "state": "OPEN"},
        8: {**closed(8), "url": "https://github.com/me/demo/pull/8"},  # a pull request: skipped silently
    }
    gh = Forge(issues=issues)
    sp.report("me/demo", {5: {"a"}, 6: {"b", "PR #3"}, 7: {"c"}, 8: {"d"}, 9: {"e"}}, "v1.2.0", "stable", False, gh)
    out = capsys.readouterr()
    assert out.out.splitlines() == [
        "#5     FIXED      a fix  [a]",
        "#6     FIXED      a fix  [PR #3, b]",
        "#7     SKIP open  a fix  [c]",
    ]
    assert out.err == "note: #9 [e] is no issue or pull request of me/demo, skipped\n"
    assert len(gh.calls) == 1


def test_754_more_issues_than_a_query_takes_are_read_in_batches(sp: ModuleType) -> None:
    numbers = list(range(1, 2 * sp.ISSUES_PER_QUERY + 2))
    gh = Forge(issues={n: closed(n) for n in numbers})
    found = sp.views("me/demo", numbers, gh)
    assert sorted(found) == numbers and all(v is not None and v["state"] == "CLOSED" for v in found.values())
    assert len(gh.calls) == 3


def test_754_an_empty_range_makes_no_call(sp: ModuleType) -> None:
    gh = Forge()
    assert sp.collect("me/demo", [], gh) == {}
    sp.report("me/demo", {}, "v1.2.0", "stable", True, gh)
    assert gh.calls == []


def test_754_each_query_stays_well_under_github_s_node_limit(sp: ModuleType) -> None:
    per_commit = sp.PRS_READ + sp.PRS_READ * sp.CLOSERS_READ
    assert sp.COMMITS_PER_QUERY * per_commit <= sp.NODE_LIMIT // 5
    assert f"associatedPullRequests(first: {sp.PRS_READ})" in sp.PULL_FIELDS
    assert f"closingIssuesReferences(first: {sp.CLOSERS_READ})" in sp.PULL_FIELDS
    assert "comments" not in sp.ISSUE_FIELDS  # D-69: no notice is looked for, so no comment is read


def test_754_a_commit_github_does_not_have_stops_the_run(sp: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    def gh(cmd: list[str]) -> str:
        return json.dumps({"data": {"repository": {"c0": {"associatedPullRequests": {"nodes": []}}, "c1": None}}})

    with pytest.raises(SystemExit) as exc:
        sp.prs_of("me/demo", ["a" * 40, "b" * 40], gh)
    assert exc.value.code == 2
    assert capsys.readouterr().err == f"error: me/demo has no commit {'b' * 40}\n"


# -- S-021-9 (D-69, #921): the link from an issue to its release, as machine output


def records(sp: ModuleType, capsys: pytest.CaptureFixture[str], tag: str, stage: str) -> list[dict[str, Any]]:
    """What --json prints for #5 (closed, named by two sources), #6 (open), and #7 (a pull request)"""
    issues = {
        5: closed(5),
        6: {**closed(6), "state": "OPEN"},
        7: {**closed(7), "url": "https://github.com/me/demo/pull/7"},
    }
    gh = Forge(issues=issues)
    sp.report("me/demo", {5: {"PR #12", "abc1234"}, 6: {"def5678"}, 7: {"PR #7"}}, tag, stage, True, gh)
    assert all(c[:3] == ["gh", "api", "graphql"] for c in gh.calls)  # reads only: nothing is written
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.mark.parametrize(
    ("tag", "stage"),
    [("v1.2.0", "stable"), ("v1.2.0rc1", "pre-release"), ("v1.3.0.dev2", "pre-release"), ("nightly", "stable")],
)
def test_s021_9_json_prints_one_record_per_closed_issue_with_its_stage(
    sp: ModuleType, capsys: pytest.CaptureFixture[str], tag: str, stage: str
) -> None:
    assert sp.stage_of(tag) == stage
    found = records(sp, capsys, tag, sp.stage_of(tag))
    assert found == [{"number": 5, "tag": tag, "stage": stage, "source": ["PR #12", "abc1234"]}]


def test_s021_9_a_deployment_s_records_carry_the_environment_as_their_stage(
    sp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    found = records(sp, capsys, "v1.2.0", "staging")
    assert found == [{"number": 5, "tag": "v1.2.0", "stage": "staging", "source": ["PR #12", "abc1234"]}]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def stamp(repo: Path, base: str, tag: str) -> None:
    """A release as shipmill cuts it: a stamp commit off main whose first parent is base"""
    git(repo, "checkout", "-q", "--detach", base)
    git(repo, "commit", "-q", "--allow-empty", "-m", f"Release {tag[1:]}")
    git(repo, "tag", tag)
    git(repo, "checkout", "-q", "main")


def test_s021_9_a_stable_promotion_reports_every_fix_its_rc_held(sp: ModuleType, tmp_path: Path) -> None:
    # v1.0.0 promotes rc1 after rc2 was cut: v1.0.0rc2..v1.0.0 holds only the stamp commit
    repo = tmp_path / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "start")
    stamp(repo, "main", "v0.9.0")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Fix the thing\n\nFixes #5")
    rc1_base = git(repo, "rev-parse", "HEAD")
    stamp(repo, "main", "v1.0.0rc1")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Fix another\n\nFixes #6")
    stamp(repo, "main", "v1.0.0rc2")
    stamp(repo, rc1_base, "v1.0.0")
    assert [body for _, body in sp.commits(str(repo), "v1.0.0rc2", "v1.0.0")] == ["Release 1.0.0"]
    pairs = sp.release_commits(str(repo), "v1.0.0rc2", "v1.0.0")
    assert sp.collect("me/demo", pairs, Forge()) == {5: {rc1_base[:7]}}  # not #6: rc2's fix isn't held
    # a pre-release reads only its own range, as before
    assert sp.release_commits(str(repo), "v1.0.0rc1", "v1.0.0rc2") == sp.commits(str(repo), "v1.0.0rc1", "v1.0.0rc2")


def test_s021_9_a_first_stable_reads_its_whole_history(sp: ModuleType, tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "start")
    stamp(repo, "main", "v1.0.0rc1")
    stamp(repo, "main", "v1.0.0rc2")
    stamp(repo, "main", "v1.0.0")
    git(repo, "tag", "nightly")  # not a version tag: never a floor
    assert sp.own_range(str(repo), "v1.0.0") == "v1.0.0"  # only rcs below: its whole history
    assert sp.own_range(str(repo), "v1.0.0rc2") is None
    assert sp.own_range(str(repo), "v1.0.0rc1") is None
    assert sp.own_range(str(repo), "nightly") is None
    stamp(repo, "main", "v1.1.0")
    assert sp.own_range(str(repo), "v1.1.0") == "v1.0.0..v1.1.0"


def test_s021_9_a_first_stable_reports_the_fixes_its_oldest_rc_held(sp: ModuleType, tmp_path: Path) -> None:
    # the first stable promotes rc1, the oldest tag: rc1..v1.0.0 holds only the stamp commit
    repo = tmp_path / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Fix the thing\n\nFixes #5")
    rc1_base = git(repo, "rev-parse", "HEAD")
    stamp(repo, "main", "v1.0.0rc1")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Fix another\n\nFixes #6")
    stamp(repo, "main", "v1.0.0rc2")
    stamp(repo, rc1_base, "v1.0.0")
    for prev in ("v1.0.0rc1", "v1.0.0rc2"):
        assert sp.collect("me/demo", sp.release_commits(str(repo), prev, "v1.0.0"), Forge()) == {5: {rc1_base[:7]}}


def script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


@pytest.mark.parametrize("name", ["stable", "pre-release", "", "-x", "a b", "prod/eu"])
def test_s021_9_environment_must_be_an_environment_s_name(name: str) -> None:
    done = script("me/demo", "v1.0.0", "v1.1.0", "--environment", name)
    assert done.returncode == 2
    assert "environment" in done.stderr


@pytest.mark.parametrize("flag", [["--post"], ["--install", "uv add demo"]])
def test_s021_9_the_flags_that_posted_a_notice_are_gone(flag: list[str]) -> None:
    # D-69: a caller still asking to post fails on the flag, before any read
    done = script("me/demo", "v1.0.0", "v1.1.0", *flag)
    assert done.returncode == 2
    assert "unrecognized arguments" in done.stderr
