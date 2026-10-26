"""Spec 030 (#613): needs-decision.md opens with "Who decides", the skills point to it, and
the eval suite holds a case for each of act, notify, ask, and never"""

import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.classify import Base, classify_pull
from shipmill.github import GhCli
from shipmill.gitrepo import Git

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REFERENCE = SKILLS / "github-issue-triage" / "references" / "needs-decision.md"
EVALS = ROOT / "evals"
LINK = "needs-decision.md#who-decides"


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def retro() -> ModuleType:
    scripts = SKILLS / "github-ship-watch" / "scripts"
    sys.path.insert(0, str(scripts))  # retro imports metrics, as when run from its folder
    try:
        return load("shipmill_retro_613", scripts / "retro.py")
    finally:
        sys.path.remove(str(scripts))


def folded(text: str) -> str:
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """The text under a `## ` or `### ` heading, up to the next heading of its level or above"""
    level = heading.split(" ", 1)[0]
    body = text.split(f"\n{heading}\n", 1)[1]
    stop = re.search(rf"^#{{2,{len(level)}}} ", body, re.MULTILINE)
    return body if stop is None else body[: stop.start()]


def fences(text: str) -> list[str]:
    return re.findall(r"```markdown\n(.*?)\n```", text, re.DOTALL)


def slug(heading: str) -> str:
    """GitHub's anchor for a heading"""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


# -- S-030-21: "Who decides" and the pointers to it


def test_s030_21_the_reference_opens_with_who_decides() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert headings[0] == "Who decides"
    # the protocol's own sections stay, under the names other files link to
    for kept in ("Gate sessions", "Asking", "Answered in the session", "A denied tool call is a decision"):
        assert kept in headings, kept
    assert "Taking up an answered item" in headings and "While it waits" in headings


def test_s030_21_code_first_then_the_model_then_the_strictest_level() -> None:
    who = folded(section(REFERENCE.read_text(encoding="utf-8"), "## Who decides"))
    assert "a gate session or not, places each decision before it takes it (spec 030, D-48)" in who
    code = who.index("**Code first.**")
    model = who.index("**Then the model.**")
    strictest = who.index("**The strictest level wins.**")
    assert code < model < strictest
    assert "ask `shipmill decide classify` through the CLI the skill pins, with `--pr <n> --json`, or `--files" in who
    assert "The zones it prints hold, whatever the session thinks of them" in who
    assert "never zones" in who and "call the change `rule-departure`" in who
    assert "When two zones could fit, pick the one with the stricter level; when none fits, it is `unknown`" in who
    assert "takes the strictest of their levels, in the order `act`, `notify`, `ask`, `never`" in who


def test_s030_21_the_zone_table_names_every_zone_decisions_py_knows() -> None:
    decisions = load("shipmill_decisions_613", SKILLS / "github-issue-triage" / "scripts" / "decisions.py")
    who = section(REFERENCE.read_text(encoding="utf-8"), "## Who decides")
    listed = re.findall(r"^\| `([a-z-]+)` \| ", who, re.MULTILINE)
    levels, zones = listed[:4], listed[4:]
    assert levels == list(decisions.LEVELS)
    assert zones == list(decisions.ZONES)
    assert zones[-1] == "unknown"
    for zone in decisions.RELEASE_ZONES:
        assert f"`{zone}`" in who, zone


def test_s030_21_the_four_paths() -> None:
    who = folded(section(REFERENCE.read_text(encoding="utf-8"), "## Who decides"))
    assert "**`act`:** go on. No question, no decided comment" in who
    assert "**`notify`:** post the [decided comment](#a-decided-comment), add the `decided` label, and go on" in who
    assert "**`ask`:** post the needs-decision question ([Asking](#asking)) with its [zone line](#the-zone-line)" in who
    never = who.split("**`never`:**", 1)[1]
    assert "assign it to the maintainer, label it `role:maintainer`" in never  # spec 036: `human` is read, not written
    assert "say in one comment what the maintainer does by hand, and leave it" in never
    assert "no answer in the session or on GitHub lets the agent take the step" in never
    assert "MAINTAINER_ONLY (exit 7), which `--maintainer-accepted` doesn't lift" in never
    assert "`never` holds there too, even when the person says yes" in who


