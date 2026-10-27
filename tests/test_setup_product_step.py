"""Spec 043, #722: shipmill-setup's Product step under The gate, its description, and its eval case"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "shipmill-setup" / "SKILL.md"
CASE = ROOT / "evals" / "shipmill-setup" / "product-component"


def folded(path: Path) -> str:
    """A file with its line wrapping folded, so a statement reads as one line"""
    return " ".join(path.read_text(encoding="utf-8").split())


def gate() -> str:
    """The body of `## The gate`, folded, up to the next `## `"""
    text = folded(SKILL)
    return text.split("## The gate ", 1)[1].split(" ## ", 1)[0]


def product_step() -> str:
    """The Product step: from its heading to the gate's step 3, the App's identity"""
    body = gate()
    assert body.count("**Product (spec 043).**") == 1
    return body.split("**Product (spec 043).**", 1)[1].split(" 3. **Its own identity", 1)[0]


def test_s043_7_the_step_sits_under_the_gate_after_config_and_before_the_app() -> None:
    body = gate()
    assert body.index("2. **Config.**") < body.index("**Product (spec 043).**") < body.index("3. **Its own identity")
    # asked in the same round as the App and mode questions (D-20)
    assert "the Product step's question below joins that round" in body


def test_s043_7_the_step_asks_whether_the_repo_is_one_of_several() -> None:
    step = product_step()
    assert '"Is `<owner/repo>` one of several repos that make up one product?"' in step
    assert "in the same round as the App and mode questions (D-20)" in step
    assert "through the needs-decision protocol in a gate session (D-21)" in step
    assert '"No, it stands alone" (recommended when no sibling was found)' in step
    assert '"Yes" (recommended when one was)' in step
    assert "On `PRODUCT_SIBLINGS`, list the siblings the row names" in step


def test_s043_7_on_yes_it_asks_for_the_home_and_the_components() -> None:
    step = product_step()
    assert "**On yes, ask for the home and the components.**" in step
    assert "the maintainer may name other repos, of any owner" in step


def test_s043_7_the_step_writes_one_of_the_three_forms_with_agents() -> None:
    step = product_step()
    assert "in the same pull request as the `[agents]` section" in step
    assert 'In the home: `[product] repos = ["<owner/component>", ...]`' in step
    assert 'In a component: `[product] home = "<owner/home>"`' in step
    assert 'On "No, it stands alone": `[product] standalone = true`' in step


def test_s043_7_product_listed_writes_home_with_no_question() -> None:
    step = product_step()
    assert "**`PRODUCT_LISTED`:**" in step
    assert 'Write the `[product] home = "<that sibling>"` line the row names, with no question' in step


def test_s043_7_the_keys_are_the_ones_the_config_parser_accepts() -> None:
    # ProductConfig allows exactly home, repos, and standalone (S-038-1, S-043-1)
    agents = (ROOT / "src" / "shipmill" / "agents.py").read_text(encoding="utf-8")
    assert 'table.allow("home", "repos", "standalone")' in agents
    written = set(re.findall(r"`\[product\] (\w+) =", product_step()))
    assert written == {"home", "repos", "standalone"}


def test_s043_8_the_step_writes_only_its_own_config_and_prints_the_rest() -> None:
    step = product_step()
    assert "**Write only this checkout's config** (D-14)" in step
    assert "never another repo's config, its pull request, or a `$CR gh -R <other repo>` write" in step
    assert (
        "print one line naming the table that repo needs and `/shipmill:shipmill-setup <repo>` to run in its checkout"
        in step
    )
    assert "show the list to the maintainer before the pull request opens" in step
    assert 'acme/api: [product] home = "acme/product" run /shipmill:shipmill-setup acme/api in its checkout' in step


def test_s043_8_the_step_names_app_install_for_an_uncovered_component() -> None:
    step = product_step()
    assert "for each component the App doesn't cover yet, run `$CR app-install <owner/component>`" in step
    # $CR is the pinned CLI the skill already defines
    assert 'CR="uvx shipmill==' in SKILL.read_text(encoding="utf-8")


def test_s043_9_the_step_lists_what_works_today_and_what_does_not_yet() -> None:
    step = product_step()
    works = step.split("**Works today:**", 1)[1].split("**Not yet:**", 1)[0]
    for named in (
        "`shipmill app-token --product`",
        "`shipmill gh --product`",
        "an `upstream` issue",
        "`upstream_state.py`",
        "`chains.py link --product --child`",
    ):
        assert named in works, named
    not_yet = step.split("**Not yet:**", 1)[1]
    assert "a plan across repos (D-46, on hold)" in not_yet
    assert "Each line goes when its issue closes" in not_yet
    # #604 and #596 closed before this step was written, so they are named as done
    assert "(shipmill/shipmill#604, closed)" in works
    assert "(shipmill/shipmill#596, closed)" in works


def test_s043_10_the_step_relays_doctors_product_lines_and_checks_nothing_itself() -> None:
    step = product_step()
    assert "Run no check of the links back of your own" in step
    assert "relay each of its lines with its fix" in step
    # S-038-27: the App on each listed repo; the line's text and fix are doctor's
    doctor = (ROOT / "src" / "shipmill" / "doctor.py").read_text(encoding="utf-8")
    assert "the coordinator can't reach it: run {fix}" in doctor and "app-install {listed}" in doctor
    assert "(S-038-27)" in step and "the coordinator can't reach it: run $CR app-install <repo>" in step
    # S-038-28: each listed repo's [product] home, with doctor's fix
    assert 'set [product] home = "{home}" in {listed}' in doctor
    assert "(S-038-28)" in step
    assert "`<repo>'s .github/shipmill.toml has no [product] home`" in step
    assert '`set [product] home = "<home>" in <repo>\'s .github/shipmill.toml`' in step
    # S-038-30: a component's home lists it
    assert 'add "{repo}" to [product] repos in {home}' in doctor
    assert "(S-038-30)" in step
    assert "`<home>'s [product] repos doesn't list <repo>`" in step
    assert '`add "<repo>" to [product] repos in <home>\'s .github/shipmill.toml`' in step


def test_s043_11_the_description_names_the_case() -> None:
    front = SKILL.read_text(encoding="utf-8").split("---\n", 2)[1]
    (line,) = [x for x in front.splitlines() if x.startswith("description: ")]
    description = line.removeprefix("description: ")
    assert "connect several repos as one product (a home repo and its components)" in description
    assert len(description) <= 1024, len(description)


def test_s043_11_the_eval_case_writes_home_in_the_component_only() -> None:
    manifest = tomllib.loads((ROOT / "evals" / "cases.toml").read_text(encoding="utf-8"))
    (entry,) = [c for c in manifest["case"] if c["path"] == "shipmill-setup/product-component"]
    assert entry["skill"] == "shipmill-setup" and entry["source"] == "shipmill/shipmill#722"
    prompt = (CASE / "prompt.md").read_text(encoding="utf-8")
    body = prompt.split("---\n", 2)[2]
    assert body.lstrip().startswith("connect acme/api and acme/web to acme/product as one product\n")
    assert "/shipmill:" not in body.splitlines()[1]  # reached by the description, no slash command
    case = (CASE / "case.yaml").read_text(encoding="utf-8")
    assert "tool: Skill" in case
    assert "pattern: '\\[product\\]\\s+home\\s*=\\s*\"acme/product\"'" in case
    assert "pattern: '\\n\\s*(repos|standalone)\\s*='" in case
    assert 'pattern: \'"kind": "(write|refused)"\'' in case
    assert re.search(r"name: no-miss\n\s+target: \{source: file, path: \.eval/gh\.jsonl\}", case)
