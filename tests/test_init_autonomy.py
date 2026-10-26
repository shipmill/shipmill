"""shipmill init writes [autonomy] uncommented, each key at the parser's default (spec 040)"""

import re
import tomllib

import pytest

from shipmill.autonomy import DEPLOY_DEFAULT, AutonomyPolicy, EnvironmentName, Stage
from shipmill.cli import main
from shipmill.config import config_path
from shipmill.doctor import OPERATE_CALLER
from shipmill.errors import ReleaseError
from shipmill.init import init_operate
from shipmill.policy import Policy

from .conftest import Repo

DEFAULTS = AutonomyPolicy()
ENVIRONMENTS = """
[environments.staging]
lane = "stable"
workflow = "deploy.yml"
health = "https://staging.example.com/health"

[environments.production]
from = "staging"
workflow = "deploy.yml"
health = "https://example.com/health"
"""


def autonomy(repo: Repo) -> dict[str, object]:
    table: dict[str, object] = tomllib.loads(repo.read(repo.policy_file))["autonomy"]
    return table


def test_s040_16_init_writes_an_uncommented_autonomy_with_release_at_its_default(repo: Repo) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    text = repo.read(repo.policy_file)
    assert "\n[autonomy]\n" in text and "# [autonomy]" not in text
    assert autonomy(repo) == {"release": DEFAULTS.release.value}
    assert re.search(r'^release = "act" +# observe \| propose \| act: ', text, re.MULTILINE)
    # the agent stages stay unset, so the legacy reading and AUTONOMY_IMPLICIT still apply (S-040-6, S-040-13)
    policy = Policy.load(config_path(repo.root))
    assert policy.autonomy == DEFAULTS


def test_s040_16_init_operate_adds_rollback_and_each_deploy_at_their_defaults(repo: Repo) -> None:
    assert main(["--repo", str(repo.root), "init", "--force"]) == 0
    before = repo.read(repo.policy_file).replace("\n[autonomy]\n", ENVIRONMENTS + "\n[autonomy]\n")
    repo.write(repo.policy_file, before)
    assert main(["--repo", str(repo.root), "init", "--operate"]) == 0
    after = repo.read(repo.policy_file)
    lines = after.splitlines(keepends=True)
    at = lines.index(next(line for line in lines if line.startswith("release = ")))
    added = lines[at + 1 : at + 4]  # after [autonomy]'s body, before the comments that follow it
    assert [line.split(" =")[0] for line in added] == ["rollback", "deploy.production", "deploy.staging"]
    assert "".join(lines[: at + 1] + lines[at + 4 :]) == before  # the rest of the file byte for byte
    assert autonomy(repo) == {
        "release": DEFAULTS.release.value,
        "rollback": DEFAULTS.rollback.value,
        "deploy": {"production": DEPLOY_DEFAULT.value, "staging": DEPLOY_DEFAULT.value},
    }
    assert after.count("# observe | propose | act: ") == 4
    policy = Policy.load(config_path(repo.root))
    for env in ("staging", "production"):  # the written value is the one an absent key reads as
        assert policy.autonomy.configured(Stage.deploy(EnvironmentName(env))) == AutonomyPolicy().configured(
            Stage.deploy(EnvironmentName(env))
        )
    assert (repo.root / OPERATE_CALLER).is_file()
    # run again: every key is set, so the policy stays as it is
    assert main(["--repo", str(repo.root), "init", "--operate", "--force"]) == 0
    assert repo.read(repo.policy_file) == after


def test_s040_16_init_operate_keeps_a_level_the_policy_sets(repo: Repo) -> None:
    text = repo.read(repo.policy_file) + ENVIRONMENTS + '\n[autonomy]\nrollback = "propose"\n'
    repo.write(repo.policy_file, text)
    init_operate(repo.root, force=False)
    assert autonomy(repo) == {"rollback": "propose", "deploy": {"production": "act", "staging": "act"}}
    assert repo.read(repo.policy_file).startswith(text)


def test_s040_16_init_operate_adds_autonomy_to_a_policy_without_one(repo: Repo) -> None:
    text = repo.read(repo.policy_file)
    assert "autonomy" not in tomllib.loads(text)
    written = init_operate(repo.root, force=False)
    assert written == (repo.root / OPERATE_CALLER, config_path(repo.root))
    assert autonomy(repo) == {"rollback": DEFAULTS.rollback.value}
    assert repo.read(repo.policy_file).startswith(text)


def test_s040_16_init_operate_writes_into_an_autonomy_deploy_table(repo: Repo) -> None:
    text = repo.read(repo.policy_file) + ENVIRONMENTS + '\n[autonomy]\nrollback = "act"\n\n[autonomy.deploy]\n'
    text += 'staging = "propose"\n'
    repo.write(repo.policy_file, text)
    init_operate(repo.root, force=False)
    assert autonomy(repo) == {"rollback": "act", "deploy": {"staging": "propose", "production": "act"}}
    assert repo.read(repo.policy_file).startswith(text)


def test_s040_16_init_operate_refuses_an_edit_it_cant_make_and_writes_nothing(repo: Repo) -> None:
    # [autonomy] set by a top-level dotted key: there is no [autonomy] header to add the line under
    text = 'autonomy.release = "act"\n' + repo.read(repo.policy_file)
    repo.write(repo.policy_file, text)
    with pytest.raises(ReleaseError, match=r'can\'t add rollback = "act" .* to \[autonomy\]'):
        init_operate(repo.root, force=False)
    assert repo.read(repo.policy_file) == text
    assert not (repo.root / OPERATE_CALLER).exists()


def test_s040_16_init_operate_refuses_without_a_policy(repo: Repo) -> None:
    config_path(repo.root).unlink()
    with pytest.raises(ReleaseError, match="no release policy"):
        init_operate(repo.root, force=False)
    assert not (repo.root / OPERATE_CALLER).exists()
