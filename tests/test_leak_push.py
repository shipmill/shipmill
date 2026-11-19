"""Spec 081: `shipmill leaks push` refuses a push whose new commits or destination ref names
hold a private term (to a public repo), a secret's exact value, or a known token format, on
temporary git repos. No test reaches the network: the remote's tracking refs are set by hand
and gh's visibility read is a capture. Names are invented: `Acme`, `example` hosts"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.leak_push import PUSH_FIX, Push, outgoing
from shipmill.leaks import PRIVATE_FILE, LeakRefused

REPO = "acme/widgets"
TERMS = 'terms = ["Acme Rocket", "acmerocket"]\n'
TOKEN_VALUE = "acme-example-0123456789"
GITHUB_TOKEN = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # put together at run time
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
RANDOM = "".join(ALPHABET[(i * 7) % len(ALPHABET)] for i in range(40))  # a high-entropy string


@dataclass
class Visibility:
    """Stands in for `gh api repos/<r> --jq .visibility`"""

    answer: str = "public"
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        return 0, f"{self.answer}\n"


@dataclass(frozen=True)
class Box:
    root: Path
    home: Path
    fakes: Path  # a PATH folder holding a gh, never run: its reads go through the capture

    @property
    def git(self) -> Git:
        return Git(self.root, "t", "t@example.com")

    def env(self) -> dict[str, str]:
        return {"PATH": str(self.fakes)}

    def commit(self, files: Mapping[str, str | bytes | None], message: str = "change") -> str:
        """A commit writing files (None removes one); its SHA"""
        for name, text in files.items():
            path = self.root / name
            if text is None:
                self.git.run("rm", "-q", "--", name)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(text, bytes):
                path.write_bytes(text)
            else:
                path.write_text(text, encoding="utf-8")
            self.git.run("add", "--", name)
        self.git.run("commit", "-q", "-m", message)
        return self.git.sha()

    def pushed(self, branch: str = "main") -> None:
        """origin's tracking ref at HEAD, as after a push"""
        self.git.run("update-ref", f"refs/remotes/origin/{branch}", "HEAD")


@pytest.fixture
def box(tmp_path: Path) -> Box:
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    Git(root).run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    gh = fakes / "gh"
    gh.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    gh.chmod(0o700)
    home = tmp_path / "home"
    (home / PRIVATE_FILE).parent.mkdir(parents=True)
    made = Box(root, home, fakes)
    made.commit({"README.md": "# demo\n\nAbout the Acme Rocket launch.\n", "notes.md": "one\ntwo\n"}, "init")
    made.pushed()
    return made


def private(box: Box, text: str = TERMS) -> None:
    (box.home / PRIVATE_FILE).write_text(text, encoding="utf-8")


def leaks_push(box: Box, *args: str, capture: Visibility | None = None) -> int:
    return main(
        ["leaks", "push", "--repo", str(box.root), *args],
        environ=box.env(),
        home=box.home,
        gh_capture=capture or Visibility(),
    )


def refused(box: Box, *args: str, capture: Visibility | None = None) -> list[str]:
    """`leaks push args` refused; its refusal's lines"""
    with pytest.raises(LeakRefused) as caught:
        leaks_push(box, *args, capture=capture)
    said = str(caught.value)
    assert said.endswith(PUSH_FIX)
    return said.splitlines()


# -- S-081-9 -------------------------------------------------------------------------------------


def test_s081_9_a_term_in_an_added_line_is_refused_naming_the_commit_path_and_line(box: Box) -> None:
    private(box)
    sha = box.commit({"notes.md": "one\ntwo\nthree, for acme  rocket\n"})
    lines = refused(box, "origin", "main")
    assert lines[0] == f"shipmill leaks push: refused, nothing was sent ({REPO} is public)"
    assert f'  term: commit {sha[:7]}, notes.md, line 3, names the private term "Acme Rocket"' in lines


def test_s081_9_a_term_in_a_path_it_adds_or_renames_to_is_refused(box: Box) -> None:
    private(box)
    added = box.commit({"docs/acmerocket-plan.md": "plain\n"})
    lines = refused(box, "origin", "main")
    assert f'  term: commit {added[:7]}\'s path names the private term "acmerocket"' in lines
    box.pushed()
    box.git.run("mv", "notes.md", "acmerocket.md")
    renamed = box.commit({})
    lines = refused(box, "origin", "main")
    assert f'  term: commit {renamed[:7]}\'s path names the private term "acmerocket"' in lines


