"""`shipmill gh` (spec 012): run the `gh` on PATH as the repo's GitHub App when its config
sets [agents] app_id, so a session a person starts writes as the App too (D-14).

The arguments reach gh exactly as given. Only the repo gh's `-R`/`--repo` names is read
from them, to limit the token to it, and a merge they ask for (`merge_of`), which spec 030
holds when the pull request has a `never` zone. The token goes to gh in GH_TOKEN, never to
output.
"""

import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shipmill.classify import Pulls
from shipmill.errors import ReleaseError

GhRunner = Callable[[Sequence[str], Mapping[str, str]], int]  # argv and env in, gh's exit code out

_REPO_FLAGS = ("-R", "--repo")
_REPO = re.compile(r"(?:github\.com/)?([A-Za-z0-9-]+/[A-Za-z0-9._-]+)", re.IGNORECASE)


def run_gh(argv: Sequence[str], env: Mapping[str, str]) -> int:
    """Run gh with the terminal's stdin, stdout, and stderr; a signal's death is 128 + its number,
    as a shell reports it"""
    code = subprocess.run(list(argv), env=dict(env), check=False).returncode
    return code if code >= 0 else 128 - code


def find_gh(environ: Mapping[str, str]) -> Path:
    found = shutil.which("gh", path=environ.get("PATH", ""))
    if found is None:
        raise ReleaseError("gh not found on PATH; install GitHub's CLI, https://cli.github.com")
    return Path(found)


def named_repo(args: Sequence[str]) -> str | None:
    """The owner/name gh's `-R`/`--repo` names in args (`-R x`, `--repo x`, `--repo=x`, `-Rx`,
    `-R=x`), the last when given twice, as gh takes it; None when no flag names one. Nothing
    after `--` is a flag"""
    found: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if arg in _REPO_FLAGS:
            if index + 1 == len(args):
                raise ReleaseError(f"gh's {arg} needs a repo, such as owner/name")
            found = args[index + 1]
            index += 2
            continue
        if arg.startswith("--repo="):
            found = arg.removeprefix("--repo=")
        elif arg.startswith("-R") and len(arg) > 2:
            found = arg[2:].removeprefix("=")
        index += 1
    if found is None:
        return None
    matched = _REPO.fullmatch(found)
    if matched is None or any(part in {".", ".."} for part in matched.group(1).split("/")):
        raise ReleaseError(f"gh's -R/--repo is {found!r}; the App's token needs owner/name on github.com")
    return matched.group(1)


def bundled_repo_flag(args: Sequence[str]) -> str | None:
    """The first short-flag cluster in args that holds -R after another flag (`-sR x`, `-dRx`),
    which gh's flag parser reads as -R naming a repo, though `named_repo` can't tell its value
    from another flag's; None when there is none. Nothing after `--` is a flag"""
    for arg in args:
        if arg == "--":
            return None
        if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2 and arg[1] != "R" and "R" in arg:
            return arg
    return None


# S-038-9, D-47: under --product, the groups whose commands write code or pull requests. A
# group in _READS runs only the subcommands named; one in _WRITES runs all but those named
_READS = {
    "pr": frozenset({"list", "view", "diff", "checks", "status"}),
    "release": frozenset({"list", "view"}),
    "repo": frozenset({"view", "list"}),
}
_WRITES = {"workflow": frozenset({"run"}), "run": frozenset({"rerun", "cancel"})}


def product_refusal(args: Sequence[str]) -> str | None:
    """The gh command `--product` refuses (`gh pr merge`), or None for one it runs. The command
    comes first and its subcommand right after it, so no flag can make gh read another
    subcommand than the one checked: gh's parser takes `pr -R list merge` as `pr merge`. An
    alias isn't read: an allowlisted group runs only the subcommands it names"""
    if not args:
        return None
    group = args[0]
    if group.startswith("-"):
        return f"gh {group}"
    if group not in _READS and group not in _WRITES:
        return None
    sub = args[1] if len(args) > 1 else None
    if sub is None or sub.startswith("-"):
        return f"gh {group}" if sub is None else f"gh {group} {sub}"
    if group in _READS and sub not in _READS[group]:
        return f"gh {group} {sub}"
    if group in _WRITES and sub in _WRITES[group]:
        return f"gh {group} {sub}"
    return None


def as_host(environ: Mapping[str, str]) -> dict[str, str]:
    """gh's env with no App: the caller's, less a GH_TOKEN set but empty, so gh uses the
    host's login as the repo chose rather than by a silent fallback"""
    env = dict(environ)
    if env.get("GH_TOKEN") == "":
        del env["GH_TOKEN"]
    return env


def as_app(environ: Mapping[str, str], token: str) -> dict[str, str]:
    """gh's env as the App: the caller's, with GH_TOKEN replaced by the App's token"""
    return {**environ, "GH_TOKEN": token}


# -- S-030-13: the merges `shipmill gh` holds ---------------------------------------------------

