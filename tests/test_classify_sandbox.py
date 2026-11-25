"""S-087-11: `shipmill decide classify --pr N` reports security at ask for a pull request that
adds a domains, read, write or tunnels entry under [agents.sandbox], also when [decisions]
security = "notify", and follows [decisions] security for one that only removes entries (D-110)"""

from typing import Any

import pytest

from shipmill.classify import Base, classify_change, sandbox_added
from shipmill.earned import Changed, Proof, landing
from shipmill.github import FileChange

from .conftest import POLICY, Repo
from .test_decide_cli import BASE, CONFIG, HEAD, FakePulls, commit, config_change, patch, run, zones_of

NOTIFY = '\n[decisions]\nsecurity = "notify"\n'
AGENTS = '\n[agents]\nprompt = "/t"\n'
TUNNEL = '\n[[agents.sandbox.tunnels]]\nssh = "readonly@db.example.com"\nlocal = 15432\nremote = "127.0.0.1:5432"\n'
SANDBOX = '\n[agents.sandbox]\ndomains = ["registry.npmjs.org"]\nread = ["~/.config/tool"]\nwrite = ["~/.cache/pnpm"]\n'


def classify(repo: Repo, capsys: pytest.CaptureFixture[str], before: str, after: str, levels: str = NOTIFY) -> Any:
    """The pull request's config at the merge base and the head, each under the base's [decisions]"""
    commit(repo, POLICY + levels)
    pulls = config_change(POLICY + levels + AGENTS + before, POLICY + levels + AGENTS + after)
    return run(repo, capsys, "classify", "--pr", "7", pulls=pulls)


def security(found: dict[str, Any]) -> tuple[str, str]:
    [detected] = [z for z in found["zones"] if z["zone"] == "security"]
    return detected["level"], detected["reason"]


@pytest.mark.parametrize(
    ("after", "named"),
    [
        (
            SANDBOX.replace('["registry.npmjs.org"]', '["registry.npmjs.org", "*.example.com"]'),
            "domains '*.example.com'",
        ),
        (SANDBOX.replace('["~/.config/tool"]', '["~/.config/tool", "~/.aws"]'), "read '~/.aws'"),
        (SANDBOX.replace('["~/.cache/pnpm"]', '["~/.cache/pnpm", "/"]'), "write '/'"),
        (SANDBOX + TUNNEL, "tunnels {'ssh': 'readonly@db.example.com'"),
    ],
    ids=["domains", "read", "write", "tunnels"],
)
def test_s087_11_an_added_entry_is_security_at_ask_under_security_notify(
    repo: Repo, capsys: pytest.CaptureFixture[str], after: str, named: str
) -> None:
    level, why = security(classify(repo, capsys, SANDBOX, after))
    assert level == "ask"
    assert f"widens [agents.sandbox]: adds {named}" in why and "(D-110)" in why


def test_s087_11_a_new_sandbox_table_is_a_widening(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    found = classify(repo, capsys, "", SANDBOX)
    assert zones_of(found) == {"security": "ask"} and found["level"] == "ask"


def test_s087_11_an_entry_added_beside_one_removed_still_asks(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    after = SANDBOX.replace('["registry.npmjs.org"]', '["pypi.example.org"]')
    level, why = security(classify(repo, capsys, SANDBOX, after))
    assert level == "ask" and "adds domains 'pypi.example.org'" in why
    assert "registry.npmjs.org" not in why


def test_s087_11_only_removing_entries_follows_decisions_security(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    narrowed = SANDBOX.replace('["registry.npmjs.org"]', "[]")
    assert security(classify(repo, capsys, SANDBOX + TUNNEL, narrowed))[0] == "notify"
    gone = classify(repo, capsys, SANDBOX + TUNNEL, "")
    assert security(gone)[0] == "notify" and "widens" not in security(gone)[1]
    assert security(classify(repo, capsys, SANDBOX, narrowed, levels=""))[0] == "ask"  # security's default


def test_s087_11_a_reorder_widens_nothing(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """The tables still differ parsed, so security follows [decisions] as for any other change"""
    before = '\n[agents.sandbox]\ndomains = ["a.org", "b.org"]\n'
    after = '\n[agents.sandbox]\n# the registries\ndomains = ["b.org", "a.org"]\n'
    level, why = security(classify(repo, capsys, before, after))
    assert level == "notify" and "widens" not in why


def test_s087_11_never_stays_never(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """A floor only raises: a base at never keeps never"""
    assert security(classify(repo, capsys, "", SANDBOX, levels='\n[decisions]\nsecurity = "never"\n'))[0] == "never"


def test_s087_11_a_head_that_doesnt_parse_asks(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    """A widening can't be ruled out in a config that doesn't parse"""
    assert security(classify(repo, capsys, "", "\nthis is not toml\n"))[0] == "ask"


def test_s087_11_an_added_config_with_a_sandbox_asks(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + NOTIFY)
    added = FakePulls((FileChange(CONFIG, "added", patch("x")),), {(HEAD, CONFIG): POLICY + NOTIFY + AGENTS + SANDBOX})
    found = run(repo, capsys, "classify", "--pr", "7", pulls=added)
    assert security(found)[0] == "ask"
    removed = FakePulls((FileChange(CONFIG, "removed", patch("x")),), {(BASE, CONFIG): POLICY + NOTIFY + SANDBOX})
    assert security(run(repo, capsys, "classify", "--pr", "7", pulls=removed))[0] == "notify"


def test_s087_11_sandbox_added_compares_raw_entries() -> None:
    def config(sandbox: object) -> dict[str, Any]:
        return {"agents": {"prompt": "/t", "sandbox": sandbox}}

    assert sandbox_added({}, config({"domains": ["https://x.org"]})) == ["domains 'https://x.org'"]
    assert sandbox_added(config({"domains": "a.org"}), config({"domains": ["a.org"]})) == []
    assert sandbox_added(config({}), config({"network": ["x"]})) == ["network 'x'"]  # a key it doesn't know
    assert sandbox_added(config({}), config(["a.org"])) == ["[agents.sandbox] ['a.org']"]
    assert sandbox_added(config({"write": ["/a", "/b"]}), config({"write": ["/b"]})) == []


def test_s087_11_an_earned_bound_never_lowers_a_widening(repo: Repo) -> None:
    """D-101's earned level lowers a path's level; the widening's ask is no path's, so it holds"""
    levels = '\n[decisions]\nsecurity = "ask"\n\n[decisions.earned]\nsecurity = "notify"\n'
    commit(repo, POLICY + levels)
    base = Base.read(repo.git, "origin/HEAD")
    holds = (Changed("src/x.py", 1),)  # every piece of evidence holds for it, the kind too
    for after, level in ((AGENTS + '\n[agents.sandbox]\nwrite = ["/"]\n', "ask"), (AGENTS, "notify")):
        pulls = config_change(POLICY + levels, POLICY + levels + after)
        found = classify_change(base, pulls, pulls.pull_change(7))
        landed = landing(found, holds, base.policy.decisions, frozenset(), Proof("ci"))
        assert all(e.holds for e in landed.evidence)
        assert landed.level is not None and landed.level.value == level