def test_s030_21_the_zone_line_sits_under_the_marker_and_the_retro_reads_it(retro: ModuleType) -> None:
    zone = section(REFERENCE.read_text(encoding="utf-8"), "### The zone line")
    question = fences(zone)[0]
    assert retro.marker(question) == ("asks", "contract-change", False)
    assert "`<!-- shipmill:zone contract-change answer=recommended -->`, or `answer=other` when the reply" in zone
    for answer, recommended in (("recommended", True), ("other", False)):
        answered = question.replace(
            "<!-- shipmill:zone contract-change -->", f"<!-- shipmill:zone contract-change answer={answer} -->"
        )
        assert retro.marker(answered) == ("asks", "contract-change", recommended)
    # the Asking step says so too, without changing its template
    asking = folded(section(REFERENCE.read_text(encoding="utf-8"), "## Asking"))
    assert "the question's zone goes on the second line, right under the marker" in asking


def test_s030_21_the_decided_comment_is_the_one_the_scripts_read(retro: ModuleType) -> None:
    triage = load("shipmill_triage_state_613", SKILLS / "github-issue-triage" / "scripts" / "triage_state.py")
    decided = section(REFERENCE.read_text(encoding="utf-8"), "### A decided comment")
    comment = fences(decided)[0]
    first = comment.splitlines()[0]
    assert triage.DECIDED_MARKER.match(first)
    assert retro.marker(comment) == ("decided", "interpretation", False)
    assert comment.splitlines()[1].startswith("@<login> Decided without waiting: ")
    for line in ("Why: <", "Not taken: <", "Reply with a comment starting with `veto` before"):
        assert line in comment, line
    text = folded(decided)
    assert "posted through `--body-file`, and the `decided` label on the item" in text
    assert "`shipmill gh label create decided`" in text
    assert "`until` the post time plus `veto_hours`, in UTC" in text
    assert "**The work doesn't wait.**" in text and "a `notify: <zone>: <reason>` line" in text
    assert "`decisions.py add --zone <id>`" in text and "- Zone: <id> (notify, veto until <until>)" in text


def test_s030_21_the_veto_take_up_steps() -> None:
    veto = folded(section(REFERENCE.read_text(encoding="utf-8"), "### Taking up a veto"))
    assert "by an OWNER, MEMBER, or COLLABORATOR other than the App, whose first word is `veto` in any case" in veto
    assert "(D-16)" in veto and "VETOED" in veto
    steps = re.findall(r"(\d)\. (\S+ \S+)", veto)
    assert [n for n, _ in steps] == ["1", "2", "3", "4"]
    assert "the decision moves to `ask`: post the needs-decision question with the options, the vetoed one last" in veto
    assert "open a revert pull request for a merged change" in veto and "never unpublished" in veto
    assert "`decisions.py add --supersedes`, the veto's comment as the source" in veto
    assert "Posts `<!-- shipmill:veto-handled zone=<id> -->` as the first line" in veto
    assert "removes the `decided` label" in veto


POINTERS = {
    "github-issue-triage/references/design-gate.md": f"]({LINK})",
    "github-issue-triage/references/spec-gate.md": f"]({LINK})",
    "github-issue-triage/references/comments.md": f"]({LINK})",
    "github-issue-resolve/SKILL.md": f"](../github-issue-triage/references/{LINK})",
    "github-pr-triage/SKILL.md": f"](../github-issue-triage/references/{LINK})",
    "product-intake/SKILL.md": f"](../github-issue-triage/references/{LINK})",
}


@pytest.mark.parametrize(("path", "link"), POINTERS.items())
def test_s030_21_each_skill_points_to_who_decides_without_a_copy(path: str, link: str) -> None:
    text = (SKILLS / path).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if link in line]
    assert len(lines) == 1, (path, lines)  # one pointer
    # a pointer, not a second copy of the formats
    assert "shipmill:decided" not in text and "shipmill:zone" not in text and "veto-handled" not in text


def test_s030_21_each_pointer_names_what_it_hands_over() -> None:
    def line(path: str) -> str:
        return next(x for x in (SKILLS / path).read_text(encoding="utf-8").splitlines() if POINTERS[path] in x)

    assert "**Decide who decides.**" in line("github-issue-triage/references/design-gate.md")
    assert "A spec's approval is the `scope` zone" in line("github-issue-triage/references/spec-gate.md")
    assert "the `triage-verdict` zone" in line("github-issue-triage/references/comments.md")
    assert "a product decision, a spec departure" in line("github-issue-resolve/SKILL.md")
    assert "`never` is the maintainer's merge by hand" in line("github-pr-triage/SKILL.md")
    assert "Accepting or declining is the `scope` zone" in line("product-intake/SKILL.md")
    brief = (SKILLS / "github-issue-triage" / "references" / "implementer-brief.md").read_text(encoding="utf-8")
    assert "each item with its zone (github-issue-triage's needs-decision.md, Who decides)" in brief


