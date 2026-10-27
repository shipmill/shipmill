#!/usr/bin/env python3
"""Report what a repo still needs before the shipmill skills can triage, land, and
release it on their own, and with --fix make the parts that need no decision.

Usage: setup_state.py <owner/repo> [--repo-dir PATH] [--fix] [--json]

Releases (.github/shipmill.toml):
  RELEASE_MISSING  no config with release keys: shipmill-setup's steps 1 to 5
  RELEASE_FOREIGN  a config, but .github/workflows/release.yml doesn't call shipmill's
                   workflows
  RELEASE_OFF      mode = "off"
  RELEASE_DRY_RUN  mode = "dry-run": run the Release workflow by hand, then the user
                   sets mode = "release"
  RELEASE_READY    mode = "release"

Agents (the config's [agents] section, read by `shipmill gate`):
  AGENTS_MISSING   no [agents] section: the gate has no prompt. Fine when agents run
                   only on demand
  AGENTS_NO_APP    a prompt but no app_id, in either mode: no App is connected, so
                   sessions write as the host's gh login (their PRs, comments, and
                   commits read as the user's, who can't approve them, and GitHub
                   won't notify them of a needs-decision mention). The gate still
                   runs; shipmill-setup's step 3 under The gate connects one (D-19).
                   --fix leaves it: it needs the user
  AGENTS_NO_MODE   a prompt and app_id but no mode key: the gate runs interactive by
                   default, but nobody chose it, so a machine nobody watches may hold
                   the repo on a question. shipmill-setup's step 4 under The gate asks
                   and writes mode = "interactive" or "headless" (D-20). --fix leaves it
  AGENTS_OK        a section with a prompt, app_id, and mode

The section reads as one row, the first that applies: AGENTS_MISSING, AGENTS_NO_APP,
AGENTS_NO_MODE, then AGENTS_OK. Setup asks for the App and the mode together, so the
one PR that sets app_id sets mode too. One more row follows it when it applies:
  AGENTS_UNPREFIXED  the prompt calls a shipmill skill as /<name>, not /shipmill:<name>: a
                   skill of that name in ~/.claude/skills or ~/.agents/skills answers it in
                   place of the plugin's (#236). The detail names the prefixed form to write.
                   --fix leaves it: the config changes through a pull request
And one more after it (spec 040):
  AUTONOMY_IMPLICIT  an [agents] section, but [autonomy] sets none of triage, fix, and
                   land: how far a session goes was never chosen, so it comes from the
                   defaults (or, for one minor release, from the prompt's words).
                   shipmill-setup's Autonomy step asks and writes all three. --fix leaves it

Product (spec 043: whether the repo is one of several that make up one product; one row,
after the agents rows, the first that applies):
  PRODUCT_LISTED   this repo has no [product], and a sibling's [product] repos lists it
                   (case ignored): the detail names the sibling and the home = "<sibling>"
                   line to write, both when two list it. --fix leaves it
  PRODUCT_SIBLINGS this repo has no [product], and siblings exist, named in the detail:
                   shipmill-setup's Product step asks once, and writes home, repos, or
                   standalone = true. --fix leaves it
  PRODUCT_OK       [product] is set in any form (standalone = true too), there is no
                   [agents] app_id, or no sibling exists; the first two read no sibling
  A sibling is a repo of the same owner, other than this one and not archived, whose
  default-branch .github/shipmill.toml sets the same [agents] app_id: the owner's repos
  are listed with the host's gh (/user/repos?affiliation=owner for the gh login's own
  account, /orgs/<owner>/repos for an organization, /users/<owner>/repos for another
  user), then each one's config is read, one call each. A 404 is no config, and so no
  sibling; any other gh failure exits 2. A sibling config that can't be read is named in
  the row's detail and skipped

Skills (the home folder's user skills, which shadow the plugin's by name):
  SKILL_SHADOWED   a link or copy of a shipmill skill in ~/.claude/skills or ~/.agents/skills
                   that doesn't resolve into the plugin's cache, one row each, as
                   github-ship-watch's SKILL_SHADOWED reads it, with its fix: remove it, or
                   call the skill as /shipmill:<name> (#236). --fix leaves it: it is the
                   user's home folder
  SKILLS_OK        none

Plugin (spec 033: the config's [agents] plugin, "host" by default, says where it loads):
  With plugin = "host" (the default, also without the key or a config): each person
  installs the plugin on their own host, and nothing in the repo turns it on. --fix never
  creates, writes, or changes .claude/settings.json
  PLUGIN_OK        an install of shipmill@shipmill applies to the repo's folder, read from
                   `claude plugin list --json`: user scope, or local or project scope keyed
                   on the repo's main checkout; the detail names its scope and version (or
                   says claude isn't on PATH, installs not read)
  PLUGIN_MISSING   no install applies; the detail gives the command, which the skill runs
                   after asking: an install changes the person's host. --fix leaves it
  PLUGIN_COMMITTED .claude/settings.json enables shipmill@shipmill, so every contributor's
                   Claude Code is offered it: set [agents] plugin = "repo" to keep it, or
                   delete it from enabledPlugins. --fix leaves it
  With plugin = "repo": .claude/settings.json enables it, so every session in the repo
  loads the skills
  PLUGIN_MISSING   shipmill@shipmill is not enabled; --fix adds the marketplace and
                   enables it, keeping every other key
  PLUGIN_OK        enabled
  In either mode:
  PLUGIN_DISABLED  enabledPlugins sets it to false on purpose; --fix leaves it
  PLUGIN_OUTDATED  in place of a PLUGIN_OK, when the user-scope install is behind shipmill's
                   latest release, with its one update, as github-ship-watch's
                   SHIPMILL_OUTDATED reads it (spec 039); and a `gate:` row when the install a
                   session loads is behind, which the gate reports and still starts sessions
                   on (spec 031). --fix leaves it
  PLUGIN_SHADOWING in place of a PLUGIN_OK too, when the host has project- or local-scope
                   installs of shipmill@shipmill, as github-ship-watch's PLUGIN_SHADOWING
                   reads them: one row, whose fix is `uvx shipmill==<version> plugin-clean`
                   (spec 039). --fix leaves the installs as they are
  [agents] plugin other than "host" or "repo", or not a string, exits 2

Labels (the triage skills and shipmill read them):
  LABELS_MISSING   some of postponed, blocked, shipmill-hold, the config's
                   blocker_label (default release-blocker), and, with an [agents]
                   section in either mode, needs-decision, role:maintainer and
                   role:<name> for each role [agents.roles] defines (a role's item,
                   spec 036; roles that isn't a table, or a name outside
                   [a-z0-9][a-z0-9-]{0,44}, exits 2), human (a person's item,
                   spec 017), shipmill-upgrade-later (a config upgrade's "not
                   now", spec 014), upstream (a report for another repo, spec
                   038), decided (a notify decision, spec 030), and
                   shipmill-direction (the question for a missing direction,
                   spec 034) don't exist; --fix creates
                   them on GitHub, as the App through `uvx shipmill==<version> gh`
                   (the version in the plugin's .claude-plugin/plugin.json, spec 031) when
                   [agents] sets app_id (spec 012), else with plain gh; a `shipmill gh`
                   exit 2 stops --fix, never retried with plain gh, and a missing or
                   malformed plugin.json exits 2 naming it
  LABELS_OK        all exist

Branches (the repo setting delete_branch_on_merge; github-pr-triage's stacked merges rely
on GitHub retargeting a stacked PR when the branch under it is deleted):
  BRANCH_DELETE_OFF  merged PR branches stay on GitHub; --fix turns the setting on, with
                     plain gh even with app_id set: the App has no Administration permission
  BRANCH_DELETE_ON   GitHub deletes a PR's branch when it merges

Whether the gate lands open pull requests is [autonomy] land's (spec 040), which
AUTONOMY_IMPLICIT asks for; [agents] prs is deprecated and read here no more.

Runner (spec 015; a warning, read only when release.yml passes shipmill's prepare.yml or
land.yml a runs-on other than ubuntu-latest and a lane sets quiet_minutes above 0):
  RUNNER_SHARED  a workflow named by an environment's workflow or a lane's dispatch has a
                 job whose runs-on labels are the same set as shipmill's, a subset, or a
                 superset, one row per workflow: the settle wait holds that runner for up
                 to quiet_minutes after each push, and a deploy queues behind it. A job
                 whose runs-on is an expression (${{ ... }}) or a runner group's mapping
                 isn't compared. --fix leaves it

Contributor rules (a warning, read only when the config's [changelog] sets fragments):
  CHANGELOG_RULES  a line of CLAUDE.md, AGENTS.md, CONTRIBUTING.md, .github/CONTRIBUTING.md,
                   or docs/CONTRIBUTING.md that mentions Unreleased, one row each, as
                   <file>:<line>: with fragments on, each pull request adds a fragment and
                   leaves CHANGELOG.md alone, so a rule to edit Unreleased is stale. The
                   repo's own docs are the maintainer's (D-42): --fix leaves them

Exit 0 when every row is RELEASE_READY, AGENTS_OK, PRODUCT_OK, PLUGIN_OK, SKILLS_OK,
LABELS_OK, or BRANCH_DELETE_ON (RUNNER_SHARED and CHANGELOG_RULES, warnings, leave the exit
code alone), 1 otherwise (AGENTS_NO_APP, AGENTS_NO_MODE, AGENTS_UNPREFIXED, AUTONOMY_IMPLICIT,
PRODUCT_LISTED, PRODUCT_SIBLINGS, PLUGIN_COMMITTED, PLUGIN_OUTDATED, PLUGIN_SHADOWING, and
SKILL_SHADOWED included), 2 on bad input, a malformed
settings.json or config (its [agents] read as github-ship-watch reads it; its [lanes] and
[environments] too when the runner is read; its [autonomy] with an [agents] section), both
config files,
a runs-on in release.yml that isn't a label or a quoted JSON list of labels, a git or gh
failure (a failed read of the repo setting never reads as off), or a malformed
`claude plugin list --json`.
Needs git and an authenticated gh, uvx for --fix's labels with app_id set, and claude on PATH
to read the plugin's installs. Python
3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

# github-ship-watch's watch_state.py: one reading of the plugin's installs for both skills
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
CONFIG = Path(".github/shipmill.toml")
CALLER = Path(".github/workflows/release.yml")
SETTINGS = Path(".claude/settings.json")
PLUGIN = "shipmill@shipmill"
# SHIPMILL_VERSION's clause when the install a session loads is behind (spec 031: reported, never a pause)
SESSION_BEHIND = re.compile(r"; (a session loads [^;]*, older than v[^;]+)")
MARKETPLACE = {"source": {"source": "github", "repo": "shipmill/shipmill"}, "autoUpdate": True}
# Where release.yml calls shipmill from: the repo, and its path before it moved to the org
SHIPMILL_REPOS = ("shipmill/shipmill/", "romamo/shipmill/")
LABELS = {
    "postponed": ("c5def5", "Triage decided not now; revisited after the next stable release"),
    "blocked": ("fbca04", "Waits on another issue, here or upstream"),
    "shipmill-hold": ("000000", "While open, no lane releases except a hotfix started by hand"),
}
BLOCKER = ("b60205", "Holds the release lanes the policy names until closed")
# Wanted only with [agents] mode = "headless" (spec 005): a session's question waits under it
NEEDS_DECISION = "needs-decision"
NEEDS_DECISION_LABEL = ("d876e3", "A shipmill session asked a question here; waits for a reply")
# Wanted wherever needs-decision is (spec 017): a person's item, which its assignees do
HUMAN = "human"
HUMAN_LABEL = ("0e8a16", "A person's item: its assignees do it, and a shipmill session hands it off")
# Wanted wherever needs-decision is (spec 036): a role's item, role:maintainer and role:<name> for
# each role [agents.roles] defines; a name as shipmill's, so the label fits GitHub's 50 characters
ROLE = "role:"
ROLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,44}")
MAINTAINER = "maintainer"
# Wanted with an [agents] section too (spec 014): a session marks a config upgrade's "not now" with it
UPGRADE_LATER = "shipmill-upgrade-later"
UPGRADE_LATER_LABEL = ("ededed", "A config upgrade the maintainer put off until shipmill changes it")
# Wanted wherever needs-decision is (spec 038): a report of a fault another repo owns, which waits outside
UPSTREAM = "upstream"
UPSTREAM_LABEL = ("5319e7", "A report for another repo: the product's coordinator or the maintainer routes it")
# Wanted wherever needs-decision is (spec 030): an agent's notify decision, which the maintainer may veto
DECIDED = "decided"
DECIDED_LABEL = ("bfd4f2", "A shipmill session decided here without waiting; the maintainer may veto it")
# Wanted wherever needs-decision is (spec 034): shipmill's question for the product's direction
DIRECTION = "shipmill-direction"
DIRECTION_LABEL = ("1d76db", "shipmill's question for the product's direction")
# D-19: the gate runs without an App, but setup isn't done until one is connected
NO_APP = (
    "no app connected: sessions write as the host's gh login, so you can't approve their PRs"
    " and GitHub won't notify you of their mentions; run shipmill-setup's step 3 (app-create)"
)
# D-20: the gate defaults to interactive, but setup writes the mode the user chose
NO_MODE = (
    'no mode in [agents]: the gate runs interactive by default, which nobody chose; set mode = "interactive"'
    ' or mode = "headless" (shipmill-setup\'s step 4)'
)
DONE = {"RELEASE_READY", "AGENTS_OK", "PRODUCT_OK", "PLUGIN_OK", "SKILLS_OK", "LABELS_OK", "BRANCH_DELETE_ON"}
# rows that warn without being part of setup's done states: they leave the exit code alone
WARNINGS = {"RUNNER_SHARED", "CHANGELOG_RULES"}
# the repo's own contributor rules, read for a stale rule to edit Unreleased and never written (D-42)
RULES_FILES = ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
UNRELEASED = re.compile(r"\bUnreleased\b")
# the runner prepare.yml's and land.yml's runs-on input defaults to (spec 015)
DEFAULT_RUNNER = "ubuntu-latest"
# a job of release.yml that calls shipmill's prepare.yml or land.yml, from a repo or locally
SHIPMILL_JOB = re.compile(r"(?:^|/)\.github/workflows/(?:prepare|land)\.ya?ml(?:@\S*)?$")
# the plugin's name: a prompt calls its skills as /shipmill:<name> (#236)
PREFIX = PLUGIN.partition("@")[0]
# shipmill's autonomy.AGENT_STAGES: the [autonomy] keys of the stages agent sessions run (spec 040)
AGENT_STAGES = ("triage", "fix", "land")
IMPLICIT = (
    "[autonomy] sets none of triage, fix, and land: how far a gate session goes was never chosen, so it"
    " comes from the defaults or the prompt's words; run shipmill-setup's Autonomy step, which writes all three"
)


@dataclass(frozen=True)
class Row:
    state: str
    detail: str

    def text(self) -> str:
        return f"{self.state:<17} {self.detail}"


def run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(f"error: {' '.join(cmd[:3])}...: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    return proc.stdout


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


# -- config --------------------------------------------------------------------------------


def config_file(repo_dir: Path) -> Path | None:
    path = repo_dir / CONFIG
    return path if path.is_file() else None


def check_requires(repo_dir: Path, ws: ModuleType) -> None:
    """The config's requires against the plugin's version, as watch_state.py checks it and with
    its words (spec 031): a plugin too old for the config exits 2 saying how to update"""
    config = config_file(repo_dir)
    if config is None:
        return
    try:
        ws.check_requires(config.read_text(encoding="utf-8"), CONFIG)
    except ws.Refused as refused:
        sys.stderr.write(f"{refused}\n")
        raise SystemExit(2) from None


def policy_value(text: str, key: str) -> str | None:
    found = re.search(rf'^{key}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return found.group(1) if found else None


def top_level(text: str) -> str:
    """The config's keys before its first table: the release keys, never [agents]'s mode"""
    return re.split(r"^\[", text, maxsplit=1, flags=re.MULTILINE)[0]


def agents_section(repo_dir: Path) -> str | None:
    """The [agents] section's body, or None without one"""
    config = config_file(repo_dir)
    text = config.read_text(encoding="utf-8") if config else ""
    section = re.search(r"^\[agents\][^\n]*\n?(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    return section.group(1) if section else None


def calls_shipmill(repo_dir: Path) -> bool:
    """release.yml calls shipmill's prepare workflow, from shipmill/shipmill (or its old
    path, romamo/shipmill) or, in shipmill itself and its forks, from a local copy"""
    caller = repo_dir / CALLER
    if not caller.is_file():
        return False
    text = caller.read_text(encoding="utf-8")
    local = repo_dir / ".github" / "workflows" / "prepare.yml"
    return any(path in text for path in SHIPMILL_REPOS) or (
        "./.github/workflows/prepare.yml" in text
        and local.is_file()
        and local.read_text(encoding="utf-8").startswith("name: shipmill prepare")
    )


def release_row(repo_dir: Path) -> Row:
    config = config_file(repo_dir)
    mode = policy_value(top_level(config.read_text(encoding="utf-8")), "mode") if config else None
    if config is None or mode is None:
        return Row("RELEASE_MISSING", f"no release keys in {CONFIG}: shipmill-setup steps 1 to 5")
    if not calls_shipmill(repo_dir):
        return Row("RELEASE_FOREIGN", f"{CALLER} doesn't call shipmill's workflows")
    if mode == "release":
        return Row("RELEASE_READY", "mode = release")
    if mode == "dry-run":
        return Row("RELEASE_DRY_RUN", "run the Release workflow by hand, then set mode = release")
    if mode == "off":
        return Row("RELEASE_OFF", "mode = off: shipmill never releases")
    fail(f"{config}: mode must be off, dry-run, or release, got {mode!r}")


def agents_row(repo_dir: Path) -> Row:
    """Presence only; `shipmill gate` and the release config loader validate the section.
    A prompt without app_id is unfinished setup in either mode (D-19): the gate runs, but its
    sessions write as the host's gh login. Without a mode key it is unfinished too (D-20): the
    gate's default, interactive, was never chosen"""
    section = agents_section(repo_dir)
    if section is None or not re.search(r"^prompt\s*=", section, re.MULTILINE):
        return Row("AGENTS_MISSING", f"no [agents] prompt in {CONFIG}: needed only for `shipmill gate`")
    if not re.search(r"^[ \t]*app_id\s*=", section, re.MULTILINE):  # TOML allows an indented key
        return Row("AGENTS_NO_APP", NO_APP)
    if not re.search(r"^[ \t]*mode\s*=", section, re.MULTILINE):
        return Row("AGENTS_NO_MODE", NO_MODE)
    return Row("AGENTS_OK", "[agents] has a prompt, app_id, and mode")


def unprefixed(prompt: str, names: list[str]) -> list[str]:
    """The skills in names the prompt calls as /<name>, in order, each once. /shipmill:<name>,
    a path such as skills/<name>/, and a longer name that starts with one are no call"""
    if not names:
        return []
    alternatives = "|".join(re.escape(name) for name in names)
    found = re.findall(rf"(?<![\w/:.-])/({alternatives})(?![\w/-])", prompt)
    return list(dict.fromkeys(found))


def prompt_rows(repo_dir: Path, ws: ModuleType) -> list[Row]:
    """AGENTS_UNPREFIXED when the [agents] prompt calls a shipmill skill without the plugin's
    prefix (#236); the config's [agents] is read as watch_state.py reads it"""
    config = config_file(repo_dir)
    if config is None:
        return []
    try:
        table = ws.agents_table(config.read_text(encoding="utf-8"), config)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    raw = (table or {}).get("prompt")
    if raw is None or not raw.startswith('"'):  # no prompt, or not a string: the gate refuses it
        return []
    found = unprefixed(json.loads(raw), ws.skill_names())
    if not found:
        return []
    calls = ", ".join(f"/{name}" for name in found)
    fixed = ", ".join(f"/{PREFIX}:{name}" for name in found)
    return [
        Row(
            "AGENTS_UNPREFIXED",
            f"[agents] prompt calls {calls}: a skill of that name in ~/.claude/skills or ~/.agents/skills"
            f" runs in place of the plugin's; write {fixed}",
        )
    ]


def autonomy_rows(repo_dir: Path, ws: ModuleType) -> list[Row]:
    """AUTONOMY_IMPLICIT when the config has an [agents] section and its [autonomy] sets none
    of the agent stages (spec 040); the levels are shipmill's to validate"""
    if agents_section(repo_dir) is None or agent_stages_set(repo_dir, ws):
        return []
    return [Row("AUTONOMY_IMPLICIT", IMPLICIT)]


def agent_stages_set(repo_dir: Path, ws: ModuleType) -> list[str]:
    """The agent stages [autonomy] sets, in AGENT_STAGES' order, read as watch_state.py reads the
    config: with tomllib on Python 3.11+, a plain [autonomy] table on 3.10. An autonomy that
    isn't a table exits 2"""
    config = repo_dir / CONFIG
    text = config.read_text(encoding="utf-8")
    if ws.tomllib is None:
        return agent_stages_set_310(text, config, ws)
    try:
        raw = ws.tomllib.loads(text)
    except ws.tomllib.TOMLDecodeError as exc:
        fail(f"{config}: {exc}")
    table = raw.get("autonomy", {})
    if not isinstance(table, dict):
        fail(f"{config}: autonomy must be a table, got {type(table).__name__}")
    return [stage for stage in AGENT_STAGES if stage in table]


def agent_stages_set_310(text: str, config: Path, ws: ModuleType) -> list[str]:
    """agent_stages_set on Python 3.10, without tomllib: keys that start their lines in a plain
    [autonomy] table, or an [autonomy.<stage>] table; an autonomy set from the top level (a
    dotted key or an inline table) is refused rather than misread"""
    tables = ws.toml_tables(text)
    if re.search(r"^\s*[\"']?autonomy[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE):
        fail(f"{config}: can't read [autonomy] on Python 3.10: use 3.11+ or a plain [autonomy] table")
    body = tables.get("autonomy", "")
    found = []
    for stage in AGENT_STAGES:
        key = re.search(rf"^\s*[\"']?{stage}[\"']?\s*[.=]", body, re.MULTILINE)
        if key is not None or f"autonomy.{stage}" in tables:
            found.append(stage)
    return found


# -- product -------------------------------------------------------------------------------

NOT_FOUND = re.compile(r"\(HTTP 404\)")  # gh's words for a 404: "gh: Not Found (HTTP 404)"
APP_ID = re.compile(r"[1-9][0-9]*")  # shipmill reads [agents] app_id as a positive integer
# a line of the owner's repo listing, as the listing's --jq writes it: archived, then owner/name
LISTED = re.compile(r"(true|false) ([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
LISTING_JQ = '.[] | "\\(.archived) \\(.full_name)"'
RAW = "Accept: application/vnd.github.raw"
STEP = "shipmill-setup's Product step"


def gh_get(cmd: list[str]) -> str | None:
    """A gh read: its output, or None when GitHub answers 404; any other failure exits 2"""
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return proc.stdout
    if NOT_FOUND.search(proc.stderr):
        return None
    sys.stderr.write(f"error: {' '.join(cmd)}: {proc.stderr.strip()}\n")  # the whole command names the repo read
    raise SystemExit(2)


def gh_need(gh: Callable[[list[str]], str | None], cmd: list[str]) -> str:
    """A gh read that must find what it reads: a 404 exits 2 too"""
    out = gh(cmd)
    if out is None:
        fail(f"{' '.join(cmd)}: not found")
    return out


def owner_repos(repo: str, gh: Callable[[list[str]], str | None]) -> list[str]:
    """The owner's unarchived repos other than this one, as owner/name, sorted with case
    ignored: the gh login's own account lists its private repos through /user/repos, an
    organization through /orgs, another user through /users. One listing, paged. The login is
    read for a user owner alone: a gate session's gh runs on the App's installation token,
    which `gh api user` refuses"""
    owner = repo.partition("/")[0]
    kind = gh_need(gh, ["gh", "api", f"users/{owner}", "--jq", ".type"]).strip()
    if kind not in ("Organization", "User"):
        fail(f"users/{owner}: expected the type Organization or User, got {kind!r}")
    if kind == "Organization":
        endpoint = f"orgs/{owner}/repos?per_page=100"
    elif gh_need(gh, ["gh", "api", "user", "--jq", ".login"]).strip().lower() == owner.lower():
        endpoint = "user/repos?affiliation=owner&per_page=100"
    else:
        endpoint = f"users/{owner}/repos?per_page=100"
    listing = gh_need(gh, ["gh", "api", "--paginate", endpoint, "--jq", LISTING_JQ])
    found: dict[str, str] = {}
    for line in listing.splitlines():
        if not line.strip():
            continue
        entry = LISTED.fullmatch(line.strip())
        if entry is None:
            fail(f"{endpoint}: expected '<archived> <owner/name>', got {line.strip()!r}")
        archived, name = entry.group(1) == "true", f"{entry.group(2)}/{entry.group(3)}"
        if archived or entry.group(2).lower() != owner.lower() or name.lower() == repo.lower():
            continue
        found.setdefault(name.lower(), name)
    return [found[key] for key in sorted(found)]


def has_product(text: str, config: Path, ws: ModuleType) -> bool:
    """Whether the config has a [product] table in any form, standalone = true too (spec 043),
    read as watch_state.py reads it: a table shipmill would refuse exits 2"""
    try:
        ws.product_repos(text, config)
        if ws.tomllib is None:
            return ws.product_table_310(text, config) is not None
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    return "product" in ws.tomllib.loads(text)


def product_rows(
    repo: str, repo_dir: Path, ws: ModuleType, gh: Callable[[list[str]], str | None] = gh_get
) -> list[Row]:
    """The Product row (spec 043), the first that applies: PRODUCT_LISTED, PRODUCT_SIBLINGS,
    then PRODUCT_OK. Siblings are read only with [agents] app_id and no [product], through gh
    reads alone, so --fix has nothing to change here"""
    config = config_file(repo_dir)
    if config is None:
        return [Row("PRODUCT_OK", "no [agents] app_id: a product's repos meet through the App, siblings not read")]
    text = config.read_text(encoding="utf-8")
    try:
        app_id = (ws.agents_table(text, config) or {}).get("app_id")
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    if app_id is None:
        return [Row("PRODUCT_OK", "no [agents] app_id: a product's repos meet through the App, siblings not read")]
    if APP_ID.fullmatch(app_id) is None:
        fail(f"{config}: [agents] app_id must be a positive integer, got {app_id}")
    if has_product(text, config, ws):
        return [Row("PRODUCT_OK", f"{CONFIG} sets [product]")]
    siblings, listing, skipped = [], [], []
    for name in owner_repos(repo, gh):
        found = gh(["gh", "api", "-H", RAW, f"repos/{name}/contents/{CONFIG.as_posix()}"])
        if found is None:  # no config, so no sibling
            continue
        where = Path(f"{name}:{CONFIG.as_posix()}")
        try:
            if (ws.agents_table(found, where) or {}).get("app_id") != app_id:
                continue
            repos = ws.product_repos(found, where)
        except ws.Refused as refused:  # another repo's to fix: named, and skipped
            skipped.append(str(refused).removeprefix("error: "))
            continue
        siblings.append(name)
        if repos is not None and repo.lower() in {listed.lower() for listed in repos}:
            listing.append(name)
    unread = "".join(f"; skipped, its config can't be read: {reason}" for reason in skipped)
    if listing:
        homes = " or ".join(f'home = "{name}"' for name in listing)
        pick = "; the maintainer picks one" if len(listing) > 1 else ""
        verb = "lists" if len(listing) == 1 else "list"
        detail = f"{', '.join(listing)} {verb} {repo} in [product] repos: write [product] {homes} in {CONFIG}{pick}"
        return [Row("PRODUCT_LISTED", f"{detail} ({STEP}){unread}")]
    if siblings:
        verb = "sets" if len(siblings) == 1 else "set"
        detail = (
            f"{', '.join(siblings)} {verb} app_id {app_id} too and {CONFIG} has no [product]: {STEP} asks whether"
            " they make up one product, and writes home, repos, or standalone = true"
        )
        return [Row("PRODUCT_SIBLINGS", f"{detail}{unread}")]
    owner = repo.partition("/")[0]
    return [Row("PRODUCT_OK", f"no other repo of {owner} sets app_id {app_id}{unread}")]


# -- plugin --------------------------------------------------------------------------------


def load_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path}: {exc}")
    if not isinstance(data, dict):
        fail(f"{path}: the top level must be a JSON object")
    for key in ("extraKnownMarketplaces", "enabledPlugins"):
        if not isinstance(data.get(key, {}), dict):
            fail(f"{path}: {key} must be a JSON object")
    return data


def plugin_row(settings: dict[str, Any]) -> Row:
    enabled = settings.get("enabledPlugins", {}).get(PLUGIN)
    if enabled is True:
        return Row("PLUGIN_OK", f"{SETTINGS} enables {PLUGIN}")
    if enabled is False:
        return Row("PLUGIN_DISABLED", f"{SETTINGS} disables {PLUGIN} on purpose")
    return Row("PLUGIN_MISSING", f"{SETTINGS} doesn't enable {PLUGIN}")


SHADOWING = "PLUGIN_SHADOWING"  # watch_state.py's row, shown as it is (S-039-6)


def plugin_rows(settings: dict[str, Any], outdated: Callable[[], list[Row]]) -> list[Row]:
    """plugin_row, and with the plugin enabled, the PLUGIN_OUTDATED and PLUGIN_SHADOWING rows
    in its place (#233, spec 039); outdated reads them only then"""
    row = plugin_row(settings)
    if row.state != "PLUGIN_OK":
        return [row]
    return outdated() or [row]


HOST, REPO = "host", "repo"  # [agents] plugin (spec 033): per person, or committed for the repo
PLUGIN_MODES = (HOST, REPO)
# An install at user scope: the command PLUGIN_MISSING gives with plugin = "host", run after asking
INSTALL = "claude plugin marketplace add shipmill/shipmill && claude plugin install shipmill@shipmill --scope user"
INSTALL_PRECEDENCE = ("local", "project", "user")  # the most specific install that applies is named


def plugin_mode(repo_dir: Path, ws: ModuleType) -> str:
    """[agents] plugin, read as watch_state.py reads [agents]: "host" without the key, the
    section, or a config; any other value, or one that isn't a string, exits 2 (S-033-1)"""
    config = config_file(repo_dir)
    if config is None:
        return HOST
    try:
        table = ws.agents_table(config.read_text(encoding="utf-8"), config)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    raw = (table or {}).get("plugin")
    if raw is None:
        return HOST
    value = json.loads(raw) if raw.startswith('"') else None
    if value not in PLUGIN_MODES:
        fail(f'{config}: [agents] plugin must be "host" (the default) or "repo", got {raw}')
    return str(value)


def host_install(plugins: object, project: Path) -> tuple[str, str] | None:
    """The install of the plugin that applies to the project, from `claude plugin list
    --json`: the most specific of local or project scope keyed on the project, then user
    scope, as (scope, version); None when none applies. A malformed listing exits 2"""
    if not isinstance(plugins, list):
        fail("claude plugin list --json: expected a JSON array")
    found: dict[str, str] = {}
    for entry in plugins:
        if not isinstance(entry, dict) or entry.get("id") != PLUGIN:
            continue
        scope, version, where = entry.get("scope"), entry.get("version"), entry.get("projectPath")
        if not isinstance(scope, str) or not isinstance(version, str) or not isinstance(where, (str, type(None))):
            fail(f"claude plugin list --json: {PLUGIN} install {entry!r}")
        applies = (scope == "user" and where is None) or (
            scope in ("local", "project") and where is not None and Path(where) == project
        )
        if applies:
            found.setdefault(scope, version)
    return next(((scope, found[scope]) for scope in INSTALL_PRECEDENCE if scope in found), None)


def host_plugin_rows(
    settings: dict[str, Any], plugins: Callable[[], object], project: Path, outdated: Callable[[], list[Row]]
) -> list[Row]:
    """The Plugin rows with plugin = "host" (spec 033). plugins is `claude plugin list --json`
    parsed, None when claude isn't on PATH; it and outdated are read only when the settings
    neither disable nor commit the plugin"""
    enabled = settings.get("enabledPlugins", {}).get(PLUGIN)
    if enabled is False:
        return [Row("PLUGIN_DISABLED", f"{SETTINGS} disables {PLUGIN} on purpose")]
    if enabled is True:
        detail = (
            f"{SETTINGS} enables {PLUGIN}, so every contributor's Claude Code is offered it, but [agents] plugin"
            f' is "host" (the default): set plugin = "repo" in [agents] to keep it, or delete "{PLUGIN}" from'
            ' enabledPlugins (and the "shipmill" entry from extraKnownMarketplaces when no other plugin uses it)'
        )
        return [Row("PLUGIN_COMMITTED", detail)]
    listed = plugins()
    if listed is None:
        row = Row("PLUGIN_OK", "claude isn't on PATH, installs not read")
    else:
        install = host_install(listed, project)
        if install is None:
            return [Row("PLUGIN_MISSING", f"no install of {PLUGIN} applies to {project}: {INSTALL}")]
        scope, version = install
        keyed = "" if scope == "user" else f" for {project}"
        row = Row("PLUGIN_OK", f"{PLUGIN} {version} is installed at {scope} scope{keyed}")
    return outdated() or [row]


def listed_plugins(ws: ModuleType) -> object:
    """`claude plugin list --json`, parsed; None when claude isn't on PATH"""
    claude = shutil.which("claude")
    if claude is None:
        return None
    try:
        return ws.claude_json(claude, "plugin", "list")
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))


