"""Spec 087's probe (S-087-1): print the `--settings` JSON a sandboxed headless launch carries.

Built by hand from the spec's tables, before `src/shipmill/sandbox.py` exists. Two shortcuts the
maintainer accepted for the probe (#1524): the whole git common dir is writable except `config`,
`hooks` and the gate's state dir (#1531 replaces this list), and the env is the gate's session
env for the App, read from the gate's helpers folder.

Usage: python3 settings.py <checkout> <app key> <bot login> <bot email> <maintainer>
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
DENY_READ = (
    "~/.ssh",
    "~/.gnupg",
    "~/.netrc",
    "~/.git-credentials",
    "~/.pypirc",
    "~/.npmrc",
    "~/.docker/config.json",
    "~/.kube",
    "~/.aws",
    "~/.azure",
    "~/.config/gcloud",
    "~/.password-store",
    "~/Library/Keychains",
    "~/.config/gh/hosts.yml",
    "~/.claude.json",
    "~/.claude/.credentials.json",
    "~/.claude/history.jsonl",
)
DOMAINS = (
    "github.com",
    "*.github.com",
    "*.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "astral.sh",
    "*.astral.sh",
    "localhost",  # probe only: does an allowedDomains entry let a command reach a local port?
)


def git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def project_dir(checkout: Path) -> str:
    """The folder name Claude Code gives a working directory under ~/.claude/projects"""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in str(checkout))


def main() -> None:
    checkout, key, login, email, maintainer = sys.argv[1:]
    root = Path(checkout).resolve()
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    main_tree = common.parent
    state = common / "shipmill"
    helpers = state / "bin"
    key_path = Path(key).resolve()

    deny = [str(Path(p).expanduser()) for p in DENY_READ]
    shipmill_config = HOME / ".config" / "shipmill"
    deny += [str(p) for p in sorted(shipmill_config.iterdir()) if p.resolve() != key_path]
    own = project_dir(root)
    deny += [str(p) for p in sorted((HOME / ".claude" / "projects").iterdir()) if p.name != own]

    write = [str(root), str(main_tree / ".claude" / "worktrees"), str(common), str(state / "uv-cache")]
    # the gate's state dir, entry by entry, except the token caches the helpers write and the uv cache
    kept = {"uv-cache"}
    state_entries = [p for p in sorted(state.iterdir()) if p.name not in kept and not p.name.startswith("app-token")]
    deny_write = [str(common / "config"), str(common / "hooks"), *(str(p) for p in state_entries)]
    for tree in (root, main_tree):
        deny_write += [str(tree / ".claude" / name) for name in ("settings.json", "settings.local.json")]
        deny_write.append(str(tree / ".mcp.json"))

    credential = str(helpers / "git-credential-shipmill")
    config = [
        ("credential.https://github.com.helper", ""),
        (
            "credential.https://github.com.helper",
            credential if shlex.quote(credential) == credential else f"!{shlex.quote(credential)}",
        ),
        ("url.https://github.com/.insteadOf", "git@github.com:"),
        ("url.https://github.com/.insteadOf", "ssh://git@github.com/"),
    ]
    env = {
        "PATH": os.pathsep.join([str(helpers), os.environ["PATH"]]),
        "GIT_AUTHOR_NAME": login,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": login,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_CONFIG_COUNT": str(len(config)),
        "SHIPMILL_APP_KEY": str(key_path),
        "UV_CACHE_DIR": str(state / "uv-cache"),
        "SHIPMILL_GATE": "1",
        "SHIPMILL_MAINTAINER": maintainer,
    }
    for index, (name, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = name
        env[f"GIT_CONFIG_VALUE_{index}"] = value

    settings = {
        "env": env,
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "failIfUnavailable": True,
            "filesystem": {"denyRead": deny, "allowWrite": write, "denyWrite": deny_write},
            "network": {"allowedDomains": list(DOMAINS)},
        },
        # an absolute path in a permission rule starts with //
        "permissions": {"deny": [rule for p in deny for rule in (f"Read(/{p})", f"Read(/{p}/**)", f"Edit(/{p}/**)")]},
    }
    print(json.dumps(settings))


if __name__ == "__main__":
    main()
