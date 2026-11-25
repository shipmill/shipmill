"""Spec 083's area-record zone: `decide classify` reads the production record only when the
base asks for it, and both `decide record` and `decide classify` fail closed when it can't be read"""

import json
from typing import Any, NoReturn

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import AuthoredIssue, Deployment, DeploymentStatus, FileChange

from .conftest import POLICY, Repo
from .test_area_record import LINE, FakeReads, S, history, later
from .test_decide_cli import FakePulls, commit

ASK = POLICY + '\n[decisions]\narea-record = "ask"\n'
EARNED = POLICY + '\n[decisions.earned]\nprotected = "act"\n'


class Refusing:
    """A record read that fails the test on any call: a repo that sets neither area-record
    above act nor [decisions.earned] makes no new read"""

    def authored_issues(self, label: str) -> list[AuthoredIssue]:
        pytest.fail(f"read the issues labelled {label}")

    def deployments(self, environment: str) -> list[Deployment]:
        pytest.fail(f"read the deployments to {environment}")

    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]:
        pytest.fail(f"read the statuses of deployment {deployment}")


def gh_fails(what: str) -> NoReturn:
    raise ReleaseError(f"gh api {what} failed: HTTP 502")


class IssuesFail(FakeReads):
    def authored_issues(self, label: str) -> list[AuthoredIssue]:
        gh_fails("issues")


class DeploymentsFail(FakeReads):
    def deployments(self, environment: str) -> list[Deployment]:
        gh_fails("deployments")


class StatusesFail(FakeReads):
    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]:
        gh_fails("statuses")


def raised_app(repo: Repo, config: str, reads: FakeReads, *clean: str) -> None:
    """v1.4.0 failed in production (#212), raising src/app and docs; each clean tag reached
    success there after it; the config lands on the base"""
    history(repo)
    later(repo)
    reads.incident(212, LINE)
    for tag in clean:
        reads.deploy("production", tag, S)
    commit(repo, config)


