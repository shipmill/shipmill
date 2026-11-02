"""Spec 053: `shipmill spec open` opens a spec's pull request naming its feature issue. git runs
on a local bare origin or a recording fake, GitHub is a recording fake or `shipmill gh`'s own path
with the App faked (MintApi, FakeSigner), and nothing reaches the network"""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

from shipmill.agent_marker import MARKER, marked
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.spec_open import GitCheckout, Record, Request, lowered, open_spec

from .test_app import REPO as APP_REPO
from .test_app import FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import FAKE_GH, MintApi, executable
from .test_gh_refuses_without_app import AGENTS_NO_APP, HOST_IDENTITY
from .test_specs import DECISIONS

TRIAGE_STATE = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = "o/r"
SPEC = "docs/specs/001-dry-run.md"
BRANCH = "spec/001-dry-run"
PULL = 41
URL = f"https://github.com/{REPO}/pull/{PULL}"
HOLD = f"On hold: the build waits on {REPO}#{PULL}, the spec PR."


def spec_text(status: str = "approved", serves: str | None = "G-1", title: str = "Dry run for the tool") -> str:
    head = [f"# S-001: {title}", "", f"status: {status}"]
    if serves is not None:
        head.append(f"serves: {serves}")
    body = [
        "## Problem",
        "",
        "Runs write files.",
        "",
        "## Behaviour",
        "",
        "Adds the `--dry-run` flag.",
        "",
        "## Acceptance criteria",
        "",
        "- S-001-1: tool run --dry-run writes nothing",
        "",
        "## Out of scope",
        "",
        "- Undo",
        "",
        "## Decisions relied on",
        "",
        "- D-2",
        "",
        "## Issues",
        "",
        "## Verification",
        "",
    ]
    return "\n".join([*head, "", *body])