def test_s081_9_a_term_in_a_message_is_refused(box: Box) -> None:
    private(box)
    sha = box.commit({"notes.md": "one\ntwo\nthree\n"}, "Plain title\n\nAs the Acme Rocket team asked")
    lines = refused(box, "origin", "main")
    assert f'  term: commit {sha[:7]}\'s message, line 3, names the private term "Acme Rocket"' in lines


def test_s081_9_a_term_in_the_destination_ref_is_refused(box: Box) -> None:
    private(box)
    box.commit({"notes.md": "one\ntwo\nthree\n"})
    lines = refused(box, "origin", "HEAD:feat/acmerocket-launch")
    assert '  term: the destination ref names the private term "acmerocket"' in lines


def test_s081_9_a_term_only_in_a_line_the_push_doesnt_add_passes(box: Box) -> None:
    """README.md names the term in a line the remote has; the push changes another line of it"""
    private(box)
    box.commit({"README.md": "# demo, renamed\n\nAbout the Acme Rocket launch.\n"})
    assert leaks_push(box, "origin", "main") == 0


def test_s081_9_a_term_in_a_commit_the_remote_has_passes(box: Box) -> None:
    private(box)
    box.commit({"notes.md": "one\ntwo\nacme rocket\n"}, "Acme Rocket notes")
    box.pushed()
    box.commit({"other.md": "plain\n"})
    assert leaks_push(box, "origin", "main") == 0


def test_s081_9_with_no_refspec_the_current_branch_is_read(box: Box) -> None:
    private(box)
    box.git.run("switch", "-q", "-c", "feat/x")
    sha = box.commit({"notes.md": "acme rocket\n"})
    assert f"commit {sha[:7]}, notes.md, line 1," in "\n".join(refused(box))
    assert f"commit {sha[:7]}" in "\n".join(refused(box, "origin"))


def test_s081_9_every_branch_and_tag_with_their_flags(box: Box) -> None:
    private(box)
    box.git.run("switch", "-q", "-c", "side")
    side = box.commit({"side.md": "acme rocket\n"})
    box.git.run("switch", "-q", "main")
    assert leaks_push(box, "origin", "main") == 0
    assert f"commit {side[:7]}" in "\n".join(refused(box, "--all", "origin"))
    assert f"commit {side[:7]}" in "\n".join(refused(box, "--branches", "origin"))
    assert f"commit {side[:7]}" in "\n".join(refused(box, "origin", "refs/heads/*:refs/heads/*"))
    box.git.run("tag", "v1", "side")
    box.git.run("branch", "-D", "side")
    assert f"commit {side[:7]}" in "\n".join(refused(box, "--tags", "origin"))
    assert f"commit {side[:7]}" in "\n".join(refused(box, "--mirror", "origin"))


def test_s081_11_the_hooks_arguments_parse(box: Box) -> None:
    """The hook passes the push's flags, then `--` and its remote and refspecs"""
    private(box)
    sha = box.commit({"notes.md": "acme rocket\n"})
    assert f"commit {sha[:7]}" in "\n".join(refused(box, "--", "origin", "main"))
    assert f"commit {sha[:7]}" in "\n".join(refused(box, "--all", "--", "origin"))
    assert leaks_push(box, "--", "origin", ":main") == 0


def test_s081_9_a_refspec_that_only_deletes_sends_nothing(box: Box) -> None:
    private(box)
    box.commit({"notes.md": "acme rocket\n"})
    assert leaks_push(box, "origin", ":refs/heads/old") == 0


def test_s081_9_a_binary_file_is_left_out(box: Box) -> None:
    private(box)
    box.commit({"logo.bin": b"\x00\x01acme rocket\x00"})
    assert leaks_push(box, "origin", "main") == 0


def test_s081_9_the_visibility_is_read_once_and_only_with_a_term(box: Box) -> None:
    box.commit({"notes.md": "one\n"})
    capture = Visibility()
    assert leaks_push(box, "origin", "main", capture=capture) == 0
    assert capture.calls == []
    private(box)
    capture = Visibility()
    assert leaks_push(box, "origin", "main", capture=capture) == 0
    assert capture.calls == [[str(box.fakes / "gh"), "api", f"repos/{REPO}", "--jq", ".visibility"]]


def test_s081_9_a_remote_off_github_is_public(box: Box) -> None:
    private(box)
    box.git.run("remote", "add", "mirror", "https://git.example.com/acme/widgets.git")
    box.git.run("update-ref", "refs/remotes/mirror/main", "refs/remotes/origin/main")
    box.commit({"notes.md": "acme rocket\n"})
    lines = refused(box, "mirror", "main", capture=Visibility("private"))
    assert lines[0] == (
        "shipmill leaks push: refused, nothing was sent (it goes to no repo on github.com, so it is checked as public)"
    )


