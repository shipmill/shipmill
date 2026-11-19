"""Spec 081: doctor's leaks block (S-081-15), and the docs and fixtures that name only invented
terms (S-081-17). The private file lives under a tmp home, gitleaks and the repo's visibility
are stand-ins: no test reads the account's own file or reaches the network. Names are
invented: `Acme`, `example` hosts"""

import re
from pathlib import Path

import pytest

from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, LeakProbe, doctor
from shipmill.errors import ReleaseError
from shipmill.leaks import PRIVATE_FILE, TERM_MIN, Visibility

from .conftest import Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\n'
TERMS = ("Acme Rocket", "acmerocket", "rocket.example")
SECRET = "s3cr3t-Acme-value-0042"  # a value no row may print


def probe(home: Path, visibility: Visibility | None = Visibility.PUBLIC, gitleaks: str | None = None) -> LeakProbe:
    return LeakProbe(home, lambda: gitleaks, lambda: visibility)


def private(home: Path, text: str) -> Path:
    path = home / PRIVATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def block(repo: Repo, leaks: LeakProbe | None) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github, leaks=leaks) if c.name == "leaks"]


@pytest.fixture
def agents_repo(repo: Repo) -> Repo:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + AGENTS)
    return repo


# -- S-081-15: the leaks block --------------------------------------------------------------------