def classify(repo: Repo, capsys: pytest.CaptureFixture[str], reads: Any, *args: str) -> dict[str, Any]:
    argv = ["--repo", str(repo.root), "decide", "classify", *args, "--json"]
    pulls = FakePulls((FileChange("src/app/a.py", "modified", "@@ -1 +1 @@\n+A = 9"),))
    assert main(argv, pulls=pulls, record_reads=reads) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def zones(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {z["zone"]: z for z in found["zones"]}


def refused(repo: Repo, capsys: pytest.CaptureFixture[str], reads: Any, command: str, match: str) -> None:
    args = ["classify", "--files", "src/app/a.py"] if command == "classify" else ["record"]
    with pytest.raises(ReleaseError, match=match):
        main(["--repo", str(repo.root), "decide", *args, "--json"], pulls=FakePulls(), record_reads=reads)
    assert capsys.readouterr().out == ""  # no area, no zone


# -- S-083-6: fail closed, and no new read without the settings ---------------------------------


@pytest.mark.parametrize("command", ["record", "classify"])
@pytest.mark.parametrize(
    ("failing", "match"),
    [
        (IssuesFail, r"the issues labelled 'incident' can't be read: gh api issues failed: HTTP 502"),
        (DeploymentsFail, r"the deployments to production can't be read: gh api deployments failed"),
        (StatusesFail, r"the deployments to production can't be read: gh api statuses failed"),
    ],
)
def test_s083_6_a_failed_issues_or_deployments_read_exits_2_naming_it_and_printing_no_area(
    repo: Repo, capsys: pytest.CaptureFixture[str], command: str, failing: type[FakeReads], match: str
) -> None:
    reads = failing()
    raised_app(repo, ASK, reads, "v1.4.1")
    refused(repo, capsys, reads, command, match)


@pytest.mark.parametrize("command", ["record", "classify"])
def test_s083_6_a_tag_an_incident_names_that_the_checkout_lacks_exits_2(
    repo: Repo, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    reads = FakeReads()
    raised_app(repo, ASK, reads)
    reads.incident(213, LINE.replace("tag=v1.4.0", "tag=v1.9.0"))
    refused(repo, capsys, reads, command, r"incident #213 names v1\.9\.0, which the checkout lacks")


@pytest.mark.parametrize(
    ("config", "why"),
    [
        (ASK, r"the base sets \[decisions\] area-record = 'ask'"),
        (POLICY + '\n[decisions]\narea-record = "notify"\n', r"the base sets \[decisions\] area-record = 'notify'"),
        (EARNED, r"the base has \[decisions\.earned\]"),
    ],
)
def test_s083_6_classify_exits_2_naming_why_it_read_the_record_when_the_base_asks_for_it(
    repo: Repo, capsys: pytest.CaptureFixture[str], config: str, why: str
) -> None:
    reads = IssuesFail()
    raised_app(repo, config, reads)
    refused(repo, capsys, reads, "classify", f"the production record can't be read, and {why}")


def test_s083_6_classify_makes_no_record_read_when_the_base_sets_neither(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    raised_app(repo, POLICY + '\n[decisions]\narea-record = "act"\n', FakeReads())
    assert zones(classify(repo, capsys, Refusing(), "--files", "src/app/a.py")) == {}
    assert zones(classify(repo, capsys, Refusing(), "--pr", "7")) == {}
    commit(repo, POLICY)  # no [decisions] at all
    assert zones(classify(repo, capsys, Refusing(), "--files", "src/app/a.py")) == {}


def test_s083_6_a_config_on_the_working_tree_alone_doesnt_make_classify_read(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    raised_app(repo, POLICY, FakeReads())
    repo.write(".github/shipmill.toml", ASK)  # D-48: the base's levels, never the change's
    assert zones(classify(repo, capsys, Refusing(), "--files", "src/app/a.py")) == {}


# -- S-083-7: the area-record zone --------------------------------------------------------------


def test_s083_7_a_path_in_a_raised_area_reports_area_record_at_the_bases_level(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    reads = FakeReads()
    raised_app(repo, ASK, reads, "v1.4.1")
    found = classify(repo, capsys, reads, "--files", "src/app/a.py")
    assert found["level"] == "ask"
    assert zones(found)["area-record"] == {
        "zone": "area-record",
        "level": "ask",
        "reason": "src/app is raised: v1.4.0 failed in production (#212), 1 of 3 clean releases since",
        "paths": [{"path": "src/app/a.py", "level": "ask", "source": "config", "glob": None}],
    }
    assert reads.labels == ["incident"]


def test_s083_7_a_pull_request_touching_a_raised_area_reports_it_too(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    reads = FakeReads()
    raised_app(repo, ASK, reads)
    found = zones(classify(repo, capsys, reads, "--pr", "7"))
    assert found["area-record"]["reason"] == (
        "src/app is raised: v1.4.0 failed in production (#212), 0 of 3 clean releases since"
    )


def test_s083_7_text_names_the_zone_and_its_reason(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    reads = FakeReads()
    raised_app(repo, ASK, reads, "v1.4.1")
    assert main(["--repo", str(repo.root), "decide", "classify", "--files", "src/app/a.py"], record_reads=reads) == 0
    assert capsys.readouterr().out == (
        "level: ask\n"
        "zone: area-record at ask: src/app is raised: v1.4.0 failed in production (#212), 1 of 3 clean releases"
        " since\n"
    )


def test_s083_7_no_zone_for_a_cleared_area_or_an_area_with_no_record(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    reads = FakeReads()
    raised_app(repo, ASK, reads, "v1.4.1", "v1.4.3", "v1.4.4")
    assert zones(classify(repo, capsys, reads, "--files", "src/app/a.py")) == {}  # cleared
    assert zones(classify(repo, capsys, reads, "--files", "src/lib/b.py")) == {}  # no record
    assert set(zones(classify(repo, capsys, reads, "--files", "docs/notes.md"))) == {"area-record"}  # still raised
