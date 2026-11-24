"""Spec 083's seeded set: earned.py's rule over every case of tests/landing/seeded.toml"""

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from shipmill.classify import Base, Classification, RepoPath, classify_paths
from shipmill.decide import Level
from shipmill.earned import Changed, Kind, Landing, Proof, ceiling_kind, landing
from shipmill.policy import Policy
from shipmill.review import REVIEW
from shipmill.review import parse as parse_review

from .conftest import POLICY

SEEDED = Path(__file__).parent / "landing" / "seeded.toml"
EXPECTED = ("act", "notify", "ask", "never", "none")
STATES = ("raised", "cleared")
_ID = re.compile(r"L-[1-9][0-9]*")


@dataclass(frozen=True)
class Case:
    id: str
    files: dict[str, int]
    decisions: dict[str, Any]
    areas: dict[str, str]
    proves: bool
    expected: str


def cases() -> tuple[list[str], list[Case]]:
    raw = tomllib.loads(SEEDED.read_text(encoding="utf-8"))
    found = []
    for entry in raw["case"]:
        extra = set(entry) - {"id", "why", "files", "decisions", "areas", "proves", "expected"}
        assert not extra, f"{entry.get('id')} has unknown keys {sorted(extra)}"
        assert _ID.fullmatch(entry["id"]), f"a case's id is L-n, got {entry['id']!r}"
        assert entry["expected"] in EXPECTED, f"{entry['id']} expects {entry['expected']!r}"
        assert entry["files"], f"{entry['id']} changes no path"
        areas = entry.get("areas", {})
        assert set(areas.values()) <= set(STATES), f"{entry['id']}: an area is raised or cleared"
        found.append(Case(entry["id"], entry["files"], entry["decisions"], areas, entry["proves"], entry["expected"]))
    return list(raw["protected"]), found


def base(protected: list[str], decisions: dict[str, Any]) -> Base:
    """The case's base: the fixture's config with its [decisions], and a REVIEW.md protecting the globs"""
    raw = tomllib.loads(POLICY) | {"decisions": decisions}
    review = "## Protected areas\n\n" + "".join(f"- `{glob}`: seeded\n" for glob in protected)
    rubric, problems = parse_review(review, PurePosixPath(REVIEW))
    assert not problems, problems
    return Base(Policy.parse(raw, "seeded.toml"), {REVIEW: rubric.protected}, None)


def run(protected: list[str], case: Case) -> tuple[Classification, Landing]:
    at = base(protected, case.decisions)
    found = classify_paths(at, [RepoPath(path) for path in case.files])
    changed = [Changed(path, lines) for path, lines in case.files.items()]
    raised = frozenset(area for area, state in case.areas.items() if state == "raised")
    proof = Proof("tests") if case.proves else Proof(None, "no required check proves")
    return found, landing(found, changed, at.policy.decisions, raised, proof)


def shown(level: Level | None) -> str:
    return "none" if level is None else level.value


def misses(protected: list[str], found: list[Case]) -> list[str]:
    """`MISS L-n: expected <level>, got <level>` for every case the rule misses"""
    lines = []
    for case in found:
        _, got = run(protected, case)
        if shown(got.level) != case.expected:
            lines.append(f"MISS {case.id}: expected {case.expected}, got {shown(got.level)}")
    return lines


def test_s083_12_every_seeded_case_lands_at_its_expected_level() -> None:
    protected, found = cases()
    missed = misses(protected, found)
    assert not missed, "\n".join(missed)


def test_s083_12_the_set_holds_at_least_12_cases_with_distinct_ids() -> None:
    _, found = cases()
    ids = [c.id for c in found]
    assert len(ids) >= 12
    assert len(set(ids)) == len(ids)


def test_s083_12_the_set_covers_each_ceiling_kind_each_evidence_failing_alone_and_the_named_cases() -> None:
    protected, found = cases()
    kinds: set[Kind] = set()
    alone: set[str] = set()
    states: set[str] = set()
    never_part = no_zone = False
    for case in found:
        classified, got = run(protected, case)
        kinds |= {k for path in case.files if (k := ceiling_kind(path)) is not None}
        failing = [e.name for e in got.evidence if not e.holds]
        if len(failing) == 1 and "earned" in case.decisions and not got.earned:
            alone.add(failing[0])
        states |= set(case.areas.values())
        parts = case.decisions.get("paths", {})
        never_part |= any(level == "never" for zone in parts.values() for level in zone.values())
        no_zone |= not classified.zones
    assert kinds == set(Kind)
    assert alone == {"checks", "size", "record", "kind"}
    assert states == {"raised", "cleared"}
    assert never_part and no_zone


