"""`shipmill gh` (spec 012): run the `gh` on PATH as the repo's GitHub App when its config
sets [agents] app_id, so a session a person starts writes as the App too (D-14).

The arguments reach gh as given, but for the bodies a create writes, which end with the agent
marker (spec 050, `marked_args`). Only the repo gh's `-R`/`--repo` names is read from them
besides, to limit the token to it, and a merge they ask for (`merge_of`), which spec 030
holds when the pull request has a `never` zone. The token goes to gh in GH_TOKEN, never to
output.
"""

import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO
from urllib.parse import unquote

from shipmill.agent_marker import BODY_LIMIT, marked
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
    found = repo_value(args)
    if found is None:
        return None
    matched = _REPO.fullmatch(found)
    if matched is None or any(part in {".", ".."} for part in matched.group(1).split("/")):
        raise ReleaseError(f"gh's -R/--repo is {found!r}; the App's token needs owner/name on github.com")
    return matched.group(1)


def repo_value(args: Sequence[str]) -> str | None:
    """The value of gh's last `-R`/`--repo` in args as written, unchecked; None without one"""
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
    return found


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
# GitHub reads the number with leading zeros (pulls/007 is #7), so they don't hide a merge
_MERGE_PATH = re.compile(r"repos/([^/]+)/([^/]+)/pulls/0*([1-9][0-9]*)/merge/?")
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
    # percent-decoded as GitHub decodes it: pulls/%37/merge merges #7
    path = unquote(_API_HOST.sub("", positional[0]).lstrip("/").partition("?")[0])
    found = _MERGE_PATH.fullmatch(path)
    if found is None:
        return None
    owner, name, number = found.groups()
    return Merge("gh api -X PUT .../merge", int(number), None, f"{owner}/{name}")


# -- S-049-8: the flags of `gh pr merge` the credit reads and rewrites ---------------------------

_BODY_LONG = frozenset({"--body", "--body-file"})
_BODY_SHORT = frozenset("bF")
_METHODS = {
    "-s": "squash",
    "--squash": "squash",
    "-m": "merge",
    "--merge": "merge",
    "-r": "rebase",
    "--rebase": "rebase",
}


@dataclass(frozen=True, slots=True)
class MergeFlags:
    """What the credit reads of `gh pr merge`'s flags: the method, the body given by --body or
    by --body-file (its path, `-` for stdin), and whether it only turns auto-merge off"""

    method: str | None  # squash, merge, or rebase; None when no flag names one
    body: str | None
    body_file: str | None
    disable_auto: bool


def merge_flags(args: Sequence[str]) -> MergeFlags:
    """The flags of `gh pr merge` in args, read as `merge_of` reads them; the last of a flag
    given twice counts, as gh takes it. Two methods, or --body with --body-file, exit 2, as
    gh refuses them too"""
    _, flags = _scan(args[1:], _PR_MERGE_LONG, _PR_MERGE_SHORT)
    switched = [(name, value) for name, value in flags if value.lower() != "false"]  # --squash=false is off
    methods = {_METHODS[name] for name, _ in switched if name in _METHODS}
    if len(methods) > 1:
        raise ReleaseError(f"gh pr merge takes one of --merge, --rebase, or --squash; got {sorted(methods)}")
    bodies = [value for name, value in flags if name in ("--body", "-b")]
    files = [value for name, value in flags if name in ("--body-file", "-F")]
    if bodies and files:
        raise ReleaseError("gh pr merge takes --body or --body-file, not both")
    return MergeFlags(
        next(iter(methods), None),
        bodies[-1] if bodies else None,
        files[-1] if files else None,
        any(name == "--disable-auto" for name, _ in switched),
    )


def with_body(args: Sequence[str], body: str) -> list[str]:
    """args with every --body/-b and --body-file/-F and its value dropped, as `_scan` reads
    them, and one `--body <body>` in their place, before any `--`; every other argument is
    kept as written, a short flag bundled with a dropped one too (`-sb x` keeps `-s`)"""
    kept: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            index -= 1
            break
        if arg.startswith("--"):
            name, equals, _ = arg.partition("=")
            takes = name in _PR_MERGE_LONG and not equals and index < len(args)
            if name not in _BODY_LONG:
                kept.append(arg)
                kept.extend(args[index : index + 1] if takes else [])
            index += 1 if takes else 0
        elif arg.startswith("-") and len(arg) > 1:
            for at, letter in enumerate(arg[1:], start=2):
                if letter not in _PR_MERGE_SHORT:
                    continue
                takes = not arg[at:] and index < len(args)
                if letter in _BODY_SHORT:
                    kept.extend([arg[: at - 1]] if at > 2 else [])
                else:
                    kept.append(arg)
                    kept.extend(args[index : index + 1] if takes else [])
                index += 1 if takes else 0
                break
            else:
                kept.append(arg)
        else:
            kept.append(arg)
    return [*kept, "--body", body, *args[index:]]


