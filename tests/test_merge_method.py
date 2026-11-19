"""Spec 072: [agents] merge picks the method `shipmill gh pr merge` lands with, a method the
repo's settings don't allow exits 2 rather than falling back, and the messages naming a merge
command and the credit's body follow the setting. No test reaches the network: the pull request
and the repo's settings are FakeReads, its records FakeCredit, GitHub MintApi"""

from pathlib import Path

import pytest

from shipmill.agents import AgentsConfig, MergeMethod, gh_identity_of
from shipmill.config import CONFIG_PATH, Table
from shipmill.credit import Message, Messages
from shipmill.errors import ReleaseError
from shipmill.github import MergeMethods

from .conftest import POLICY, Repo
from .test_app import REPO
from .test_app_gh_merge import CODE, FakeReads, connected, pinned_to
from .test_credit import (
    OCTOCAT_TRAILER,
    ON,
    WITH_APP,
    CreditReader,
    FakeCredit,
    Runner,
    approved,
    body_of,
    gh,
)

MERGE = 'merge = "merge"\n'
SQUASH = 'merge = "squash"\n'
AUTHOR = WITH_APP + 'author = "app"\n'
API_MERGE = ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"]


# -- S-072-1: the setting ------------------------------------------------------------------------


def agents(merge: object | None) -> Table:
    return Table({"prompt": "/t", **({} if merge is None else {"merge": merge})}, "shipmill.toml [agents]")


def test_s072_1_merge_reads_as_squash_without_the_key_and_as_set_with_it(tmp_path: Path) -> None:
    assert AgentsConfig.parse(agents(None)).merge is None  # no key: the default, which doctor names
    assert AgentsConfig.parse(agents(None)).merge_method is MergeMethod.SQUASH
    assert AgentsConfig.parse(agents("squash")).merge_method is MergeMethod.SQUASH
    assert AgentsConfig.parse(agents("merge")).merge_method is MergeMethod.MERGE
    (tmp_path / CONFIG_PATH).parent.mkdir()
    (tmp_path / CONFIG_PATH).write_text(POLICY + WITH_APP, encoding="utf-8")
    assert gh_identity_of(tmp_path).merge_method is MergeMethod.SQUASH
    (tmp_path / CONFIG_PATH).write_text(POLICY + WITH_APP + MERGE, encoding="utf-8")
    assert gh_identity_of(tmp_path).merge_method is MergeMethod.MERGE


@pytest.mark.parametrize("value", ["rebase", "Merge", "", "squash-merge", True, 1, ["merge"]])
def test_s072_1_any_other_merge_fails_to_load_naming_the_key_and_both_values(tmp_path: Path, value: object) -> None:
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        AgentsConfig.parse(agents(value))
    message = str(raised.value)
    assert '[agents] merge must be "squash" or "merge"' in message and repr(value) in message
    (tmp_path / CONFIG_PATH).parent.mkdir()
    (tmp_path / CONFIG_PATH).write_text(POLICY + WITH_APP + 'merge = "rebase"\n', encoding="utf-8")
    with pytest.raises(ReleaseError, match=r'\[agents\] merge must be "squash" or "merge"'):
        gh_identity_of(tmp_path)


# -- S-072-6: a method the repo doesn't allow ------------------------------------------------------


def test_s072_6_merge_under_merge_where_merge_commits_are_off_exits_2_before_any_merge(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + MERGE)
    reads, runner = FakeReads((CODE,), allowed=MergeMethods(squash=True, merge=False)), Runner(capsys)
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["pr", "merge", "7", "--merge"], runner, merge=reads)
    message = str(raised.value)
    assert '[agents] merge = "merge"' in message and "allow_merge_commit" in message and "D-96" in message
    assert runner.calls == []  # no merge, and none retried with --squash
    assert reads.methods_read == 1


def test_s072_6_squash_under_squash_where_squash_merges_are_off_exits_2(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + SQUASH)
    reads, runner = FakeReads((CODE,), allowed=MergeMethods(squash=False, merge=True)), Runner(capsys)
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["pr", "merge", "7", "-s"], runner, merge=reads)
    message = str(raised.value)
    assert '[agents] merge = "squash"' in message and "allow_squash_merge" in message
    assert runner.calls == []


@pytest.mark.parametrize(
    ("config", "args", "allowed", "names"),
    [
        (WITH_APP, ["pr", "merge", "7", "--squash"], MergeMethods(False, True), "allow_squash_merge"),
        (WITH_APP + SQUASH, ["pr", "merge", "7", "--merge"], MergeMethods(True, False), "allow_merge_commit"),
        (WITH_APP + MERGE, ["pr", "merge", "7", "--squash"], MergeMethods(False, True), "allow_squash_merge"),
        (WITH_APP + MERGE, [*API_MERGE, "-f", "merge_method=merge"], MergeMethods(True, False), "allow_merge_commit"),
        (WITH_APP, [*API_MERGE, "-f", "merge_method=squash"], MergeMethods(False, True), "allow_squash_merge"),
    ],
)
def test_s072_6_any_named_method_the_repo_doesnt_allow_exits_2_naming_its_setting(
    repo: Repo,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    config: str,
    args: list[str],
    allowed: MergeMethods,
    names: str,
) -> None:
    key = connected(repo, tmp_path, POLICY + config)
    runner = Runner(capsys)
    with pytest.raises(ReleaseError, match=f"is refused: .*{names}.*D-96"):
        gh(repo, tmp_path, key, args, runner, merge=FakeReads((CODE,), allowed=allowed))
    assert runner.calls == []


