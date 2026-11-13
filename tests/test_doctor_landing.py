"""Spec 054's landing row in shipmill doctor: the rules that refuse land's push, read through a
fake reader, no network (S-054-10 to S-054-16)"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill import cli_command
from shipmill.doctor import CALLER, Check, doctor
from shipmill.errors import ReleaseError
from shipmill.landing import ACTIONS_BOT, ACTIONS_ID, Classic, GhRules, Unreadable, ref_matches

from .conftest import POLICY, Repo

REPO = "o/demo"
APP = 42
CALLER_TEXT = """\
jobs:
  prepare:
    uses: shipmill/shipmill/.github/workflows/prepare.yml@v0
  land:
    uses: shipmill/shipmill/.github/workflows/land.yml@v0
    with:
      tag: v1
"""
OPTED_IN = CALLER_TEXT + "      land-environment: shipmill-land\n"
WITH_APP = POLICY + f'\n[agents]\nprompt = "/t"\napp_id = {APP}\n'
NOT_PROTECTED = Classic(True, None)


@dataclass
class FakeRules:
    """RulesReader over fixed answers: a ReleaseError value is raised"""

    rules: dict[str, list[dict[str, Any]] | ReleaseError] = field(default_factory=dict)
    sets: dict[int, dict[str, Any] | ReleaseError] = field(default_factory=dict)
    listed: list[dict[str, Any]] | ReleaseError = field(default_factory=list)
    classic: dict[str, Classic | ReleaseError] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)

    def branch_rules(self, repo: str, branch: str) -> Sequence[Mapping[str, Any]]:
        self.reads.append(f"rules {branch}")
        found = self.rules.get(branch, [])
        if isinstance(found, ReleaseError):
            raise found
        return found

    def ruleset(self, repo: str, ruleset_id: int) -> Mapping[str, Any]:
        self.reads.append(f"ruleset {ruleset_id}")
        found = self.sets[ruleset_id]
        if isinstance(found, ReleaseError):
            raise found
        return found

    def rulesets(self, repo: str) -> Sequence[Mapping[str, Any]]:
        self.reads.append("rulesets")
        if isinstance(self.listed, ReleaseError):
            raise self.listed
        return self.listed

    def protection(self, repo: str, branch: str) -> Classic:
        self.reads.append(f"protection {branch}")
        found = self.classic.get(branch, NOT_PROTECTED)
        if isinstance(found, ReleaseError):
            raise found
        return found


def rule(kind: str, ruleset_id: int) -> dict[str, Any]:
    return {"type": kind, "ruleset_id": ruleset_id, "ruleset_source_type": "Organization"}


def ruleset(
    name: str, *actors: tuple[int, str], target: str = "branch", include: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "name": name,
        "target": target,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": list(include), "exclude": []}},
        "bypass_actors": [{"actor_id": i, "actor_type": "Integration", "bypass_mode": m} for i, m in actors],
    }


def landing(repo: Repo, reader: FakeRules | None, caller: str = CALLER_TEXT, config: str = POLICY) -> list[Check]:
    repo.write(str(CALLER), caller)
    repo.write(repo.policy_file, config)
    return [c for c in doctor(repo.root, repo.github, repo=REPO, rules=lambda: reader) if c.name == "landing"]


def test_s054_10_no_refusing_rule_passes(repo: Repo) -> None:
    reader = FakeRules(rules={"main": [rule("deletion", 1), rule("non_fast_forward", 1)]})
    rows = landing(repo, reader)
    assert [(c.status, c.detail) for c in rows] == [
        ("PASS", "main has no rule that refuses landing's push"),
        ("PASS", "release/1.0 has no rule that refuses landing's push"),
    ]
    assert "ruleset 1" not in reader.reads  # a ruleset with no refusing rule isn't read


def test_s054_10_the_row_shows_only_where_land_pushes(repo: Repo) -> None:
    assert landing(repo, FakeRules(), config=POLICY.replace('mode = "release"', 'mode = "off"')) == []
    repo.write(repo.policy_file, POLICY)
    (repo.root / CALLER).unlink()  # no release workflow, no row (D-9)
    assert [c for c in doctor(repo.root, repo.github, repo=REPO, rules=FakeRules) if c.name == "landing"] == []


def test_s054_11_a_ruleset_without_the_actions_bypass_fails_naming_the_opt_in(repo: Repo) -> None:
    reader = FakeRules(
        rules={"main": [rule("pull_request", 7), rule("required_status_checks", 7), rule("deletion", 7)]},
        sets={7: ruleset("protect main")},
    )
    [main, release] = landing(repo, reader)
    assert main.status == "FAIL"
    assert main.detail.startswith(
        "main: ruleset 'protect main' (7) has the rules pull_request, required_status_checks, and its bypass list"
        f" doesn't name {ACTIONS_BOT} with bypass_mode always, so land's push is refused; fix: land as the App:"
    )
    for needle in (
        "[agents] app_id",
        "SHIPMILL_LAND_KEY",
        "land-environment: shipmill-land",
        f"`{cli_command()} ruleset`",
    ):
        assert needle in main.detail, needle
    assert release.status == "PASS"


def test_s054_11_the_actions_integration_with_always_passes(repo: Repo) -> None:
    reader = FakeRules(
        rules={"main": [rule("pull_request", 7)]}, sets={7: ruleset("protect main", (ACTIONS_ID, "always"))}
    )
    assert [(c.status, c.detail) for c in landing(repo, reader)][0] == (
        "PASS",
        f"main: {ACTIONS_BOT} bypasses every rule that refuses landing's push, in ruleset 'protect main' (7)",
    )


def test_s054_12_with_the_opt_in_the_app_must_bypass_each_ruleset_always(repo: Repo) -> None:
    reader = FakeRules(
        rules={"main": [rule("pull_request", 7), rule("required_status_checks", 8), rule("update", 9)]},
        sets={
            7: ruleset("org rules", (APP, "always")),
            8: ruleset("checks", (APP, "pull_request")),
            9: ruleset("frozen", (ACTIONS_ID, "always")),
        },
    )
    rows = landing(repo, reader, OPTED_IN, WITH_APP)
    fails = [c.detail for c in rows if c.status == "FAIL"]
    assert len(fails) == 2
    assert fails[0].startswith(
        "main: ruleset 'checks' (8) has the rules required_status_checks, and its bypass list doesn't name"
        f" the App {APP} with bypass_mode always (it lists the App {APP} with bypass_mode pull_request)"
    )
    assert fails[0].endswith(
        f"fix: add the App {APP} to ruleset 'checks' (8)'s bypass list as an Integration actor with bypass_mode always"
    )
    assert fails[1].startswith(
        f"main: ruleset 'frozen' (9) has the rules update, and its bypass list doesn't name the App {APP}"
    )
    assert "'org rules'" not in " ".join(fails)
    reader.sets[8] = ruleset("checks", (APP, "always"))
    reader.sets[9] = ruleset("frozen", (APP, "always"), (ACTIONS_ID, "always"))
    rows = landing(repo, reader, OPTED_IN, WITH_APP)
    assert rows[0] == Check(
        "PASS",
        "landing",
        f"main: the App {APP} bypasses every rule that refuses landing's push, in ruleset 'org rules' (7),"
        " ruleset 'checks' (8), ruleset 'frozen' (9)",
    )


def test_s054_13_release_series_is_read_with_a_hotfix_lane(repo: Repo) -> None:
    reader = FakeRules()
    landing(repo, reader)
    assert "rules release/1.0" in reader.reads and "protection release/1.0" in reader.reads
    without = POLICY.replace("[lanes.hotfix]\ngithub_release = true\n", "")
    reader = FakeRules()
    landing(repo, reader, config=without)
    assert not any("release/" in read for read in reader.reads)


def test_s054_13_creation_refuses_a_release_branch_github_hasnt_got(repo: Repo) -> None:
    reader = FakeRules(
        rules={"release/1.0": [rule("creation", 3)], "main": [rule("creation", 3)]},
        sets={3: ruleset("releases")},
        classic={"release/1.0": Classic(False, None)},
    )
    [main, release] = landing(repo, reader)
    assert main.status == "PASS"  # main exists: creation doesn't apply
    assert release.status == "FAIL" and release.detail.startswith(
        "release/1.0: ruleset 'releases' (3) has the rules creation"
    )


def test_s054_13_classic_protection_reports_its_refusing_parts(repo: Repo) -> None:
    body: dict[str, Any] = {
        "required_pull_request_reviews": {"bypass_pull_request_allowances": {"apps": []}},
        "required_status_checks": {"contexts": ["checks"]},
        "required_signatures": {"enabled": True},
        "restrictions": {"users": [], "teams": [], "apps": []},
        "enforce_admins": {"enabled": False},
    }
    reader = FakeRules(classic={"main": Classic(True, body)})
    [main, _] = landing(repo, reader)
    assert main.status == "FAIL"
    assert main.detail.startswith(
        "main: classic branch protection has required reviews, required status checks, required signatures,"
        f" push restrictions, which refuse {ACTIONS_BOT}'s push; fix: land as the App"
    )
    allowed = {"apps": [{"id": APP, "slug": "shipmill-app"}]}
    body["required_pull_request_reviews"] = {"bypass_pull_request_allowances": allowed}
    body["restrictions"] = allowed
    body["required_status_checks"] = None
    body["required_signatures"] = {"enabled": False}
    [main, _] = landing(repo, reader, OPTED_IN, WITH_APP)
    assert main == Check(
        "PASS",
        "landing",
        f"main: the App {APP} bypasses every rule that refuses landing's push, in classic branch protection",
    )


def test_s054_10_classic_protection_with_no_refusing_part_passes_as_no_rule(repo: Repo) -> None:
    body = {"allow_deletions": {"enabled": False}, "allow_force_pushes": {"enabled": False}}
    [main, _] = landing(repo, FakeRules(classic={"main": Classic(True, body)}))
    assert main == Check("PASS", "landing", "main has no rule that refuses landing's push")


def test_s054_14_no_gh_warns_and_every_other_row_prints(repo: Repo) -> None:
    repo.write(str(CALLER), CALLER_TEXT)
    without = doctor(repo.root, repo.github, repo=REPO)
    found = doctor(repo.root, repo.github, repo=REPO, rules=lambda: None)
    assert [c for c in found if c.name != "landing"] == without
    assert [c for c in found if c.name == "landing"] == [
        Check(
            "WARN",
            "landing",
            "can't read the branch rules and their bypass lists: gh isn't installed; landing may be refused",
        )
    ]


def test_s054_14_a_403_or_404_warns_naming_the_read(repo: Repo) -> None:
    reader = FakeRules(
        rules={
            "main": [rule("pull_request", 7)],
            "release/1.0": Unreadable("GET repos/o/demo/rules/branches/release/1.0 answered 403"),
        },
        sets={7: Unreadable("GET repos/o/demo/rulesets/7 answered 404: Not Found")},
        classic={"main": Unreadable("GET repos/o/demo/branches/main/protection answered 403")},
        listed=ReleaseError("gh api repos/o/demo/rulesets failed: HTTP 502"),
    )
    rows = [(c.status, c.detail) for c in landing(repo, reader)]
    there = "landing may be refused there"
    assert rows == [
        (
            "WARN",
            f"can't read main's classic protection: GET repos/o/demo/branches/main/protection answered 403; {there}",
        ),
        (
            "WARN",
            "can't read the bypass list of ruleset 7 on main: GET repos/o/demo/rulesets/7 answered 404: Not Found;"
            f" {there}",
        ),
        (
            "WARN",
            f"can't read release/1.0's rules: GET repos/o/demo/rules/branches/release/1.0 answered 403; {there}",
        ),
        (
            "WARN",
            "can't read the tag rulesets: gh api repos/o/demo/rulesets failed: HTTP 502; the tag push may be refused",
        ),
    ]


def test_s054_14_a_ruleset_answer_without_its_bypass_list_warns(repo: Repo) -> None:
    hidden = ruleset("org rules")
    del hidden["bypass_actors"]
    reader = FakeRules(rules={"main": [rule("pull_request", 7)]}, sets={7: hidden})
    [main, _] = landing(repo, reader)
    assert main.status == "WARN" and main.detail.startswith("can't read ruleset 'org rules' (7)'s bypass list on main")


def test_s054_15_the_opt_in_without_an_app_id_fails_naming_the_key(repo: Repo) -> None:
    reader = FakeRules()
    [row] = landing(repo, reader, OPTED_IN)
    assert row.status == "FAIL"
    assert "sets land-environment: shipmill-land" in row.detail and "no [agents] app_id" in row.detail
    assert reader.reads == []
    commented = CALLER_TEXT + "      # land-environment: shipmill-land\n"
    assert [c.status for c in landing(repo, FakeRules(), commented)] == ["PASS", "PASS"]
    empty = CALLER_TEXT + '      land-environment: ""\n'
    assert [c.status for c in landing(repo, FakeRules(), empty)] == ["PASS", "PASS"]


def test_s054_16_a_tag_ruleset_matching_the_next_tag_warns(repo: Repo) -> None:
    listed = [
        {"id": 20, "target": "tag", "enforcement": "active"},
        {"id": 21, "target": "tag", "enforcement": "active"},
        {"id": 22, "target": "tag", "enforcement": "evaluate"},
        {"id": 23, "target": "tag", "enforcement": "active"},
        {"id": 24, "target": "branch", "enforcement": "active"},
    ]
    reader = FakeRules(
        listed=listed,
        sets={
            20: ruleset("release tags", target="tag", include=("refs/tags/v*",)),
            21: ruleset("bypassed", (ACTIONS_ID, "always"), target="tag", include=("~ALL",)),
            22: ruleset("evaluated", target="tag", include=("~ALL",)),
            23: ruleset("other tags", target="tag", include=("refs/tags/docs-*",)),
        },
    )
    rows = landing(repo, reader)
    warns = [c.detail for c in rows if c.status == "WARN"]
    assert warns == [
        f"tag ruleset 'release tags' (20) matches refs/tags/v1.0.1 and its bypass list doesn't name {ACTIONS_BOT},"
        " which pushes the release tag, so the tag push may be refused; add the GitHub Actions integration"
        f" ({ACTIONS_ID}) to its bypass list with bypass_mode always, or narrow its include"
    ]
    assert "ruleset 22" not in reader.reads and "ruleset 24" not in reader.reads


def fake_gh(tmp_path: Path, stderr: str, code: int = 1, stdout: str = "") -> str:
    """A gh that prints the given answer whatever it's asked"""
    script = tmp_path / "gh"
    script.write_text(f"#!/bin/sh\nprintf '%s' '{stdout}'\nprintf '%s' '{stderr}' >&2\nexit {code}\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


# proves: S-054-14
def test_gh_rules_tells_an_unprotected_or_missing_branch_from_an_unreadable_one(tmp_path: Path) -> None:
    unprotected = GhRules(tmp_path, fake_gh(tmp_path, "gh: Branch not protected (HTTP 404)"))
    assert unprotected.protection(REPO, "main") == Classic(True, None)
    missing = GhRules(tmp_path, fake_gh(tmp_path, "gh: Branch not found (HTTP 404)"))
    assert missing.protection(REPO, "release/1.0") == Classic(False, None)
    forbidden = GhRules(tmp_path, fake_gh(tmp_path, "gh: Not Found (HTTP 404)"))
    with pytest.raises(Unreadable, match="answered 404"):
        forbidden.protection(REPO, "main")
    with pytest.raises(Unreadable, match="answered 404"):
        forbidden.branch_rules(REPO, "main")
    broken = GhRules(tmp_path, fake_gh(tmp_path, "gh: Server Error (HTTP 502)"))
    with pytest.raises(ReleaseError, match="failed") as raised:
        broken.ruleset(REPO, 7)
    assert not isinstance(raised.value, Unreadable)
    listed = GhRules(tmp_path, fake_gh(tmp_path, "", 0, '[{"type": "pull_request", "ruleset_id": 7}]'))
    assert listed.branch_rules(REPO, "main") == [{"type": "pull_request", "ruleset_id": 7}]


def test_ref_patterns_match_as_github_does() -> None:
    assert ref_matches("refs/tags/v*", "refs/tags/v1.0.1")
    assert not ref_matches("refs/tags/*", "refs/tags/a/b")
    assert ref_matches("refs/tags/**", "refs/tags/a/b")
    assert ref_matches("~ALL", "refs/tags/v1.0.1")
    assert not ref_matches("refs/tags/v?.0.1", "refs/tags/v10.0.1")
