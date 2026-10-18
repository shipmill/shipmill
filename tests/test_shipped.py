"""github-pr-triage's shipped.py: who its notices post as (#290, spec 012), without gh"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-pr-triage" / "scripts" / "shipped.py"
APP_GH = ["uvx", "--from", "git+https://github.com/shipmill/shipmill@v0", "shipmill", "--repo"]
CLOSED = json.dumps({"state": "CLOSED", "title": "a fix", "comments": [], "url": "https://github.com/me/demo/issues/5"})
MARK = "<!-- shipmill:available: stable v1.2.0 -->\n"  # every notice's first line (spec 021)


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


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.calls.append(cmd)
        return CLOSED if cmd[:3] == ["gh", "issue", "view"] else ""


def test_290_with_app_id_the_notice_posts_through_shipmill_gh(sp: ModuleType, tmp_path: Path) -> None:
    config(tmp_path, '[agents]\nprompt = "x"\napp_id = 7\n')
    write = sp.writer(tmp_path, sp.watch_module())
    assert write == [*APP_GH, str(tmp_path.resolve()), "gh"]
    gh = FakeGh()
    sp.tell("me/demo", {5: {"abc1234"}}, "v1.2.0", "", write, gh)
    view, comment = gh.calls
    assert view[:3] == ["gh", "issue", "view"]  # reads stay on plain gh
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
    gh = FakeGh()
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

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[0] == "uvx":
            return str(sp.run(["false"]))  # shipmill gh exits 2: no key, App not installed
        return CLOSED

    write = [*APP_GH, "/repo", "gh"]
    with pytest.raises(SystemExit) as exc:
        sp.tell("me/demo", {5: {"a"}, 6: {"b"}}, "v1.2.0", "", write, gh)
    assert exc.value.code == 2
    assert [c[0] for c in calls] == ["gh", "uvx"]  # the first write stops the run


def test_without_post_nothing_is_written(sp: ModuleType) -> None:
    gh = FakeGh()
    sp.tell("me/demo", {5: {"abc1234"}}, "v1.2.0", "", None, gh)
    assert [c[:3] for c in gh.calls] == [["gh", "issue", "view"]]


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
    calls: list[list[str]] = []
    prs = [pr('quotes ("Closes #424.")\nFixes #5'), {**pr("Fixes #8", merged=False), "number": 10}]

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        commit = {"associatedPullRequests": {"nodes": prs}}
        return json.dumps({"data": {"repository": {"object": commit}}})

    pairs = [("a" * 40, "a change\n\nFixes #3\nsee Fixes #4 mid-line"), ("b" * 40, "a second")]
    assert sp.collect("me/demo", pairs, gh) == {3: {"aaaaaaa"}, 5: {"PR #9"}}
    assert [c[:3] for c in calls] == [["gh", "api", "graphql"]] * 2
    assert f"oid={'b' * 40}" in calls[1]


def test_368_an_unresolvable_number_is_skipped_and_the_rest_still_told(
    sp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:4] == ["gh", "issue", "view", "424"]:
            raise sp.NotFound(424)
        return CLOSED if cmd[:3] == ["gh", "issue", "view"] else ""

    write = ["gh"]
    sp.tell("me/demo", {424: {"PR #365"}, 500: {"abc1234"}}, "v1.2.0", "", write, gh)
    out = capsys.readouterr()
    assert "#424" in out.err and "skipped" in out.err
    assert "POSTED" in out.out
    assert calls[-1] == ["gh", "issue", "comment", "500", "-R", "me/demo", "--body", MARK + "Released in v1.2.0."]


NOT_FOUND_ERR = "GraphQL: Could not resolve to an issue or pull request with the number of 424. (repository.issue)"


@pytest.mark.parametrize(
    ("cmd", "stderr", "expected"),
    [
        (["gh", "issue", "view", "424", "-R", "me/demo"], NOT_FOUND_ERR, True),
        (["gh", "issue", "view", "42", "-R", "me/demo"], NOT_FOUND_ERR, False),  # another number's answer
        (["gh", "issue", "view", "424", "-R", "me/demo"], "HTTP 401: Bad credentials", False),
        (["gh", "issue", "view", "424", "-R", "me/demo"], "error connecting to api.github.com", False),
        (["gh", "issue", "comment", "424", "-R", "me/demo"], NOT_FOUND_ERR, False),  # a write never skips
    ],
)
def test_368_only_gh_s_not_found_for_that_issue_view_is_a_skip(
    sp: ModuleType, cmd: list[str], stderr: str, expected: bool
) -> None:
    assert sp.missing(cmd, stderr) is expected


def test_368_a_numeric_repo_name_reaches_graphql_as_a_string(sp: ModuleType) -> None:
    # gh's -F turns "2048" into a number, and GraphQL refuses it for String!; -f keeps it a string
    calls: list[list[str]] = []

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        return json.dumps({"data": {"repository": {"object": {"associatedPullRequests": {"nodes": []}}}}})

    sp.prs_for("1984/2048", "1" * 40, gh)
    flags = {calls[0][i + 1].partition("=")[0]: calls[0][i] for i, a in enumerate(calls[0]) if a in ("-f", "-F")}
    assert flags == {"query": "-f", "owner": "-f", "name": "-f", "oid": "-f"}


# -- spec 021: a notice per stage


def viewed(*comments: str) -> str:
    """gh issue view's JSON of a closed issue with these comments, oldest first"""
    url = "https://github.com/me/demo/issues/5"
    return json.dumps({"state": "CLOSED", "title": "a fix", "comments": [{"body": c} for c in comments], "url": url})


def posted(sp: ModuleType, tag: str, command: str, *comments: str) -> list[str]:
    """The bodies tell posts on issue #5, whose comments are these"""
    calls: list[list[str]] = []

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        return viewed(*comments) if cmd[:3] == ["gh", "issue", "view"] else ""

    sp.tell("me/demo", {5: {"abc1234"}}, tag, command, ["gh"], gh)
    return [c[-1] for c in calls if c[1:3] == ["issue", "comment"]]


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

    def no_prs(cmd: list[str]) -> str:
        return json.dumps({"data": {"repository": {"object": {"associatedPullRequests": {"nodes": []}}}}})

    pairs = sp.release_commits(str(repo), "v1.0.0rc2", "v1.0.0")
    assert sp.collect("me/demo", pairs, no_prs) == {5: {rc1_base[:7]}}  # not #6: rc2's fix isn't held
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

    def no_prs(cmd: list[str]) -> str:
        return json.dumps({"data": {"repository": {"object": {"associatedPullRequests": {"nodes": []}}}}})

    for prev in ("v1.0.0rc1", "v1.0.0rc2"):
        assert sp.collect("me/demo", sp.release_commits(str(repo), prev, "v1.0.0"), no_prs) == {5: {rc1_base[:7]}}


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
    calls: list[list[str]] = []

    def gh(cmd: list[str]) -> str:
        calls.append(cmd)
        return viewed(*comments) if cmd[:3] == ["gh", "issue", "view"] else ""

    sp.tell("me/demo", {5: {"abc1234"}}, tag, "`uv add demo`", ["gh"], gh, environment=environment)
    return [c[-1] for c in calls if c[1:3] == ["issue", "comment"]]


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
