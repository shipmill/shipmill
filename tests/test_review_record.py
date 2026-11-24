"""Spec 055: `shipmill review record` posts, as the App, the review record pr_gate.py reads, and the
skills record the reviewed head with it. GitHub is a recording fake or `shipmill gh`'s own path with
the App faked (MintApi, FakeSigner), and nothing reaches the network"""

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.agent_marker import MARKER
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.review_record import Findings, Head, Request, Verdict, record

from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_gh_refuses_without_app import AGENTS_NO_APP, HOST_IDENTITY

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
HEAD = "abcdef0123456789abcdef0123456789abcdef01"
OTHER = "0123456789abcdef0123456789abcdef01234567"
PULL = 41


@dataclass
class FakeHub:
    """A pull request whose head is current; every read and write recorded"""

    current: str = HEAD
    reads: list[int] = field(default_factory=list)
    posts: list[tuple[int, str, str]] = field(default_factory=list)

    def head(self, number: int) -> str:
        self.reads.append(number)
        return self.current

    def post(self, number: int, head: Head, body: str) -> None:
        self.posts.append((number, str(head), body))


def report(tmp_path: Path, text: str = "Verdict: MERGE\n\nNo findings.\n") -> Path:
    path = tmp_path / "report.md"
    path.write_text(text, encoding="utf-8")
    return path


def available() -> None:
    """The App is available"""


def missing() -> None:
    raise ReleaseError("no App private key at /k.pem")


def clean(report: str) -> None:
    """The report holds nothing the leak check refuses"""


# --- S-055-16: the record, and every refusal before a write ----------------------------------------


@pytest.mark.parametrize("verdict", list(Verdict))
def test_s055_16_the_record_is_the_verdicts_marker_then_the_report_at_the_head(
    tmp_path: Path, verdict: Verdict
) -> None:
    hub = FakeHub()
    said = record(Request(PULL, HEAD.upper(), verdict, report(tmp_path)), hub, available, clean)
    assert hub.posts == [(PULL, HEAD, f"<!-- shipmill:review {verdict} -->\n\nVerdict: MERGE\n\nNo findings.")]
    assert said == f"recorded {verdict} for #{PULL} at {HEAD}"


@pytest.mark.parametrize("head", ["abcdef0", HEAD[:39], HEAD + "0", "g" * 40, f" {HEAD}", ""])
def test_s055_16_a_head_that_isnt_40_hex_characters_exits_2_before_any_read(tmp_path: Path, head: str) -> None:
    hub = FakeHub()
    with pytest.raises(ReleaseError, match="40 hex characters"):
        record(Request(PULL, head, Verdict.MERGE, report(tmp_path)), hub, available, clean)
    assert (hub.reads, hub.posts) == ([], [])


def test_s055_16_a_head_that_isnt_the_prs_current_one_writes_nothing(tmp_path: Path) -> None:
    hub = FakeHub(current=OTHER)
    with pytest.raises(ReleaseError, match=f"--head {HEAD} is not #{PULL}'s current head, {OTHER}"):
        record(Request(PULL, HEAD, Verdict.MERGE, report(tmp_path)), hub, available, clean)
    assert (hub.reads, hub.posts) == ([PULL], [])


def test_s055_16_without_the_app_nothing_is_read_or_written(tmp_path: Path) -> None:
    hub = FakeHub()
    with pytest.raises(ReleaseError, match="no App private key"):
        record(Request(PULL, HEAD, Verdict.MERGE, report(tmp_path)), hub, missing, clean)
    assert (hub.reads, hub.posts) == ([], [])


def test_s055_16_a_report_that_cant_be_read_writes_nothing(tmp_path: Path) -> None:
    hub = FakeHub()
    with pytest.raises(ReleaseError, match="--body-file .* can't be read"):
        record(Request(PULL, HEAD, Verdict.MERGE, tmp_path / "none.md"), hub, available, clean)
    assert (hub.reads, hub.posts) == ([], [])


# --- S-055-16 through the CLI: `shipmill gh`'s path, as the App -------------------------------------


@dataclass
class FakeGh:
    """gh as `shipmill gh` runs it, its output captured: pull request #41 at head; every argv
    and env recorded"""

    head: str = HEAD
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.calls.append((args, dict(env)))
        if "POST" in args:
            return 0, '{"id": 1, "state": "COMMENTED"}'
        return 0, json.dumps({"number": PULL, "head": {"sha": self.head}})


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    executable(fakes / "gh", FAKE_GH)
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return Host(fakes, record_dir, home)


