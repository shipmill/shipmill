"""Spec 084, Reports and docs: release-lanes.md documents the probes and what a difference
does, and github-issue-resolve tells an implementer to add a `Changes answers:` line"""

from pathlib import Path

from shipmill.operate import COMPARE_PREFIX, compare_incident_title
from shipmill.version import Version

ROOT = Path(__file__).resolve().parents[1]


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def section(doc: str, heading: str) -> str:
    return doc.split(heading, 1)[1].split(" ### ", 1)[0].split(" ## ", 1)[0]


def test_s084_13_release_lanes_documents_the_probes_and_the_environment_url() -> None:
    environments = section(folded("docs", "release-lanes.md"), "### Environments")
    assert "[[environments.production.probes]]" in environments
    for key in ('name = "items"', 'path = "/api/items?limit=100"', 'ignore = ["/generated_at"'):
        assert key in environments, key
    assert "'*' matches any one segment" in environments
    assert "more than 20 probes in one environment fails the config" in environments
    assert "A probe is a `GET` with no body, cookie, or credential" in environments
    assert "environment: { name, url }" in environments
    assert "GitHub Actions writes the `url` as the deployment status's `environment_url`" in environments
    assert "name: ${{ inputs.environment }} url: ${{ steps.deploy.outputs.url }}" in environments
    assert "An environment without probes compares nothing" in environments


def test_s084_13_release_lanes_says_what_a_difference_does() -> None:
    operate = section(folded("docs", "release-lanes.md"), "### Operate: health, bake, promotion, and rollback")
    compare = operate.split("**Comparing answers.**", 1)[1]
    assert "```markdown Changes answers: items, orders ```" in compare
    for description in (
        "same answers as <previous tag> on <n> probes",
        "differs from <previous tag> on <names>, explained by #N",
        "answers differ from <previous tag> on <names>",
    ):
        assert f"`{COMPARE_PREFIX} {description}`" in compare, description
    # the title the code writes, with the placeholders the doc names
    title = compare_incident_title("<env>", Version(1, 1, 0), Version(1, 0, 0))
    assert f"titled `{title.replace('v1.1.0', '<tag>').replace('v1.0.0', '<previous tag>')}`" in compare
    assert "**Opens the incident at once**, without waiting for `rollback_after`" in compare
    assert "its hidden line holding `cause=compare`" in compare
    assert "it quotes no value of either answer" in compare
    assert "**Rolls back** as a failed check does, under `rollback` in `[autonomy]` and the hold" in compare
    assert "`--dry-run` sends the probes and says what it would write" in compare
    assert "`(unstable: <names>)` and `(unchecked: <names>)`" in compare


def test_s084_13_the_resolve_skill_asks_for_a_changes_answers_line() -> None:
    resolve = folded("skills", "github-issue-resolve", "SKILL.md")
    assert "When the change alters an answer a declared probe covers" in resolve
    assert "add a line `Changes answers: <probe names>` to the body" in resolve