# The flags that take a value, as gh's own parser reads them; any other flag is a switch, so
# a value never reads as the pull request, and a flag between `pr` and `merge` is skipped
_PR_MERGE_LONG = frozenset({"--author-email", "--body", "--body-file", "--match-head-commit", "--subject", "--repo"})
_PR_MERGE_SHORT = frozenset("AbFtR")
_API_LONG = frozenset(
    {
        "--cache",
        "--field",
        "--header",
        "--hostname",
        "--input",
        "--jq",
        "--method",
        "--preview",
        "--raw-field",
        "--template",
    }
)
_API_SHORT = frozenset("FHqXpft")
_METHOD_FLAGS = ("-X", "--method")
_PULL_URL = re.compile(r"https?://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/pull/([1-9][0-9]*)(?:[/?#].*)?")
_NUMBER = re.compile(r"#?([1-9][0-9]*)")
_API_HOST = re.compile(r"^https?://api\.github\.com/", re.IGNORECASE)
_MERGE_PATH = re.compile(r"repos/([^/]+)/([^/]+)/pulls/([1-9][0-9]*)/merge/?")
PLACEHOLDER = ("{owner}", "{repo}")  # gh api fills them with the current repo


@dataclass(frozen=True, slots=True)
class Merge:
    """A merge gh's arguments ask for: the pull request by number, or by the selector gh
    resolves (a branch; None for the current branch's), in repo (owner/name; None for the
    repo gh picks: GH_REPO, else the checkout's)"""

    command: str  # as the refusal names it, such as `gh pr merge`
    number: int | None
    selector: str | None
    repo: str | None  # gh api's {owner} and {repo} placeholders kept, for target to fill

    def target(self, default: str) -> str:
        """The repo the merge is in: repo, its placeholders filled from default, else default"""
        if self.repo is None:
            return default
        owner, name = self.repo.split("/")
        default_owner, default_name = default.split("/")
        owner = default_owner if owner == PLACEHOLDER[0] else owner
        return f"{owner}/{default_name if name == PLACEHOLDER[1] else name}"


class MergeReads(Pulls, Protocol):
    """What the hold reads of the pull request; GhCli is one, tests pass a fake"""

    def pull_of(self, selector: str | None) -> str:
        """The pull request's URL, as `gh pr view <selector> --json url` prints it"""
        ...


MergeReader = Callable[[Path, Path, Mapping[str, str]], MergeReads]  # checkout, gh, and env in


def _scan(
    args: Sequence[str], long_values: frozenset[str], short_values: frozenset[str]
) -> tuple[list[str], list[tuple[str, str]]]:
    """gh's positional arguments and its flags with their values, in order. A value flag takes
    the next argument, or its rest after `=` (or, for a short one, after its letter); nothing
    after `--` is a flag"""
    positional: list[str] = []
    flags: list[tuple[str, str]] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            positional.extend(args[index:])
            break
        if arg.startswith("--"):
            name, equals, value = arg.partition("=")
            if name in long_values and not equals and index < len(args):
                value, index = args[index], index + 1
            flags.append((name, value))
        elif arg.startswith("-") and len(arg) > 1:
            for at, letter in enumerate(arg[1:], start=2):
                if letter not in short_values:
                    flags.append((f"-{letter}", ""))
                    continue
                value = arg[at:].removeprefix("=")
                if not value and index < len(args):
                    value, index = args[index], index + 1
                flags.append((f"-{letter}", value))
                break
        else:
            positional.append(arg)
    return positional, flags


def merge_of(args: Sequence[str]) -> Merge | None:
    """The merge gh's args ask for: `pr merge [<number> | <url> | <branch>]`, flags anywhere,
    or `api` with `-X`/`--method PUT` on `repos/<owner>/<repo>/pulls/<n>/merge`; None for any
    other gh call, read from the arguments alone"""
    if not args or args[0] not in ("pr", "api"):
        return None
    if args[0] == "pr":
        positional, _ = _scan(args[1:], _PR_MERGE_LONG, _PR_MERGE_SHORT)
        if not positional or positional[0] != "merge":
            return None
        selector = positional[1] if len(positional) > 1 else None
        named = named_repo(args)
        url = None if selector is None else _PULL_URL.fullmatch(selector)
        if url is not None:
            return Merge("gh pr merge", int(url.group(2)), None, url.group(1))
        numbered = None if selector is None else _NUMBER.fullmatch(selector)
        if numbered is not None:
            return Merge("gh pr merge", int(numbered.group(1)), None, named)
        return Merge("gh pr merge", None, selector, named)
    positional, flags = _scan(args[1:], _API_LONG, _API_SHORT)
    methods = [value for name, value in flags if name in _METHOD_FLAGS]
    if not positional or not methods or methods[-1].upper() != "PUT":
        return None
    path = _API_HOST.sub("", positional[0]).lstrip("/").partition("?")[0]
    found = _MERGE_PATH.fullmatch(path)
    if found is None:
        return None
    owner, name, number = found.groups()
    return Merge("gh api -X PUT .../merge", int(number), None, f"{owner}/{name}")


def pull_url(url: str) -> tuple[str, int]:
    """owner/name and the number of a pull request's URL on github.com"""
    found = _PULL_URL.fullmatch(url.strip())
    if found is None:
        raise ReleaseError(f"gh pr view named the pull request {url.strip()!r}, not a github.com pull request URL")
    return found.group(1), int(found.group(2))