@pytest.mark.parametrize("config", [WITH_APP, WITH_APP + SQUASH, WITH_APP + MERGE])
@pytest.mark.parametrize(
    "args",
    [
        ["pr", "merge", "7", "--squash"],
        ["pr", "merge", "7", "--merge"],
        [*API_MERGE, "-f", "merge_method=merge"],
    ],
)
def test_s072_6_an_allowed_method_merges_as_before(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, args: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + config)
    reads, runner = FakeReads((CODE,)), Runner(capsys)
    assert gh(repo, tmp_path, key, args, runner, merge=reads) == 0
    assert [argv[1:] for argv in runner.calls] == [pinned_to(args)]
    assert reads.methods_read == 1


@pytest.mark.parametrize("args", [["pr", "merge", "7", "--rebase"], ["pr", "merge", "7", "--disable-auto"], API_MERGE])
def test_s072_6_a_merge_naming_no_squash_or_merge_reads_no_setting(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + MERGE)
    reads, runner = FakeReads((CODE,), allowed=MergeMethods(False, False)), Runner(capsys)
    assert gh(repo, tmp_path, key, args, runner, merge=reads) == 0
    assert reads.methods_read == 0


@pytest.mark.parametrize(
    ("found", "message"),
    [
        ({"allow_squash_merge": True, "allow_merge_commit": False}, None),
        ({"allow_squash_merge": True}, "allow_merge_commit as None"),
        ({"allow_squash_merge": "yes", "allow_merge_commit": True}, "allow_squash_merge as 'yes'"),
        ([], "not a repo"),
    ],
)
def test_s072_6_the_repos_settings_parse_strictly(found: object, message: str | None) -> None:
    if message is None:
        assert MergeMethods.parse(found) == MergeMethods(squash=True, merge=False)
        return
    with pytest.raises(ReleaseError, match=message):
        MergeMethods.parse(found)


# -- S-072-7: the messages naming a merge command --------------------------------------------------


@pytest.mark.parametrize(
    ("config", "method"),
    [
        (ON + MERGE, "--merge"),
        (AUTHOR + MERGE, "--merge"),
        (ON + SQUASH, "--squash"),
        (ON, "--squash"),
        (AUTHOR, "--squash"),
    ],
)
def test_s072_7_the_api_merge_refusal_names_the_settings_method(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, method: str
) -> None:
    key = connected(repo, tmp_path, POLICY + config)
    runner = Runner(capsys)
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, API_MERGE, runner, CreditReader(FakeCredit()))
    assert f"gh pr merge 7 {method}` instead" in str(raised.value)
    assert runner.calls == []


@pytest.mark.parametrize(
    ("config", "add"),
    [
        (ON + MERGE, "add --merge"),
        (ON + SQUASH, "add --squash (or --merge for a stack's base, D-96)"),
        (ON, "add --squash (or --merge for a stack's base, D-96)"),
    ],
)
def test_s072_7_a_merge_naming_no_method_is_told_the_settings_method(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, add: str
) -> None:
    key = connected(repo, tmp_path, POLICY + config)
    credit, runner = CreditReader(FakeCredit(reviews=[approved("octocat")])), Runner(capsys)
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["pr", "merge", "7"], runner, credit)
    assert str(raised.value).endswith(add)
    assert runner.calls == []


# -- S-072-8: the credit's body under a merge commit -----------------------------------------------


@pytest.mark.parametrize(
    ("setting", "body"),
    [
        (Message.PR_BODY, f"The change.\n\nFixes #9\n\n{OCTOCAT_TRAILER}"),
        (Message.PR_TITLE, OCTOCAT_TRAILER),
        (Message.BLANK, OCTOCAT_TRAILER),
    ],
)
def test_s072_8_merge_under_merge_writes_the_merge_commit_message_body_and_the_trailer(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str], setting: Message, body: str
) -> None:
    key = connected(repo, tmp_path, POLICY + ON + MERGE)
    reads = FakeCredit(reviews=[approved("octocat")], messages=Messages(Message.COMMIT_MESSAGES, setting))
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--merge"], runner, credit) == 0
    [argv] = runner.calls
    assert argv[1:5] == ["pr", "merge", "7", "--merge"]
    assert body_of(argv) == body  # merge_commit_message's body; a merge commit adds no commit co-authors


def test_s072_8_squash_under_squash_still_writes_the_squash_message_body(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = connected(repo, tmp_path, POLICY + ON + SQUASH)
    reads = FakeCredit(reviews=[approved("octocat")], messages=Messages(Message.PR_BODY, Message.BLANK))
    credit, runner = CreditReader(reads), Runner(capsys)
    assert gh(repo, tmp_path, key, ["pr", "merge", "7", "--squash"], runner, credit) == 0
    [argv] = runner.calls
    assert body_of(argv) == f"The change.\n\nFixes #9\n\nCo-authored-by: A <a@x>\n{OCTOCAT_TRAILER}"
