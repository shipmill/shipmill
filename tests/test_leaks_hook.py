"""Spec 081: the delivery hook's leaks rule runs `uvx shipmill==<pinned> leaks push` for a git
push in a repo with [agents] that the other rules allow, and refuses the push when the check
exits 2, can't run, or doesn't finish in 45 seconds (S-081-11). The check is a stand-in"""

import io
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import leak_push
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.leaks import Destination, LeakRefused, refusal

from .test_delivery_hooks import (
    AGENTS,
    APP,
    DELIVERY,
    HOOKS_JSON,
    PINNED,
    RELEASE_ONLY,
    Sandbox,
    fixture,
    git_repo,
)
from .test_leak_push import GITHUB_TOKEN


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> Sandbox:
    base = tmp_path_factory.mktemp("leaks-hook")
    outside = base / "outside"
    outside.mkdir()
    return Sandbox(
        app=git_repo(base / "app", APP, origin=True),
        agents=git_repo(base / "agents", AGENTS),
        release=git_repo(base / "release", RELEASE_ONLY),
        bare=git_repo(base / "bare", None),
        outside=outside,
    )


Done = subprocess.CompletedProcess[str]

FINDINGS = (
    "shipmill leaks push: refused, nothing was sent (acme/widgets is public)\n"
    '  term: commit 1a2b3c4, notes.md, line 3, names the private term "Acme Rocket"\n'
    "Instead: rewrite the unpushed commits without it\n"
)


@dataclass
class Check:
    """Stands in for `uvx shipmill==<pinned> leaks push`: answers code with stderr, or raises"""

    code: int = 0
    stderr: str = ""
    raises: BaseException | None = None
    calls: list[tuple[list[str], Path, float]] = field(default_factory=list)

    def __call__(self, cmd: Sequence[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(cmd), cwd, timeout))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(list(cmd), self.code, "", self.stderr)


def pre(command: str, where: Path, check: Callable[[Sequence[str], Path, float], Done]) -> tuple[int, list[str]]:
    """The pre hook on a Bash command run in where, in a session without the App (the push
    rules don't read it); its exit and its stderr's lines"""
    data = fixture("bash-read.json", where, command)
    stderr = io.StringIO()
    code = DELIVERY.main(["pre"], io.StringIO(json.dumps(data)), stderr, env={}, timed=check)
    return code, stderr.getvalue().splitlines()


def leaks_argv(where: Path, *args: str) -> list[str]:
    return ["uvx", PINNED, "leaks", "push", "--repo", str(where), *args]


# -- S-081-11 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("git push origin feat/x", ["--", "origin", "feat/x"]),
        ("git push", []),
        ("git push -u origin HEAD", ["--", "origin", "HEAD"]),
        ("git push origin feat/x:feat/y feat/z", ["--", "origin", "feat/x:feat/y", "feat/z"]),
        ("git push --force-with-lease=feat/x:abc123 origin feat/x", ["--", "origin", "feat/x"]),
        ("git push --tags origin", ["--tags", "--", "origin"]),
        ("git push --all", ["--all"]),
        ("git push -d origin feat/x", ["--", "origin", ":feat/x"]),
        ("git push --delete origin feat/x feat/y", ["--", "origin", ":feat/x", ":feat/y"]),
        ("git push -o ci.skip origin feat/x", ["--", "origin", "feat/x"]),
        ("git push --repo=upstream", ["--", "upstream"]),  # --repo names the remote when no argument does
        ("git push --repo upstream", ["--", "upstream"]),
        ("git push --repo=upstream origin feat/x", ["--", "origin", "feat/x"]),
    ],
)
def test_s081_11_a_push_runs_the_pinned_leak_check_with_its_remote_and_refspecs(
    box: Sandbox, command: str, args: list[str]
) -> None:
    check = Check()
    assert pre(command, box.agents, check) == (0, [])
    assert check.calls == [(leaks_argv(box.agents, *args), box.agents, 45)]


