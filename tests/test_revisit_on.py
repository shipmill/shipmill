"""Spec 061's Revisit on: line: a postponed issue comes back when what it waits on changed"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("o", "r")
POSTPONE = "Triage: postpone, no goal it serves yet.\n\nRevisit on: `src/a/**`"
# #1766: a postpone counts only from a trusted author (D-16)
MAINTAINER = {"author": {"__typename": "User", "login": "ana"}, "authorAssociation": "MEMBER"}
TAGS = [
    ("v1.1.0", "2026-08-01T10:00:00Z"),
    ("v1.2.0", "2026-09-01T10:00:00Z"),
    ("v1.3.0.dev1", "2026-09-15T10:00:00Z"),
    ("v1.3.0", "2026-10-01T10:00:00Z"),
]


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tag(name: str, date: str) -> dict[str, Any]:
    return {"name": name, "target": {"tagger": {"date": date}}}


def tags(cursor: str | None = None, names: list[tuple[str, str]] = TAGS) -> dict[str, Any]:
    nodes = [tag(n, d) for n, d in names]
    return {"pageInfo": {"hasPreviousPage": cursor is not None, "startCursor": cursor}, "nodes": nodes}


def postponed(body: str = POSTPONE, at: str = "2026-09-10T10:00:00Z", number: int = 7) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"issue {number}",
        "body": "",
        "labels": {"nodes": [{"name": "postponed"}]},
        "comments": {"nodes": [{"createdAt": at, "body": body, **MAINTAINER}]},
        "timelineItems": {"nodes": []},
    }


class Compare:
    """A stand-in for `gh api repos/o/r/compare/...`: each call answers the next page"""

    def __init__(self, *pages: list[str], code: int = 0) -> None:
        self.pages = list(pages)
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        index = len(self.calls) - 1
        files = self.pages[index] if index < len(self.pages) else []
        out = json.dumps({"status": "ahead", "files": [{"filename": f} for f in files]})
        return subprocess.CompletedProcess(cmd, self.code, out, "gh: Not Found (HTTP 404)\n" if self.code else "")


def no_graphql(query: str, variables: dict[str, str | int]) -> dict[str, Any]:
    raise AssertionError("no older tags were due")


def read(
    ts: ModuleType, item: dict[str, Any], gh: Compare, connection: dict[str, Any] | None = None
) -> tuple[str, str]:
    connection = connection or tags()
    revisits = ts.Revisits("o", "r", connection, run=no_graphql, execute=gh)
    stable = ts.latest_stable(connection["nodes"])
    state: tuple[str, str] = ts.classify_open(item, "Triage:", "postponed", {}, stable, REPO, revisits=revisits)
    return state


def test_s061_14_a_postpone_whose_paths_did_not_change_waits(ts: ModuleType) -> None:
    gh = Compare(["docs/a.md", "src/b/a.py", "src/a"])
    assert read(ts, postponed(), gh) == ("POSTPONED", "waits on src/a/**")
    # the base is the newest stable tag before the comment, not a dev tag or the newest
    assert gh.calls == [["gh", "api", "repos/o/r/compare/v1.2.0...v1.3.0?per_page=100&page=1"]]


def test_s061_14_a_postpone_whose_path_changed_is_revisited_naming_it(ts: ModuleType) -> None:
    gh = Compare(["docs/a.md", "src/a/b/c.py"])
    assert read(ts, postponed(), gh) == ("REVISIT", "postponed before v1.3.0; src/a/b/c.py changed")


def test_s061_14_a_renamed_file_matches_by_its_old_name(ts: ModuleType) -> None:
    def renamed(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        out = json.dumps({"files": [{"filename": "lib/c.py", "previous_filename": "src/a/c.py"}]})
        return subprocess.CompletedProcess(cmd, 0, out, "")

    revisits = ts.Revisits("o", "r", tags(), run=no_graphql, execute=renamed)
    stable = ts.latest_stable(tags()["nodes"])
    assert ts.classify_open(postponed(), "Triage:", "postponed", {}, stable, REPO, revisits=revisits) == (
        "REVISIT",
        "postponed before v1.3.0; src/a/c.py changed",
    )


def test_s061_14_a_re_decision_after_the_newest_tag_waits_without_a_compare(ts: ModuleType) -> None:
    gh = Compare()
    assert read(ts, postponed(at="2026-10-05T10:00:00Z"), gh) == ("POSTPONED", "waits on src/a/**")
    assert gh.calls == []


def test_s061_15_the_compare_is_read_once_per_base_tag(ts: ModuleType) -> None:
    gh = Compare(["docs/a.md"])
    revisits = ts.Revisits("o", "r", tags(), run=no_graphql, execute=gh)
    stable = ts.latest_stable(tags()["nodes"])
    for number, at in ((7, "2026-09-10T10:00:00Z"), (8, "2026-09-20T10:00:00Z")):
        item = postponed(at=at, number=number)
        state = ts.classify_open(item, "Triage:", "postponed", {}, stable, REPO, revisits=revisits)
        assert state == ("POSTPONED", "waits on src/a/**")
    assert len(gh.calls) == 1


def test_s061_15_a_full_page_of_files_reads_the_next_page(ts: ModuleType) -> None:
    gh = Compare([f"docs/{i}.md" for i in range(100)], ["src/a/x.py"])
    assert read(ts, postponed(), gh) == ("REVISIT", "postponed before v1.3.0; src/a/x.py changed")
    assert [c[-1].rsplit("&", 1)[-1] for c in gh.calls] == ["page=1", "page=2"]
    assert all("per_page=100" in c[-1] for c in gh.calls)


def test_s061_15_a_compare_at_githubs_cap_of_300_files_reads_revisit(ts: ModuleType) -> None:
    gh = Compare([f"docs/{i}.md" for i in range(300)])
    assert read(ts, postponed(), gh) == ("REVISIT", "postponed before v1.3.0")
    assert len(gh.calls) == 1


def test_s061_15_no_stable_tag_before_the_comment_reads_revisit(ts: ModuleType) -> None:
    gh = Compare()
    assert read(ts, postponed(at="2026-07-01T10:00:00Z"), gh) == ("REVISIT", "postponed before v1.3.0")
    assert gh.calls == []


def test_s061_15_older_tags_are_paged_back_to_the_base(ts: ModuleType) -> None:
    calls: list[str | int] = []

    def older(query: str, variables: dict[str, str | int]) -> dict[str, Any]:
        assert query == ts.TAGS_PAGE
        calls.append(variables["cursor"])
        return {"data": {"repository": {"tags": tags(None, [("v1.0.0", "2026-06-01T10:00:00Z")])}}}

    connection = tags("t1", [("v1.3.0", "2026-10-01T10:00:00Z")])
    gh = Compare(["docs/a.md"])
    revisits = ts.Revisits("o", "r", connection, run=older, execute=gh)
    stable = ts.latest_stable(connection["nodes"])
    item = postponed(at="2026-07-01T10:00:00Z")
    state = ts.classify_open(item, "Triage:", "postponed", {}, stable, REPO, revisits=revisits)
    assert state == ("POSTPONED", "waits on src/a/**")
    assert calls == ["t1"]
    assert gh.calls[0][-1].startswith("repos/o/r/compare/v1.0.0...v1.3.0?")


def test_s061_15_a_compare_gh_refuses_exits_2(ts: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        read(ts, postponed(), Compare(code=1))
    assert exc.value.code == 2
    assert "compare/v1.2.0...v1.3.0" in capsys.readouterr().err


def test_s061_16_without_the_line_it_reads_as_before(ts: ModuleType) -> None:
    gh = Compare()
    plain = "Triage: postpone, no goal it serves yet."
    assert read(ts, postponed(plain), gh) == ("REVISIT", "postponed before v1.3.0")
    assert read(ts, postponed(plain, at="2026-10-05T10:00:00Z"), gh) == ("POSTPONED", "")
    assert gh.calls == []


@pytest.mark.parametrize(
    "line",
    [
        "Revisit on: src/a/**",
        "Revisit on:",
        "Revisit on: `src/a/**`, src/b",
        "Revisit on: `src/a/**` `src/b/**`",
    ],
)
def test_s061_17_an_unreadable_line_reads_revisit_quoting_it(ts: ModuleType, line: str) -> None:
    gh = Compare()
    body = f"Triage: postpone.\n\n{line}"
    # at once, even when the comment is newer than the newest tag: a session rewrites it
    assert read(ts, postponed(body, at="2026-10-05T10:00:00Z"), gh) == ("REVISIT", f"revisit line unreadable: {line}")
    assert gh.calls == []


def test_s061_17_the_unreadable_line_is_cut_to_100_characters(ts: ModuleType) -> None:
    line = "Revisit on: " + "x" * 200
    state = read(ts, postponed(f"Triage: postpone.\n{line}"), Compare())
    assert state == ("REVISIT", f"revisit line unreadable: {line[:100]}")


def test_s061_17_a_line_in_a_fence_is_no_line(ts: ModuleType) -> None:
    body = "Triage: postpone.\n\n```\nRevisit on: src/a\n```"
    assert read(ts, postponed(body), Compare()) == ("REVISIT", "postponed before v1.3.0")


def test_s061_14_several_paths_are_listed_in_the_note(ts: ModuleType) -> None:
    body = "Triage: postpone.\n\nRevisit on: `docs/product.md`, `docs/product/**`"
    gh = Compare(["src/a.py"])
    assert read(ts, postponed(body), gh) == ("POSTPONED", "waits on docs/product.md, docs/product/**")


@pytest.mark.parametrize(
    ("path", "filename", "matches"),
    [
        ("src/**", "src/a/b.py", True),
        ("src/**", "src/a.py", True),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/a/b.py", False),
        ("src/?.py", "src/a.py", True),
        ("src/?.py", "src/ab.py", False),
        ("src/?", "src//", False),
        ("src/[ab].py", "src/a.py", False),
        ("src/[ab].py", "src/[ab].py", True),
        ("docs/product.md", "docs/product.md", True),
        ("docs/product.md", "docs/productxmd", False),
        ("docs/product.md", "docs/product.md.bak", False),
        ("**/gate.py", "src/shipmill/gate.py", True),
    ],
)
def test_s061_18_a_path_matches_by_its_own_glob_rules(ts: ModuleType, path: str, filename: str, matches: bool) -> None:
    assert ts.glob_match(path, filename) is matches


FAKE_GH = """#!{python}
import json, os, sys
if sys.argv[1:3] == ["api", "graphql"]:
    print(open(os.environ["FAKE_GH_DATA"]).read())
