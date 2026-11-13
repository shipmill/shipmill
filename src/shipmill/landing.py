"""doctor's `landing` row (spec 054): whether the rules on the default branch, and on
release/<series> with a hotfix lane, refuse the pushes land makes, read with the person's gh"""

import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from shipmill import cli_command
from shipmill.errors import ReleaseError

ROW = "landing"
ACTIONS_ID = 15368  # the GitHub Actions integration, the workflow token's App
ACTIONS_BOT = "github-actions[bot]"
ENVIRONMENT = "shipmill-land"  # the environment the opt-in names by default
SECRET = "SHIPMILL_LAND_KEY"  # the environment's secret holding the App's private key
INTEGRATION = "Integration"  # a ruleset bypass actor that is an App
ALWAYS = "always"  # the bypass_mode that lets a push past the rules
# a ruleset's rule types that refuse land's push of an existing branch; `creation` refuses a new one
REFUSING = ("pull_request", "required_status_checks", "required_signatures", "required_deployments", "update")
CREATION = "creation"
_OPT_IN = re.compile(r"^[ \t]+land-environment:[ \t]*(?P<value>[^#\n]*?)[ \t]*(?:#.*)?$", re.MULTILINE)
_HTTP = re.compile(r"\bHTTP (\d{3})\b")


class Unreadable(ReleaseError):
    """A read GitHub answered 403 or 404: a login without admin, or no such thing"""


@dataclass(frozen=True, slots=True)
class Classic:
    """A branch's classic protection: exists says the branch is on GitHub, body is the
    protection, None when the branch has none"""

    exists: bool
    body: Mapping[str, Any] | None


class RulesReader(Protocol):
    """What the landing row reads, with the person's gh; each raises Unreadable on a 403 or a
    404, another ReleaseError when gh fails otherwise"""

    def branch_rules(self, repo: str, branch: str) -> Sequence[Mapping[str, Any]]:
        """GET repos/<repo>/rules/branches/<branch>: every active rule on the branch"""
        ...

    def ruleset(self, repo: str, ruleset_id: int) -> Mapping[str, Any]:
        """GET repos/<repo>/rulesets/<id>: its conditions, rules, and bypass actors"""
        ...

    def rulesets(self, repo: str) -> Sequence[Mapping[str, Any]]:
        """GET repos/<repo>/rulesets: the repository's rulesets, its organization's included"""
        ...

    def protection(self, repo: str, branch: str) -> Classic:
        """GET repos/<repo>/branches/<branch>/protection"""
        ...


ReadRuleset = Callable[[int], Mapping[str, Any]]  # a ruleset by id, each read once per run