def test_s081_11_a_push_from_another_folder_names_its_repo(box: Sandbox) -> None:
    check = Check()
    assert pre(f"git -C {box.agents} push origin feat/x", box.outside, check)[0] == 0
    assert check.calls[0][0] == leaks_argv(box.agents, "--", "origin", "feat/x")


def test_s081_11_findings_refuse_the_push_and_are_printed(box: Sandbox) -> None:
    code, lines = pre("git push origin feat/x", box.agents, Check(2, FINDINGS))
    assert code == 2
    assert lines[0] == "shipmill hook leaks: git push origin feat/x"
    assert lines[1].startswith("Rule: a push sends no listed private term to a public repo") and lines[1].endswith(
        "(D-94)"
    )
    assert lines[2].startswith("Instead: rewrite the unpushed commits without what the check names below")
    assert lines[2].endswith("then run: git push origin feat/x")
    assert lines[3:] == FINDINGS.strip().splitlines()


@pytest.mark.parametrize(
    ("check", "why"),
    [
        (Check(raises=subprocess.TimeoutExpired(["uvx"], 45)), "didn't finish in 45 s"),
        (Check(raises=FileNotFoundError(2, "No such file or directory", "uvx")), "didn't start: "),
        (Check(1, "error: no such command\n"), "exited 1"),
        (Check(2, "shipmill: ~/.config/shipmill/private.toml isn't valid TOML\n"), None),
    ],
)
def test_s081_11_a_check_that_cant_run_or_finish_refuses_the_push(box: Sandbox, check: Check, why: str | None) -> None:
    code, lines = pre("git push origin feat/x", box.agents, check)
    assert code == 2
    assert lines[0] == "shipmill hook leaks: git push origin feat/x"
    if why is not None:
        assert lines[2].startswith("Instead: the leak check couldn't run (`uvx ")
        assert why in lines[2]
    assert lines[2].endswith("then run: git push origin feat/x")
    if check.stderr:
        assert lines[3:] == check.stderr.strip().splitlines()