else:
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(sys.argv[2] + "\\n")
    print(json.dumps({{"files": [{{"filename": "src/a/x.py"}}]}}))
"""


def test_s061_14_the_script_reads_the_compare_for_a_postponed_issue(tmp_path: Path) -> None:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    page = {
        "open": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [postponed()]},
        "tags": tags(),
        "closed": {"nodes": []},
        "vetoable": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
    }
    page["open"]["nodes"][0]["labels"]["pageInfo"] = {"hasNextPage": False}
    page["open"]["nodes"][0]["timelineItems"]["pageInfo"] = {"hasNextPage": False, "endCursor": None}
    data = tmp_path / "gh.json"
    data.write_text(json.dumps({"data": {"repository": page}}), encoding="utf-8")
    log = tmp_path / "compare.log"
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(data),
        "FAKE_GH_LOG": str(log),
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "o/r", "--json"], capture_output=True, text=True, check=False, env=env
    )
    assert proc.returncode == 1, proc.stderr
    assert [json.loads(line) for line in proc.stdout.splitlines()] == [
        {"number": 7, "state": "REVISIT", "title": "issue 7", "note": "postponed before v1.3.0; src/a/x.py changed"}
    ]
    assert log.read_text(encoding="utf-8") == "repos/o/r/compare/v1.2.0...v1.3.0?per_page=100&page=1\n"