def pull_url(url: str) -> tuple[str, int]:
    """owner/name and the number of a pull request's URL on github.com"""
    found = _PULL_URL.fullmatch(url.strip())
    if found is None:
        raise ReleaseError(f"gh pr view named the pull request {url.strip()!r}, not a github.com pull request URL")
    return found.group(1), int(found.group(2))


# -- S-037-4, S-037-5: the reads `shipmill gh` runs as the host without an App --------------------

# A group reads with the subcommands named, or with any (None). Every command not named here
# is a write, so a gh subcommand added later is refused until it is listed: `shipmill gh` fails
# safe, where the delivery hook's is_gh_write fails open (D-54)
_HOST_READS: Mapping[str, frozenset[str] | None] = {
    "help": None,
    "version": None,
    "status": None,
    "search": None,
    "issue": frozenset({"list", "view", "status"}),
    "pr": frozenset({"list", "view", "status", "diff", "checks"}),
    "release": frozenset({"list", "view", "download"}),
    "label": frozenset({"list"}),
    "run": frozenset({"list", "view", "watch", "download"}),
    "workflow": frozenset({"list", "view"}),
    "repo": frozenset({"view", "list", "clone"}),
    "secret": frozenset({"list"}),
    "variable": frozenset({"list", "get"}),
    "cache": frozenset({"list"}),
    "ruleset": frozenset({"list", "view", "check"}),
    "gist": frozenset({"list", "view"}),
    "org": frozenset({"list"}),
    "project": frozenset({"list", "view", "field-list", "item-list"}),
    "auth": frozenset({"status", "token"}),
    "config": frozenset({"get", "list"}),
    "alias": frozenset({"list"}),
    "extension": frozenset({"list"}),
}
_READ_METHODS = frozenset({"GET", "HEAD"})
_API_FIELDS = frozenset({"-f", "-F", "--field", "--raw-field"})


def is_read(args: Sequence[str]) -> bool:
    """Whether gh's args only read, by the list spec 037 names; anything else is a write. The
    command comes first and its subcommand right after it, as `product_refusal` reads them, so
    no flag can make gh run another subcommand than the one checked; `--help` makes nothing a
    read. Only the arguments before `--` name the command"""
    if not args:
        return True  # gh alone prints its help
    head = list(args[: args.index("--")]) if "--" in args else list(args)
    if head == ["--version"]:
        return True
    if not head or head[0].startswith("-"):
        return False
    group = head[0]
    if group == "api":
        return _api_read(args[1:])
    if group not in _HOST_READS:
        return False
    subs = _HOST_READS[group]
    return subs is None or (len(head) > 1 and head[1] in subs)


def _api_read(args: Sequence[str]) -> bool:
    """`gh api`: GET or HEAD, given with -X/--method or implied (no field and no --input, which
    make gh POST); graphql only with every query given inline and none holding a mutation, since
    a query from a file (`-F query=@file`) or --input isn't read here"""
    positional, flags = _scan(args, _API_LONG, _API_SHORT)
    fields = [value for name, value in flags if name in _API_FIELDS]
    has_input = any(name == "--input" for name, _ in flags)
    endpoint = _API_HOST.sub("", positional[0]).strip("/").lower() if positional else ""
    if endpoint == "graphql":
        queries = [
            (name, value.partition("=")[2])
            for name, value in flags
            if name in _API_FIELDS and value.partition("=")[0] == "query"
        ]
        from_file = any(name in ("-F", "--field") and query.startswith("@") for name, query in queries)
        return not has_input and not from_file and not any("mutation" in query for _, query in queries)
    methods = [value for name, value in flags if name in _METHOD_FLAGS]
    if methods:
        return methods[-1].upper() in _READ_METHODS
    return not fields and not has_input


