"""Spec 071, A component reads its product's direction: in a checkout whose config sets
`[product] home`, `shipmill product show` adds the home's goals and non-goals and `shipmill
product check` checks each serves line's ids against the home's Goals, both reading the home's
docs/product.md on its default branch through spec 065's read token. No test reaches the
network: GitHub is HomeApi"""

import base64
import datetime as dt
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app import Answer
from shipmill.cli import main
from shipmill.doctor import Check, direction_check
from shipmill.errors import ReleaseError
from shipmill.product import DIRECTION, Section, read

from .test_app import APP_ID, FakeSigner, key_file
from .test_app_gh import WITH_APP, checkout
from .test_component_read import READ
from .test_product_serves import PLAIN, SERVED

ROOT = Path(__file__).resolve().parents[1]
HOME = "romamo/product"
COMPONENT = "romamo/demo"  # checkout()'s origin
CONFIG = WITH_APP + f'\n[product]\nhome = "{HOME}"\n'
HOME_CONFIG = WITH_APP + f'\n[product]\nrepos = ["{COMPONENT}", "romamo/web"]\n'
HOME_DIRECTION = """\
# Acme

## Mission

The data platform partners build on.

## Users

- U-1: A partner

## Goals

- G-1: Partners ship in a week
  measure: lead_time_p90 < 7d
- G-2: Partners trust the numbers
- G-4: Partners pay for what they use

## Non-goals

- N-1: Raw data dumps
- N-3: An on-premises edition

## Quality bar

- Q-1: Every change is reviewed
"""
HOME_GOALS = HOME_DIRECTION[HOME_DIRECTION.index("## Goals") : HOME_DIRECTION.index("## Non-goals")]
HOME_MOVED = HOME_DIRECTION.replace(HOME_GOALS, "## Goals\n\nSee [Goals](product/goals.md).\n\n")
HOUR = dt.timedelta(hours=1)


def b64(text: str) -> Answer:
    content = base64.b64encode(text.encode()).decode()
    return Answer(200, json.dumps({"type": "file", "encoding": "base64", "content": content}))


@dataclass
class HomeApi:
    """GitHub with the App installed on the home: /app, the home's installation, access tokens
    (token-1, token-2, ...), and the home's files through the contents API, from files (a path
    missing answers 404, one mapped to an int answers that status)"""

    files: dict[str, str | int] = field(
        default_factory=lambda: {".github/shipmill.toml": HOME_CONFIG, "docs/product.md": HOME_DIRECTION}
    )
    installed: bool = True
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)  # method, path, token
    posts: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append(("GET", path, token))
        if path == "/app":
            return Answer(200, json.dumps({"slug": "demo-agent", "id": APP_ID}))
        if path == f"/repos/{HOME}/installation":
            if not self.installed:
                return Answer(404, '{"message": "Not Found"}')
            return Answer(200, json.dumps({"id": 55, "permissions": READ}))
        prefix = f"/repos/{HOME}/contents/"
        if path.startswith(prefix):
            found = self.files.get(path.removeprefix(prefix))
            if found is None:
                return Answer(404, '{"message": "Not Found"}')
            if isinstance(found, int):
                return Answer(found, '{"message": "Server Error"}')
            return b64(found)
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.calls.append(("POST", path, token))
        self.posts.append((path, body))
        names = body["repositories"]
        assert isinstance(names, list)
        expires = (dt.datetime.now(dt.UTC) + HOUR).isoformat().replace("+00:00", "Z")
        answer = {
            "token": f"token-{len(self.posts)}",
            "expires_at": expires,
            "repositories": [{"full_name": f"romamo/{n}"} for n in names],
            "permissions": body["permissions"],
        }
        return Answer(201, json.dumps(answer))


class NoNetwork:
    """A GitHub that must not be asked anything"""

    def get(self, path: str, token: str | None) -> Answer:
        raise AssertionError(f"GET {path}: nothing of another repo may be read")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        raise AssertionError(f"POST {path}: nothing of another repo may be read")


def component(tmp_path: Path, text: str = SERVED, config: str | None = CONFIG) -> Path:
    root = checkout(tmp_path, config)
    (root / DIRECTION).parent.mkdir(parents=True, exist_ok=True)
    (root / DIRECTION).write_text(text, encoding="utf-8")
    return root


