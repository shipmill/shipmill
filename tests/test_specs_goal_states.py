"""specs.py under spec 106: a draft or approved spec serves no goal the direction records as met
or dropped (S-106-3), and a stopped spec needs no Verification and is never split (S-106-20)"""

from pathlib import Path

from .test_specs import DIRECTION, direction, repo, serving, spec, specs

ENDED = DIRECTION.replace(
    "- G-1: Widgets reach buyers in a day\n",
    "- G-1: Widgets reach buyers in a day\n"
    "- G-4: Widgets ship. Check: a buyer gets one. By: 2026-12-31. Met: 2026-12-20\n"
    "- G-5: Widgets glow. Check: one glows. By: 0.7.0. Dropped: 2026-12-01: no paint\n",
)


def stopped(number: str, verification: bool = False) -> str:
    """A stopped spec, without its Verification section unless asked"""
    text = spec(number, status="stopped")
    return text if verification else text.split("\n## Verification")[0] + "\n"


# -- S-106-3 --------------------------------------------------------------------------------


def test_s106_3_a_draft_or_approved_spec_serving_a_met_or_dropped_goal_is_refused(tmp_path: Path) -> None:
    root = direction(
        repo(
            tmp_path,
            **{
                "001-met.md": serving(spec("001"), "G-4"),
                "002-dropped.md": serving(spec("002", status="draft"), "G-1, G-5"),
                "003-open.md": serving(spec("003"), "G-1, G-3"),
                "004-built.md": serving(
                    spec("004", status="built", verification="- S-004-1: ran it\n- S-004-2: ran it"), "G-4"
                ),
                "005-stopped.md": serving(stopped("005"), "G-5"),
            },
        ),
        ENDED,
    )
    out = specs(root, "check")
    assert out.returncode == 1, out.stdout + out.stderr
    assert out.stdout.splitlines() == [
        "docs/specs/001-met.md:4: serves G-4, which docs/product.md records as met or dropped; "
        "a spec still approved serves only a goal still open (spec 106)",
        "docs/specs/002-dropped.md:4: serves G-5, which docs/product.md records as met or dropped; "
        "a spec still draft serves only a goal still open (spec 106)",
    ]


def test_s106_3_a_goal_without_an_end_or_written_otherwise_is_open(tmp_path: Path) -> None:
    # a goal of kind none whose text merely holds the word, and one ended in a moved Goals file
    moved = DIRECTION.replace(
        "- G-1: Widgets reach buyers in a day\n- G-3: Buyers can track a widget\n", "See [goals](product/goals.md).\n"
    )
    goals = "- G-1: Met: every buyer\n- G-3: Track. Check: van. By: 0.7.0. Met: 2026-12-20\n"
    root = direction(
        repo(tmp_path, **{"001-a.md": serving(spec("001"), "G-1"), "002-b.md": serving(spec("002"), "G-3")}),
        moved,
        **{"goals.md": goals},
    )
    out = specs(root, "check")
    assert out.stdout.splitlines() == [
        "docs/specs/002-b.md:4: serves G-3, which docs/product.md records as met or dropped; "
        "a spec still approved serves only a goal still open (spec 106)"
    ]


# -- S-106-20 -------------------------------------------------------------------------------


def test_s106_20_check_accepts_a_stopped_spec_without_verification(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"005-stopped.md": stopped("005"), "006-kept.md": stopped("006", verification=True)})
    out = specs(root, "check")
    assert (out.returncode, out.stdout) == (0, ""), out.stdout + out.stderr
    # every other status still needs the section
    root = repo(
        tmp_path / "other", **{"007-approved.md": stopped("007").replace("status: stopped", "status: approved")}
    )
    assert "007-approved.md:1: missing the section 'Verification'" in specs(root, "check").stdout


def test_s106_20_split_refuses_a_stopped_spec(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"005-stopped.md": stopped("005")})
    out = specs(root, "split", "5")
    assert out.returncode == 2
    assert "S-005 is stopped; a stopped spec is never split into build issues" in out.stderr


def test_s106_20_a_stopped_specs_sections_keep_their_order(tmp_path: Path) -> None:
    text = stopped("005")
    behaviour, criteria = text.index("## Behaviour"), text.index("## Acceptance criteria")
    swapped = text[:behaviour] + text[criteria:] + text[behaviour:criteria]
    root = repo(tmp_path, **{"005-stopped.md": swapped})
    out = specs(root, "check")
    assert "005-stopped.md:1: sections out of order" in out.stdout, out.stdout