def cli(root: Path, host: Host, gh: FakeGh, api: MintApi, *extra: str, **env: str) -> int:
    args = ["--repo", str(root), "review", "record", str(PULL), "--head", HEAD, "--verdict", "merge"]
    return main(
        [*args, "--body-file", str(report(root)), *extra],
        api=api,
        signer=FakeSigner(),
        environ=host.env(**env),
        home=host.home,
        gh_capture=gh,
    )


def field_of(args: list[str], name: str) -> str:
    return next(
        args[i + 1][len(name) + 1 :] for i, a in enumerate(args) if a == "-f" and args[i + 1].startswith(f"{name}=")
    )


def test_s055_16_the_cli_posts_a_comment_review_at_the_head_as_the_app(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh, api = FakeGh(), MintApi(expires_from=dt.datetime.now(dt.UTC))
    assert cli(root, host, gh, api, SHIPMILL_APP_KEY=str(key_file(tmp_path))) == 0
    assert capsys.readouterr().out == f"recorded merge for #{PULL} at {HEAD}\n"
    (read, _), (post, _) = gh.calls
    assert read == ["api", f"repos/{REPO}/pulls/{PULL}"]
    assert post[:4] == ["api", "-X", "POST", f"repos/{REPO}/pulls/{PULL}/reviews"]
    assert (field_of(post, "event"), field_of(post, "commit_id")) == ("COMMENT", HEAD)
    body = field_of(post, "body")
    assert body.splitlines()[0] == "<!-- shipmill:review merge -->"
    assert body.endswith(f"\n\n{MARKER}")  # D-62: shipmill gh marks the body it writes
    assert all(env["GH_TOKEN"].startswith("token-") for _, env in gh.calls)  # the App's, never the host's


def test_s055_16_the_cli_refuses_a_moved_head_after_one_read(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh, api = FakeGh(head=OTHER), MintApi(expires_from=dt.datetime.now(dt.UTC))
    with pytest.raises(ReleaseError, match="is not #41's current head"):
        cli(root, host, gh, api, SHIPMILL_APP_KEY=str(key_file(tmp_path)))
    assert [args[:2] for args, _ in gh.calls] == [["api", f"repos/{REPO}/pulls/{PULL}"]]


def test_s055_16_without_the_apps_key_it_exits_2_before_any_gh_call(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh, api = FakeGh(), MintApi()
    with pytest.raises(ReleaseError, match="no App private key at"):
        cli(root, host, gh, api)
    assert (gh.calls, api.posts) == ([], [])


@pytest.mark.parametrize("config", [AGENTS_NO_APP, HOST_IDENTITY, None])
def test_s055_16_without_app_id_it_exits_2_even_with_identity_host(
    tmp_path: Path, host: Host, config: str | None
) -> None:
    root = checkout(tmp_path, config)
    gh, api = FakeGh(), MintApi()
    with pytest.raises(ReleaseError, match=r"review record posts as the App, and .* sets no \[agents\] app_id"):
        cli(root, host, gh, api, GH_TOKEN="")
    assert (gh.calls, api.posts) == ([], [])


def test_s055_16_a_verdict_other_than_merge_or_refuse_is_refused_by_the_parser(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh = FakeGh()
    with pytest.raises(SystemExit) as raised:
        main(
            ["--repo", str(root), "review", "record", "41", "--head", HEAD, "--verdict", "approve", "--body-file", "x"],
            environ=host.env(),
            home=host.home,
            gh_capture=gh,
        )
    assert raised.value.code == 2 and gh.calls == []


# --- S-075-4, S-075-5, S-075-6: the second look's finding counts ------------------------------------

REFUSE_LINE = "<!-- shipmill:findings confirmed=2 rejected=1 minor=0 -->"


@pytest.mark.parametrize(
    "findings", ["confirmed=2,rejected=1,minor=0", "minor=0,confirmed=2,rejected=1", "rejected=1,minor=0,confirmed=2"]
)
def test_s075_4_a_refusal_carries_the_findings_line_after_its_marker_keys_in_one_order(
    tmp_path: Path, findings: str
) -> None:
    hub = FakeHub()
    record(Request(PULL, HEAD, Verdict.REFUSE, report(tmp_path), findings), hub, available, clean)
    (_, _, body), *rest = hub.posts
    assert rest == []
    assert body == f"<!-- shipmill:review refuse -->\n{REFUSE_LINE}\n\nVerdict: MERGE\n\nNo findings."


def test_s075_4_without_a_report_the_body_ends_at_the_findings_line(tmp_path: Path) -> None:
    hub = FakeHub()
    record(
        Request(PULL, HEAD, Verdict.REFUSE, report(tmp_path, "\n"), "confirmed=2,rejected=1,minor=0"),
        hub,
        available,
        clean,
    )
    assert hub.posts == [(PULL, HEAD, f"<!-- shipmill:review refuse -->\n{REFUSE_LINE}")]


def test_s075_4_the_cli_posts_the_findings_line_after_the_refuse_marker(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh, api = FakeGh(), MintApi(expires_from=dt.datetime.now(dt.UTC))
    args = ["--repo", str(root), "review", "record", str(PULL), "--head", HEAD, "--verdict", "refuse"]
    findings = ["--findings", "rejected=1,confirmed=2,minor=0", "--body-file", str(report(root))]
    code = main(
        [*args, *findings],
        api=api,
        signer=FakeSigner(),
        environ=host.env(SHIPMILL_APP_KEY=str(key_file(tmp_path))),
        home=host.home,
        gh_capture=gh,
    )
    assert code == 0
    (_, _), (post, _) = gh.calls
    assert field_of(post, "body").splitlines()[:4] == [
        "<!-- shipmill:review refuse -->",
        REFUSE_LINE,
        "",
        "Verdict: MERGE",
    ]


@pytest.mark.parametrize(
    ("findings", "says"),
    [
        ("confirmed=2,rejected=1", "lacks minor"),
        ("confirmed=2", "lacks rejected, minor"),
        ("", "'' in '' is not key=N"),
        ("confirmed=2,rejected=1,minor=0,confirmed=1", "confirmed is given twice"),
        ("confirmed=2,rejected=1,minor=0,major=1", "'major' .* is not one of confirmed, rejected, minor"),
        ("confirmed=2,rejected=1,Minor=0", "'Minor' .* is not one of"),
        ("confirmed=2,rejected=-1,minor=0", "rejected='-1' .* is not a whole number of 0 or more"),
        ("confirmed=2,rejected=one,minor=0", "rejected='one' .* is not a whole number"),
        ("confirmed=2,rejected=1.5,minor=0", "rejected='1.5' .* is not a whole number"),
        ("confirmed=2,rejected=,minor=0", "rejected='' .* is not a whole number"),
        ("confirmed=2,rejected=1,minor= 0", "minor=' 0' .* is not a whole number"),
        ("confirmed=2 rejected=1 minor=0", "confirmed='2 rejected=1 minor=0' .* is not a whole number"),
        ("confirmed=2,rejected=1,minor=0,", "'' in .* is not key=N"),
        ("confirmed:2,rejected=1,minor=0", "'confirmed:2' in .* is not key=N"),
    ],
)
def test_s075_5_a_malformed_findings_value_exits_2_naming_the_form_before_any_read(
    tmp_path: Path, findings: str, says: str
) -> None:
    hub = FakeHub()
    with pytest.raises(ReleaseError, match="--findings is confirmed=N,rejected=N,minor=N, each key once") as raised:
        record(Request(PULL, HEAD, Verdict.REFUSE, report(tmp_path), findings), hub, available, clean)
    assert re.search(says, str(raised.value)), str(raised.value)
    assert (hub.reads, hub.posts) == ([], [])


def test_s075_5_a_negative_count_is_refused_when_built_directly() -> None:
    with pytest.raises(ReleaseError, match="minor is -1"):
        Findings(1, 0, -1)


@pytest.mark.parametrize(
    ("verdict", "findings", "says"),
    [
        (Verdict.REFUSE, "confirmed=0,rejected=2,minor=1", "confirmed no finding, so record --verdict merge"),
        (Verdict.MERGE, "confirmed=1,rejected=0,minor=0", "a confirmed finding refuses, so record --verdict refuse"),
    ],
)
def test_s075_5_a_verdict_the_counts_contradict_exits_2_before_any_read(
    tmp_path: Path, verdict: Verdict, findings: str, says: str
) -> None:
    hub = FakeHub()
    with pytest.raises(ReleaseError, match=says):
        record(Request(PULL, HEAD, verdict, report(tmp_path), findings), hub, available, clean)
    assert (hub.reads, hub.posts) == ([], [])


def test_s075_5_the_cli_exits_2_on_bad_findings_before_any_gh_call(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh, api = FakeGh(), MintApi(expires_from=dt.datetime.now(dt.UTC))
    with pytest.raises(ReleaseError, match="a confirmed finding refuses"):
        cli(
            root,
            host,
            gh,
            api,
            "--findings",
            "confirmed=1,rejected=0,minor=0",
            SHIPMILL_APP_KEY=str(key_file(tmp_path)),
        )
    assert (gh.calls, api.posts) == ([], [])


@pytest.mark.parametrize("verdict", list(Verdict))
def test_s075_6_without_findings_the_body_is_as_before(tmp_path: Path, verdict: Verdict) -> None:
    hub = FakeHub()
    record(Request(PULL, HEAD, verdict, report(tmp_path)), hub, available, clean)
    assert hub.posts == [(PULL, HEAD, f"<!-- shipmill:review {verdict} -->\n\nVerdict: MERGE\n\nNo findings.")]
    empty = FakeHub()
    record(Request(PULL, HEAD, verdict, report(tmp_path, "")), empty, available, clean)
    assert empty.posts == [(PULL, HEAD, f"<!-- shipmill:review {verdict} -->")]


def test_s075_6_an_overturned_refusal_records_merge_with_its_findings_line(tmp_path: Path) -> None:
    hub = FakeHub()
    record(
        Request(PULL, HEAD, Verdict.MERGE, report(tmp_path), "confirmed=0,rejected=2,minor=1"), hub, available, clean
    )
    assert hub.posts == [
        (
            PULL,
            HEAD,
            "<!-- shipmill:review merge -->\n<!-- shipmill:findings confirmed=0 rejected=2 minor=1 -->"
            "\n\nVerdict: MERGE\n\nNo findings.",
        )
    ]


def test_s075_6_a_parsed_findings_value_is_taken_as_it_is(tmp_path: Path) -> None:
    hub = FakeHub()
    record(Request(PULL, HEAD, Verdict.MERGE, report(tmp_path), Findings(0, 2, 1)), hub, available, clean)
    assert hub.posts[0][2].splitlines()[1] == "<!-- shipmill:findings confirmed=0 rejected=2 minor=1 -->"


# --- S-055-18: the skills read the answer and record the reviewed head ------------------------------


def folded(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_s055_18_the_landing_skills_name_no_maintainer_accepted() -> None:
    for path in (
        SKILLS / "github-pr-triage" / "SKILL.md",
        SKILLS / "github-pr-triage" / "references" / "landing.md",
        SKILLS / "github-issue-triage" / "references" / "needs-decision.md",
    ):
        assert "--maintainer-accepted" not in path.read_text(encoding="utf-8"), path


def test_s055_18_the_reviewer_reports_its_head_and_landing_records_it() -> None:
    brief = folded(SKILLS / "github-pr-triage" / "references" / "reviewer-brief.md")
    assert "the HEAD SHA of review-{N}, the head you reviewed" in brief
    assert "shipmill review record" in brief
    landing = folded(SKILLS / "github-pr-triage" / "references" / "landing.md")
    assert "review record <n> --head <reviewed head> --verdict merge|refuse --body-file" in landing
    assert "UNREVIEWED" in landing and "exit 9" in landing
    skill = folded(SKILLS / "github-pr-triage" / "SKILL.md")
    assert "Exit 9 (UNREVIEWED)" in skill and "the pinned CLI's `review record`" in skill
    assert "Record the reviewed head." in skill and "(references/landing.md#recording-the-review)" in skill


def section(path: Path, heading: str) -> str:
    """The folded text under a heading line, up to the next heading of its level or above, fences skipped"""
    level = len(heading) - len(heading.lstrip("#"))
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading)
    fenced = False
    end = len(lines)
    for at in range(start + 1, len(lines)):
        line = lines[at]
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(rf"#{{1,{level}}} ", line):
            end = at
            break
    return " ".join(" ".join(lines[start:end]).split())


BRIEF = SKILLS / "github-pr-triage" / "references" / "reviewer-brief.md"


def test_s075_1_the_open_pr_report_lists_each_unfixed_finding_with_an_id() -> None:
    open_pr = section(BRIEF, "## Open PR")
    assert "each finding you did not fix as `F-1`, `F-2`, and so on" in open_pr
    assert "its file and line, the claim in one sentence, and `blocking` when the verdict stands on it or `nit`" in (
        open_pr
    )
    assert "A REFUSE names at least one blocking finding" in open_pr
    assert "a report whose REFUSE names none is sent back to you" in open_pr


def test_s075_2_the_verify_a_refusal_brief_marks_each_finding_by_the_code() -> None:
    verify = section(BRIEF, "## Verify a refusal")
    assert 'a fresh agent (`subagent_type: general-purpose`, `isolation: "worktree"`)' in verify
    assert "never the first reviewer and never the landing session itself" in verify
    assert "the PR, the reviewed head, and each blocking finding's id, file and line, and claim" in verify
    assert "never the first reviewer's verdict or the rest of its report" in verify
    assert "{reviewed_head}" in verify and "{findings:" in verify
    assert "Do NOT push, comment on GitHub, merge, or fix anything." in verify
    assert "`confirmed`, with the failure scenario" in verify
    assert "`rejected`, with the file and line of the code that already handles it" in verify
    assert "`minor`, with one line saying why it is real and doesn't block: a note" in verify
    assert "mark it `minor` with the note starting `unproven:`" in verify
    assert "Save a security finding" in verify and "mark it `confirmed`, with what you could not rule out" in verify
    # The brief the agent receives names no verdict
    fence = verify[verify.index("```text") :]
    assert "REFUSE" not in fence and "verdict" not in fence


def test_s075_3_the_landing_session_verifies_a_refusal_before_recording_it() -> None:
    step = section(SKILLS / "github-pr-triage" / "SKILL.md", "### 3. Verify each reviewer's report")
    assert "A reviewer's REFUSE is verified before it is recorded or handed back" in step
    assert "(references/reviewer-brief.md#verify-a-refusal)" in step
    assert "a fresh agent, neither the first reviewer nor this landing session" in step
    assert "in the foreground in a headless session" in step
    assert "the verdict is REFUSE only when at least one finding is `confirmed`" in step
    assert 'followed by a "Second look" part, one line per `F-n`' in step
    assert "The handback names only confirmed findings, each with its failure scenario" in step


def test_s075_9_landing_records_the_counts_and_the_retro_reads_them() -> None:
    landing = section(SKILLS / "github-pr-triage" / "references" / "landing.md", "## Recording the review")
    assert "--findings confirmed=N,rejected=N,minor=N --body-file <report>" in landing
    assert "A refusal is recorded only after the second look" in landing
    watch = folded(SKILLS / "github-ship-watch" / "SKILL.md")
    gather = watch[watch.index("1. Gather: `scripts/retro.py gather") : watch.index(" 2. Recurring findings")]
    assert "also pass `--reviews`" in gather


def test_the_pr_triage_skill_leaves_no_detached_worktree_for_the_prune() -> None:
    """The prune keeps a detached worktree forever (S-002-4) and finds a landed pull request by a
    branch named for it (D-91), so a worktree the skill may leave behind holds such a branch (#1513)"""
    verify = section(BRIEF, "## Verify a refusal")
    assert "--detach" not in verify
    assert "`git fetch origin pull/{N}/head`, then `git checkout -B review-{N}-verify {reviewed_head}`" in verify
    assert "`git branch --set-upstream-to=origin/{head_branch} review-{N}-verify`" in verify
    landing = folded(SKILLS / "github-pr-triage" / "references" / "landing.md")
    assert "--detach" not in landing
    assert "`git checkout -B land-<child> origin/<default>`" in landing
    assert "`git worktree add -B land-<N> tmp/wt-land-<N> <ref>`" in landing
    step = section(SKILLS / "github-pr-triage" / "SKILL.md", "### 7. Clean up")
    assert "holds a branch named for its pull request" in step and "never a detached HEAD" in step
    three = section(SKILLS / "github-pr-triage" / "SKILL.md", "### 3. Verify each reviewer's report")
    assert "`{head_branch}`" in three


def test_s055_18_the_implementer_opens_the_pr_with_its_plan_in_the_body() -> None:
    brief = folded(SKILLS / "github-issue-triage" / "references" / "implementer-brief.md")
    assert "the body the PR is opened with" in brief
