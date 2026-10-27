"""github-pr-triage's shipped.py: who its notices post as (#290, spec 012), without gh"""

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
# the plugin's pinned CLI (spec 031): the version in .claude-plugin/plugin.json
PINNED = json.loads((SCRIPT.parents[3] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
APP_GH = ["uvx", f"shipmill=={PINNED}", "--repo"]
MARK = "<!-- shipmill:available: stable v1.2.0 -->\n"  # every notice's first line (spec 021)


def closed(number: int = 5, *comments: str) -> dict[str, Any]:
    """A closed issue as shipped.py reads it, with these comments, oldest first"""
    nodes = [
        {"author": {"login": "someone"}, "body": c, "createdAt": "2026-10-01T00:00:00Z", "url": ""} for c in comments
    ]
    return {
        "state": "CLOSED",
        "title": "a fix",
        "comments": nodes,
        "url": f"https://github.com/me/demo/issues/{number}",
    }


def variables(cmd: list[str]) -> dict[str, str]:
    """A gh api graphql call's -f and -F fields but the query"""
    pairs = (cmd[i + 1].partition("=") for i, a in enumerate(cmd) if a in ("-f", "-F"))
    return {k: v for k, _, v in pairs if k != "query"}


class Forge:
    """A fake gh answering shipped.py's aliased GraphQL reads as GitHub does, recording each call:
    prs by commit, issues by number (a number not among them resolves to nothing, as GitHub
    answers: null data and a NOT_FOUND error), comments paged by `page`"""

    def __init__(
        self, prs: dict[str, list[dict[str, Any]]] | None = None, issues: dict[int, dict[str, Any]] | None = None
    ) -> None:
        self.prs = prs or {}
        self.issues = issues or {}
        self.page = 100
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.calls.append(cmd)
        if cmd[:3] != ["gh", "api", "graphql"]:
            return ""
        fields = variables(cmd)
        if "after" in fields:  # the next page of one issue's comments
            start = int(fields["after"])
            return json.dumps({"data": {"repository": {"issueOrPullRequest": self.comments(int(fields["n"]), start)}}})
        repository: dict[str, Any] = {}
        errors = []
        for key, value in fields.items():
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
                    repository[alias] = {**self.issues[number], **self.comments(number, 0)}
        out: dict[str, Any] = {"data": {"repository": repository}}
        return json.dumps({**out, "errors": errors} if errors else out)

    def comments(self, number: int, start: int) -> dict[str, Any]:
        nodes = self.issues[number]["comments"]
        more = start + self.page < len(nodes)
        info = {"hasNextPage": more, "endCursor": str(start + self.page) if more else None}
        return {"comments": {"pageInfo": info, "nodes": nodes[start : start + self.page]}}

    def reads(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["gh", "api", "graphql"]]


@pytest.fixture(scope="module")
def sp() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shipped", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def config(root: Path, text: str) -> None:
    (root / ".github").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "shipmill.toml").write_text(text, encoding="utf-8")


def test_290_with_app_id_the_notice_posts_through_shipmill_gh(sp: ModuleType, tmp_path: Path) -> None:
    config(tmp_path, '[agents]\nprompt = "x"\napp_id = 7\n')
    write = sp.writer(tmp_path, sp.watch_module())
    assert write == [*APP_GH, str(tmp_path.resolve()), "gh"]
    gh = Forge(issues={5: closed()})
    sp.tell("me/demo", {5: {"abc1234"}}, "v1.2.0", "", write, gh)
    view, comment = gh.calls
    assert view[:3] == ["gh", "api", "graphql"]  # reads stay on plain gh
    assert comment == [*write, "issue", "comment", "5", "-R", "me/demo", "--body", MARK + "Released in v1.2.0."]


def test_290_run_from_a_subfolder_the_notice_still_posts_as_the_app(sp: ModuleType, tmp_path: Path) -> None:
    # --repo-dir defaults to the cwd: a subfolder of the checkout must not read as "no App"
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    config(tmp_path, '[agents]\nprompt = "x"\napp_id = 7\n')
    assert sp.writer(tmp_path / "docs", sp.watch_module()) == [*APP_GH, str(tmp_path.resolve()), "gh"]


@pytest.mark.parametrize("text", [None, 'mode = "release"\n', '[agents]\nprompt = "x"\n'])
def test_290_without_app_id_the_notice_posts_with_plain_gh(sp: ModuleType, tmp_path: Path, text: str | None) -> None:
    if text is not None:
        config(tmp_path, text)
    write = sp.writer(tmp_path, sp.watch_module())
    assert write == ["gh"]
    gh = Forge(issues={5: closed()})
    sp.tell("me/demo", {5: {"abc1234"}}, "v1.2.0", "`uv add x`", write, gh)
    body = MARK + "Released in v1.2.0. `uv add x`"
    assert gh.calls[1] == ["gh", "issue", "comment", "5", "-R", "me/demo", "--body", body]


@pytest.mark.parametrize(
    "text",
    [
        "[agents\napp_id = 7\n",  # TOML's syntax error
        "[release]\napp_id = 7\n",  # an app_id the [agents] reader never sees, as 3.10's fallback can miss it
    ],
)
def test_290_a_malformed_config_fails_rather_than_posting_as_the_person(
    sp: ModuleType, tmp_path: Path, text: str
) -> None:
    config(tmp_path, text)
    with pytest.raises(SystemExit) as exc:
        sp.writer(tmp_path, sp.watch_module())
    assert exc.value.code == 2


def test_290_a_failing_shipmill_gh_stops_and_is_never_retried(sp: ModuleType) -> None:
    calls: list[list[str]] = []
    forge = Forge(issues={5: closed(5), 6: closed(6)})

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[0] == "uvx":
            return str(sp.run(["false"]))  # shipmill gh exits 2: no key, App not installed
        return forge(cmd)

    write = [*APP_GH, "/repo", "gh"]
    with pytest.raises(SystemExit) as exc:
        sp.tell("me/demo", {5: {"a"}, 6: {"b"}}, "v1.2.0", "", write, gh)
    assert exc.value.code == 2
    assert [c[0] for c in calls] == ["gh", "uvx"]  # the first write stops the run


def test_without_post_nothing_is_written(sp: ModuleType) -> None:
    gh = Forge(issues={5: closed()})
    sp.tell("me/demo", {5: {"abc1234"}}, "v1.2.0", "", None, gh)
    assert [c[:3] for c in gh.calls] == [["gh", "api", "graphql"]]


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


def test_368_an_unresolvable_number_is_skipped_and_the_rest_still_told(
    sp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = Forge(issues={500: closed(500)})  # 424 resolves to nothing: null, and GitHub's NOT_FOUND
    sp.tell("me/demo", {424: {"PR #365"}, 500: {"abc1234"}}, "v1.2.0", "", ["gh"], gh)
    out = capsys.readouterr()
    assert out.err == "note: #424 [PR #365] is no issue or pull request of me/demo, skipped\n"
    assert "POSTED" in out.out
    assert gh.calls[-1] == ["gh", "issue", "comment", "500", "-R", "me/demo", "--body", MARK + "Released in v1.2.0."]


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
        (["gh", "issue", "comment", "424"], answer([MISSING_I0]), False),  # a write never skips
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


def test_754_the_closed_issues_are_read_in_one_query_and_tell_as_one_call_each_did(
    sp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    told = "<!-- shipmill:available: stable v1.2.0 -->\nReleased in v1.2.0."
    issues = {
        5: closed(5),
        6: closed(6, told),
        7: {**closed(7), "state": "OPEN"},
        8: {**closed(8), "url": "https://github.com/me/demo/pull/8"},  # a pull request: skipped silently
    }
    gh = Forge(issues=issues)
    sp.tell("me/demo", {5: {"a"}, 6: {"b"}, 7: {"c"}, 8: {"d"}, 9: {"e"}}, "v1.2.0", "", ["gh"], gh)
    out = capsys.readouterr()
    assert out.out.splitlines() == [
        "#5     POSTED            a fix  [a]",
        "#6     SKIP notified     a fix",
        "#7     SKIP open         a fix  [c]",
    ]
    assert out.err == "note: #9 [e] is no issue or pull request of me/demo, skipped\n"
    assert len(gh.reads()) == 1
    assert [c[3] for c in gh.calls if c[1:3] == ["issue", "comment"]] == ["5"]


def test_754_more_issues_than_a_query_takes_are_read_in_batches(sp: ModuleType) -> None:
    numbers = list(range(1, 2 * sp.ISSUES_PER_QUERY + 2))
    gh = Forge(issues={n: closed(n) for n in numbers})
    found = sp.views("me/demo", numbers, gh)
    assert sorted(found) == numbers and all(v is not None and v["state"] == "CLOSED" for v in found.values())
    assert len(gh.calls) == 3


def test_754_an_issue_with_more_comments_than_a_page_is_read_to_its_last(sp: ModuleType) -> None:
    # the notice is the 250th comment: gh issue view read every comment, so the batch does too
    notice = "<!-- shipmill:available: stable v1.2.0 -->\nReleased in v1.2.0."
    gh = Forge(issues={5: closed(5, *(["Thanks!"] * 249), notice)})
    assert posted_with(sp, gh, "v1.2.0") == []
    assert len(gh.calls) == 3  # the batch, then two more pages of #5's comments
    assert variables(gh.calls[2])["after"] == "200"


def test_754_an_empty_range_makes_no_call(sp: ModuleType) -> None:
    gh = Forge()
    assert sp.collect("me/demo", [], gh) == {}
    sp.tell("me/demo", {}, "v1.2.0", "", ["gh"], gh)
    assert gh.calls == []


def test_754_each_query_stays_well_under_github_s_node_limit(sp: ModuleType) -> None:
    per_commit = sp.PRS_READ + sp.PRS_READ * sp.CLOSERS_READ
    assert sp.COMMITS_PER_QUERY * per_commit <= sp.NODE_LIMIT // 5
    assert sp.ISSUES_PER_QUERY * sp.COMMENTS_READ <= sp.NODE_LIMIT // 5
    assert f"associatedPullRequests(first: {sp.PRS_READ})" in sp.PULL_FIELDS
    assert f"closingIssuesReferences(first: {sp.CLOSERS_READ})" in sp.PULL_FIELDS
    assert f"comments(first: {sp.COMMENTS_READ})" in sp.ISSUE_FIELDS


def test_754_a_commit_github_does_not_have_stops_the_run(sp: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    def gh(cmd: list[str]) -> str:
        return json.dumps({"data": {"repository": {"c0": {"associatedPullRequests": {"nodes": []}}, "c1": None}}})

    with pytest.raises(SystemExit) as exc:
        sp.prs_of("me/demo", ["a" * 40, "b" * 40], gh)
    assert exc.value.code == 2
    assert capsys.readouterr().err == f"error: me/demo has no commit {'b' * 40}\n"


# -- spec 021: a notice per stage


def posted_with(sp: ModuleType, gh: Forge, tag: str, command: str = "") -> list[str]:
    """The bodies tell posts on issue #5 as gh answers"""
    sp.tell("me/demo", {5: {"abc1234"}}, tag, command, ["gh"], gh)
    return [c[-1] for c in gh.calls if c[1:3] == ["issue", "comment"]]


def posted(sp: ModuleType, tag: str, command: str, *comments: str) -> list[str]:
    """The bodies tell posts on issue #5, whose comments are these"""
    return posted_with(sp, Forge(issues={5: closed(5, *comments)}), tag, command)


@pytest.mark.parametrize("tag", ["v1.0.0rc1", "v1.1.0.dev3", "v1.0.0rc2.dev1", "v2.0.0b1"])
def test_s021_1_a_pre_release_notice_names_its_stage_and_carries_the_pin(sp: ModuleType, tag: str) -> None:
    notices = sp.Notices(pin="uv add '{name}=={version}'", install="uv add {name}", name="demo")
    command = sp.command_for(tag, notices, "--install text")
    assert command == f"`uv add 'demo=={tag[1:]}'`"
    (body,) = posted(sp, tag, command)
    assert body.splitlines() == [
        f"<!-- shipmill:available: pre-release {tag} -->",
        f"Released in {tag} (pre-release). `uv add 'demo=={tag[1:]}'`",
        "A plain install gets it with the next stable release.",
        "If you filed this: react 👍 on this comment once it works for you, or reply if it doesn't.",
    ]


def test_s021_1_a_stable_notice_carries_the_install_command(sp: ModuleType) -> None:
    notices = sp.Notices(pin="uv add 'demo=={version}'", install="uv add {name}  # {tag}", name="demo")
    (body,) = posted(sp, "v1.0.0", sp.command_for("v1.0.0", notices, ""))
    assert body == "<!-- shipmill:available: stable v1.0.0 -->\nReleased in v1.0.0. `uv add demo  # v1.0.0`"


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


def test_s021_2_a_stable_promotion_tells_every_fix_its_rc_held(sp: ModuleType, tmp_path: Path) -> None:
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
    # #5 was told of rc1 in the form before spec 021; the stable notice still posts
    (body,) = posted(sp, "v1.0.0", "", "Released in v1.0.0rc1. `uv add 'demo==1.0.0rc1'`")
    assert body == "<!-- shipmill:available: stable v1.0.0 -->\nReleased in v1.0.0."
    # a pre-release reads only its own range, as before
    assert sp.release_commits(str(repo), "v1.0.0rc1", "v1.0.0rc2") == sp.commits(str(repo), "v1.0.0rc1", "v1.0.0rc2")


def test_s021_2_a_first_stable_reads_its_whole_history(sp: ModuleType, tmp_path: Path) -> None:
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


def test_s021_2_a_first_stable_tells_the_fixes_its_oldest_rc_held(sp: ModuleType, tmp_path: Path) -> None:
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


def test_s021_3_a_second_run_posts_nothing(sp: ModuleType) -> None:
    for tag in ("v1.0.0rc1", "v1.0.0"):
        (first,) = posted(sp, tag, "`uv add demo`")
        assert posted(sp, tag, "`uv add demo`", "Thanks!", first) == []


@pytest.mark.parametrize(
    ("tag", "comments", "told"),
    [
        ("v1.0.0", ["Released in v1.0.0."], True),  # the form before spec 021
        ("v1.0.0", ["Released in v1.0.0. `uv add demo`"], True),
        ("v1.0.0", ["Released in v1.0.0rc1."], False),  # a pre-release told is not the stable stage
        ("v1.0.0", ["<!-- shipmill:available: stable v0.9.0 -->\nReleased in v0.9.0."], False),
        ("v1.0.0rc2", ["Released in v1.0.0rc1."], True),  # once per stage
        (
            "v1.0.0rc2",
            ["<!-- shipmill:available: pre-release v1.0.0rc1 -->\nReleased in v1.0.0rc1 (pre-release)."],
            True,
        ),
        ("v1.1.0.dev2", ["Released in v1.1.0.dev1."], True),
        ("v1.1.0rc1", ["Released in v1.0.0rc1.", "Released in v1.0.0."], False),  # fixed again after a stable
        ("v1.0.0rc1", ["Not Released in v1.0.0rc1.", "released in v1.0.0rc1."], False),
    ],
)
def test_s021_3_an_existing_notice_counts_as_told_for_its_tag_and_stage(
    sp: ModuleType, tag: str, comments: list[str], told: bool
) -> None:
    assert sp.told([{"body": c} for c in comments], tag) is told
    assert (posted(sp, tag, "", *comments) == []) is told


def deployed(sp: ModuleType, environment: str, tag: str, *comments: str) -> list[str]:
    """The bodies tell posts on issue #5, whose comments are these, for tag's deployment"""
    gh = Forge(issues={5: closed(5, *comments)})
    sp.tell("me/demo", {5: {"abc1234"}}, tag, "`uv add demo`", ["gh"], gh, environment=environment)
    return [c[-1] for c in gh.calls if c[1:3] == ["issue", "comment"]]


@pytest.mark.parametrize(
    ("comments", "posts"),
    [
        ([], True),
        (["<!-- shipmill:available: stable v1.2.0 -->\nReleased in v1.2.0.", "Released in v1.2.0."], True),
        (["<!-- shipmill:available: production v1.2.0 -->\nDeployed to production in v1.2.0."], True),
        (["<!-- shipmill:available: staging v1.1.0 -->\nDeployed to staging in v1.1.0."], False),  # once per stage
        (["<!-- shipmill:available: staging v1.2.0 -->\nDeployed to staging in v1.2.0."], False),
        (["Deployed to staging in v1.2.0."], True),  # a person's words without the marker are no notice
    ],
)
def test_s021_4_a_deployment_posts_deployed_to_once_per_environment(
    sp: ModuleType, comments: list[str], posts: bool
) -> None:
    found = deployed(sp, "staging", "v1.2.0", *comments)
    if not posts:
        assert found == []
        return
    # no command: the deployment, not the person, puts it there
    assert found == ["<!-- shipmill:available: staging v1.2.0 -->\nDeployed to staging in v1.2.0."]


def test_s021_4_a_deployment_notice_leaves_the_release_stages_as_they_were(sp: ModuleType) -> None:
    staging = {"body": sp.deployed_notice("staging", "v1.0.0")}
    rc = {"body": "<!-- shipmill:available: pre-release v1.0.0rc1 -->\nReleased in v1.0.0rc1 (pre-release)."}
    stable = {"body": "<!-- shipmill:available: stable v1.0.0 -->\nReleased in v1.0.0."}
    assert sp.told([staging], "v1.0.0") is False
    assert sp.told([staging], "v1.0.0rc1") is False
    assert sp.told([rc, staging], "v1.0.0rc2") is True
    assert sp.told([rc, stable, staging], "v1.1.0rc1") is False
    assert sp.told([stable, staging], "v1.0.0") is True


@pytest.mark.parametrize("name", ["stable", "pre-release", "", "-x", "a b", "prod/eu"])
def test_s021_4_environment_must_be_an_environment_s_name(sp: ModuleType, name: str) -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "me/demo", "v1.0.0", "v1.1.0", "--environment", name],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "environment" in done.stderr


@pytest.mark.parametrize(
    ("pin", "install", "given", "pre", "stable"),
    [
        (None, None, "`uv add x`", "`uv add x`", "`uv add x`"),  # no [notices]: --install, as today
        (None, None, "", "", ""),
        ("uv add 'demo=={version}'", None, "`uv add x`", "`uv add 'demo==1.0.0rc1'`", "`uv add x`"),
        (None, "uv add demo", "`uv add x`", "", "`uv add demo`"),  # never the stable command on a pre-release
        ("echo `{tag}`", "pip install {name}=={version}", "", "`` echo `v1.0.0rc1` ``", "`pip install demo==1.0.0`"),
    ],
)
def test_s021_5_the_commands_come_from_notices_else_install(
    sp: ModuleType, pin: str | None, install: str | None, given: str, pre: str, stable: str
) -> None:
    notices = sp.Notices(pin=pin, install=install, name="demo")
    assert sp.command_for("v1.0.0rc1", notices, given) == pre
    assert sp.command_for("v1.0.0", notices, given) == stable


NOTICES = "name = \"demo\"\n\n[notices]\npin = \"uv add 'demo=={version}'\"  # the rc\ninstall = 'uv add {name}'\n"


def test_s021_5_notices_read_alike_on_3_11_and_3_10(sp: ModuleType, tmp_path: Path) -> None:
    ws = sp.watch_module()
    config(tmp_path, NOTICES)
    (tmp_path / ".git").mkdir()
    (tmp_path / "missing" / ".git").mkdir(parents=True)  # a checkout with no config
    expected = sp.Notices(pin="uv add 'demo=={version}'", install="uv add {name}", name="demo")
    assert sp.notices_config(tmp_path, ws) == expected
    path = tmp_path / ".github" / "shipmill.toml"
    assert sp.notices_310(NOTICES, path, ws) == ({"pin": expected.pin, "install": expected.install}, "demo")
    assert sp.notices_310('name = "demo"\n', path, ws) == (None, "demo")
    assert sp.notices_config(tmp_path / "missing", ws) == sp.Notices()


@pytest.mark.parametrize(
    "text",
    [
        "[notices]\nupgrade = 'uv add -U demo'\n",  # an unknown key
        "[notices]\npin = 1\n",
        "[notices]\ninstall = ''\n",
        "[notices]\npin = 'uv add demo=={semver}'\n",  # an unknown placeholder
        "[notices]\ninstall = 'uv add {name}'\n",  # {name} with no name
        "notices = 1\n",
        "[notices\npin = 'x'\n",  # TOML's syntax error
    ],
)
def test_s021_5_a_notices_section_the_policy_refuses_exits_2(sp: ModuleType, tmp_path: Path, text: str) -> None:
    config(tmp_path, text)
    with pytest.raises(SystemExit) as exc:
        sp.notices_config(tmp_path, sp.watch_module())
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "text",
    [
        'name = "demo"\nnotices.pin = "x"\n',  # a dotted key
        'name = "demo"\nnotices = { pin = "x" }\n',  # an inline table
        '[notices]\npin = "a \\"quoted\\" x"\n',  # an escape the fallback can't decode
        '[notices.extra]\npin = "x"\n',
        '[notices\npin = "x"\n',
        '[notices]\npin = "x"\npin = "y"\n',  # invalid TOML, which tomllib refuses too
        '[notices]\npin = "x"\n[notices]\ninstall = "y"\n',
    ],
)
def test_s021_5_a_notices_form_3_10_cannot_read_is_refused(sp: ModuleType, tmp_path: Path, text: str) -> None:
    with pytest.raises(SystemExit) as exc:
        sp.notices_310(text, tmp_path / "shipmill.toml", sp.watch_module())
    assert exc.value.code == 2
