"""Spec 083's production record of an area: `shipmill decide record`"""

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.github import AuthoredIssue, Deployment, DeploymentState, DeploymentStatus, Issue, authored_of

from .conftest import POLICY, Repo, at_day

LINE = "<!-- shipmill:incident env=production tag=v1.4.0 to=v1.3.2 state=rolled-back -->"


@dataclass
class FakeReads:
    issues: list[AuthoredIssue] = field(default_factory=list)
    envs: dict[str, list[Deployment]] = field(default_factory=dict)  # newest first
    statuses: dict[int, list[DeploymentStatus]] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)  # each authored_issues call's label
    env_reads: list[str] = field(default_factory=list)

    def authored_issues(self, label: str) -> list[AuthoredIssue]:
        self.labels.append(label)
        return sorted(self.issues, key=lambda a: -a.issue.number)

    def deployments(self, environment: str) -> list[Deployment]:
        self.env_reads.append(environment)
        return list(self.envs.get(environment, []))

    def deployment_statuses(self, deployment: int) -> list[DeploymentStatus]:
        return list(self.statuses[deployment])

    def incident(self, number: int, body: str, *, bot: bool = True, association: str = "NONE") -> None:
        self.issues.append(AuthoredIssue(Issue(number, f"Incident #{number}", body), bot, association))

    def deploy(self, env: str, tag: str, *states: DeploymentState) -> None:
        number = 1000 + sum(len(d) for d in self.envs.values())
        self.envs.setdefault(env, []).insert(0, Deployment(number, tag, "0" * 40, at_day(1)))
        self.statuses[number] = [
            DeploymentStatus(number * 10 + i, state, at_day(1), "") for i, state in enumerate(states)
        ]


def release(repo: Repo, tag: str, when: dt.datetime, **files: str) -> None:
    """Commit the files on main and tag the commit, the tag created at when"""
    repo.at(when)
    for path, text in files.items():
        repo.write(path, text)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "--allow-empty", "-m", f"Release {tag}")
    repo.git.run("tag", "-a", tag, "-m", tag)


def tag_at(repo: Repo, tag: str, rev: str, when: dt.datetime) -> None:
    repo.at(when)
    repo.git.run("tag", "-a", tag, rev, "-m", tag)


def history(repo: Repo) -> None:
    """v1.3.2 changes src/web, v1.4.0 changes src/app and docs; the failed release's diff
    from v1.3.2 is src/app/a.py and docs/notes.md"""
    release(repo, "v1.3.2", at_day(-3), **{"src/web/c.py": "C = 1\n", "src/lib/b.py": "B = 1\n"})
    release(repo, "v1.4.0", at_day(-2), **{"src/app/a.py": "A = 1\n", "docs/notes.md": "notes\n"})


def record(repo: Repo, reads: FakeReads, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "decide", "record", "--json"], record_reads=reads) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def text(repo: Repo, reads: FakeReads, capsys: pytest.CaptureFixture[str]) -> str:
    assert main(["--repo", str(repo.root), "decide", "record"], record_reads=reads) == 0
    return capsys.readouterr().out


def areas(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a["area"]: a for a in found["areas"]}


# -- S-083-4: what a failed release raises -----------------------------------------------------