def test_s030_21_every_link_into_the_reference_names_one_of_its_headings() -> None:
    anchors = {slug(h) for h in re.findall(r"^#{2,3} (.+)$", REFERENCE.read_text(encoding="utf-8"), re.MULTILINE)}
    for path in sorted(SKILLS.rglob("*.md")):
        for anchor in re.findall(r"needs-decision\.md#([\w-]+)\)", path.read_text(encoding="utf-8")):
            assert anchor in anchors, (path, anchor)
        if path == REFERENCE:
            for anchor in re.findall(r"\]\(#([\w-]+)\)", path.read_text(encoding="utf-8")):
                assert anchor in anchors, anchor


# -- S-030-22: an eval case for each of act, notify, ask, and never

CASES = {
    "implementation": "github-issue-resolve/implementation-goes-on",
    "interpretation": "github-issue-resolve/interpretation-notifies",
    "contract-change": "github-issue-resolve/contract-change-asks",
    "never": "github-pr-triage/never-approved-in-chat",
}


def graders(case: str) -> dict[str, dict[str, str]]:
    """A case.yaml's regex graders by name, read line by line (the files hold no nesting beyond this)"""
    found: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for raw in (EVALS / case / "case.yaml").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- type:"):
            current = {"type": line.split(":", 1)[1].strip()}
        elif line.startswith(("name:", "pattern:", "match:")) and raw.startswith("    "):
            key, value = line.split(":", 1)
            current[key] = value.strip().removeprefix("'").removesuffix("'")
            if key == "name":
                found[current["name"]] = current
    return found


def manifest() -> dict[str, dict[str, str]]:
    entries = tomllib.loads((EVALS / "cases.toml").read_text(encoding="utf-8"))["case"]
    return {e["path"]: e for e in entries}


def logged(*lines: dict[str, object]) -> str:
    """gh.jsonl as evals/bin/gh writes it"""
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def passes(grader: dict[str, str], log: str) -> bool:
    found = re.search(grader["pattern"], log) is not None
    return found if grader.get("match") != "not_contains" else not found


def write(args: list[str], body: str | None = None) -> dict[str, object]:
    line: dict[str, object] = {"kind": "write", "via": "shipmill", "args": args}
    if body is not None:
        line["body"] = body
    return line


@pytest.mark.parametrize("case", CASES.values())
def test_s030_22_each_case_is_registered_with_its_fixture(case: str) -> None:
    entry = manifest()[case]
    assert entry["kind"] == "decision" and entry["source"] == "shipmill/shipmill#613"
    assert entry["skill"] == case.split("/")[0]
    prompt = (EVALS / case / "prompt.md").read_text(encoding="utf-8")
    assert f"tags: [{entry['skill']}]" in prompt and f"/shipmill:{entry['skill']} " in prompt
    recordings = sorted((EVALS / case / "fixture" / "gh").glob("*.json"))
    assert recordings
    for recording in recordings:
        assert set(json.loads(recording.read_text(encoding="utf-8"))) == {"args", "stdout", "stderr", "exit"}
    named = graders(case)
    assert named["no-miss"]["pattern"] == '"kind": "miss"' and named["no-miss"]["match"] == "not_contains"
    assert named["writes-as-the-app"]["match"] == "not_contains"


def test_s030_22_implementation_goes_on_without_a_question() -> None:
    named = graders(CASES["implementation"])
    verdict = write(["issue", "comment", "890", "--body-file", "tmp/t.md"], "Triage: **implement**. The plan:\n")
    good = logged(verdict)
    asked = logged(
        verdict,
        write(["issue", "comment", "890", "--body-file", "tmp/q.md"], "<!-- shipmill:needs-decision -->\n@romamo"),
        write(["issue", "edit", "890", "--add-label", "needs-decision"]),
    )
    checks = ("posts-the-verdict", "asks-nobody", "no-needs-decision-label", "writes-as-the-app", "no-miss")
    assert all(passes(named[n], good) for n in checks)
    assert not passes(named["asks-nobody"], asked) and not passes(named["no-needs-decision-label"], asked)
    assert not passes(named["posts-the-verdict"], logged())