def test_s083_12_every_miss_is_named_with_its_expected_and_got_level() -> None:
    protected, found = cases()
    wrong = [replace(c, expected="never") for c in found if c.id in ("L-1", "L-12", "L-13")]
    assert misses(protected, wrong) == ["MISS L-1: expected never, got act", "MISS L-12: expected never, got notify"]


# -- the rule's evidence and zones, as #1548's classify will show them ---------------------------


def test_s083_12_the_evidence_is_in_the_tables_order_with_its_details() -> None:
    protected, found = cases()
    _, got = run(protected, next(c for c in found if c.id == "L-1"))
    assert [e.record() for e in got.evidence] == [
        {"name": "checks", "holds": True, "detail": "tests"},
        {"name": "size", "holds": True, "detail": "40 of at most 200 lines"},
        {"name": "record", "holds": True, "detail": "no raised area"},
        {"name": "kind", "holds": True, "detail": "no ceiling path"},
    ]
    (zone,) = got.zones
    assert zone.reason.endswith("(earned act from ask by [decisions.earned])")
    assert [(lw.zone.value, lw.before.value, lw.after.value) for lw in got.lowered] == [("protected", "ask", "act")]
    assert got.record()["earned"] is True


@pytest.mark.parametrize(
    ("case_id", "name", "detail"),
    [
        ("L-2", "size", "201 of at most 200 lines"),
        ("L-4", "checks", "no required check proves"),
        ("L-5", "record", "src/auth raised"),
        ("L-10", "kind", "web/package.json is of the dependencies kind"),
    ],
)
def test_s083_12_a_failing_piece_of_evidence_names_why(case_id: str, name: str, detail: str) -> None:
    protected, found = cases()
    _, got = run(protected, next(c for c in found if c.id == case_id))
    assert [(e.name, e.detail) for e in got.evidence if not e.holds] == [(name, detail)]
    assert not got.earned


def test_s083_12_without_the_table_checks_and_record_are_not_read() -> None:
    protected, found = cases()
    case = next(c for c in found if c.id == "L-15")
    at = base(protected, case.decisions)
    classified = classify_paths(at, [RepoPath(p) for p in case.files])
    got = landing(classified, [Changed(p, n) for p, n in case.files.items()], at.policy.decisions, None, None)
    assert [(e.name, e.holds, e.detail) for e in got.evidence] == [
        ("checks", False, "not read: [decisions.earned] is not set"),
        ("size", True, "40 of at most 200 lines"),
        ("record", False, "not read: [decisions.earned] is not set"),
        ("kind", True, "no ceiling path"),
    ]
    assert (got.level, got.earned) == (Level.ASK, False)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (".github/shipmill.toml", Kind.CONTROLS),
        ("REVIEW.md", Kind.CONTROLS),
        (".github/workflows/ci.yml", Kind.CONTROLS),
        (".github/actions/setup/action.yml", Kind.CONTROLS),
        (".claude/settings.json", Kind.CONTROLS),
        ("infra/main.tf", Kind.INFRASTRUCTURE),
        ("main.tf", Kind.INFRASTRUCTURE),
        ("Dockerfile", Kind.INFRASTRUCTURE),
        ("services/api/Dockerfile", Kind.INFRASTRUCTURE),
        ("db/migrations/0001.sql", Kind.INFRASTRUCTURE),
        ("uv.lock", Kind.DEPENDENCIES),
        ("web/package.json", Kind.DEPENDENCIES),
        ("requirements-dev.txt", Kind.DEPENDENCIES),
        (".github/dependabot.yml", Kind.DEPENDENCIES),
        ("src/auth/login.py", None),
        ("docs/flow.md", None),
        (".github/ISSUE_TEMPLATE/bug.md", None),
    ],
)
def test_s083_12_the_ceiling_kinds_match_their_paths_at_the_root_and_under_any_directory(
    path: str, kind: Kind | None
) -> None:
    assert ceiling_kind(path) is kind
