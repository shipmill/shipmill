"""Spec 047, Deprecations, catalogued: every deprecated key and reading D-63 keeps alive is an
entry of src/shipmill/deprecations.py, and doctor's deprecation warnings come from it"""

import tomllib
from collections import Counter

import pytest

from shipmill import refused, upgrades
from shipmill.deprecations import CATALOGUE, DeprecationId, find, relied_on
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError
from shipmill.policy import Policy
from shipmill.upgrades import UpgradeId
from shipmill.version import Version

from .conftest import POLICY, Repo

# what a config writes to rely on each entry, beside an [agents] table whose prompt is "/t"
RELIES = {
    "agents-prs": ("", "prs = true\n", ""),
    "agents-prompt-land": (" merge when green", "", ""),
    "roadmap": ("", "", "\n[roadmap]\nwip = 3\n"),
    "agents-credit": ("", 'credit = "off"\n', ""),
}


def config(*ids: str) -> str:
    """POLICY with [agents], and the settings that rely on each id"""
    prompt = "".join(RELIES[i][0] for i in ids)
    keys = "".join(RELIES[i][1] for i in ids)
    tables = "".join(RELIES[i][2] for i in ids)
    return POLICY + f'\n[agents]\nprompt = "/t{prompt}"\n{keys}{tables}'


def parsed(text: str) -> Policy:
    return Policy.parse(tomllib.loads(text), "shipmill.toml")


def warns(repo: Repo, text: str) -> Counter[Check]:
    repo.write(repo.policy_file, text)
    return Counter(c for c in doctor(repo.root, repo.github) if c.status == "WARN")


def test_s047_11_the_catalogue_holds_each_deprecation_with_its_replacement_and_upgrade() -> None:
    entries = {str(d.id): (d.subject, d.since, d.replacement, d.upgrade) for d in CATALOGUE}
    autonomy = UpgradeId("agent-autonomy")
    assert entries == {
        "agents-prs": ("[agents] prs", Version.parse("0.79.0"), "[autonomy] land", autonomy),
        "agents-prompt-land": (
            '[agents] prompt read as land = "act" ("merge when green" or "land")',
            Version.parse("0.78.0"),
            "[autonomy] land",
            autonomy,
        ),
        "roadmap": ("[roadmap]", Version.parse("0.50.0"), "[agents] wip", None),
        "agents-credit": ("[agents] credit", Version.parse("0.102.0"), "[agents] author", None),
    }
    for deprecation in CATALOGUE:  # each migrating upgrade is one the upgrades catalogue offers
        if deprecation.upgrade is not None:
            assert upgrades.find(deprecation.upgrade).id == deprecation.upgrade
    # a refused key has no entry (D-64): its config fails to load, so nothing relies on it
    keys = {f"{r.table} {r.key}" for r in refused.CATALOGUE}
    assert not keys & {d.subject for d in CATALOGUE}


@pytest.mark.parametrize("ids", [(), *((i,) for i in RELIES), tuple(RELIES)])
def test_s047_11_doctors_deprecation_warnings_are_exactly_the_entries_the_config_relies_on(
    repo: Repo, ids: tuple[str, ...]
) -> None:
    text = config(*ids)
    policy = parsed(text)
    assert [str(d.id) for d in relied_on(policy)] == [str(d.id) for d in CATALOGUE if str(d.id) in ids]
    expected = Counter(Check("WARN", d.row, d.warn(policy) or "") for d in relied_on(policy))
    assert warns(repo, text) - warns(repo, config()) == expected
    assert warns(repo, config()) - warns(repo, text) == Counter()  # relying on one takes no other warning away


def test_s047_11_the_check_reads_a_parsed_config_with_no_checkout() -> None:
    # spec 047's report reads configs through the contents API, so the check takes no path
    policy = parsed(config("agents-prs", "roadmap"))
    assert [str(d.id) for d in relied_on(policy)] == ["agents-prs", "roadmap"]
    assert find(DeprecationId("roadmap")).relies(policy)
    assert not find(DeprecationId("agents-credit")).relies(policy)


def test_a_deprecation_id_is_checked_and_an_unknown_one_named() -> None:
    with pytest.raises(ReleaseError, match="lowercase words joined by '-'"):
        DeprecationId("Agents PRS")
    with pytest.raises(ReleaseError, match="unknown deprecation nope; known: agents-prs, agents-prompt-land"):
        find(DeprecationId("nope"))
