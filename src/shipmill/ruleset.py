"""`shipmill ruleset` (spec 054): the body of a branch ruleset that protects the default branch
and lets the App land, for `gh api -X POST repos/<repo>/rulesets --input -`; it writes nothing
and calls no API"""

import re
from pathlib import Path
from typing import Any

from shipmill import cli_command
from shipmill.errors import ReleaseError
from shipmill.policy import Lane, Policy

CALLER = Path(".github") / "workflows" / "release.yml"
NAME = "shipmill: protected default branch"
RELEASE_BRANCHES = "refs/heads/release/*"  # where a hotfix lane lands
_BOT_WORKFLOWS = frozenset({"prepare.yml", "land.yml"})
_LOCAL_USES = re.compile(r"^\s+uses:\s*\./\.github/workflows/(?P<file>[\w.-]+\.ya?ml)\s*(?:#.*)?$", re.MULTILINE)


def ci_workflow(root: Path) -> Path:
    """The CI workflow the release workflow calls on its release commit: its one local
    `uses: ./.github/workflows/<file>` that isn't prepare.yml or land.yml"""
    caller = root / CALLER
    if not caller.is_file():
        raise ReleaseError(
            f"no {CALLER}, whose CI workflow names the required checks; `{cli_command()} init` writes one"
        )
    called = sorted({m["file"] for m in _LOCAL_USES.finditer(caller.read_text(encoding="utf-8"))} - _BOT_WORKFLOWS)
    if len(called) != 1:
        found = ", ".join(called) or "none"
        raise ReleaseError(f"{CALLER} must call one local CI workflow to name the required checks; it calls {found}")
    path = caller.parent / called[0]
    if not path.is_file():
        raise ReleaseError(f"{CALLER} calls {called[0]}, which isn't in {path.parent.relative_to(root)}")
    return path


def check_names(workflow: Path) -> tuple[str, ...]:
    """The check each job of the workflow reports on a pull request: its `name:`, else its id.
    A text check, not a YAML parse; a job whose check name can't be told from the text (a
    matrix, a reusable workflow's call, a name with an expression) raises ReleaseError"""
    text = workflow.read_text(encoding="utf-8")
    jobs = re.search(r"^jobs:[ \t]*(?:#.*)?$(?P<body>(?:\n(?:[ \t#].*)?)*)", text, re.MULTILINE)
    if jobs is None:
        raise ReleaseError(f"{workflow.name} has no jobs")
    found: dict[str, dict[str, str]] = {}
    job_indent: int | None = None
    key_indent: int | None = None
    current = ""
    for line in jobs["body"].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if job_indent is None or indent <= job_indent:
            job_indent, key_indent = indent, None
            current = stripped.split(":", 1)[0].strip().strip("'\"")
            found[current] = {}
            continue
        if key_indent is None:
            key_indent = indent
        if indent == key_indent and ":" in stripped:
            key, _, value = stripped.partition(":")
            found[current][key.strip()] = re.sub(r"\s+#.*$", "", value).strip().strip("'\"")
    names = []
    for job, keys in found.items():
        if "strategy" in keys or "uses" in keys or "${{" in keys.get("name", ""):
            raise ReleaseError(
                f"{workflow.name}'s job {job} reports checks whose names its text doesn't tell (a matrix, a reusable"
                " workflow's call, or a name with an expression): give it a plain name:, or add its checks to the"
                " printed ruleset by hand"
            )
        names.append(keys.get("name") or job)
    if not names:
        raise ReleaseError(f"{workflow.name} has no jobs")
    return tuple(names)


def ruleset(policy: Policy, root: Path) -> dict[str, Any]:
    """S-054-17: the ruleset's body. Without [agents] app_id it raises ReleaseError (exit 2):
    a protected branch on an organization repository lands unattended only through an App"""
    app_id = None if policy.agents is None else policy.agents.app_id
    if app_id is None:
        raise ReleaseError(
            "the ruleset lets the App land past its rules, and the config sets no [agents] app_id: set it in"
            " .github/shipmill.toml to the App's id"
        )
    include = ["~DEFAULT_BRANCH"] + ([RELEASE_BRANCHES] if Lane.HOTFIX in policy.lanes else [])
    checks = [{"context": name} for name in check_names(ci_workflow(root))]
    return {
        "name": NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": include, "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,  # the maintainer raises it
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {"strict_required_status_checks_policy": False, "required_status_checks": checks},
            },
        ],
        "bypass_actors": [{"actor_id": app_id, "actor_type": "Integration", "bypass_mode": "always"}],
    }
