"""`shipmill gh` (spec 012): run the `gh` on PATH as the repo's GitHub App when its config
sets [agents] app_id, so a session a person starts writes as the App too (D-14).

The arguments reach gh exactly as given. Only the repo gh's `-R`/`--repo` names is read
from them, to limit the token to it. The token goes to gh in GH_TOKEN, never to output.
"""

import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

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