# -- Spec 050: the agent marker on every body `shipmill gh` creates ------------------------------

BodyRead = Callable[[str, str], str]  # a body flag and its path (`-` for stdin) in, the text out


def body_reader(stdin: TextIO) -> BodyRead:
    """The text a body flag's path names: stdin for `-`, else the file's; a file that can't be
    read exits 2, so a body is never written empty for a typo"""

    def read(flag: str, path: str) -> str:
        if path == "-":
            return stdin.read()
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            why = exc.strerror if isinstance(exc, OSError) else str(exc)
            raise ReleaseError(f"gh's {flag} {path} can't be read: {why}") from None

    return read


@dataclass(frozen=True, slots=True)
class _Flags:
    """The flags of one gh command that take a value, long and short; any other is a switch"""

    long: frozenset[str]
    short: frozenset[str]


_COMMENT_FLAGS = _Flags(frozenset({"--body", "--body-file", "--repo"}), frozenset("bFR"))
_ISSUE_CREATE = _Flags(
    frozenset(
        {
            "--assignee",
            "--body",
            "--body-file",
            "--label",
            "--milestone",
            "--project",
            "--recover",
            "--repo",
            "--template",
            "--title",
        }
    ),
    frozenset("abFlmpRTt"),
)
_PR_CREATE = _Flags(
    _ISSUE_CREATE.long | {"--base", "--head", "--reviewer"},
    _ISSUE_CREATE.short | frozenset("BHr"),
)
_CLOSE_FLAGS = _Flags(frozenset({"--comment", "--reason", "--duplicate-of", "--repo"}), frozenset("crR"))
_CREATES: Mapping[tuple[str, str], _Flags] = {
    ("issue", "create"): _ISSUE_CREATE,
    ("issue", "new"): _ISSUE_CREATE,
    ("issue", "comment"): _COMMENT_FLAGS,
    ("pr", "create"): _PR_CREATE,
    ("pr", "new"): _PR_CREATE,
    ("pr", "comment"): _COMMENT_FLAGS,
}
_REVIEW = _COMMENT_FLAGS  # -a, -c, and -r are switches of `gh pr review`: approve, comment, request changes
_CLOSES = frozenset({("issue", "close"), ("issue", "reopen"), ("pr", "close"), ("pr", "reopen")})
# what finds the subcommand when a flag comes before it: every flag of the group's commands
_GROUP_FLAGS = {
    group: _Flags(
        frozenset().union(*(f.long for (g, _), f in _CREATES.items() if g == group), _CLOSE_FLAGS.long),
        frozenset().union(*(f.short for (g, _), f in _CREATES.items() if g == group), _CLOSE_FLAGS.short),
    )
    for group in ("issue", "pr")
}
_BODY_FLAGS = frozenset({"--body", "-b", "--body-file", "-F"})
_COMMENT_FLAG = frozenset({"--comment", "-c"})
_HELP = frozenset({"-h", "--help"})
# The REST endpoints that create a record with a body, past `repos/<owner>/<repo>/`
_API_CREATES = re.compile(
    r"repos/[^/]+/[^/]+/(?:issues|issues/[0-9]+/comments|pulls|pulls/[0-9]+/comments"
    r"|pulls/[0-9]+/comments/[0-9]+/replies|pulls/[0-9]+/reviews)/?",
    re.IGNORECASE,
)
# The GraphQL mutations that write a body, a create or an edit: shipmill gh can neither mark
# the one nor keep the other's origin, so each takes the REST form (spec 050)
_MUTATIONS = re.compile(
    r"\b(addComment|updateIssueComment|createIssue|updateIssue|createPullRequest|updatePullRequest"
    r"|addPullRequestReview|submitPullRequestReview|updatePullRequestReview|addPullRequestReviewComment"
    r"|addPullRequestReviewThread|addDiscussionComment|updateDiscussionComment|createDiscussion"
    r"|updateDiscussion)\b"
)
_REST_FORM = (
    "the REST form instead, such as `gh api repos/<owner>/<repo>/issues/<n>/comments -f body=...` for a comment or "
    "`gh api -X PATCH repos/<owner>/<repo>/issues/<n> -F body=@<file>` for an edit"
)