def repo_files(root: Path, spec: str | None) -> None:
    (root / "docs" / "specs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "decisions.md").write_text(DECISIONS, encoding="utf-8")
    if spec is not None:
        (root / SPEC).write_text(spec, encoding="utf-8")


def git(root: Path, *args: str) -> str:
    return Git(root).run(*args)


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A checkout whose origin is a local bare repo, its default branch main holding the
    decisions log; the spec file is written but not committed, as `specs.py new` leaves it"""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    root = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, value in (("user.name", "Dev"), ("user.email", "dev@example.com"), ("commit.gpgsign", "false")):
        git(root, "config", key, value)
    git(root, "remote", "add", "origin", str(origin))
    repo_files(root, None)
    git(root, "add", "docs")
    git(root, "commit", "-q", "-m", "Start")
    git(root, "push", "-q", "origin", "main")
    (root / SPEC).write_text(spec_text(), encoding="utf-8")
    return root


@dataclass
class FakeHub:
    """GitHub: each number's record, and every write in order"""

    records: dict[int, Record | None] = field(default_factory=lambda: {7: Record(pull=False, open=True)})
    reads: list[int] = field(default_factory=list)
    writes: list[tuple[str, ...]] = field(default_factory=list)

    def record(self, number: int) -> Record | None:
        self.reads.append(number)
        return self.records.get(number)

    def open_pull(self, title: str, body: str, head: str, base: str) -> str:
        self.writes.append(("pull", title, body, head, base))
        return URL

    def comment(self, number: int, body: str) -> None:
        self.writes.append(("comment", str(number), body))


@dataclass
class FakeCheckout:
    """origin: its default branch and branches; every publish recorded, none pushed"""

    branches: dict[str, str] = field(default_factory=dict)
    published: list[tuple[str, str, tuple[PurePosixPath, ...], str]] = field(default_factory=list)

    def default_branch(self) -> str:
        return "trunk"

    def remote_branch(self, branch: str) -> str | None:
        return self.branches.get(branch)

    def publish(self, branch: str, base: str, paths: Sequence[PurePosixPath], message: str) -> None:
        self.published.append((branch, base, tuple(paths), message))


def available() -> None:
    """The App is available"""


def request(
    issue: int | None = 7, path: str = SPEC, with_paths: tuple[str, ...] = (), body_file: Path | None = None
) -> Request:
    return Request(path, issue, with_paths, body_file)


def refused(top: Path, ask: Request, hub: FakeHub, fake: FakeCheckout | None = None) -> str:
    """The refusal's message; nothing was published and nothing was written to GitHub"""
    fake = fake or FakeCheckout()
    with pytest.raises(ReleaseError) as raised:
        open_spec(top, REPO, ask, fake, hub, available)
    assert (fake.published, hub.writes) == ([], [])
    return str(raised.value)


def only_file(root: Path) -> Path:
    repo_files(root, spec_text())
    return root


# --- S-053-1: a branch from origin's default branch, the pull request, the verdict, the URL ------


def test_s053_1_one_commit_on_origins_default_branch_a_pull_request_and_the_verdict(clone: Path) -> None:
    base = git(clone, "rev-parse", "origin/main").strip()
    branch_before = git(clone, "branch", "--show-current")
    status_before = git(clone, "status", "--porcelain")
    hub = FakeHub()
    url = open_spec(clone, REPO, request(), GitCheckout(clone), hub, available)
    assert url == URL
    head = git(clone, "ls-remote", "--heads", "origin", BRANCH).split()[0]
    assert git(clone, "rev-list", "--parents", "-n", "1", head).split() == [head, base]  # one commit on main
    changed = git(clone, "diff-tree", "--no-commit-id", "--name-status", "-r", base, head).splitlines()
    assert changed == [f"A\t{SPEC}"]
    assert git(clone, "log", "-1", "--format=%s", head).strip() == "Spec 001: dry run for the tool"
    (pull, title, body, branch, onto), (comment, issue, verdict) = hub.writes
    assert (pull, title, branch, onto) == ("pull", "Spec 001: Dry run for the tool", BRANCH, "main")
    assert body.splitlines()[0] == "Spec for #7"
    assert (comment, issue) == ("comment", "7")
    assert verdict.startswith("Triage: **feature**.")
    assert HOLD in verdict.splitlines()
    assert "implement" not in verdict.lower()  # triage_state.py reads the verdict from it
    # the working tree, the index, and the current branch stay as they were
    assert (git(clone, "branch", "--show-current"), git(clone, "status", "--porcelain")) == (
        branch_before,
        status_before,
    )


def test_s053_1_the_commit_subject_lowercases_the_first_letter_but_not_an_acronym() -> None:
    assert lowered("Dry run for the tool") == "dry run for the tool"
    assert lowered("GitHub writes as the App") == "GitHub writes as the App"
    assert lowered("CLI flags") == "CLI flags"


# --- S-053-2: Serves, --body-file, and --with ----------------------------------------------------


@pytest.mark.parametrize(
    ("serves", "said"),
    [("G-1", " Serves: G-1. "), ("G-1, G-3", " Serves: G-1, G-3. "), ("quality bar", None), (None, None)],
)
def test_s053_2_the_verdict_names_the_goals_the_spec_serves(
    tmp_path: Path, serves: str | None, said: str | None
) -> None:
    repo_files(tmp_path, spec_text(serves=serves))
    hub = FakeHub()
    open_spec(tmp_path, REPO, request(), FakeCheckout(), hub, available)
    verdict = hub.writes[1][2]
    first = verdict.splitlines()[0]
    if said is None:
        assert "Serves:" not in verdict and first.startswith("Triage: **feature**. The behaviour")
    else:
        assert first.startswith(f"Triage: **feature**.{said}")


def test_s053_2_a_serves_line_naming_no_goal_id_is_refused(tmp_path: Path) -> None:
    repo_files(tmp_path, spec_text(serves="the parser"))
    assert "names 'the parser'" in refused(tmp_path, request(), FakeHub())


def test_s053_2_body_file_follows_the_spec_for_line_and_with_paths_share_the_commit(clone: Path) -> None:
    (clone / "docs" / "decisions.md").write_text(DECISIONS + "\n## D-3: Dry runs\n", encoding="utf-8")
    notes = clone.parent / "body.md"
    notes.write_text("\n## Decisions for you\n\n- None\n", encoding="utf-8")
    base = git(clone, "rev-parse", "origin/main").strip()
    hub = FakeHub()
    ask = request(with_paths=("docs/decisions.md",), body_file=notes)
    open_spec(clone, REPO, ask, GitCheckout(clone), hub, available)
    assert hub.writes[0][2] == "Spec for #7\n\n## Decisions for you\n\n- None"
    head = git(clone, "ls-remote", "--heads", "origin", BRANCH).split()[0]
    changed = git(clone, "diff-tree", "--no-commit-id", "--name-only", "-r", base, head).split()
    assert sorted(changed) == ["docs/decisions.md", SPEC]
    assert git(clone, "rev-list", "--count", f"{base}..{head}").strip() == "1"


@pytest.mark.parametrize("given", ["/etc/hosts", "../outside.md", ".git/config", "docs/missing.md", SPEC, "docs"])
def test_s053_2_a_with_path_that_isnt_a_file_of_the_repo_is_refused(tmp_path: Path, given: str) -> None:
    repo_files(tmp_path, spec_text())
    assert "--with" in refused(tmp_path, request(with_paths=(given,)), FakeHub())


def test_s053_2_a_with_path_through_a_symlinked_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repo_files(root, spec_text())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("not the repo's\n", encoding="utf-8")
    (root / "linked").symlink_to(outside)
    assert "--with linked/secret.md" in refused(root, request(with_paths=("linked/secret.md",)), FakeHub())


# --- S-053-3: no --issue -------------------------------------------------------------------------


def test_s053_3_without_issue_it_exits_2_naming_issue_and_the_feature_issue(tmp_path: Path) -> None:
    message = refused(only_file(tmp_path), request(issue=None), hub := FakeHub())
    assert "--issue" in message and "feature issue" in message
    assert hub.reads == []


def test_s053_3_through_the_cli_it_exits_2_and_runs_no_gh(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    repo_files(root, spec_text())
    env = {**host.env(), "HOME": str(host.home)}
    done = subprocess.run(
        [sys.executable, "-m", "shipmill", "--repo", str(root), "spec", "open", SPEC],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr.startswith("shipmill: a spec pull request needs its feature issue: pass --issue N")
    assert not (host.record / "gh-args").exists()  # gh never ran
    assert git(root, "branch", "--list").strip() == ""  # no branch, no commit


# --- S-053-4: --issue names a closed issue, a pull request, or nothing ----------------------------


@pytest.mark.parametrize(
    ("found", "said"),
    [
        (Record(pull=False, open=False), "#7 in o/r is closed"),
        (Record(pull=True, open=True), "#7 in o/r is a pull request"),
        (Record(pull=True, open=False), "#7 in o/r is a pull request"),
        (None, "#7 is no issue of o/r"),
    ],
)
def test_s053_4_issue_must_be_an_open_issue_of_the_repo(tmp_path: Path, found: Record | None, said: str) -> None:
    hub = FakeHub(records={7: found})
    assert refused(only_file(tmp_path), request(), hub).startswith(said)


# --- S-053-5: the path, specs.py check, and the status --------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "docs/specs/01-dry-run.md",
        "docs/specs/001-Dry-run.md",
        "docs/specs/001_dry_run.md",
        "specs/001-dry-run.md",
        "./docs/specs/001-dry-run.md",
        "/docs/specs/001-dry-run.md",
        "docs/specs/001-dry-run.txt",
    ],
)
def test_s053_5_a_path_not_shaped_docs_specs_nnn_slug_is_refused(tmp_path: Path, path: str) -> None:
    hub = FakeHub()
    assert "docs/specs/NNN-<slug>.md" in refused(only_file(tmp_path), request(path=path), hub)
    assert hub.reads == []


def test_s053_5_a_missing_spec_file_is_refused(tmp_path: Path) -> None:
    repo_files(tmp_path, None)
    assert refused(tmp_path, request(), FakeHub()).startswith(f"no spec file at {SPEC}")


def test_s053_5_a_spec_failing_specs_py_check_is_refused_with_its_messages(tmp_path: Path) -> None:
    repo_files(tmp_path, spec_text().replace("## Out of scope\n\n- Undo\n\n", ""))
    hub = FakeHub()
    message = refused(tmp_path, request(), hub)
    assert message.startswith("the specs don't pass specs.py check, so nothing was written:\n")
    assert f"{SPEC}:1: missing the section 'Out of scope'" in message
    assert hub.reads == []


@pytest.mark.parametrize("status", ["draft", "built"])
def test_s053_5_a_spec_not_approved_is_refused(tmp_path: Path, status: str) -> None:
    text = spec_text(status=status)
    if status == "built":
        text = text.replace("## Issues\n", "## Issues\n\n- o/r#12: S-001-1\n").replace(
            "## Verification\n", "## Verification\n\n- S-001-1: ran it, nothing written\n"
        )
    repo_files(tmp_path, text)
    hub = FakeHub()
    assert refused(tmp_path, request(), hub).startswith(f"{SPEC} is {status}, and a spec pull request opens")
    assert hub.reads == []


# --- S-053-6: the branch exists on origin --------------------------------------------------------


def test_s053_6_a_spec_branch_on_origin_is_refused_and_left_alone(clone: Path) -> None:
    git(clone, "push", "-q", "origin", f"main:refs/heads/{BRANCH}")
    before = git(clone, "ls-remote", "origin").splitlines()
    hub = FakeHub()
    with pytest.raises(ReleaseError, match=f"origin already has the branch {BRANCH}"):
        open_spec(clone, REPO, request(), GitCheckout(clone), hub, available)
    assert hub.writes == []
    assert git(clone, "ls-remote", "origin").splitlines() == before


def test_s053_6_with_a_fake_origin_nothing_is_published(tmp_path: Path) -> None:
    fake = FakeCheckout(branches={BRANCH: "abc123"})
    assert refused(only_file(tmp_path), request(), FakeHub(), fake).startswith("origin already has the branch")


# --- S-053-7: every write through the App, as `shipmill gh` writes ----------------------------------


@dataclass
class FakeGh:
    """gh as `shipmill gh` runs it, its output captured: an open issue #7, then the pull
    request's URL and the comment's; every argv and env recorded"""

    issue: str = '{"number": 7, "state": "open"}'
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        args = list(argv[1:])
        self.calls.append((args, dict(env)))
        if args[0] == "api":
            return 0, self.issue
        if args[:2] == ["pr", "create"]:
            return 0, f"https://github.com/{APP_REPO}/pull/{PULL}\n"
        return 0, f"https://github.com/{APP_REPO}/issues/7#issuecomment-1\n"


def cli(root: Path, host: Host, gh: FakeGh, fake: FakeCheckout, api: MintApi, **env: str) -> int:
    return main(
        ["--repo", str(root), "spec", "open", SPEC, "--issue", "7"],
        api=api,
        signer=FakeSigner(),
        environ=host.env(**env),
        home=host.home,
        gh_capture=gh,
        spec_checkout=fake,
    )


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


def body_of(args: list[str]) -> str:
    return args[args.index("--body") + 1]


# proves: S-053-1
def test_s053_7_every_github_call_runs_as_the_app_with_the_marker(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    root = checkout(tmp_path, WITH_APP)
    repo_files(root, spec_text())
    key = key_file(tmp_path)
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi(expires_from=dt.datetime.now(dt.UTC))
    assert cli(root, host, gh, fake, api, SHIPMILL_APP_KEY=str(key)) == 0
    assert capsys.readouterr().out == f"https://github.com/{APP_REPO}/pull/{PULL}\n"
    (read, _), (pull, _), (comment, _) = gh.calls
    assert read == ["api", f"repos/{APP_REPO}/issues/7"]
    assert pull[:9] == ["pr", "create", "-R", APP_REPO, "--head", BRANCH, "--base", "trunk", "--title"]
    assert comment[:4] == ["issue", "comment", "7", "-R"]
    assert all(env["GH_TOKEN"].startswith("token-") for _, env in gh.calls)  # the App's, never the host's
    for args in (pull, comment):  # D-62: shipmill gh marks every body it writes
        assert body_of(args).endswith(f"\n\n{MARKER}")
    assert body_of(pull).splitlines()[0] == "Spec for #7"
    assert f"On hold: the build waits on {APP_REPO}#{PULL}, the spec PR." in body_of(comment).splitlines()
    [(branch, base, paths, message)] = fake.published
    assert (branch, base, paths, message) == (BRANCH, "trunk", (PurePosixPath(SPEC),), "Spec 001: dry run for the tool")


def test_s053_7_without_the_apps_key_it_exits_2_with_shipmill_ghs_reason_before_any_push(
    tmp_path: Path, host: Host
) -> None:
    root = checkout(tmp_path, WITH_APP)
    repo_files(root, spec_text())
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi()
    with pytest.raises(ReleaseError, match="no App private key at") as raised:
        cli(root, host, gh, fake, api)
    assert str(host.home) in str(raised.value)  # the default path, as `shipmill gh` names it
    assert (gh.calls, fake.published, api.posts) == ([], [], [])


def test_s053_7_without_app_id_it_exits_2_with_shipmill_ghs_refusal(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, AGENTS_NO_APP)
    repo_files(root, spec_text())
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi()
    with pytest.raises(ReleaseError) as raised:
        cli(root, host, gh, fake, api)
    first, second = str(raised.value).split("\n")
    assert first == (
        f"refusing a write to {APP_REPO} as the host's gh login: .github/shipmill.toml sets no [agents] app_id"
    )
    assert 'set [agents] identity = "host"' in second
    assert (gh.calls, fake.published, api.posts) == ([], [], [])


def test_s053_7_identity_host_writes_as_the_host_as_shipmill_gh_does(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    repo_files(root, spec_text())
    gh, fake, api = FakeGh(), FakeCheckout(), MintApi()
    assert cli(root, host, gh, fake, api, GH_TOKEN="") == 0
    assert [args[:2] for args, _ in gh.calls] == [
        ["api", f"repos/{APP_REPO}/issues/7"],
        ["pr", "create"],
        ["issue", "comment"],
    ]
    assert all("GH_TOKEN" not in env for _, env in gh.calls)
    assert (api.posts, len(fake.published)) == ([], 1)


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        ((1, json.dumps({"message": "Not Found", "status": "404"})), "#7 is no issue of romamo/demo"),
        ((0, json.dumps({"number": 7, "state": "open", "pull_request": {}})), "#7 in romamo/demo is a pull request"),
        ((0, json.dumps({"number": 7, "state": "closed"})), "#7 in romamo/demo is closed"),
        ((1, ""), "exited 1, so #7 can't be read"),
    ],
)
def test_s053_4_the_cli_reads_the_issue_through_shipmill_gh(
    tmp_path: Path, host: Host, answer: tuple[int, str], said: str
) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    repo_files(root, spec_text())
    fake = FakeCheckout()

    @dataclass
    class Answering(FakeGh):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
            self.calls.append((list(argv[1:]), dict(env)))
            return answer

    gh = Answering()
    with pytest.raises(ReleaseError) as raised:
        cli(root, host, gh, fake, MintApi())
    assert said in str(raised.value)
    assert [args[0] for args, _ in gh.calls] == ["api"]  # the read, and no write
    assert fake.published == []


# --- S-053-8: triage_state.py holds the feature issue on the spec pull request ---------------------


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    found = importlib.util.spec_from_file_location("triage_state", TRIAGE_STATE)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[found.name] = module
    found.loader.exec_module(module)
    return module


def test_s053_8_the_feature_issue_reads_blocked_until_the_spec_pull_request_merges(
    tmp_path: Path, ts: ModuleType
) -> None:
    hub = FakeHub()
    open_spec(only_file(tmp_path), REPO, request(), FakeCheckout(), hub, available)
    posted = marked(hub.writes[1][2])  # as shipmill gh posts it
    item = {
        "number": 7,
        "body": "Add a dry run.",
        "labels": {"nodes": []},
        "comments": {"nodes": [{"createdAt": "2026-11-02T10:00:00Z", "body": posted}]},
        "timelineItems": {"nodes": []},
    }
    ref = ("o", "r", PULL)
    assert ts.upstream_refs(item, ("o", "r")) == [ref]  # the spec pull request alone, never #7 itself
    for state, expected in (("OPEN", "BLOCKED"), ("MERGED", "UNBLOCKED")):
        verdict = ts.classify_open(item, "Triage:", "postponed", {ref: state}, None, ("o", "r"))
        assert verdict == (expected, f"o/r#{PULL}:{state.lower()}")
