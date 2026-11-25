"""Spec 081: `shipmill leaks check` over a file or stdin (S-081-13), and the leak check `spec
open` and `review record` run before their first write (S-081-12). No test reaches the network:
gh's reads are captures, origin a local bare repo. Names are invented: `Acme`, `example` hosts"""

import datetime as dt
import io
from pathlib import Path

import pytest

from shipmill.cli import SPEC_PUSH_FIX, _SpecLeaks, _Vet, main
from shipmill.errors import ReleaseError
from shipmill.leaks import FIX, WARNING, LeakRefused, Private
from shipmill.spec_open import GitCheckout, open_spec

from .test_app import REPO as ORIGIN
from .test_app import FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, checkout
from .test_app_token import MintApi
from .test_area_record import FakeReads
from .test_earned_landing import Rules
from .test_gh_refuses_without_app import HOST_IDENTITY
from .test_leak_push import RANDOM
from .test_leaks import CLEAN, GITHUB_TOKEN, LEAKED, PUBLIC, TERM, Reads, host, private, with_term
from .test_review_record import HEAD, PULL, AtHead, based
from .test_review_record import FakeGh as ReviewGh
from .test_spec_open import BRANCH, SPEC, FakeCheckout, FakeHub, available, git, repo_files, request, spec_text
from .test_spec_open import REPO as SPEC_REPO
from .test_spec_open import FakeGh as SpecGh
from .test_spec_open import clone as clone

__all__ = ["clone", "host"]  # pytest's fixtures, imported for this module

OTHER_TERM = "Acme Orbit"  # listed, never in a text: no output names it
VISIBILITY = ["--jq", ".visibility"]


def check(
    host: Host,
    *args: str,
    stdin: str = "",
    capture: Reads | None = None,
    repo: Path | None = None,
) -> int:
    """`shipmill leaks check args`, its stdin the given text"""
    return main(
        ["--repo", str(repo or host.home), "leaks", "check", *args],
        environ=host.env(),
        home=host.home,
        stdin=io.StringIO(stdin),
        gh_capture=capture or Reads(),
    )


def check_refused(host: Host, *args: str, stdin: str = "", capture: Reads | None = None) -> list[str]:
    """`shipmill leaks check args` refused; its refusal's lines"""
    with pytest.raises(LeakRefused) as caught:
        check(host, *args, stdin=stdin, capture=capture)
    said = str(caught.value)
    assert said.endswith(FIX)
    return said.splitlines()