def _split(
    args: Sequence[str], flags: _Flags, take: Callable[[str, str], bool]
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """args before any `--` less the flags take picks, with their values, read as `_scan` reads
    them; the flags picked, in order; and args from `--` on. A short flag bundled with a picked
    one is kept (`-wb x` keeps `-w`). A picked flag with no value left exits 2, as gh would"""
    kept: list[str] = []
    taken: list[tuple[str, str]] = []
    index = 0
    while index < len(args) and args[index] != "--":
        arg = args[index]
        index += 1
        if arg.startswith("--"):
            name, equals, value = arg.partition("=")
            takes = name in flags.long and not equals
            if takes and index == len(args):
                raise ReleaseError(f"gh's {name} needs a value")
            value = args[index] if takes else value
            if take(name, value):
                taken.append((name, value))
            else:
                kept.extend([arg, args[index]] if takes else [arg])
            index += 1 if takes else 0
            continue
        if not arg.startswith("-") or len(arg) == 1:
            kept.append(arg)
            continue
        for at, letter in enumerate(arg[1:], start=2):
            if letter not in flags.short:
                continue
            rest = arg[at:]
            if not rest and index == len(args):
                raise ReleaseError(f"gh's -{letter} needs a value")
            value = rest.removeprefix("=") if rest else args[index]
            if take(f"-{letter}", value):
                taken.append((f"-{letter}", value))
                kept.extend([arg[: at - 1]] if at > 2 else [])
            else:
                kept.extend([arg] if rest else [arg, args[index]])
            index += 0 if rest else 1
            break
        else:
            kept.append(arg)
    return kept, taken, list(args[index:])


def _on(flags: Sequence[tuple[str, str]], *names: str) -> bool:
    """Whether a switch in names is given and not turned off (`--web=false`)"""
    return any(name in names and value.lower() != "false" for name, value in flags)


def _helped(flags: Sequence[tuple[str, str]]) -> bool:
    """Whether -h/--help is given as a flag, not as a flag's value: gh prints help, writing nothing"""
    return _on(flags, *_HELP)


def _sized(body: str, what: str) -> str:
    """body marked, refused when GitHub would cut the marker off"""
    text = marked(body)
    if len(text) > BODY_LIMIT:
        raise ReleaseError(
            f"{what}'s body, marked as an agent's (spec 050), is {len(text):,} characters, over GitHub's limit of "
            f"{BODY_LIMIT:,}, which would cut the marker off; shorten it"
        )
    return text


def marked_args(args: Sequence[str], read: BodyRead) -> list[str]:
    """Spec 050: gh's args with the agent marker ending every body they create: `issue create`,
    `issue comment`, `pr create`, `pr comment`, `pr review`, `issue|pr close|reopen --comment`,
    and the `gh api` creates; every other command's args as given (S-050-6). A create whose body
    can't be marked exits 2 before gh runs. read gives a body file's text"""
    if not args or args[0] == "--":
        return list(args)
    if args[0] == "api":
        return ["api", *_marked_api(args[1:], read)]
    if args[0] not in _GROUP_FLAGS:
        return list(args)
    positional, _ = _scan(args[1:], _GROUP_FLAGS[args[0]].long, _GROUP_FLAGS[args[0]].short)
    if not positional:
        return list(args)
    command = (args[0], positional[0])
    what = f"gh {' '.join(command)}"
    if command in _CLOSES:
        _, flags = _scan(args[1:], _CLOSE_FLAGS.long, _CLOSE_FLAGS.short)
        comments = [value for name, value in flags if name in _COMMENT_FLAG]
        if not comments or _helped(flags):
            return list(args)  # no comment: no body written
        kept, _, tail = _split(args, _CLOSE_FLAGS, lambda name, _: name in _COMMENT_FLAG)
        return [*kept, "--comment", _sized(comments[-1], what), *tail]
    review = command == ("pr", "review")
    if not review and command not in _CREATES:
        return list(args)
    table = _REVIEW if review else _CREATES[command]
    _, flags = _scan(args[1:], table.long, table.short)
    if _helped(flags):
        return list(args)
    if not review:
        _refuse_unmarkable(what, flags)
    if command[1] == "comment" and _on(flags, "--delete-last"):
        return list(args)  # deletes the last comment: no body written
    kept, taken, tail = _split(args, table, lambda name, _: name in _BODY_FLAGS)
    names = {name for name, _ in taken}
    if names & {"--body", "-b"} and names & {"--body-file", "-F"}:
        raise ReleaseError(f"{what} takes --body or --body-file, not both")
    if not taken:
        if review and _on(flags, "--approve", "-a"):
            return [*kept, "--body", marked(""), *tail]
        raise ReleaseError(
            f"{what} with no --body or --body-file is refused: shipmill gh marks the body it writes as an agent's "
            "(spec 050), and gh would ask for it in an editor or prompt; write it to a file and pass --body-file"
        )
    name, value = taken[-1]
    body = value if name in ("--body", "-b") else read(name, value)
    return [*kept, "--body", _sized(body, what), *tail]


def _refuse_unmarkable(what: str, flags: Sequence[tuple[str, str]]) -> None:
    """S-050-2: a create whose body gh would take from an editor, a browser, or an edit of the
    last comment, which shipmill gh can't mark"""
    if _on(flags, "--edit-last"):
        raise ReleaseError(
            f"{what} --edit-last is refused: it edits a comment shipmill gh can't mark (spec 050); edit it with "
            "`gh api -X PATCH repos/<owner>/<repo>/issues/comments/<id> -f body=...` instead"
        )
    given = [name for name in ("--web", "-w", "--editor", "-e") if _on(flags, name)]
    if given:
        raise ReleaseError(
            f"{what} {given[0]} is refused: shipmill gh marks the body it writes as an agent's (spec 050), and "
            "can't mark one written in a browser or an editor; write it to a file and pass --body-file"
        )


def _field(name: str, value: str) -> str | None:
    """The key of a gh api field flag's `key=value`; None for any other flag"""
    if name not in _API_FIELDS or "=" not in value:
        return None
    return value.partition("=")[0]


def _marked_api(args: Sequence[str], read: BodyRead) -> list[str]:
    """`gh api`'s args past `api`: a create on a body endpoint gets its `body` field marked, or
    one holding the marker alone; such a create with --input, and a graphql mutation that
    writes a body, exit 2"""
    positional, flags = _scan(args, _API_LONG, _API_SHORT)
    if not positional:
        return list(args)
    endpoint = unquote(_API_HOST.sub("", positional[0]).lstrip("/").partition("?")[0])
    has_input = [value for name, value in flags if name == "--input"]
    if endpoint.strip("/").lower() == "graphql":
        queries = [
            (name, value.partition("=")[2]) for name, value in flags if _field(name, value) in ("query", "mutation")
        ]
        if "-" in has_input or any(name in ("-F", "--field") and query == "@-" for name, query in queries):
            raise ReleaseError(
                "gh api graphql reading its query from stdin is refused: shipmill gh reads it first for a mutation "
                "that writes a body it can't mark (spec 050), and gh couldn't read stdin again; pass the query "
                "inline (-f query=...) or from a file (-F query=@<file>)"
            )
        texts = [
            read(name, query[1:]) if name in ("-F", "--field") and query.startswith("@") else query
            for name, query in queries
        ]
        texts.extend(read("--input", path) for path in has_input)
        found = next((m.group(1) for m in map(_MUTATIONS.search, texts) if m is not None), None)
        if found is not None:
            raise ReleaseError(
                f"gh api graphql with {found} is refused: it writes a body shipmill gh can't mark as an agent's "
                f"or keep as its record's (spec 050); use {_REST_FORM}"
            )
        return list(args)
    methods = [value for name, value in flags if name in _METHOD_FLAGS]
    fields = [value for name, value in flags if name in _API_FIELDS]
    method = methods[-1].upper() if methods else ("POST" if fields or has_input else "GET")
    if method != "POST" or _API_CREATES.fullmatch(endpoint) is None:
        return list(args)
    what = f"gh api {positional[0]}"
    if has_input:
        raise ReleaseError(
            f"{what} with --input is refused: shipmill gh marks the body it creates as an agent's (spec 050) and "
            "can't read one from --input; pass the body with -F body=@<file> instead"
        )
    kept, taken, tail = _split(args, _Flags(_API_LONG, _API_SHORT), lambda name, value: _field(name, value) == "body")
    if not taken:
        return [*kept, "-f", f"body={marked('')}", *tail]
    name, value = taken[-1]
    body = value.partition("=")[2]
    if name in ("-F", "--field") and body.startswith("@"):
        body = read(name, body[1:])
    return [*kept, "-f", f"body={_sized(body, what)}", *tail]