@dataclass
class Real:
    """Runs the real `shipmill leaks push` in process for `uvx shipmill==<pinned> leaks push`,
    its exit and stderr as `shipmill.cli.run` gives them; no gh on PATH, so a repo off
    github.com is checked as public"""

    home: Path

    def __call__(self, cmd: Sequence[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        assert list(cmd[:2]) == ["uvx", PINNED]
        try:
            code, said = main(list(cmd[2:]), environ={"PATH": ""}, home=self.home), ""
        except LeakRefused as exc:
            code, said = 2, f"{exc}\n"
        except ReleaseError as exc:
            code, said = 2, f"shipmill: {exc}\n"
        return subprocess.CompletedProcess(list(cmd), code, "", said)


def test_a_push_of_a_branch_the_same_command_creates_claims_no_leak(tmp_path: Path) -> None:
    """#1542's Check: the hook sees the whole command before any part runs, so `new` doesn't
    exist yet; the push is still refused, naming the missing ref, and claims no leak"""
    repo = git_repo(tmp_path / "repo", AGENTS, origin=True)
    command = "git switch -c new && git commit --allow-empty -m x && git push -u origin new"
    code, lines = pre(command, repo, Real(tmp_path / "home"))
    assert code == 2
    assert lines[0] == "shipmill hook leaks: git push -u origin new"
    assert lines[2].startswith("Instead: ")
    assert "rewrite" not in lines[2]
    assert "doesn't exist" in lines[2] and "before any part of it runs" in lines[2]
    assert lines[2].endswith("then run: git push -u origin new")
    assert any("`new`" in line and leak_push.MISSING_REF in line for line in lines[3:])


def test_a_push_of_an_existing_ref_with_a_finding_still_says_to_rewrite_it(tmp_path: Path) -> None:
    repo = git_repo(tmp_path / "repo", AGENTS, origin=True)
    git = Git(repo, "t", "t@example.com")
    git.run("switch", "-q", "-c", "leak")
    (repo / "deploy.sh").write_text(f"export GH={GITHUB_TOKEN}\n", encoding="utf-8")
    git.run("add", "deploy.sh")
    git.run("commit", "-q", "-m", "deploy")
    code, lines = pre("git push -u origin leak", repo, Real(tmp_path / "home"))
    assert code == 2
    assert lines[2].startswith("Instead: rewrite the unpushed commits without what the check names below")
    assert lines[3].startswith(DELIVERY.LEAKS_FOUND)
    assert any("secret-format: commit" in line for line in lines[3:])


def test_a_check_that_cant_read_the_push_says_so_and_claims_no_leak(box: Sandbox) -> None:
    said = "shipmill: git rev-list --reverse --topo-order feat/x failed: fatal: bad object\n"
    code, lines = pre("git push origin feat/x", box.agents, Check(2, said))
    assert code == 2
    assert lines[2].startswith("Instead: the leak check couldn't read the push (")
    assert "fatal: bad object" in lines[2] and "rewrite" not in lines[2]
    assert lines[2].endswith("then run: git push origin feat/x")
    assert lines[3:] == said.strip().splitlines()


def test_the_hooks_phrases_are_the_clis() -> None:
    """The hook tells findings from a ref that doesn't exist yet by the phrases the CLI writes;
    both ship in the same pinned release"""
    assert DELIVERY.LEAKS_MISSING_REF == leak_push.MISSING_REF
    found = str(refusal(leak_push.COMMAND, Destination(None, None), []))
    assert found.startswith(DELIVERY.LEAKS_FOUND)


def test_s081_11_a_push_that_goes_on_passes_on_its_warnings(box: Sandbox) -> None:
    warned = "Installed 15 packages\nshipmill leaks: warning: high-entropy: commit 1a2b3c4, a.txt holds ...\n"
    assert pre("git push origin feat/x", box.agents, Check(0, warned)) == (
        0,
        ["shipmill leaks: warning: high-entropy: commit 1a2b3c4, a.txt holds ..."],
    )


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git fetch origin",
        "git commit -m x",
        "git log --oneline origin/main..HEAD",
        "ls && git diff",
        "gh pr view 7",
        "echo git push",
        "uvx shipmill==1.0.0 leaks push --repo .",
    ],
)
def test_s081_11_no_command_but_a_git_push_starts_it(box: Sandbox, command: str) -> None:
    check = Check(2, FINDINGS)
    assert pre(command, box.agents, check)[0] == 0
    assert check.calls == []


def test_s081_11_a_push_another_rule_refuses_never_starts_it(box: Sandbox) -> None:
    check = Check()
    code, lines = pre("git push --force origin feat/x", box.app, check)
    assert code == 2 and lines[0].startswith("shipmill hook force-push: ")
    code, lines = pre("git push origin main", box.app, check)
    assert code == 2 and lines[0].startswith("shipmill hook default-branch-push: ")
    assert check.calls == []


@pytest.mark.parametrize("where", ["release", "bare", "outside"])
def test_s081_11_a_push_outside_a_repo_with_agents_starts_nothing(box: Sandbox, where: str) -> None:
    check = Check(2, FINDINGS)
    assert pre("git push origin feat/x", getattr(box, where), check)[0] == 0
    assert check.calls == []


def test_s081_11_the_bash_hooks_timeout_is_60() -> None:
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    [bash] = [h for entry in hooks["PreToolUse"] if entry["matcher"] == "Bash" for h in entry["hooks"]]
    assert bash["timeout"] == 60
    assert DELIVERY.LEAKS_TIMEOUT == 45


def test_s081_11_the_real_runner_stops_a_check_past_its_timeout(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        DELIVERY.run_timed([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 0.2)
    done = DELIVERY.run_timed([sys.executable, "-c", "print('ok')"], tmp_path, 10)
    assert (done.returncode, done.stdout) == (0, "ok\n")