def fix_plugin(settings_path: Path, settings: dict[str, Any], mode: str) -> dict[str, Any]:
    """--fix's plugin step: with plugin = "repo", the marketplace and enabledPlugins written
    into the settings when they don't enable it, keeping every other key; with "host" the
    settings file is never created or changed (S-033-2)"""
    if mode != REPO or plugin_row(settings).state != "PLUGIN_MISSING":
        return settings
    merged = enable_plugin(settings)
    settings_path.parent.mkdir(exist_ok=True)
    settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


def watch_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shipmill_watch_state", WATCH_STATE)
    if spec is None or spec.loader is None:
        fail(f"can't load {WATCH_STATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def outdated_installs(repo: str, repo_dir: Path, ws: ModuleType) -> list[Row]:
    """watch_state.py's SHIPMILL_OUTDATED rows as PLUGIN_OUTDATED, each detail `<subject>:
    <detail>`: the user install with its single update (spec 039); then, when the install a
    session loads is behind, SHIPMILL_VERSION's words for it: the gate's sessions run that
    release's skills until it is updated (spec 031); then its PLUGIN_SHADOWING row, the
    project- and local-scope installs on the host with plugin-clean's fix (S-039-6)"""
    try:
        rows = ws.shipmill_rows(repo, repo_dir)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    found = [Row("PLUGIN_OUTDATED", f"{r.subject}: {r.detail}") for r in rows if r.state == "SHIPMILL_OUTDATED"]
    for r in rows:
        behind = SESSION_BEHIND.search(r.detail) if r.state == "SHIPMILL_VERSION" else None
        if behind is not None:
            found.append(Row("PLUGIN_OUTDATED", f"gate: {behind.group(1)}"))
    found += [Row(r.state, f"{r.subject}: {r.detail}") for r in rows if r.state == SHADOWING]
    return found


def skill_rows(home: Path, ws: ModuleType) -> list[Row]:
    """watch_state.py's SKILL_SHADOWED rows for the home folder, each as `<name>: <detail>`,
    or SKILLS_OK (#236)"""
    rows = [Row(r.state, f"{r.subject}: {r.detail}") for r in ws.shadow_rows(home, ws.skill_names())]
    none = "no link or copy in ~/.claude/skills or ~/.agents/skills shadows a shipmill skill"
    return rows or [Row("SKILLS_OK", none)]


def enable_plugin(settings: dict[str, Any]) -> dict[str, Any]:
    """The settings with the shipmill marketplace known and the plugin on. An existing
    marketplace entry (a fork, a local path) is kept"""
    merged = dict(settings)
    merged["extraKnownMarketplaces"] = {"shipmill": MARKETPLACE, **settings.get("extraKnownMarketplaces", {})}
    merged["enabledPlugins"] = {**settings.get("enabledPlugins", {}), PLUGIN: True}
    return merged


# -- labels --------------------------------------------------------------------------------


def wanted_labels(repo_dir: Path, ws: ModuleType | None = None) -> dict[str, tuple[str, str]]:
    """The labels the repo needs; ws is watch_state.py, which reads [agents.roles], loaded
    here when not given"""
    wanted = dict(LABELS)
    config = config_file(repo_dir)
    blocker = policy_value(config.read_text(encoding="utf-8"), "blocker_label") if config else None
    wanted[blocker or "release-blocker"] = BLOCKER
    if agents_section(repo_dir) is not None:  # every gate session asks this way, in either mode (D-21)
        wanted[NEEDS_DECISION] = NEEDS_DECISION_LABEL
        wanted.update(role_labels(repo_dir, ws or watch_module()))  # a role's item (spec 036)
        wanted[HUMAN] = HUMAN_LABEL  # a person's item in a chain (spec 017)
        wanted[UPGRADE_LATER] = UPGRADE_LATER_LABEL  # a config upgrade's "not now" (spec 014)
        wanted[UPSTREAM] = UPSTREAM_LABEL  # a report for another repo (spec 038)
        wanted[DECIDED] = DECIDED_LABEL  # a notify decision, open to a veto (spec 030)
        wanted[DIRECTION] = DIRECTION_LABEL  # the question for a missing direction (spec 034)
    return wanted


def role_labels(repo_dir: Path, ws: ModuleType) -> dict[str, tuple[str, str]]:
    """role:maintainer, then role:<name> for each other role [agents.roles] defines, in its
    order (spec 036)"""
    names = dict.fromkeys([MAINTAINER, *role_names(repo_dir, ws)])
    return {f"{ROLE}{name}": ("0e8a16", f"A step for the {name} role: its people do it") for name in names}


def role_names(repo_dir: Path, ws: ModuleType) -> list[str]:
    """The names [agents.roles] defines, in order, read as watch_state.py reads the config:
    with tomllib on Python 3.11+, with plain tables on 3.10. Only the names: shipmill
    validates the fillers. A roles that isn't a table, or a name outside shipmill's pattern,
    exits 2"""
    config = repo_dir / CONFIG
    text = config.read_text(encoding="utf-8")
    if ws.tomllib is None:
        names = role_names_310(text, config, ws)
    else:
        try:
            raw = ws.tomllib.loads(text)
        except ws.tomllib.TOMLDecodeError as exc:
            fail(f"{config}: {exc}")
        agents = raw.get("agents")
        roles = agents.get("roles") if isinstance(agents, dict) else None
        if roles is not None and not isinstance(roles, dict):
            fail(f"{config}: [agents.roles] must be a table of role names, got {type(roles).__name__}")
        names = list(roles or {})
    for name in names:
        if ROLE_NAME.fullmatch(name) is None:
            fail(
                f"{config}: [agents.roles] {name!r} isn't a role name: lowercase letters, digits, and '-',"
                " starting with a letter or digit, at most 45 characters"
            )
    return names


def role_names_310(text: str, config: Path, ws: ModuleType) -> list[str]:
    """role_names on Python 3.10, without tomllib: a plain [agents.roles] table whose keys
    start their lines; roles set any other way (a roles key under [agents], dotted or inline,
    an [agents.roles.<name>] table, or an array of tables) is refused rather than misread"""
    tables = ws.toml_tables(text)
    dotted = re.search(r"^\s*[\"']?roles[\"']?\s*[.=]", tables.get("agents", ""), re.MULTILINE)
    # toml_tables skips an array of tables, [[agents.roles]], which tomllib reads as a list: refused
    arrays = [m.group(1) for m in re.finditer(r"^\s*\[\[\s*([^\[\]]+?)\s*\]\]", text, re.MULTILINE)]
    in_roles = [[p.strip().strip("\"'") for p in name.split(".")][:2] == ["agents", "roles"] for name in arrays]
    if dotted or any(in_roles) or any(name.startswith("agents.roles.") for name in tables):
        fail(f"{config}: can't read [agents.roles] on Python 3.10: use 3.11+ or a plain [agents.roles] table")
    names = []
    for line in tables.get("agents.roles", "").splitlines():
        key = re.match(r"^\s*([\"']?)([^\"'=\s#]+)\1\s*=", line)
        if key is not None:
            names.append(key.group(2))
    return names


def labels_row(missing: list[str], wanted: dict[str, tuple[str, str]]) -> Row:
    if missing:
        return Row("LABELS_MISSING", ", ".join(missing))
    extra = "".join(
        f" {label},"
        for label in (NEEDS_DECISION, HUMAN, UPGRADE_LATER, UPSTREAM, DECIDED, DIRECTION)
        if label in wanted
    )
    return Row("LABELS_OK", f"postponed, blocked, shipmill-hold,{extra} and the blocker label exist")


def create_labels(
    repo: str,
    wanted: dict[str, tuple[str, str]],
    missing: list[str],
    write: list[str],
    gh: Callable[[list[str]], str] = run,
) -> None:
    """--fix: create each missing label with its color and description, through write (the
    writing gh, `shipmill gh` with [agents] app_id set); a failure stops, never retried"""
    for name in missing:
        color, description = wanted[name]
        gh([*write, "label", "create", name, "-R", repo, "--color", color, "--description", description])


def gh_writer(repo_dir: Path, ws: ModuleType) -> list[str]:
    """watch_state.py's writing gh for the checkout (spec 012, #290); a config it refuses fails"""
    try:
        found: list[str] = ws.gh_writer(repo_dir)
    except ws.Refused as refused:
        fail(str(refused).removeprefix("error: "))
    return found


def existing_labels(repo: str) -> set[str]:
    out = run(["gh", "label", "list", "-R", repo, "--limit", "500", "--json", "name"])
    return {label["name"] for label in json.loads(out)}


# -- branches ------------------------------------------------------------------------------


def read_flag(out: str, what: str) -> bool:
    """gh's -q output for a boolean: anything but true or false fails, never reads as off"""
    value = out.strip()
    if value not in ("true", "false"):
        fail(f"{what}: expected true or false, got {value!r}")
    return value == "true"


def branch_delete_row(repo: str, fix: bool, gh: Callable[[list[str]], str] = run) -> Row:
    """Whether GitHub deletes a PR's branch on merge; with fix, turns it on when it's off"""
    query = ["-q", ".delete_branch_on_merge"]
    on = read_flag(gh(["gh", "api", f"repos/{repo}", *query]), f"{repo}'s delete_branch_on_merge")
    if not on and fix:
        patch = ["gh", "api", "-X", "PATCH", f"repos/{repo}", "-F", "delete_branch_on_merge=true", *query]
        on = read_flag(gh(patch), f"{repo}'s delete_branch_on_merge after --fix")
        if not on:
            fail(f"{repo}: turning delete_branch_on_merge on didn't take")
    if on:
        return Row("BRANCH_DELETE_ON", "GitHub deletes a pull request's branch when it merges")
    return Row("BRANCH_DELETE_OFF", "merged branches stay on GitHub and stacked PRs aren't retargeted")


# -- runner --------------------------------------------------------------------------------
# A workflow is read without a YAML library: the block mappings a workflow is written in, by
# indentation, which is all runs-on and the jobs around it need


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def content(line: str) -> bool:
    """Neither blank nor a comment"""
    return bool(line.strip()) and not line.lstrip().startswith("#")


def children(lines: list[str]) -> dict[str, tuple[str, list[str]]]:
    """The keys of a block mapping at its own indent, each with the value on its line and the
    lines under it; a sequence item at the key's own indent belongs to the key, as YAML reads it"""
    rows = [line for line in lines if content(line)]
    if not rows:
        return {}
    depth = indent(rows[0])
    found: dict[str, tuple[str, list[str]]] = {}
    key: str | None = None
    for line in lines:
        if not content(line):
            continue
        if indent(line) > depth or (indent(line) == depth and line.lstrip().startswith("- ")):
            if key is not None:
                found[key][1].append(line)
            continue
        if indent(line) < depth:
            break
        pair = re.match(r"^\s*(\"[^\"]*\"|'[^']*'|[^\s#'\"-][^:#]*?)\s*:(?:\s+(.*))?$", line)
        key = None if pair is None else pair.group(1).strip("\"'")
        if key is not None:
            found[key] = ((pair.group(2) or "").strip(), [])
    return found


def scalar(text: str) -> str:
    """A one-line YAML scalar: a quoted one unquoted, a plain one without its comment"""
    single = re.match(r"^'((?:[^']|'')*)'\s*(?:#.*)?$", text)
    if single:
        return single.group(1).replace("''", "'")
    double = re.match(r'^("(?:[^"\\]|\\.)*")\s*(?:#.*)?$', text)
    if double:
        value: str = json.loads(double.group(1))
        return value
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()


def jobs(text: str) -> dict[str, dict[str, tuple[str, list[str]]]]:
    """Each job of a workflow, as its keys"""
    top = children(text.splitlines())
    if "jobs" not in top:
        return {}
    return {name: children(body) for name, (_, body) in children(top["jobs"][1]).items()}


def job_labels(value: str, under: list[str]) -> frozenset[str] | None:
    """A job's runs-on labels: a label, an inline list, or a block list; None for an
    expression, which only the run resolves, or a runner group's mapping (spec 015 leaves
    groups out), so neither is compared"""
    items: list[str]
    flow = re.match(r"^\[(.*)\]\s*(?:#.*)?$", value)
    if flow:
        items = [scalar(item.strip()) for item in flow.group(1).split(",") if item.strip()]
    elif value and not value.startswith("#"):
        items = [scalar(value)]
    else:
        listed = [re.match(r"^\s*-\s+(.*)$", line) for line in under]
        if not listed or any(item is None for item in listed):
            return None
        items = [scalar(item.group(1).strip()) for item in listed if item is not None]
    if not items or any(not item or "${{" in item for item in items):
        return None
    return frozenset(item.casefold() for item in items)


def shipmill_runners(text: str, where: Path) -> list[frozenset[str]]:
    """The runs-on each job calling shipmill's prepare.yml or land.yml passes, other than the
    default: a label, or a JSON list of labels in a quoted string, as the input takes it. An
    expression is left out, since only the run resolves it"""
    found: list[frozenset[str]] = []
    for name, keys in jobs(text).items():
        if not SHIPMILL_JOB.search(scalar(keys.get("uses", ("", []))[0])) or "with" not in keys:
            continue
        given = children(keys["with"][1]).get("runs-on")
        if given is None:
            continue
        raw, under = given
        if raw.startswith("[") or not raw or under:
            fail(f"{where}: job {name} passes runs-on as a YAML list; the input takes a label or a quoted JSON list")
        value = scalar(raw)
        if "${{" in value:
            continue
        labels: object = [value]
        if value.startswith("["):
            try:
                labels = json.loads(value)
            except json.JSONDecodeError as exc:
                fail(f"{where}: job {name}'s runs-on {value!r} starts with '[' but isn't JSON: {exc.msg}")
        if not (isinstance(labels, list) and labels and all(isinstance(v, str) and v for v in labels)):
            fail(f"{where}: job {name}'s runs-on {value!r} is not a label or a non-empty JSON list of labels")
        runner = frozenset(label.casefold() for label in labels)
        if runner != {DEFAULT_RUNNER} and runner not in found:
            found.append(runner)
    return found


def lane_runner_config(raw: dict[str, Any], where: Path) -> tuple[int, list[str]]:
    """The longest quiet_minutes across the lanes and the workflows the environments' workflow
    and the lanes' dispatch name, from the parsed config"""
    lanes, environments = raw.get("lanes", {}), raw.get("environments", {})
    if not isinstance(lanes, dict) or not isinstance(environments, dict):
        fail(f"{where}: lanes and environments must be tables")
    quiet, workflows = 0, []
    for name, table in lanes.items():
        if not isinstance(table, dict):
            fail(f"{where}: lanes.{name} is not a table")
        minutes, dispatch = table.get("quiet_minutes", 0), table.get("dispatch", [])
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            fail(f"{where}: lanes.{name} quiet_minutes must be an integer, got {minutes!r}")
        if not (isinstance(dispatch, list) and all(isinstance(w, str) for w in dispatch)):
            fail(f"{where}: lanes.{name} dispatch must be a list of workflow files, got {dispatch!r}")
        quiet = max(quiet, minutes)
        workflows += dispatch
    for name, table in environments.items():
        workflow = table.get("workflow") if isinstance(table, dict) else None
        if not isinstance(workflow, str):
            fail(f"{where}: environments.{name} needs a workflow file")
        workflows.append(workflow)
    return quiet, list(dict.fromkeys(workflows))


def lane_runner_config_310(text: str, where: Path, ws: ModuleType) -> tuple[int, list[str]]:
    """lane_runner_config on Python 3.10, without tomllib: plain [lanes.<name>] and
    [environments.<name>] tables of one-line keys and a dispatch list; any other form is
    refused rather than misread"""
    unreadable = (
        f"{where}: can't read [lanes] or [environments] on Python 3.10: use 3.11+ or plain"
        " [lanes.<name>] and [environments.<name>] tables"
    )
    tables = ws.toml_tables(text)
    nested = re.search(r"^\s*[\"']?(?:lanes|environments)[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE)
    if nested or not ws.blank(tables.get("lanes", "")) or not ws.blank(tables.get("environments", "")):
        fail(unreadable)
    quiet, workflows, deploys = 0, [], []  # the lanes' dispatch first, as tomllib's reading lists them
    for name, body in tables.items():
        parts = name.split(".")
        if parts[0] not in ("lanes", "environments") or len(parts) == 1:
            continue
        if len(parts) != 2:
            fail(unreadable)
        if parts[0] == "environments":
            workflow = ws.toml_string(body, "workflow")
            if workflow is None:
                fail(f"{where}: environments.{parts[1]} needs a workflow file (or can't be read on Python 3.10)")
            deploys.append(workflow)
            continue
        minutes = re.search(r"^\s*[\"']?quiet_minutes[\"']?\s*=\s*(\d+)\s*(?:#.*)?$", body, re.MULTILINE)
        if minutes is None and re.search(r"^\s*[\"']?quiet_minutes[\"']?\s*=", body, re.MULTILINE):
            fail(unreadable)
        quiet = max(quiet, int(minutes.group(1)) if minutes else 0)
        dispatch = re.search(r"^\s*[\"']?dispatch[\"']?\s*=\s*\[(.*?)\]", body, re.MULTILINE | re.DOTALL)
        if dispatch is None:
            if re.search(r"^\s*[\"']?dispatch[\"']?\s*=", body, re.MULTILINE):
                fail(unreadable)
            continue
        strings = r"\"([^\"]*)\"|'([^']*)'"
        rest = re.sub(r"#[^\n]*", "", re.sub(strings, "", dispatch.group(1)))
        if rest.replace(",", "").strip():
            fail(unreadable)
        workflows += [double or single for double, single in re.findall(strings, dispatch.group(1))]
    return quiet, list(dict.fromkeys(workflows + deploys))


def runner_rows(repo_dir: Path, ws: ModuleType) -> list[Row]:
    """RUNNER_SHARED for each deploy workflow with a job on shipmill's runner, while a lane's
    settle wait holds that runner after a push (spec 015); the config is read only then"""
    caller, config = repo_dir / CALLER, config_file(repo_dir)
    if not caller.is_file() or config is None:
        return []
    runners = shipmill_runners(caller.read_text(encoding="utf-8"), caller)
    if not runners:
        return []
    text = config.read_text(encoding="utf-8")
    if ws.tomllib is None:
        quiet, workflows = lane_runner_config_310(text, config, ws)
    else:
        try:
            raw = ws.tomllib.loads(text)
        except ws.tomllib.TOMLDecodeError as exc:
            fail(f"{config}: {exc}")
        quiet, workflows = lane_runner_config(raw, config)
    if quiet <= 0:
        return []
    rows = []
    for workflow in workflows:
        path = repo_dir / ".github" / "workflows" / workflow
        if not path.is_file():  # doctor reports a missing deploy workflow
            continue
        for job, keys in jobs(path.read_text(encoding="utf-8")).items():
            labels = job_labels(*keys["runs-on"]) if "runs-on" in keys else None
            shared = next((r for r in runners if labels is not None and (labels <= r or r <= labels)), None)
            if shared is None:
                continue
            rows.append(
                Row(
                    "RUNNER_SHARED",
                    f"{workflow}'s job {job} runs on {', '.join(sorted(labels or ()))}, as shipmill's release jobs"
                    f" do ({', '.join(sorted(shared))}): a runner takes one job at a time, so the settle wait holds"
                    f" it for up to {quiet} minutes after each push and a deploy queues behind it; give shipmill a"
                    " runner of its own (another label or instance), or drop quiet_minutes for a schedule",
                )
            )
            break
    return rows


# -- contributor rules ---------------------------------------------------------------------


def changelog_rule_rows(repo_dir: Path, ws: ModuleType) -> list[Row]:
    """CHANGELOG_RULES for each line of the repo's contributor rules that mentions Unreleased,
    once the config's [changelog] sets fragments; read only, as the files are the maintainer's
    (D-42)"""
    config = config_file(repo_dir)
    if config is None:
        return []
    folder = ws.toml_string(ws.toml_tables(config.read_text(encoding="utf-8")).get("changelog", ""), "fragments")
    if not folder:
        return []
    rows = []
    for name in RULES_FILES:
        path = repo_dir / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            fail(f"{path}: not UTF-8: {exc}")
        for number, line in enumerate(lines, start=1):
            if UNRELEASED.search(line):
                rows.append(
                    Row(
                        "CHANGELOG_RULES",
                        f"{name}:{number} mentions Unreleased: with fragments on, each pull request adds"
                        f" {folder}/<issue>-<slug>.md and leaves CHANGELOG.md alone; the change is yours (D-42)",
                    )
                )
    return rows


# -- main ----------------------------------------------------------------------------------


def check_checkout(repo: str, repo_dir: Path) -> None:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        fail(f"repo must be owner/name, got {repo!r}")
    origin = run(["git", "remote", "get-url", "origin"], cwd=repo_dir).strip()
    if not re.search(rf"[:/]{re.escape(repo)}(\.git)?/?$", origin, re.IGNORECASE):
        fail(f"{repo_dir}'s origin is {origin}, not {repo}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--repo-dir", type=Path, default=Path.cwd(), help="the repo's checkout (default: here)")
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            'with [agents] plugin = "repo", enable the plugin in .claude/settings.json; create the missing labels,'
            " and turn on deleting branches on merge"
        ),
    )
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a table")
    args = parser.parse_args()
    repo_dir: Path = args.repo_dir.resolve()
    check_checkout(args.repo, repo_dir)
    ws = watch_module()
    check_requires(repo_dir, ws)  # first, as shipmill checks it before the config's other keys
    # before any change, so a config that can't be read stops --fix with nothing made
    write = gh_writer(repo_dir, ws) if args.fix else ["gh"]

    mode = plugin_mode(repo_dir, ws)  # before any change, as the config's other keys
    settings_path = repo_dir / SETTINGS
    settings = load_settings(settings_path)
    if args.fix:
        settings = fix_plugin(settings_path, settings, mode)

    wanted = wanted_labels(repo_dir, ws)
    have = existing_labels(args.repo)
    missing = [name for name in wanted if name not in have]
    if args.fix:
        create_labels(args.repo, wanted, missing, write)
        missing = []

    def outdated() -> list[Row]:
        return outdated_installs(args.repo, repo_dir, ws)

    plugin = (
        plugin_rows(settings, outdated)
        if mode == REPO
        else host_plugin_rows(settings, lambda: listed_plugins(ws), ws.project_folder(repo_dir), outdated)
    )
    rows = [
        release_row(repo_dir),
        agents_row(repo_dir),
        *prompt_rows(repo_dir, ws),
        *autonomy_rows(repo_dir, ws),
        *product_rows(args.repo, repo_dir, ws),  # reads only: --fix leaves it (S-043-6)
        *plugin,
        *skill_rows(Path.home(), ws),
        labels_row(missing, wanted),
        branch_delete_row(args.repo, args.fix),
        *runner_rows(repo_dir, ws),
        *changelog_rule_rows(repo_dir, ws),
    ]
    for row in rows:
        print(json.dumps({"state": row.state, "detail": row.detail}) if args.json else row.text())
    return exit_code(rows)


def exit_code(rows: list[Row]) -> int:
    """0 when every row but a warning is done, 1 otherwise"""
    return 0 if all(row.state in DONE for row in rows if row.state not in WARNINGS) else 1


if __name__ == "__main__":
    sys.exit(main())