class GhRules:
    """RulesReader through the person's gh"""

    def __init__(self, root: Path, gh: str = "gh") -> None:
        self.root = root
        self.gh = gh

    def _api(self, path: str) -> Any:
        proc = subprocess.run(
            [self.gh, "api", path], capture_output=True, text=True, encoding="utf-8", cwd=self.root, check=False
        )
        if proc.returncode != 0:
            message = proc.stderr.strip()[:300]
            status = _HTTP.search(proc.stderr)
            if status is not None and int(status[1]) in {403, 404}:
                raise Unreadable(f"GET {path} answered {status[1]}: {message}")
            raise ReleaseError(f"gh api {path} failed: {message}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise ReleaseError(f"gh api {path} printed no JSON") from None

    def _list(self, path: str) -> Sequence[Mapping[str, Any]]:
        found = self._api(path)
        if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
            raise ReleaseError(f"gh api {path} printed something other than a list of objects")
        return found

    def branch_rules(self, repo: str, branch: str) -> Sequence[Mapping[str, Any]]:
        return self._list(f"repos/{repo}/rules/branches/{branch}?per_page=100")

    def ruleset(self, repo: str, ruleset_id: int) -> Mapping[str, Any]:
        found = self._api(f"repos/{repo}/rulesets/{ruleset_id}")
        if not isinstance(found, dict):
            raise ReleaseError(f"gh api repos/{repo}/rulesets/{ruleset_id} printed something other than an object")
        return found

    def rulesets(self, repo: str) -> Sequence[Mapping[str, Any]]:
        return self._list(f"repos/{repo}/rulesets?per_page=100")

    def protection(self, repo: str, branch: str) -> Classic:
        path = f"repos/{repo}/branches/{branch}/protection"
        try:
            found = self._api(path)
        except Unreadable as exc:  # GitHub's 404 tells an unprotected or a missing branch by its message
            if "Branch not protected" in str(exc):
                return Classic(True, None)
            if "Branch not found" in str(exc):
                return Classic(False, None)
            raise
        if not isinstance(found, dict):
            raise ReleaseError(f"gh api {path} printed something other than an object")
        return Classic(True, found)


@dataclass(frozen=True, slots=True)
class Identity:
    """Who pushes land's branches: the App under the opt-in, github-actions[bot] without it"""

    app_id: int
    name: str
    opted_in: bool


def land_environment(caller: str) -> str | None:
    """The environment the release workflow's land job names with `land-environment`, the
    opt-in (spec 054); None when it sets none or sets it empty. A text check, not a YAML parse"""
    for found in _OPT_IN.finditer(caller):
        value = found["value"].strip().strip("'\"")
        if value:
            return value
    return None


def ref_matches(pattern: str, ref: str) -> bool:
    """Whether a ruleset's ref_name pattern matches ref: ~ALL matches every ref, ** any path,
    * and ? one segment's characters, as GitHub's fnmatch does"""
    if pattern == "~ALL":
        return True
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    wild = {"**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.fullmatch("".join(wild.get(p, re.escape(p)) for p in parts), ref) is not None


def _bypasses(actors: Sequence[Mapping[str, Any]], app_id: int) -> str | None:
    """The bypass_mode the list gives the App, or None when it doesn't list it"""
    for actor in actors:
        if actor.get("actor_type") == INTEGRATION and actor.get("actor_id") == app_id:
            return str(actor.get("bypass_mode"))
    return None


def _apps(allowances: object) -> set[int]:
    """The App ids a classic protection's bypass allowances or push restrictions name"""
    if not isinstance(allowances, Mapping):
        return set()
    apps = allowances.get("apps")
    if not isinstance(apps, list):
        return set()
    return {a["id"] for a in apps if isinstance(a, Mapping) and isinstance(a.get("id"), int)}


def classic_refusals(body: Mapping[str, Any], app_id: int) -> list[str]:
    """The parts of a classic protection that refuse a push by the App app_id: required reviews
    unless its pull request bypass allowances name it, required status checks, required
    signatures, and push restrictions unless they name it"""
    refusing = []
    reviews = body.get("required_pull_request_reviews")
    if isinstance(reviews, Mapping) and app_id not in _apps(reviews.get("bypass_pull_request_allowances")):
        refusing.append("required reviews")
    if isinstance(body.get("required_status_checks"), Mapping):
        refusing.append("required status checks")
    signatures = body.get("required_signatures")
    if isinstance(signatures, Mapping) and signatures.get("enabled") is True:
        refusing.append("required signatures")
    restrictions = body.get("restrictions")
    if isinstance(restrictions, Mapping) and app_id not in _apps(restrictions):
        refusing.append("push restrictions")
    return refusing


@dataclass(frozen=True, slots=True)
class Branch:
    name: str
    release: bool  # release/<series>, whose first hotfix creates it


@dataclass(frozen=True, slots=True)
class Landing:
    """What the row checks: the branches land pushes, the next release tag's ref, and the
    release workflow's opt-in with the config's [agents] app_id"""

    repo: str | None
    default_branch: str
    branches: tuple[Branch, ...]
    next_tag: str
    environment: str | None  # the release workflow's land-environment, the opt-in
    app_id: int | None


def _fix(landing: Landing, who: Identity, ruleset: str | None) -> str:
    ruleset_cmd = f"`{cli_command()} ruleset`"
    if who.opted_in:
        if ruleset is None:
            return (
                f"fix: replace the classic protection with a ruleset that lists the App {who.app_id} as a bypass"
                f" actor; {ruleset_cmd} prints one"
            )
        return (
            f"fix: add the App {who.app_id} to {ruleset}'s bypass list as an {INTEGRATION} actor with"
            f" bypass_mode {ALWAYS}"
        )
    return (
        "fix: land as the App: install an App, set [agents] app_id in .github/shipmill.toml, create the environment"
        f" {ENVIRONMENT} limited to {landing.default_branch} with the App's private key as its secret {SECRET},"
        f" add `land-environment: {ENVIRONMENT}` to the land job in .github/workflows/release.yml, and add the App"
        f" to the bypass list; {ruleset_cmd} prints the ruleset"
    )


def landing_checks(landing: Landing, reader: RulesReader | None) -> list[tuple[str, str]]:
    """The row's (status, detail) pairs (spec 054): per branch, a PASS when no rule refuses
    land's push or the landing identity bypasses each, a FAIL per ruleset or classic
    protection that refuses it, a WARN per read that failed; a WARN for an active tag ruleset
    matching the next release tag that doesn't bypass github-actions[bot]. A FAIL alone when the
    release workflow opts in and the config sets no [agents] app_id. reader None: no gh"""
    if landing.environment is not None and landing.app_id is None:
        detail = (
            f"the land job in .github/workflows/release.yml sets land-environment: {landing.environment}, so land"
            " pushes as the App, but the config sets no [agents] app_id: set [agents] app_id in"
            " .github/shipmill.toml to the App's id, or drop land-environment"
        )
        return [("FAIL", detail)]
    unread = "landing may be refused"
    if reader is None:
        return [("WARN", f"can't read the branch rules and their bypass lists: gh isn't installed; {unread}")]
    if landing.repo is None:
        return [("WARN", f"can't read the branch rules: this checkout's origin isn't a GitHub repo; {unread}")]
    repo = landing.repo
    if landing.environment is not None and landing.app_id is not None:
        who = Identity(landing.app_id, f"the App {landing.app_id}", True)
    else:
        who = Identity(ACTIONS_ID, ACTIONS_BOT, False)
    rows: list[tuple[str, str]] = []
    rulesets: dict[int, Mapping[str, Any]] = {}

    def ruleset(ruleset_id: int) -> Mapping[str, Any]:
        if ruleset_id not in rulesets:
            rulesets[ruleset_id] = reader.ruleset(repo, ruleset_id)
        return rulesets[ruleset_id]

    for branch in landing.branches:
        rows.extend(_branch(landing, branch, who, reader, ruleset))
    rows.extend(_tags(landing, reader, ruleset))
    return rows


def _branch(
    landing: Landing, branch: Branch, who: Identity, reader: RulesReader, ruleset: ReadRuleset
) -> list[tuple[str, str]]:
    repo, name = landing.repo or "", branch.name
    unread = "landing may be refused there"
    warns: list[tuple[str, str]] = []
    fails: list[tuple[str, str]] = []
    passed: list[str] = []
    try:
        classic = reader.protection(repo, name)
    except ReleaseError as exc:
        warns.append(("WARN", f"can't read {name}'s classic protection: {exc}; {unread}"))
        classic = None
    try:
        rules = reader.branch_rules(repo, name)
    except ReleaseError as exc:
        warns.append(("WARN", f"can't read {name}'s rules: {exc}; {unread}"))
        rules = []
    refusing = REFUSING + ((CREATION,) if branch.release and classic is not None and not classic.exists else ())
    by_ruleset: dict[int, list[str]] = {}
    for rule in rules:
        kind, ruleset_id = rule.get("type"), rule.get("ruleset_id")
        if kind in refusing and isinstance(ruleset_id, int) and kind not in by_ruleset.setdefault(ruleset_id, []):
            by_ruleset[ruleset_id].append(str(kind))
    for ruleset_id, kinds in sorted(by_ruleset.items()):
        try:
            found = ruleset(ruleset_id)
        except ReleaseError as exc:
            warns.append(("WARN", f"can't read the bypass list of ruleset {ruleset_id} on {name}: {exc}; {unread}"))
            continue
        label = f"ruleset {found.get('name', ruleset_id)!r} ({ruleset_id})"
        actors = found.get("bypass_actors")
        if not isinstance(actors, list):
            detail = (
                f"can't read {label}'s bypass list on {name}: GitHub's answer has none (a login without admin);"
                f" {unread}"
            )
            warns.append(("WARN", detail))
            continue
        mode = _bypasses(actors, who.app_id)
        if mode == ALWAYS:
            passed.append(label)
            continue
        listed = "" if mode is None else f" (it lists {who.name} with bypass_mode {mode})"
        detail = (
            f"{name}: {label} has the rules {', '.join(kinds)}, and its bypass list doesn't name {who.name} with"
            f" bypass_mode {ALWAYS}{listed}, so land's push is refused; {_fix(landing, who, label)}"
        )
        fails.append(("FAIL", detail))
    if classic is not None and classic.body is not None:
        parts = classic_refusals(classic.body, who.app_id)
        if parts:
            detail = (
                f"{name}: classic branch protection has {', '.join(parts)}, which refuse {who.name}'s push;"
                f" {_fix(landing, who, None)}"
            )
            fails.append(("FAIL", detail))
        elif any(isinstance(classic.body.get(k), Mapping) for k in ("required_pull_request_reviews", "restrictions")):
            passed.append("classic branch protection")  # its allowances name the identity
    if fails or warns:
        return fails + warns
    if not passed:
        return [("PASS", f"{name} has no rule that refuses landing's push")]
    return [("PASS", f"{name}: {who.name} bypasses every rule that refuses landing's push, in {', '.join(passed)}")]


def _tags(landing: Landing, reader: RulesReader, ruleset: ReadRuleset) -> list[tuple[str, str]]:
    """S-054-16: a WARN per active tag ruleset whose include matches the next release tag and
    whose bypass list doesn't name the GitHub Actions integration with bypass_mode always"""
    repo, ref = landing.repo or "", f"refs/tags/{landing.next_tag}"
    try:
        listed = reader.rulesets(repo)
    except ReleaseError as exc:
        return [("WARN", f"can't read the tag rulesets: {exc}; the tag push may be refused")]
    rows = []
    for item in listed:
        ruleset_id = item.get("id")
        if item.get("target") != "tag" or item.get("enforcement") != "active" or not isinstance(ruleset_id, int):
            continue
        try:
            found = ruleset(ruleset_id)
        except ReleaseError as exc:
            rows.append(("WARN", f"can't read tag ruleset {ruleset_id}: {exc}; the tag push may be refused"))
            continue
        label = f"tag ruleset {found.get('name', ruleset_id)!r} ({ruleset_id})"
        conditions = found.get("conditions")
        names = conditions.get("ref_name") if isinstance(conditions, Mapping) else None
        include = names.get("include", []) if isinstance(names, Mapping) else []
        exclude = names.get("exclude", []) if isinstance(names, Mapping) else []
        if not any(ref_matches(str(p), ref) for p in include) or any(ref_matches(str(p), ref) for p in exclude):
            continue
        actors = found.get("bypass_actors")
        if not isinstance(actors, list):
            detail = (
                f"can't read {label}'s bypass list: GitHub's answer has none (a login without admin), and it"
                f" matches {ref}, so the tag push may be refused"
            )
            rows.append(("WARN", detail))
            continue
        if _bypasses(actors, ACTIONS_ID) == ALWAYS:
            continue
        detail = (
            f"{label} matches {ref} and its bypass list doesn't name {ACTIONS_BOT}, which pushes the release tag,"
            f" so the tag push may be refused; add the GitHub Actions integration ({ACTIONS_ID}) to its bypass"
            f" list with bypass_mode {ALWAYS}, or narrow its include"
        )
        rows.append(("WARN", detail))
    return rows