def test_s083_4_a_bots_incident_raises_the_parent_directories_of_its_diff(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    history(repo)
    reads = FakeReads()
    reads.incident(212, f"Production fails its checks.\n\n{LINE}\n")
    found = record(repo, reads, capsys)
    assert reads.labels == ["incident"]
    assert found["clean_releases"] == 3
    assert sorted(areas(found)) == ["docs", "src/app"]  # src/web and src/lib changed before v1.3.2
    assert areas(found)["src/app"] == {
        "area": "src/app",
        "state": "raised",
        "incident": 212,
        "env": "production",
        "tag": "v1.4.0",
        "clean": [],
    }


def test_s083_4_a_file_at_the_root_raises_the_root_area(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    release(repo, "v1.3.2", at_day(-3))
    release(repo, "v1.4.0", at_day(-2), **{"setup.cfg": "[x]\n"})
    reads = FakeReads()
    reads.incident(212, LINE)
    assert sorted(areas(record(repo, reads, capsys))) == ["."]


def test_s083_4_to_dash_diffs_from_the_newest_earlier_tag_by_version_not_by_date(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    release(repo, "v1.3.1", at_day(-5), **{"src/lib/b.py": "B = 1\n"})
    release(repo, "v1.3.9", at_day(-5), **{"src/web/c.py": "C = 1\n"})
    web = repo.git.sha()
    repo.git.run("tag", "-d", "v1.3.9")
    release(repo, "v1.4.0", at_day(-4), **{"src/app/a.py": "A = 1\n"})
    tag_at(repo, "v1.3.10", web, at_day(-1))  # tagged after v1.4.0, and 1.3.10 > 1.3.9 > 1.3.1
    reads = FakeReads()
    reads.incident(212, LINE.replace("to=v1.3.2", "to=-"))
    # by date the tag before v1.4.0 is v1.3.1, whose diff would hold src/web too
    assert sorted(areas(record(repo, reads, capsys))) == ["src/app"]


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR"])
def test_s083_4_the_same_issue_by_an_untrusted_person_raises_nothing(
    repo: Repo, capsys: pytest.CaptureFixture[str], association: str
) -> None:
    history(repo)
    reads = FakeReads()
    reads.incident(212, LINE, bot=False, association=association)
    assert record(repo, reads, capsys) == {"clean_releases": 3, "areas": []}
    reads.labels.clear()
    assert text(repo, reads, capsys) == "no failed release on record\n"
    assert reads.env_reads == []  # no incident counts: no deployment is read


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_s083_4_a_trusted_persons_incident_counts(
    repo: Repo, capsys: pytest.CaptureFixture[str], association: str
) -> None:
    history(repo)
    reads = FakeReads()
    reads.incident(212, LINE, bot=False, association=association)
    assert sorted(areas(record(repo, reads, capsys))) == ["docs", "src/app"]


def test_s083_4_an_incident_without_the_line_raises_nothing(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    history(repo)
    reads = FakeReads()
    reads.incident(212, "Production is down after v1.4.0, rolled back to v1.3.2.")
    assert text(repo, reads, capsys) == "no failed release on record\n"


def test_s083_4_a_trusted_incident_whose_line_doesnt_read_exits_2_and_an_untrusted_one_is_skipped(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    history(repo)
    broken = "<!-- shipmill:incident env=production tag=v1.4.0 state=rolled-back -->"
    reads = FakeReads()
    reads.incident(212, broken, bot=False, association="NONE")
    assert text(repo, reads, capsys) == "no failed release on record\n"
    reads.incident(213, broken)
    with pytest.raises(ReleaseError, match=r"incident #213 holds a shipmill:incident line that doesn't read"):
        main(["--repo", str(repo.root), "decide", "record"], record_reads=reads)
    assert capsys.readouterr().out == ""


def test_s083_4_a_tag_the_checkout_lacks_exits_2_naming_it(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    history(repo)
    reads = FakeReads()
    reads.incident(212, LINE.replace("tag=v1.4.0", "tag=v1.5.0"))
    with pytest.raises(ReleaseError, match=r"incident #212 names v1\.5\.0, which the checkout lacks"):
        main(["--repo", str(repo.root), "decide", "record", "--json"], record_reads=reads)
    assert capsys.readouterr().out == ""


def test_s083_4_the_incident_label_comes_from_operate(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.write(str(CONFIG_PATH), POLICY + '\n[operate]\nincident_label = "outage"\n')
    reads = FakeReads()
    record(repo, reads, capsys)
    assert reads.labels == ["outage"]


def test_s083_4_gh_lists_issues_with_their_authors_and_skips_pull_requests() -> None:
    listed = [
        {
            "number": 212,
            "title": "Incident",
            "body": LINE,
            "user": {"login": "shipmill[bot]", "type": "Bot"},
            "author_association": "NONE",
            "closed_at": None,
        },
        {
            "number": 213,
            "title": "A pull request",
            "body": None,
            "user": {"login": "x", "type": "User"},
            "author_association": "NONE",
            "pull_request": {},
        },
        {
            "number": 180,
            "title": "Old",
            "body": None,
            "user": {"login": "maintainer", "type": "User"},
            "author_association": "OWNER",
            "closed_at": "2026-10-01T00:00:00Z",
        },
    ]
    found = authored_of(listed)
    assert [(a.issue.number, a.bot, a.association, a.issue.body, a.issue.closed) for a in found] == [
        (212, True, "NONE", LINE, False),
        (180, False, "OWNER", "", True),
    ]
    with pytest.raises(ReleaseError, match="without a number, title, body, author, and association"):
        authored_of([{"number": 1, "title": "x", "body": "", "user": None, "author_association": "OWNER"}])


# -- S-083-5: raised until clean releases clear it ---------------------------------------------


def later(repo: Repo) -> None:
    """After the failed v1.4.0: v1.4.1 touches src/app, v1.4.2 docs only, v1.4.3 src/app,
    v1.4.4 src/app, v1.4.5 src/app"""
    release(repo, "v1.4.1", at_day(-1, 1), **{"src/app/a.py": "A = 2\n"})
    release(repo, "v1.4.2", at_day(-1, 2), **{"docs/more.md": "more\n"})
    release(repo, "v1.4.3", at_day(-1, 3), **{"src/app/a.py": "A = 3\n"})
    release(repo, "v1.4.4", at_day(-1, 4), **{"src/app/a.py": "A = 4\n"})
    release(repo, "v1.4.5", at_day(-1, 5), **{"src/app/a.py": "A = 5\n"})


S, F = DeploymentState.SUCCESS, DeploymentState.FAILURE


def test_s083_5_one_clean_release_that_touched_the_area_reads_raised_1_of_3(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    history(repo)
    later(repo)
    reads = FakeReads()
    reads.incident(212, LINE)
    reads.deploy("production", "v1.4.0", S, F)
    reads.deploy("production", "v1.4.1", DeploymentState.IN_PROGRESS, S)
    reads.deploy("production", "v1.4.2", S)  # touched docs, not src/app
    reads.deploy("production", "v1.4.3", DeploymentState.IN_PROGRESS, F)  # never reached success
    reads.deploy("staging", "v1.4.4", S)  # reached success, but not in production
    found = record(repo, reads, capsys)
    assert areas(found)["src/app"]["state"] == "raised"
    assert areas(found)["src/app"]["clean"] == ["v1.4.1"]
    assert areas(found)["docs"]["clean"] == ["v1.4.2"]
    assert text(repo, reads, capsys) == (
        "RAISED  docs  v1.4.0 failed in production (#212), 1 of 3 clean releases since (v1.4.2)\n"
        "RAISED  src/app  v1.4.0 failed in production (#212), 1 of 3 clean releases since (v1.4.1)\n"
    )


def test_s083_5_three_clean_releases_clear_the_area_and_raised_areas_come_first(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    history(repo)
    later(repo)
    reads = FakeReads()
    reads.incident(212, LINE)
    for tag in ("v1.4.1", "v1.4.2", "v1.4.3", "v1.4.4", "v1.4.5"):
        reads.deploy("production", tag, S)
    found = record(repo, reads, capsys)
    assert areas(found)["src/app"]["state"] == "cleared"
    assert areas(found)["src/app"]["clean"] == ["v1.4.1", "v1.4.3", "v1.4.4"]  # the first three
    assert text(repo, reads, capsys) == (
        "RAISED  docs  v1.4.0 failed in production (#212), 1 of 3 clean releases since (v1.4.2)\n"
        "CLEARED src/app  v1.4.0 failed in production (#212), 3 of 3 clean releases since (v1.4.1, v1.4.3, v1.4.4)\n"
    )


def test_s083_5_a_later_tag_with_its_own_incident_is_not_counted(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    history(repo)
    later(repo)
    reads = FakeReads()
    reads.incident(212, LINE)
    for tag in ("v1.4.1", "v1.4.3", "v1.4.4", "v1.4.5"):
        reads.deploy("production", tag, S)
    own = "<!-- shipmill:incident env=staging tag=v1.4.3 to=- state=failing -->"
    reads.incident(230, own, bot=False, association="NONE")  # untrusted: counts for nothing
    assert areas(record(repo, reads, capsys))["src/app"]["clean"] == ["v1.4.1", "v1.4.3", "v1.4.4"]
    reads.incident(231, own)
    app = areas(record(repo, reads, capsys))["src/app"]
    # v1.4.3 failed in staging: the area's newest failed release, never one of its clean ones
    assert (app["tag"], app["env"], app["incident"], app["state"]) == ("v1.4.3", "staging", 231, "raised")
    assert "v1.4.3" not in app["clean"]
    reads.deploy("staging", "v1.4.3", S)
    reads.deploy("staging", "v1.4.5", S)
    app = areas(record(repo, reads, capsys))["src/app"]
    assert app["clean"] == ["v1.4.5"]  # v1.4.4 reached success in production, not in staging


def test_s083_5_clean_releases_1_clears_the_area_after_one(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.write(str(CONFIG_PATH), POLICY + "\n[decisions]\nclean_releases = 1\n")
    history(repo)
    later(repo)
    reads = FakeReads()
    reads.incident(212, LINE)
    reads.deploy("production", "v1.4.1", S)
    found = record(repo, reads, capsys)
    assert found["clean_releases"] == 1
    assert (areas(found)["src/app"]["state"], areas(found)["src/app"]["clean"]) == ("cleared", ["v1.4.1"])
    assert "CLEARED src/app  v1.4.0 failed in production (#212), 1 of 1 clean releases since (v1.4.1)\n" in text(
        repo, reads, capsys
    )
