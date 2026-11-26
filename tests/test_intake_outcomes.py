"""intake_state.py under [agents] outcomes (spec 101): the product's outcomes in flight, run as a
session runs it, with a fake gh and a fake uvx (for `shipmill gh --product`) on PATH"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_intake_state import issue, opportunity, said

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "product-intake" / "scripts" / "intake_state.py"
BOT = "shipmill-app[bot]"
HELD = "<!-- shipmill:intake-held -->\nThis outcome waits for room under `[agents] outcomes`.\n<!-- shipmill:agent -->"

FAKE_GH = """
import json, re, sys
from pathlib import Path

data = json.loads((Path(__file__).parent / "gh.json").read_text())
query = next(a[len("query="):] for a in sys.argv if a.startswith("query="))
page = lambda nodes: {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
if "labels: [$label]" in query:
    repo = {"issues": page(data["opportunities"])}
elif "issues(states: OPEN" in query:
    repo = {"hasDiscussionsEnabled": False, "issues": page(data["opened"])}
elif "issueOrPullRequest" in query:
    repo = {f"m{n}": {"reactions": {"totalCount": 0}} for n in re.findall(r"m(\\d+):", query)}
else:
    sys.exit(f"unexpected query: {query}")
print(json.dumps({"data": {"repository": repo}}))
"""

# `uvx shipmill==<version> --repo <checkout> gh --product <repo> api graphql -f query=...`
FAKE_UVX = """
import json, re, sys
from pathlib import Path

here = Path(__file__).parent
with (here / "uvx.log").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
data = json.loads((here / "uvx.json").read_text())
query = next(a[len("query="):] for a in sys.argv if a.startswith("query="))
if "HEAD:.github/shipmill.toml" in query:
    if data["home_read"] == "refused":
        sys.exit("error: no read token for o/home")
    if data["home_read"] == "unlisted":
        print(json.dumps({"data": {"repository": None}}))
        sys.exit(0)
    blob = None if data["home_config"] is None else {"text": data["home_config"]}
    print(json.dumps({"data": {"repository": {"object": blob}}}))
    sys.exit(0)
found = {}
for alias, owner, name in re.findall(r'(r\\d+): repository\\(owner: "([^"]+)", name: "([^"]+)"\\)', query):
    repo = f"{owner}/{name}"
    if repo in data["fail"]:
        sys.exit(f"error: gh --product refused {repo}")
    found[alias] = {"issues": {"totalCount": data["counts"][repo]}}
print(json.dumps({"data": found}))
"""


@pytest.fixture(scope="module")
def ist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("intake_state_outcomes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def opportunities() -> list[dict[str, Any]]:
    """Open ones reading OPPORTUNITY_OPEN, ACCEPTED (expedite too), and HANDED_OFF; closed ones
    reading DONE, DECLINED, and MERGED"""
    closed = "2026-11-20T10:00:00Z"
    return [
        opportunity(10, "- #1"),
        opportunity(11, "- #3", labels=("planned", "expedite")),
        opportunity(12, "- #4", "Triage: **feature**. Spec in #99", labels=("planned",)),
        opportunity(13, "- #5", state="CLOSED", reason="COMPLETED", closed_at=closed),
        opportunity(
            14, "- #6", "Not now.", state="CLOSED", reason="NOT_PLANNED", closed_at=closed, commented_at=closed
        ),
        opportunity(15, "- #7", state="CLOSED", reason="DUPLICATE", closed_at=closed),
    ]


def held_request() -> dict[str, Any]:
    found = issue(2)
    found["comments"]["nodes"] = [said(HELD, "2026-11-24T10:00:00Z", "NONE", "shipmill-app", "Bot")]
    return found


class Checkout:
    """A checkout with its config, and the fake gh and uvx its run finds on PATH"""

    def __init__(self, root: Path, config: str | None, uvx: dict[str, Any] | None = None) -> None:
        self.dir = root / "checkout"
        (self.dir / ".git").mkdir(parents=True)
        if config is not None:
            (self.dir / ".github").mkdir()
            (self.dir / ".github" / "shipmill.toml").write_text(config)
        self.bin = root / "bin"
        self.bin.mkdir()
        gh = {"opened": [issue(1), held_request(), issue(3), issue(4)], "opportunities": opportunities()}
        (self.bin / "gh.json").write_text(json.dumps(gh))
        fake = {"home_config": None, "home_read": "ok", "counts": {}, "fail": [], **(uvx or {})}
        (self.bin / "uvx.json").write_text(json.dumps(fake))
        for name, body in (("gh", FAKE_GH), ("uvx", FAKE_UVX)):
            (self.bin / name).write_text(f"#!{sys.executable}\n{body}")
            (self.bin / name).chmod(0o755)

    def run(self, *flags: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        cmd = [sys.executable, str(SCRIPT), "o/r", "--bot-login", BOT, *flags]
        return subprocess.run(cmd, cwd=self.dir, env=env, capture_output=True, text=True, check=False)

    def product_calls(self) -> list[list[str]]:
        log = self.bin / "uvx.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def via(call: list[str]) -> str:
    return call[call.index("--product") + 1]


# As intake_state.py printed them before spec 101, for the same GitHub data, the held comment
# on #2 included
BEFORE_TEXT = (
    "intake autonomy: propose\n"
    "#11    ACCEPTED         Issue 11  [1 requests, +1 0; hand it to triage's spec gate]\n"
    "#2     NEW_FEEDBACK     Issue 2  [+1 0; issue]\n"
    "#10    OPPORTUNITY_OPEN Issue 10  [1 requests, +1 0]\n"
    "#12    HANDED_OFF       Issue 12  [1 requests, +1 0; triage: feature]\n"
    "#14    DECLINED         Issue 14  [1 requests, +1 0; Not now.]\n"
    "#13    DONE             Issue 13  [1 requests, +1 0]\n"
    "#15    MERGED           Issue 15  [1 requests, +1 0; closed as a duplicate]\n"
)


@pytest.mark.parametrize(
    "config",
    [None, '[autonomy]\nintake = "propose"\n', '[agents]\napp_id = 1\nwip = 3\n[product]\nrepos = ["o/c1"]\n'],
    ids=["no config", "lone repo", "home"],
)
def test_s101_3_without_the_key_both_outputs_and_the_exit_are_as_before(tmp_path: Path, config: str | None) -> None:
    checkout = Checkout(tmp_path, config)
    text = checkout.run()
    assert (text.returncode, text.stdout) == (1, BEFORE_TEXT), text.stderr
    lines = checkout.run("--json")
    assert lines.returncode == 1, lines.stderr
    first, *rows = lines.stdout.splitlines()
    assert first == '{"autonomy": "propose"}'
    assert [json.loads(r)["number"] for r in rows] == [11, 2, 10, 12, 14, 13, 15]
    assert json.loads(rows[1]) == {
        "number": 2,
        "kind": "issue",
        "state": "NEW_FEEDBACK",
        "title": "Issue 2",
        "thumbs": 0,
        "members": [],
        "note": "issue",
        "author": None,
        "association": None,
        "handed": None,
    }
    assert checkout.product_calls() == []  # nothing read through shipmill gh --product


def test_s101_3_a_component_whose_home_sets_no_limit_prints_as_before(tmp_path: Path) -> None:
    home = '[agents]\napp_id = 1\n[product]\nrepos = ["o/r"]\n'
    checkout = Checkout(tmp_path, '[product]\nhome = "o/home"\n', {"home_config": home})
    text = checkout.run()
    assert (text.returncode, text.stdout) == (1, BEFORE_TEXT), text.stderr
    assert [via(c) for c in checkout.product_calls()] == ["o/home"]  # the home's config, nothing counted


def test_s101_4_every_open_opportunity_counts_once(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path, "[agents]\noutcomes = 3\n")
    lines = checkout.run("--json")
    assert lines.returncode == 1, lines.stderr
    first, *rows = lines.stdout.splitlines()
    assert first == '{"autonomy": "propose", "outcomes": {"limit": 3, "in_flight": 3, "room": 0}}'
    assert [json.loads(r)["number"] for r in rows] == [11, 2, 10, 12, 14, 13, 15]
    text = checkout.run()
    assert text.stdout.splitlines()[:2] == ["intake autonomy: propose", "outcomes in flight: 3 of 3 (product o/r)"]
    assert text.stdout.splitlines()[2:] == BEFORE_TEXT.splitlines()[1:]
    assert checkout.product_calls() == []  # a lone repo counts what it read already


def test_s101_4_the_room_is_what_the_limit_leaves(tmp_path: Path) -> None:
    lines = Checkout(tmp_path, "[agents]\noutcomes = 5\n").run("--json")
    assert json.loads(lines.stdout.splitlines()[0])["outcomes"] == {"limit": 5, "in_flight": 3, "room": 2}


def test_s101_5_the_home_counts_its_listed_repos_one_call_per_owner(tmp_path: Path) -> None:
    config = '[agents]\napp_id = 1\noutcomes = 4\n[product]\nrepos = ["o/c1", "o/c2", "x/c3"]\n'
    counts = {"o/c1": 1, "o/c2": 0, "x/c3": 2}
    checkout = Checkout(tmp_path, config, {"counts": counts})
    lines = checkout.run("--json")
    assert lines.returncode == 1, lines.stderr
    assert json.loads(lines.stdout.splitlines()[0])["outcomes"] == {"limit": 4, "in_flight": 6, "room": 0}
    calls = checkout.product_calls()
    assert sorted(via(c) for c in calls) == ["o/c1", "x/c3"]
    assert all(c[c.index("--repo") + 1] == str(checkout.dir.resolve()) for c in calls)
    text = checkout.run()
    assert text.stdout.splitlines()[1] == "outcomes in flight: 6 of 4 (product o/r)"


def test_s101_5_a_component_reads_the_homes_limit_and_counts_the_same_set(tmp_path: Path) -> None:
    home = '[agents]\napp_id = 1\noutcomes = 9\n[product]\nrepos = ["o/r", "o/c2", "x/c3"]\n'
    counts = {"o/home": 2, "o/c2": 1, "x/c3": 1}
    checkout = Checkout(
        tmp_path, '[agents]\napp_id = 1\n[product]\nhome = "o/home"\n', {"home_config": home, "counts": counts}
    )
    lines = checkout.run("--json")
    assert lines.returncode == 1, lines.stderr
    assert json.loads(lines.stdout.splitlines()[0])["outcomes"] == {"limit": 9, "in_flight": 7, "room": 2}
    calls = checkout.product_calls()
    # the home's config, then one count per owner: the home's owner through the home itself
    assert [via(c) for c in calls] == ["o/home", "o/home", "x/c3"]
    assert any("HEAD:.github/shipmill.toml" in a for a in calls[0])
    text = checkout.run()
    assert text.stdout.splitlines()[1] == "outcomes in flight: 7 of 9 (product o/home)"


def test_s101_5_a_read_that_fails_exits_2_naming_the_repo(tmp_path: Path) -> None:
    config = '[agents]\napp_id = 1\noutcomes = 4\n[product]\nrepos = ["o/c1", "x/c3"]\n'
    checkout = Checkout(tmp_path, config, {"counts": {"o/c1": 1}, "fail": ["x/c3"]})
    found = checkout.run("--json")
    assert found.returncode == 2
    assert found.stdout == ""
    assert "x/c3" in found.stderr and "counting the open opportunities" in found.stderr
    assert "refused x/c3" in found.stderr


@pytest.mark.parametrize(
    ("home_read", "said"),
    [
        ("refused", "exited 1: error: no read token for o/home"),
        ("unlisted", "GitHub returned no repository o/home"),
        ("ok", "GitHub has no o/home:.github/shipmill.toml on its default branch"),
    ],
    ids=["read refused", "home unlisted", "no home config"],
)
def test_s101_3_a_component_whose_homes_config_cant_be_read_prints_as_before(
    tmp_path: Path, home_read: str, said: str
) -> None:
    # A home with a limit, set should the read succeed: the limit applies only where it is read
    home = '[agents]\noutcomes = 1\n[product]\nrepos = ["o/r"]\n'
    uvx = {"home_read": home_read, "home_config": None if home_read == "ok" else home}
    checkout = Checkout(tmp_path, '[product]\nhome = "o/home"\n', uvx)
    text = checkout.run()
    assert (text.returncode, text.stdout) == (1, BEFORE_TEXT), text.stderr
    note = text.stderr.splitlines()
    assert len(note) == 1 and note[0].startswith("note: no [agents] outcomes limit"), text.stderr
    assert "reading the product's limit from o/home" in note[0] or "o/home:.github/shipmill.toml" in note[0]
    assert said in note[0]
    lines = checkout.run("--json")
    assert lines.returncode == 1, lines.stderr
    assert lines.stdout.splitlines()[0] == '{"autonomy": "propose"}'
    assert [via(c) for c in checkout.product_calls()] == ["o/home", "o/home"]  # the home's config only


def test_s101_5_a_component_never_sets_the_limit_itself(tmp_path: Path) -> None:
    found = Checkout(tmp_path, '[agents]\noutcomes = 3\n[product]\nhome = "o/home"\n').run()
    assert found.returncode == 2
    assert "o/home" in found.stderr and "[agents] outcomes" in found.stderr


@pytest.mark.parametrize("bad", ["0", "-1", "101", '"3"', "true", "2.5"])
def test_s101_4_a_bad_limit_is_refused_naming_the_key(tmp_path: Path, bad: str) -> None:
    found = Checkout(tmp_path, f"[agents]\noutcomes = {bad}\n").run()
    assert found.returncode == 2
    assert "[agents] outcomes" in found.stderr


def test_the_310_reader_reads_a_one_line_array(ist: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "shipmill.toml"
    text = '[product]\nrepos = ["o/a", "x/b",]  # the components\n[agents]\noutcomes = 3\n'
    assert ist.config_values_310(text, path, "product", ("repos",)) == {"repos": ["o/a", "x/b"]}
    assert ist.config_values_310(text, path, "agents", ("outcomes",)) == {"outcomes": 3}
    assert ist.config_values_310("[product]\nrepos = []\n", path, "product", ("repos",)) == {"repos": []}
    with pytest.raises(SystemExit):
        ist.config_values_310('[product]\nrepos = [\n  "o/a",\n]\n', path, "product", ("repos",))