def test_s081_15_terms_on_print_their_count_and_never_a_term(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    listed = ", ".join(f'"{term}"' for term in TERMS)
    private(home, f"terms = [{listed}]\n")
    found = block(agents_repo, probe(home))
    assert found[0] == Check("PASS", "leaks", "terms on: 3 terms from ~/.config/shipmill/private.toml")
    text = " ".join(c.detail for c in found).lower()
    assert all(term.lower() not in text for term in TERMS)


@pytest.mark.parametrize(
    ("visibility", "status", "seen"),
    [
        (Visibility.PUBLIC, "WARN", "the repo is public"),
        (None, "WARN", "the repo's visibility can't be read"),
        (Visibility.PRIVATE, "PASS", "(the repo is private)"),
        (Visibility.INTERNAL, "PASS", "(the repo is internal)"),
    ],
)
def test_s081_15_terms_off_warns_when_the_repo_is_public(
    agents_repo: Repo, tmp_path: Path, visibility: Visibility | None, status: str, seen: str
) -> None:
    found = block(agents_repo, probe(tmp_path / "home", visibility))
    assert found[0].status == status
    assert found[0].detail.startswith("terms off: no ~/.config/shipmill/private.toml")
    assert seen in found[0].detail


def test_s081_15_a_file_with_no_terms_reads_as_off(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    private(home, "terms = []\n")
    (first, *_) = block(agents_repo, probe(home))
    assert first.status == "WARN"
    assert first.detail.startswith("terms off: ~/.config/shipmill/private.toml lists no terms, and the repo is public")


def test_s081_15_terms_on_reads_no_visibility(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    private(home, 'terms = ["Acme Rocket"]\n')

    def unread() -> Visibility | None:
        raise AssertionError("no visibility read while terms are listed")

    assert block(agents_repo, LeakProbe(home, lambda: None, unread))[0].status == "PASS"


def test_s081_15_secrets_name_each_file_and_its_count_never_a_name_or_value(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    exported = tmp_path / "acme-rocket.env"
    exported.write_text(f"DEPLOY_TOKEN={SECRET}\nDB_PASSWORD={SECRET}x\n", encoding="utf-8")
    private(home, f'terms = ["Acme Rocket"]\nsecret_files = ["{exported}"]\n')
    agents_repo.write(".env", f"API_TOKEN={SECRET}\nLOG_LEVEL=debug-verbose\n")  # untracked
    agents_repo.write(".env.example", "API_TOKEN=placeholder-value\n")
    agents_repo.git.run("add", "-f", ".env.example")
    (secrets_row,) = [c for c in block(agents_repo, probe(home)) if c.detail.startswith("secrets:")]
    assert secrets_row == Check("PASS", "leaks", f"secrets: values by file: .env 1, {exported} 2")
    assert SECRET not in secrets_row.detail and "API_TOKEN" not in secrets_row.detail


def test_s081_15_no_secret_file_says_so(agents_repo: Repo, tmp_path: Path) -> None:
    (secrets_row,) = [c for c in block(agents_repo, probe(tmp_path / "home")) if c.detail.startswith("secrets:")]
    assert secrets_row.status == "PASS"
    assert secrets_row.detail.startswith("secrets: no untracked .env file in the checkout's root and no secret_files")


@pytest.mark.parametrize(
    ("version", "status", "detail"),
    [
        (None, "PASS", "scanner: built-in formats; gitleaks is not on PATH"),
        ("8.21.2", "PASS", "scanner: built-in formats and gitleaks 8.21.2"),
        ("v8.19.0", "PASS", "scanner: built-in formats and gitleaks v8.19.0"),
        (
            "8.18.4",
            "WARN",
            "scanner: built-in formats; gitleaks 8.18.4 is on PATH, but the check runs only 8.19 or newer:"
            " upgrade gitleaks",
        ),
    ],
)
def test_s081_15_scanner_names_gitleaks_version_or_its_absence(
    agents_repo: Repo, tmp_path: Path, version: str | None, status: str, detail: str
) -> None:
    assert block(agents_repo, probe(tmp_path / "home", gitleaks=version))[-1] == Check(status, "leaks", detail)


def test_s081_15_a_gitleaks_that_cant_tell_its_version_warns(agents_repo: Repo, tmp_path: Path) -> None:
    def broken() -> str | None:
        raise ReleaseError("gitleaks version exited 1: boom")

    last = block(agents_repo, LeakProbe(tmp_path / "home", broken, lambda: None))[-1]
    assert last == Check(
        "WARN", "leaks", "scanner: built-in formats; can't tell gitleaks' version: gitleaks version exited 1: boom"
    )


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ('terms = ["Acme Rocket"]\nallow = true\n', "unknown key 'allow'"),
        ('terms = "Acme Rocket"\n', "terms must be a list of strings"),
        ('terms = ["ab"]\n', "terms holds a term under 3 characters"),
        ("terms = [\n", "isn't valid TOML"),
    ],
)
def test_s081_15_a_private_file_that_doesnt_parse_fails_naming_the_fix(
    agents_repo: Repo, tmp_path: Path, text: str, names: str
) -> None:
    home = tmp_path / "home"
    path = private(home, text)
    found = block(agents_repo, probe(home))
    assert [c.status for c in found] == ["FAIL", "PASS"]  # then the scanner line still
    assert found[0].detail.startswith(f"private file: {path}")
    assert names in found[0].detail
    assert found[0].detail.endswith("is refused: fix it as docs/leaks.md describes")


@pytest.mark.parametrize(
    ("text", "where"),
    [
        ('terms = []\n["Acme Rocket"]\n["Acme Rocket"]\n', "isn't valid TOML at line 3, column 15"),
        ("terms = []\nx = {acmerocket = 1, acmerocket = 2}\n", "isn't valid TOML at line 2, column 36"),
    ],
)
def test_s081_15_a_private_file_that_isnt_toml_fails_naming_where_never_a_term(
    agents_repo: Repo, tmp_path: Path, text: str, where: str
) -> None:
    home = tmp_path / "home"
    path = private(home, text)
    (failed, _) = block(agents_repo, probe(home))
    assert failed.status == "FAIL"
    assert failed.detail.startswith(f"private file: {path} {where}; fix it")
    assert "acme" not in failed.detail.lower().replace(str(path).lower(), "")


def test_s081_15_an_unreadable_secret_file_fails_naming_the_key(agents_repo: Repo, tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = private(home, 'secret_files = ["~/gone/acme.env"]\n')
    (failed,) = [c for c in block(agents_repo, probe(home)) if c.status == "FAIL"]
    assert failed.detail.startswith("secrets: secret_files' ~/gone/acme.env can't be read")
    assert f"fix secret_files in {path}" in failed.detail


def test_s081_15_a_repo_without_agents_gets_no_leaks_block(repo: Repo, tmp_path: Path) -> None:
    def unasked() -> str | None:
        raise AssertionError("no leaks block without [agents]")

    assert block(repo, LeakProbe(tmp_path / "home", unasked, lambda: None)) == []


def test_s081_15_without_a_probe_doctor_checks_none(agents_repo: Repo) -> None:
    assert block(agents_repo, None) == []


# -- S-081-17: the docs and fixtures name only invented terms -------------------------------------

LEAKS_DOC = ROOT / "docs" / "leaks.md"
INSTALL_DOC = ROOT / "docs" / "install.md"
_TERMS_ARRAY = re.compile(r"terms\s*=\s*\[([^\]\n]*)\]")
_QUOTED = re.compile(r"\"([^\"{}]+)\"|'([^'{}]+)'")
_TERM_CONSTANT = re.compile(r"^TERM\w*\s*=\s*\"([^\"]+)\"", re.M)
_URL_HOST = re.compile(r"[a-z][a-z0-9+.-]*://(?:[^\s/@]*@)?([A-Za-z0-9.-]+)|@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_PUBLIC_HOSTS = frozenset({"github.com"})  # the public host the docs name on purpose


def invented(term: str) -> bool:
    """A term of Acme's, or an example host"""
    return "acme" in term.lower() or re.search(r"(?:^|\.)example(?:\.|$)", term.lower()) is not None


def listed_terms(text: str) -> list[str]:
    """The strings a text lists as terms: a `terms = [...]` array's items and a TERM constant,
    leaving out the ones under 3 characters, which the private file refuses as terms"""
    found = [a or b for array in _TERMS_ARRAY.findall(text) for a, b in _QUOTED.findall(array)]
    return [term for term in (*found, *_TERM_CONSTANT.findall(text)) if len(term.strip()) >= TERM_MIN]


def fixtures() -> list[Path]:
    """The tests' fixtures: every file under tests/fixtures/, and the test modules, which hold
    the private files they write"""
    tests = ROOT / "tests"
    return sorted([*(p for p in (tests / "fixtures").rglob("*") if p.is_file()), *tests.glob("*.py")])


def test_s081_17_leaks_md_documents_the_file_the_detectors_and_both_refusals() -> None:
    text = LEAKS_DOC.read_text(encoding="utf-8")
    assert "~/.config/shipmill/private.toml" in text and "secret_files" in text
    for detector in ("`term`", "`secret-value`", "`secret-format`", "`high-entropy`"):
        assert detector in text
    assert "shipmill gh: refused, nothing was sent" in text  # the write's refusal
    assert "`git push`" in text and re.search(r"refuses\s+the push with exit 2", text)  # the push's
    assert "(leaks.md)" in INSTALL_DOC.read_text(encoding="utf-8")


def test_s081_17_leaks_md_names_only_acme_and_example_hosts() -> None:
    text = LEAKS_DOC.read_text(encoding="utf-8")
    terms = listed_terms(text)
    assert terms and all(invented(term) for term in terms), terms
    hosts = {a or b for a, b in _URL_HOST.findall(text)}
    assert all(invented(host) or host in _PUBLIC_HOSTS for host in hosts), hosts


def test_s081_17_no_fixture_names_a_term_outside_acme_and_example_hosts() -> None:
    named = {path: listed_terms(path.read_text(encoding="utf-8", errors="replace")) for path in fixtures()}
    outside = {str(path.relative_to(ROOT)): [t for t in terms if not invented(t)] for path, terms in named.items()}
    assert {path: terms for path, terms in outside.items() if terms} == {}
    assert any(named.values())  # the scan reads the terms the leak tests write