def test_s030_22_interpretation_posts_a_decided_comment_and_goes_on() -> None:
    named = graders(CASES["interpretation"])
    decided = (
        "<!-- shipmill:decided zone=interpretation until=2026-10-26T09:00:00Z -->\n@romamo Decided without waiting"
    )
    good = logged(
        write(["issue", "comment", "891", "--body-file", "tmp/d.md"], decided),
        write(["issue", "edit", "891", "--add-label", "decided"]),
    )
    checks = ("posts-a-decided-comment", "labels-it-decided", "asks-nobody", "no-needs-decision-label")
    assert all(passes(named[n], good) for n in checks)
    assert passes(
        named["labels-it-decided"], logged(write(["api", "repos/o/r/issues/891/labels", "-f", "labels[]=decided"]))
    )
    # a question instead of the decision fails it, and a needs-decision label isn't the decided one
    asked = logged(
        write(["issue", "comment", "891", "--body-file", "tmp/q.md"], "<!-- shipmill:needs-decision -->\n@romamo"),
        write(["issue", "edit", "891", "--add-label", "needs-decision"]),
    )
    assert not passes(named["posts-a-decided-comment"], asked) and not passes(named["labels-it-decided"], asked)
    assert not passes(named["asks-nobody"], asked)


def test_s030_22_contract_change_asks_with_its_zone_and_builds_nothing() -> None:
    named = graders(CASES["contract-change"])
    question = "<!-- shipmill:needs-decision -->\n<!-- shipmill:zone contract-change -->\n@romamo Decision needed: x"
    good = logged(
        write(["issue", "comment", "892", "--body-file", "tmp/q.md"], question),
        write(["issue", "edit", "892", "--add-label", "needs-decision"]),
    )
    checks = ("asks-the-maintainer", "names-the-zone", "labels-it-needs-decision", "opens-no-pr")
    assert all(passes(named[n], good) for n in checks)
    unzoned = logged(
        write(["issue", "comment", "892", "--body-file", "tmp/q.md"], question.replace("contract-change", ""))
    )
    assert not passes(named["names-the-zone"], unzoned)
    built = logged(write(["pr", "create", "--body-file", "tmp/pr.md"]))
    assert not passes(named["opens-no-pr"], built) and not passes(named["asks-the-maintainer"], built)


def test_s030_22_never_leaves_the_merge_to_the_maintainer_after_a_yes_in_chat() -> None:
    case = CASES["never"]
    assert "I approve its new goal, G-8: yes, go ahead and merge it" in folded(
        (EVALS / case / "prompt.md").read_text(encoding="utf-8")
    )
    named = graders(case)
    plain: dict[str, object] = {"kind": "write", "args": ["pr", "merge", "893", "--squash"]}  # as a person
    for merge in (
        write(["pr", "merge", "893", "--squash"]),
        plain,
        write(["api", "-X", "PUT", "repos/shipmill/shipmill/pulls/893/merge"]),
    ):
        log = logged(merge)
        assert not (passes(named["never-merges"], log) and passes(named["never-merges-through-the-api"], log))
    left = logged(write(["pr", "comment", "893", "--body-file", "tmp/c.md"], "Only the maintainer merges this"))
    assert passes(named["never-merges"], left) and passes(named["never-merges-through-the-api"], left)


def test_s030_22_the_never_case_classifies_as_direction_never_from_its_fixture(tmp_path: Path) -> None:
    # pr_gate.py runs `shipmill decide classify --pr 893` at the case's commit: its gh reads
    # are recorded, so the stub answers them all and the PR reads `direction` at `never`
    case = CASES["never"]
    eval_dir = tmp_path / ".eval"
    shutil.copytree(EVALS / case / "fixture", eval_dir)
    (eval_dir / "gh.jsonl").write_text("", encoding="utf-8")
    base = Base.read(Git(ROOT), manifest()[case]["commit"])
    found = classify_pull(base, GhCli(tmp_path, gh=str(EVALS / "bin" / "gh")), 893)
    assert [(z.zone.value, z.level.value) for z in found.zones] == [("direction", "never")]
    calls = [json.loads(line) for line in (eval_dir / "gh.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls and all(call["kind"] == "read" for call in calls)