def test_s081_9_a_merge_is_read_against_its_first_parent(box: Box) -> None:
    """The side commit is read by itself, and the merge against main, its first parent, so the
    side's lines are its added lines too; main's own commit is no added line of the merge"""
    private(box)
    box.git.run("switch", "-q", "-c", "side")
    side = box.commit({"side.md": "acme rocket\n"})
    box.git.run("switch", "-q", "main")
    box.commit({"notes.md": "one\ntwo\nAcme Rocket\n"})
    box.pushed()
    box.git.run("merge", "-q", "--no-edit", "side")
    merge = box.git.sha()
    said = "\n".join(refused(box, "origin", "main"))
    assert f"commit {side[:7]}, side.md, line 1," in said
    assert f"commit {merge[:7]}, side.md, line 1," in said
    assert "notes.md" not in said


# -- S-081-10 ------------------------------------------------------------------------------------


def test_s081_10_a_secret_value_is_refused_in_a_private_repo_though_a_later_commit_removes_it(box: Box) -> None:
    private(box)
    (box.root / ".env").write_text(f"API_TOKEN={TOKEN_VALUE}\n", encoding="utf-8")
    added = box.commit({"config.py": f'TOKEN = "{TOKEN_VALUE}"\n'})
    box.commit({"config.py": "TOKEN = None\n"})
    capture = Visibility("private")
    lines = refused(box, "origin", "main", capture=capture)
    assert lines[0] == f"shipmill leaks push: refused, nothing was sent ({REPO} is private)"
    assert f"  secret-value: commit {added[:7]}, config.py, line 1, holds the value of API_TOKEN from .env" in lines
    assert TOKEN_VALUE not in "\n".join(lines)


def test_s081_10_a_known_format_is_refused_though_a_later_commit_removes_it(box: Box) -> None:
    added = box.commit({"deploy.sh": f"echo start\nexport GH={GITHUB_TOKEN}\n"})
    box.commit({"deploy.sh": None})
    lines = refused(box, "origin", "main", capture=Visibility("private"))
    assert f"  secret-format: commit {added[:7]}, deploy.sh, line 2, holds a GitHub token (ghp_…)" in lines
    assert GITHUB_TOKEN[4:] not in "\n".join(lines)


def test_s081_10_a_term_in_a_private_repo_passes(box: Box) -> None:
    private(box)
    box.commit({"notes.md": "acme rocket\n"}, "Acme Rocket")
    assert leaks_push(box, "origin", "main", capture=Visibility("private")) == 0


def test_s081_10_a_malformed_private_file_refuses_every_push(box: Box) -> None:
    private(box, "terms = [3]\n")
    box.commit({"notes.md": "plain\n"})
    with pytest.raises(ReleaseError, match="terms must be a list of strings") as caught:
        leaks_push(box, "origin", "main")
    assert not isinstance(caught.value, LeakRefused)


# -- S-081-8 on a push ---------------------------------------------------------------------------


def test_s081_8_a_high_entropy_line_warns_and_the_push_goes_on(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    sha = box.commit({"keys.txt": f"one\nvalue {RANDOM}\n", "uv.lock": f"hash = {RANDOM[::-1]}\n"})
    assert leaks_push(box, "origin", "main") == 0
    assert capsys.readouterr().err.splitlines() == [
        f"shipmill leaks: warning: high-entropy: commit {sha[:7]}, keys.txt, line 2, holds a high-entropy string"
        f" of 40 characters ({RANDOM[:4]}…)"
    ]


# -- what a push sends ---------------------------------------------------------------------------


def test_outgoing_reads_each_commit_by_itself(box: Box) -> None:
    first = box.commit({"notes.md": "one\ntwo\nadded\n"})
    second = box.commit({"notes.md": "one\ntwo\n", "new.md": "x\ny\n"})
    sent = outgoing(box.git, Push("origin", ("main",)))
    assert sent.repo == REPO
    texts = [(t.where, t.text) for t in sent.texts]
    assert (f"commit {first[:7]}, notes.md", "added") in texts
    assert (f"commit {second[:7]}, new.md", "x\ny") in texts
    assert (f"commit {second[:7]}'s path", "notes.md") in texts
    assert ("the destination ref", "main") in texts
    assert sent.lines[f"commit {first[:7]}, notes.md"] == (3,)