def run(root: Path, tmp_path: Path, api: object, *args: str, key: bool = True) -> int:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environ = {"SHIPMILL_APP_KEY": str(key_file(tmp_path))} if key else {}
    return main(
        ["--repo", str(root), "product", *args],
        api=api,  # type: ignore[arg-type]
        signer=FakeSigner(),
        environ=environ,
        home=home,
    )


def out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


# -- S-071-3 ---------------------------------------------------------------------------------


def test_s071_3_check_refuses_a_serves_id_the_homes_goals_dont_list_naming_file_line_id_and_home(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = HomeApi()
    root = component(tmp_path, SERVED.replace("  serves: G-1\n", "  serves: G-1, G-3\n"))
    assert run(root, tmp_path, api, "check") == 1
    assert out(capsys) == (
        f"{DIRECTION}:17: G-3 is not a goal of the product's direction, {HOME}:{DIRECTION} on its default branch; "
        "name a goal its Goals list, or remove G-3\n"
    )


def test_s071_3_a_goal_the_home_retired_is_refused_too(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    api = HomeApi()
    api.files["docs/product.md"] = HOME_DIRECTION.replace("- G-4: Partners pay for what they use\n", "")
    assert run(component(tmp_path), tmp_path, api, "check") == 1
    assert out(capsys).startswith(f"{DIRECTION}:15: G-4 is not a goal of the product's direction, {HOME}:")


@pytest.mark.parametrize("moved", [False, True], ids=["inline", "moved to docs/product/"])
def test_s071_3_check_exits_0_when_every_id_is_a_goal_of_the_home(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], moved: bool
) -> None:
    api = HomeApi()
    if moved:
        api.files["docs/product.md"] = HOME_MOVED
        api.files["docs/product/goals.md"] = HOME_GOALS
    assert run(component(tmp_path), tmp_path, api, "check") == 0
    assert out(capsys) == f"{DIRECTION}: well formed, 6 items\n"
    read_files = [p.removeprefix(f"/repos/{HOME}/contents/") for m, p, _ in api.calls if "/contents/" in p]
    assert read_files == [".github/shipmill.toml", "docs/product.md", *(["docs/product/goals.md"] if moved else [])]


def test_s071_3_a_component_direction_check_refuses_reads_nothing_of_the_home(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = component(tmp_path, SERVED.replace("  serves: G-1\n", "  serves: G-1, G-1\n"))
    assert run(root, tmp_path, NoNetwork(), "check") == 1
    assert out(capsys) == f"{DIRECTION}:17: a serves line names G-1 twice; it names each goal once\n"


# -- S-071-4 ---------------------------------------------------------------------------------


def test_s071_4_without_a_serves_line_check_reads_nothing_of_the_home(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(component(tmp_path, PLAIN), tmp_path, NoNetwork(), "check", key=False) == 0
    assert out(capsys) == f"{DIRECTION}: well formed, 6 items\n"


# -- S-071-5 ---------------------------------------------------------------------------------

OWN_NON_GOALS = "## Non-goals\n\n- N-1: A GraphQL API\n"
PRODUCT_NON_GOALS = (
    f"## Product non-goals ({HOME})\n\n- {HOME} N-1: Raw data dumps\n- {HOME} N-3: An on-premises edition\n"
)
PRODUCT_GOALS = (
    f"## Product goals ({HOME})\n\n- {HOME} G-1: Partners ship in a week\n- {HOME} G-2: Partners trust the numbers\n"
    f"- {HOME} G-4: Partners pay for what they use\n"
)


def test_s071_5_show_non_goals_prints_the_components_then_the_products_qualified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = component(tmp_path)
    assert run(root, tmp_path, HomeApi(), "show", "--section", "non-goals") == 0
    assert out(capsys) == f"{OWN_NON_GOALS}\n{PRODUCT_NON_GOALS}"


def test_s071_5_show_goals_prints_the_products_goals_the_same_way(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = component(tmp_path)
    assert run(root, tmp_path, HomeApi(), "show", "--local", "--section", "goals") == 0
    own = out(capsys)
    assert run(root, tmp_path, HomeApi(), "show", "--section", "goals") == 0
    assert out(capsys) == f"{own}\n{PRODUCT_GOALS}"
    assert run(root, tmp_path, HomeApi(), "show", "--section", "goals", "--section", "non-goals") == 0
    assert out(capsys).endswith(f"\n{PRODUCT_GOALS}\n{PRODUCT_NON_GOALS}")
    assert run(root, tmp_path, HomeApi(), "show") == 0  # the whole direction: both, after it
    assert out(capsys) == f"{read(root).render()}\n{PRODUCT_GOALS}\n{PRODUCT_NON_GOALS}"


def test_s071_5_show_of_sections_the_product_has_no_part_of_reads_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = component(tmp_path)
    assert run(root, tmp_path, NoNetwork(), "show", "--section", "quality", "--section", "users") == 0
    assert out(capsys) == read(root).render([Section.USERS, Section.QUALITY])


@pytest.mark.parametrize(
    ("sections", "keys"),
    [
        (["--section", "goals"], ["goals"]),
        (["--section", "non-goals"], ["non_goals"]),
        (["--section", "users", "--section", "non-goals"], ["non_goals"]),
        ([], ["goals", "non_goals"]),
    ],
)
def test_s071_5_show_json_adds_one_product_key_and_leaves_the_components_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sections: list[str], keys: list[str]
) -> None:
    root = component(tmp_path)
    assert run(root, tmp_path, HomeApi(), "show", "--local", "--json", *sections) == 0
    own = json.loads(out(capsys))
    assert run(root, tmp_path, HomeApi(), "show", "--json", *sections) == 0
    shown = json.loads(out(capsys))
    product = shown.pop("product")
    assert shown == own
    assert list(product) == ["home", "name", *keys]
    assert (product["home"], product["name"]) == (HOME, "Acme")
    if "goals" in keys:
        assert [(g["id"], g["text"]) for g in product["goals"]] == [
            ("G-1", "Partners ship in a week"),
            ("G-2", "Partners trust the numbers"),
            ("G-4", "Partners pay for what they use"),
        ]
        assert product["goals"][0]["measure"]["text"] == "lead_time_p90 < 7d"
    if "non_goals" in keys:
        assert product["non_goals"] == [
            {"id": "N-1", "text": "Raw data dumps"},
            {"id": "N-3", "text": "An on-premises edition"},
        ]


# -- S-071-6 ---------------------------------------------------------------------------------


def test_s071_6_the_home_is_read_with_gets_on_its_default_branch_through_a_read_token_over_it_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = HomeApi()
    api.files["docs/product.md"] = HOME_MOVED
    api.files["docs/product/goals.md"] = HOME_GOALS
    root = component(tmp_path)
    assert run(root, tmp_path, api, "show", "--section", "goals") == 0
    # one token, over the home alone, asking only reads
    assert [path for path, _ in api.posts] == ["/app/installations/55/access_tokens"]
    assert api.posts[0][1]["repositories"] == ["product"]
    assert api.posts[0][1]["permissions"] == READ
    # every other request is a GET; every read of a file is of the home, with that token, at no ref
    assert {m for m, _, _ in api.calls} == {"GET", "POST"}
    reads = [(p, t) for m, p, t in api.calls if m == "GET" and p not in ("/app", f"/repos/{HOME}/installation")]
    assert reads == [
        (f"/repos/{HOME}/contents/.github/shipmill.toml", "token-1"),
        (f"/repos/{HOME}/contents/docs/product.md", "token-1"),
        (f"/repos/{HOME}/contents/docs/product/goals.md", "token-1"),
    ]
    assert all("?" not in p for p, _ in reads)  # the default branch: no ref named
    out(capsys)
    # the token is cached with the read tokens (spec 065) and reused: no second mint
    api.calls.clear()
    assert run(root, tmp_path, api, "check") == 0
    assert len(api.posts) == 1
    assert [(m, p) for m, p, _ in api.calls] == [
        ("GET", f"/repos/{HOME}/contents/docs/product.md"),
        ("GET", f"/repos/{HOME}/contents/docs/product/goals.md"),
    ]


# -- S-071-7 ---------------------------------------------------------------------------------


def no_app_id(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    return component(tmp_path, config=f'[product]\nhome = "{HOME}"\n'), HomeApi(), True


def no_key(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    return component(tmp_path), HomeApi(), False


def not_installed(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    return component(tmp_path), HomeApi(installed=False), True


def not_listed(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    api = HomeApi()
    api.files[".github/shipmill.toml"] = WITH_APP + '\n[product]\nrepos = ["romamo/web"]\n'
    return component(tmp_path), api, True


def read_fails(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    api = HomeApi()
    api.files["docs/product.md"] = 502
    return component(tmp_path), api, True


def no_direction(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    api = HomeApi()
    del api.files["docs/product.md"]
    return component(tmp_path), api, True


def broken_grammar(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    api = HomeApi()
    api.files["docs/product.md"] = HOME_DIRECTION.replace("- G-2: Partners", "- X-2: Partners")
    return component(tmp_path), api, True


def moved_file_missing(tmp_path: Path) -> tuple[Path, HomeApi, bool]:
    api = HomeApi()
    api.files["docs/product.md"] = HOME_MOVED
    return component(tmp_path), api, True


CANT_READ = [
    pytest.param(no_app_id, "sets no [agents] app_id", "fix: set [agents] app_id", id="no app_id"),
    pytest.param(no_key, "the read token can't be minted: no App private key at", "fix: put the App's key", id="key"),
    pytest.param(not_installed, "the read token can't be minted", "fix: run `", id="not installed"),
    pytest.param(
        not_listed,
        f"its [product] repos doesn't list {COMPONENT}",
        f'fix: add "{COMPONENT}" to [product] repos in {HOME}',
        id="home doesn't list it",
    ),
    pytest.param(read_fails, f"{HOME}:docs/product.md can't be read", "fix: retry once GitHub answers", id="read"),
    pytest.param(
        no_direction,
        f"GitHub has no docs/product.md on {HOME}'s default branch",
        f"fix: ask the maintainer to write {HOME}'s docs/product.md",
        id="no docs/product.md",
    ),
    pytest.param(
        broken_grammar,
        "breaks the grammar of spec 024; fix: ask the maintainer to fix it (`",
        f"\n  {HOME}:docs/product.md:15: `## Goals` holds G-n items; got X-2",
        id="grammar",
    ),
    pytest.param(
        moved_file_missing, f"{HOME}:docs/product.md:13: `## Goals` moved to docs/product/goals.md", "fix:", id="moved"
    ),
]


@pytest.mark.parametrize(("setup", "why", "fix"), CANT_READ)
@pytest.mark.parametrize("command", [["show"], ["show", "--section", "non-goals"], ["show", "--json"], ["check"]])
def test_s071_7_show_and_check_exit_2_naming_the_home_and_the_fix_printing_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    setup: Callable[[Path], tuple[Path, HomeApi, bool]],
    why: str,
    fix: str,
    command: list[str],
) -> None:
    root, api, key = setup(tmp_path)
    with pytest.raises(ReleaseError) as refused:  # shipmill's run() exits 2 on it
        run(root, tmp_path, api, *command, key=key)
    message = str(refused.value)
    assert message.startswith(HOME), message
    assert why in message and fix in message, message
    assert "or pass --local to read only this checkout's docs/product.md" in message
    assert out(capsys) == ""  # nothing of the component's direction either


# -- S-071-8 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [SERVED, SERVED.replace("  serves: G-1\n", "  serves: G-9\n")])
def test_s071_8_local_reads_nothing_of_the_home_and_gives_the_prior_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    root = component(tmp_path, text)
    direction = read(root)
    assert run(root, tmp_path, NoNetwork(), "check", "--local", key=False) == 0  # ids aren't checked: G-9 passes
    assert out(capsys) == f"{DIRECTION}: well formed, 6 items\n"
    assert run(root, tmp_path, NoNetwork(), "show", "--local", key=False) == 0
    assert out(capsys) == direction.render()
    assert run(root, tmp_path, NoNetwork(), "show", "--local", "--section", "non-goals", key=False) == 0
    assert out(capsys) == OWN_NON_GOALS
    assert run(root, tmp_path, NoNetwork(), "show", "--local", "--json", key=False) == 0
    assert json.loads(out(capsys)) == direction.record(today=dt.datetime.now(dt.UTC).date())
    assert run(root, tmp_path, NoNetwork(), "ids", key=False) == 0  # ids never reads the home
    assert out(capsys).splitlines() == [str(item) for item in direction.all_items()]


def test_s071_8_local_still_checks_a_serves_lines_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = component(tmp_path, SERVED.replace("  serves: G-1\n", "  serves: G-1,G-2\n"))
    assert run(root, tmp_path, NoNetwork(), "check", "--local") == 1
    assert "a serves line names goal ids" in out(capsys)


@pytest.mark.parametrize(
    "config",
    [
        None,
        WITH_APP,
        "[product]\nstandalone = true\n",
        WITH_APP + '\n[product]\nrepos = ["romamo/api"]\n',  # the home itself
    ],
    ids=["no config", "no [product]", "standalone", "the home"],
)
def test_s071_8_a_repo_without_product_home_reads_no_other_repo_and_prints_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str | None
) -> None:
    root = component(tmp_path, PLAIN, config)
    direction = read(root)
    for local in ([], ["--local"]):
        assert run(root, tmp_path, NoNetwork(), "check", *local) == 0
        assert out(capsys) == f"{DIRECTION}: well formed, 6 items\n"
        assert run(root, tmp_path, NoNetwork(), "show", *local) == 0
        assert out(capsys) == direction.render()
        assert run(root, tmp_path, NoNetwork(), "show", *local, "--section", "goals", "--section", "non-goals") == 0
        assert out(capsys) == direction.render([Section.GOALS, Section.NON_GOALS])
        assert run(root, tmp_path, NoNetwork(), "show", *local, "--json") == 0
        assert json.loads(out(capsys)) == direction.record(today=dt.datetime.now(dt.UTC).date())
    assert run(root, tmp_path, NoNetwork(), "ids") == 0
    assert out(capsys).splitlines()[0] == "U-1: A partner's developer"


def test_s071_8_this_repo_reads_only_its_own_direction(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """shipmill sets no [product] home: the triage passes' `product show --section goals` is as before"""
    for args in (["--section", "goals"], ["--section", "non-goals"], ["--section", "goals", "--json"]):
        assert run(ROOT, tmp_path, NoNetwork(), "show", *args) == 0
        shown = out(capsys)
        assert "## Product" not in shown and '"product"' not in shown
    assert run(ROOT, tmp_path, NoNetwork(), "show", "--section", "goals") == 0
    assert out(capsys) == read(ROOT).render([Section.GOALS])


# -- S-071-13 --------------------------------------------------------------------------------


def test_s071_13_doctors_direction_line_checks_as_local_and_reads_nothing_of_the_home(tmp_path: Path) -> None:
    # G-9 isn't a goal of the home; doctor never reads the home (it takes no GitHub here), so it passes
    root = component(tmp_path, SERVED.replace("  serves: G-1\n", "  serves: G-9\n"))
    assert direction_check(root) == Check("PASS", "direction", "docs/product.md is well formed")
    (tmp_path / "broken").mkdir()
    broken = component(tmp_path / "broken", SERVED.replace("  serves: G-1\n", "  serves: G-9, G-9\n"))
    found = direction_check(broken)
    assert found.status == "FAIL" and "a serves line names G-9 twice" in found.detail


def test_s071_13_the_hooks_run_the_direction_check_as_local() -> None:
    hook = (ROOT / "hooks" / "delivery.py").read_text(encoding="utf-8")
    assert re.search(r'local = \("--local",\) if check == "product" else \(\)', hook)


def folded(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_s071_13_setup_shows_the_homes_goals_asks_which_each_serves_and_never_chooses() -> None:
    skill = folded(ROOT / "skills" / "shipmill-setup" / "SKILL.md")
    step = skill.split("**In a component, the product goals each goal serves (spec 071).**", 1)[1]
    step = step.split(" - **", 1)[0].split(" Then tell the maintainer", 1)[0]
    assert "run `$CR product show --section goals` and show the maintainer the home's goals" in step
    assert "For each component goal, ask which of those goals it serves" in step
    assert "Write each answer with `$CR product serves G-n <the home's G-n ids>`, never by hand" in step
    assert "Never choose a product goal for a component goal yourself" in step
    assert "leave the serves lines for a later run rather than guessing" in step