def text_file(tmp_path: Path, text: str, name: str = "body.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# -- S-081-13: leaks check -----------------------------------------------------------------------


def test_s081_13_a_term_in_a_file_for_a_public_repo_exits_2_with_its_findings(tmp_path: Path, host: Host) -> None:
    with_term(host)
    path = text_file(tmp_path, f"First line.\n\nSecond, {LEAKED}.\n")
    capture = Reads()
    lines = check_refused(host, "--to", PUBLIC, str(path), capture=capture)
    assert lines[0] == f"shipmill leaks check: refused, nothing was sent ({PUBLIC} is public)"
    assert f'  term: the file {path}, line 3, names the private term "{TERM}"' in lines
    assert capture.reads == [PUBLIC]  # read once


def test_s081_13_stdin_is_checked_and_field_names_it(host: Host) -> None:
    with_term(host)
    lines = check_refused(host, "--to", PUBLIC, stdin=f"Title on {LEAKED}\n")
    assert f'  term: the text on stdin names the private term "{TERM}"' in lines
    lines = check_refused(host, "--to", PUBLIC, "--field", "pull request body", "-", stdin=f"On {LEAKED}\n")
    assert f'  term: the pull request body names the private term "{TERM}"' in lines


def test_s081_13_a_token_is_refused_in_any_repo_and_never_printed_whole(host: Host) -> None:
    lines = check_refused(host, "--to", PUBLIC, stdin=f"key: {GITHUB_TOKEN}\n", capture=Reads("private"))
    assert "  secret-format: the text on stdin holds a GitHub token (ghp_…)" in lines
    assert all(GITHUB_TOKEN[:5] not in line for line in lines)


def test_s081_13_a_secret_value_names_its_variable_never_its_value(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, None)
    value = "acme-example-0123456789"
    (root / ".env").write_text(f"API_TOKEN={value}\n", encoding="utf-8")
    with pytest.raises(LeakRefused) as caught:
        check(host, "--to", PUBLIC, stdin=f"the key is {value}\n", repo=root)
    said = str(caught.value)
    assert "  secret-value: the text on stdin holds the value of API_TOKEN from .env" in said.splitlines()
    assert value[:5] not in said


def test_s081_13_no_listed_term_is_printed_beyond_the_ones_found(host: Host) -> None:
    private(host, f'terms = ["{TERM}", "{OTHER_TERM}"]\n')
    said = "\n".join(check_refused(host, "--to", PUBLIC, stdin=f"{LEAKED}\n"))
    assert TERM in said
    assert OTHER_TERM not in said


def test_s081_13_a_clean_text_exits_0_with_its_warnings(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    with_term(host)
    path = text_file(tmp_path, f"{CLEAN}\nchecksum {RANDOM}\n")
    assert check(host, "--to", PUBLIC, str(path)) == 0
    err = capsys.readouterr().err
    assert err.startswith(f"{WARNING} high-entropy: the file {path}, line 2, holds a high-entropy string")
    assert RANDOM not in err


def test_s081_13_a_private_repos_text_is_not_checked_for_terms(host: Host) -> None:
    with_term(host)
    capture = Reads("private")
    assert check(host, "--to", PUBLIC, stdin=f"{LEAKED}\n", capture=capture) == 0
    assert capture.reads == [PUBLIC]


def test_s081_13_without_to_the_checkouts_origin_is_the_repo(tmp_path: Path, host: Host) -> None:
    with_term(host)
    root = checkout(tmp_path, None)
    capture = Reads("private")
    assert check(host, stdin=f"{LEAKED}\n", capture=capture, repo=root) == 0
    assert capture.reads == [ORIGIN]


def test_s081_13_outside_a_checkout_without_to_the_text_goes_to_no_repo(host: Host) -> None:
    with_term(host)
    capture = Reads("private")
    lines = check_refused(host, stdin=f"{LEAKED}\n", capture=capture)
    assert lines[0] == (
        "shipmill leaks check: refused, nothing was sent (it goes to no repo on github.com, so it is checked as public)"
    )
    assert capture.reads == []


@pytest.mark.parametrize("to", ["acme", "acme/widgets/x", "/widgets", "acme/", "ac me/widgets", "acme/wid;gets"])
def test_s081_13_a_malformed_to_exits_2_before_anything_is_read(host: Host, to: str) -> None:
    with_term(host)
    stdin, capture = io.StringIO(f"{LEAKED}\n"), Reads()
    with pytest.raises(ReleaseError, match="--to needs owner/name") as caught:
        main(
            ["--repo", str(host.home), "leaks", "check", "--to", to],
            environ=host.env(),
            home=host.home,
            stdin=stdin,
            gh_capture=capture,
        )
    assert not isinstance(caught.value, LeakRefused)
    assert (stdin.tell(), capture.calls) == (0, [])


@pytest.mark.parametrize("name", ["", " body", "body\nline", "the  body", "body:"])
def test_s081_13_a_malformed_field_exits_2(host: Host, name: str) -> None:
    with pytest.raises(ReleaseError, match="--field names the text"):
        check(host, "--to", PUBLIC, "--field", name, stdin="x\n")


def test_s081_13_a_file_that_cant_be_read_exits_2_naming_it(tmp_path: Path, host: Host) -> None:
    missing = tmp_path / "none.md"
    with pytest.raises(ReleaseError, match=f"{missing} can't be read") as caught:
        check(host, "--to", PUBLIC, str(missing))
    assert not isinstance(caught.value, LeakRefused)


def test_s081_13_a_malformed_private_file_exits_2(host: Host) -> None:
    private(host, "terms = [1]\n")
    with pytest.raises(ReleaseError, match="terms must be a list of strings"):
        check(host, "--to", PUBLIC, stdin="x\n")


# -- S-081-12: spec open -------------------------------------------------------------------------


def spec_open_cli(root: Path, host: Host, gh: SpecGh, fake: FakeCheckout, body: Path) -> int:
    return main(
        ["--repo", str(root), "spec", "open", SPEC, "--issue", "7", "--body-file", str(body)],
        api=MintApi(),
        signer=FakeSigner(),
        environ=host.env(GH_TOKEN=""),
        home=host.home,
        gh_capture=gh,
        spec_checkout=fake,
    )


def test_s081_12_spec_open_refuses_a_body_file_before_its_first_write(tmp_path: Path, host: Host) -> None:
    with_term(host)
    root = checkout(tmp_path, HOST_IDENTITY)
    repo_files(root, spec_text())
    gh, fake = SpecGh(), FakeCheckout()
    with pytest.raises(LeakRefused) as caught:
        spec_open_cli(root, host, gh, fake, text_file(tmp_path, f"Context.\n\n{LEAKED}\n"))
    lines = str(caught.value).splitlines()
    assert lines[0] == f"shipmill spec open: refused, nothing was sent ({ORIGIN}, checked as public)"
    assert f'  term: the body, line 3, names the private term "{TERM}"' in lines
    assert fake.published == []  # no commit pushed
    assert [args for args, _ in gh.calls] == [["api", f"repos/{ORIGIN}", *VISIBILITY]]  # the read alone


def test_s081_12_spec_open_refuses_a_token_in_its_body_file_with_no_private_file(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, HOST_IDENTITY)
    repo_files(root, spec_text())
    gh, fake = SpecGh(), FakeCheckout()
    with pytest.raises(LeakRefused, match="secret-format: the body holds a GitHub token"):
        spec_open_cli(root, host, gh, fake, text_file(tmp_path, f"key {GITHUB_TOKEN}\n"))
    assert (fake.published, gh.calls) == ([], [])


def test_s081_12_spec_open_with_a_clean_body_file_goes_on(tmp_path: Path, host: Host) -> None:
    with_term(host)
    root = checkout(tmp_path, HOST_IDENTITY)
    repo_files(root, spec_text())
    gh, fake = SpecGh(), FakeCheckout()
    assert spec_open_cli(root, host, gh, fake, text_file(tmp_path, f"{CLEAN}\n")) == 0
    assert len(fake.published) == 1


def spec_leaks(top: Path, home: Path, reads: list[str]) -> _SpecLeaks:
    """spec open's leak check as the CLI builds it, the visibility read recorded and failing"""

    def visibility(repo: str) -> None:
        reads.append(repo)

    return _SpecLeaks(top, SPEC_REPO, _Vet(Private.load(home), top, visibility, {"PATH": ""}))


def test_s081_12_spec_open_refuses_the_commit_it_would_push_before_the_push(clone: Path, host: Host) -> None:
    with_term(host)
    (clone / SPEC).write_text(spec_text().replace("Runs write files.", f"Runs write {LEAKED} files."), encoding="utf-8")
    hub, reads = FakeHub(), list[str]()
    with pytest.raises(LeakRefused) as caught:
        open_spec(clone, SPEC_REPO, request(), GitCheckout(clone), hub, available, spec_leaks(clone, host.home, reads))
    said = str(caught.value)
    lines = said.splitlines()
    assert lines[0].startswith("shipmill spec open: refused, nothing was sent (it goes to no repo on github.com")
    assert any(line.endswith(f'{SPEC}, line 8, names the private term "{TERM}"') for line in lines)
    assert said.endswith(SPEC_PUSH_FIX)
    assert git(clone, "ls-remote", "--heads", "origin", BRANCH).strip() == ""  # nothing pushed
    assert hub.writes == []
    assert reads == []  # origin off github.com: no repo, no visibility read


def test_s081_12_spec_open_pushes_a_clean_commit(clone: Path, host: Host) -> None:
    with_term(host)
    hub = FakeHub()
    open_spec(clone, SPEC_REPO, request(), GitCheckout(clone), hub, available, spec_leaks(clone, host.home, []))
    assert git(clone, "ls-remote", "--heads", "origin", BRANCH).strip() != ""


# -- S-081-12: review record ---------------------------------------------------------------------


def review_cli(root: Path, host: Host, gh: ReviewGh, body: Path, key: Path) -> int:
    return main(
        [
            "--repo",
            str(root),
            "review",
            "record",
            str(PULL),
            "--head",
            HEAD,
            "--verdict",
            "merge",
            "--body-file",
            str(body),
        ],
        api=MintApi(expires_from=dt.datetime.now(dt.UTC)),
        signer=FakeSigner(),
        environ=host.env(SHIPMILL_APP_KEY=str(key)),
        home=host.home,
        gh_capture=gh,
        pulls=AtHead(),
        record_reads=FakeReads(),
        rules_reader=Rules(),
    )


def test_s081_12_review_record_refuses_a_body_file_before_its_first_write(tmp_path: Path, host: Host) -> None:
    with_term(host)
    root = checkout(tmp_path, WITH_APP)
    gh = ReviewGh()
    with pytest.raises(LeakRefused) as caught:
        review_cli(root, host, gh, text_file(tmp_path, f"Verdict: MERGE\n\n{LEAKED}\n"), key_file(tmp_path))
    lines = str(caught.value).splitlines()
    assert lines[0] == f"shipmill review record: refused, nothing was sent ({ORIGIN}, checked as public)"
    assert f'  term: the body, line 3, names the private term "{TERM}"' in lines
    assert [args for args, _ in gh.calls] == [["api", f"repos/{ORIGIN}", *VISIBILITY]]  # no POST, no head read


def test_s081_12_review_record_refuses_a_token_in_any_repo(tmp_path: Path, host: Host) -> None:
    root = checkout(tmp_path, WITH_APP)
    gh = ReviewGh()
    with pytest.raises(LeakRefused, match="secret-format: the body, line 3, holds a GitHub token"):
        review_cli(root, host, gh, text_file(tmp_path, f"Verdict: MERGE\n\n{GITHUB_TOKEN}\n"), key_file(tmp_path))
    assert gh.calls == []


def test_s081_12_review_record_with_a_clean_body_file_posts(tmp_path: Path, host: Host) -> None:
    with_term(host)
    root = based(checkout(tmp_path, WITH_APP))
    gh = ReviewGh()
    assert review_cli(root, host, gh, text_file(tmp_path, f"Verdict: MERGE\n\n{CLEAN}\n"), key_file(tmp_path)) == 0
    assert ["api", "-X", "POST"] in [args[:3] for args, _ in gh.calls]
