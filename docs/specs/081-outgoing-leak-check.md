# S-081: Agents never leak a private name or a secret from the machine to a repo

status: built
serves: G-2

## Problem

An agent working in a public repo wrote an issue body that named one of the maintainer's
private projects and details of its infrastructure. It noticed and edited the text, but
GitHub keeps the edit history and watchers had already received the original by email: only
a repo admin can delete a revision, and the emails can't be recalled (#1219, grouped into
#1234, which the maintainer accepted on 2026-11-18). A check after the fact is too late; the
only useful check runs before the write leaves the machine.

The same holds for code and for secrets (#1219's second comment, the maintainer's widening
of the scope). A private name in a pushed commit costs more than one in an issue: removing
it means rewriting history, and forks, clones, and caches keep the old commits. A key is a
leak in a private repo too. GitHub's push protection blocks known token formats on a push to
a public repo, but not in issue, comment, or pull request text, and it knows nothing of the
maintainer's private names. The secret patterns in `src/shipmill/operate.py` only hide
secrets in incident excerpts and block nothing.

It hits every maintainer who runs agents in public and private repos from one machine, and
it grows with the share of writes no person reads before they are sent.

## Behaviour

### The private file

The terms and the secret sources live in one file on the machine, outside every repo:
`~/.config/shipmill/private.toml`, next to the App's key (D-94). shipmill ships the
mechanism, never the terms; `.github/shipmill.toml` holds none of this, since a public
repo's config would publish the very names it hides.

```toml
terms = ["Acme Rocket", "acmerocket", "rocket.example"]
secret_files = ["~/work/acme-rocket/.env"]
```

- `terms`: a list of strings, each at least 3 characters once trimmed. A term matches
  case-insensitively and only at word boundaries (no letter or digit right before or after
  it), and a run of whitespace in the text matches a space in the term. Spelling variants
  are listed one by one
- `secret_files`: a list of dotenv files (`~` expanded) whose values are secrets, beside the
  checkout's own (below)

Both keys are optional. An unknown key, a wrong type, a term under 3 characters, a file that
isn't TOML, or a `secret_files` path that can't be read fails every check that would read it
with exit 2 naming the key and the file (Q-1). With no file, no term is checked and only the
checkout's own secret files are read. No environment variable or flag names another path or
turns a check off: a session can't switch it off for itself (D-94).

### What is checked

`src/shipmill/leaks.py` holds the detectors, shared by every path below:

| Detector | Finds | Where | On a finding |
|---|---|---|---|
| `term` | A term of the private file | A write to a public repo | Refused |
| `secret-value` | The exact value of a secret from the machine | Any repo | Refused |
| `secret-format` | A known token format | Any repo | Refused |
| `high-entropy` | A long random-looking string | Any repo | A warning; the write goes on |

**Public.** The repo a write goes to is public unless GitHub says otherwise: its
`visibility` from `gh api repos/<owner>/<name>` is read once per command, and `private` or
`internal` skips the `term` detector. `public`, a read that fails, a remote that isn't on
github.com, and a write that goes to no repo (a gist) count as public. With no term listed,
the visibility isn't read.

**Secret values.** The secrets are read from the dotenv files `.env` and `.env.*` in the root
of the checkout the command runs in that git doesn't track, and from `secret_files`. A line
`NAME=value` (an optional `export`, quotes stripped) gives a secret when the value has at
least 8 characters and the name holds `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `PWD`,
`CREDENTIAL`, `AUTH`, `COOKIE`, `SESSION`, or `DSN` in any case; a value that is a URL with
`user:password@` gives its password when that has at least 8 characters, whatever the name.
The match is the exact value, case-sensitive, anywhere in the text. The comparison runs on
the machine; no value is sent anywhere or printed.

**Secret formats.** Built in: GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`,
`github_pat_`), Anthropic keys (`sk-ant-`), AWS access key ids (`AKIA`, `ASIA`), Slack tokens
(`xox?-`), a PEM `PRIVATE KEY` block, and a URL with `user:password@` whose password has at
least 8 characters and none of `$`, `{`, `<`, `*` (so `${TOKEN}` and `<password>` pass). When
`gitleaks` 8.19 or newer is on PATH, the same text also goes through `gitleaks stdin` with
its default rules and no config from the repo, and each of its findings is a `secret-format`
finding; a `gitleaks:allow` comment or a `.gitleaks.toml` in the checked repo passes nothing.
No marker in the text lets a finding through.

**High entropy.** A run of at least 32 characters of `A-Z a-z 0-9 + / = _ -` holding a letter
and a digit, not hex only (a commit SHA or a checksum), with a Shannon entropy of at least
4.0 bits per character, outside lock files (`*.lock`, `package-lock.json`). It prints
`shipmill leaks: warning: ...` lines on stderr, at most 5 and then `and N more`, and changes
no exit code.

### `shipmill gh`

Before `shipmill gh` hands a write to `gh` (`src/shipmill/cli.py`, `src/shipmill/app_gh.py`:
any call `is_read` doesn't read as a read), it checks all the text the write sends: every
argument after the subcommand (a title, a `--body`, a label name, a `-f name=value` field)
and the content of each file the write reads (`--body-file`, `-F`, `--notes-file`, a
`--input`, an `@file` field value, stdin for `-`), as it stands after the agent marker is
added. The repo is the one the write goes to: the endpoint's `repos/<owner>/<name>` for
`gh api`, else `-R`, else the checkout's. `shipmill spec open` and `shipmill review record`
check their `--body-file` the same way before their first write.

A finding exits 2 before `gh` runs, so nothing is sent. stderr names every finding, up to 10,
then the fix:

```
shipmill gh: refused, nothing was sent (acme/widgets is public)
  term: the body, line 4, names the private term "Acme Rocket"
  secret-value: the title holds the value of STRIPE_API_KEY from .env
  secret-format: the field note, line 2, holds a GitHub token (ghp_…)
Rewrite the text in general terms: describe the case by its traits, never by the project,
customer, or host it came from, and take the secret out. A person can post it with plain gh
```

A term is named, as #1219 asks, so the agent can remove it; a secret's value never is, only
its name and file, or its format and first 4 characters.

### `git push`

`hooks/delivery.py` gains a rule, `leaks`, for a `git push` in a repo with `[agents]` (where
spec 026's rules apply). For a push the other rules allow, it runs `uvx shipmill==<pinned>
leaks push --repo <dir> [<remote> [<refspec>...]]` with the push's own remote, refspecs, and
`--all`, `--branches`, `--tags`, or `--mirror`, and refuses with exit 2 and the command's
findings when it exits 2. `shipmill leaks push` (`src/shipmill/cli.py`) checks only what the
push would send:

- **The commits:** those reachable from each pushed ref and from no remote-tracking ref of
  that remote (`git rev-list <sources> --not --remotes=<remote>`); with no refspec, the
  current branch. A refspec that only deletes sends none
- **Per commit:** its message, the paths it adds, changes, or renames to, and the added lines
  of its diff against its first parent, binary files left out. Each commit is read by
  itself, so a line added in one commit and removed in a later one is still found. The rest
  of the tree is never read
- **The destination ref names**

The repo is the remote's, read from its URL. A finding names the commit (7 characters), the
path and line, or `message`, `path`, or `ref`. The `Instead:` line says to rewrite the
commits (amend or rebase the unpushed ones, never a pushed one) and push again. A check that
can't finish (git or the CLI fails, the private file is malformed, or 45 seconds pass)
refuses too, naming why: a push is never sent unchecked by this rule. The Bash PreToolUse
hook's timeout in `hooks/hooks.json` rises from 10 to 60 seconds; no command but a `git push`
starts the CLI. `shipmill spec open` runs the same check on its own push, which no hook
sees.

`shipmill leaks check [--repo DIR] [--to <owner/name>] [--field NAME] [FILE]` runs the
detectors over a file or stdin and exits 2 on a refused finding, 0 otherwise, so a person or
a skill can check a text before writing it.

A person's own terminal is not checked: a plain `gh` or `git push` there is the way through
for a finding the person judges harmless, as for every hook rule (spec 026).

### `doctor` and docs

`src/shipmill/doctor.py`, for a repo with `[agents]`, adds a `leaks` block:

- `terms`: PASS `on: N terms from ~/.config/shipmill/private.toml`, never the terms
  themselves, or PASS `off: no ~/.config/shipmill/private.toml` (WARN when the repo is
  public)
- `secrets`: PASS naming each secret file read and how many values it gave, never a name or
  a value
- `scanner`: PASS `built-in formats and gitleaks <version>`, or `built-in formats; gitleaks
  is not on PATH`
- FAIL naming the key and the fix when the private file doesn't parse or a `secret_files`
  path can't be read

`docs/leaks.md` documents the file, the detectors, and the refusals, with invented names
only (`Acme Rocket`, `example` hosts); `docs/install.md` links it.

Touched areas: `src/shipmill/leaks.py`, `src/shipmill/cli.py` (`leaks check`, `leaks push`,
`gh`), `src/shipmill/app_gh.py`, `src/shipmill/spec_open.py`, `src/shipmill/review_record.py`,
`src/shipmill/doctor.py`, `hooks/delivery.py`, `hooks/hooks.json`, `shipmill gh`, `git push`,
`~/.config/shipmill/private.toml`, `docs/leaks.md`, `docs/install.md`, and
`tests/test_leaks.py`.

## Acceptance criteria

- S-081-1: with `terms = ["Acme Rocket"]` in the private file, `shipmill gh issue create`, `issue comment`, `issue edit`, `pr create`, `pr edit`, and `pr comment` to a public repo whose title, `--body`, or `--body-file` text holds `acme  rocket` exit 2 without running `gh`, naming the term and the field; the same writes pass when the text holds only `AcmeRocketry`
- S-081-2: `shipmill gh api` with a write method to a public repo is refused the same way for a term in a `-f` or `-F` field value, an `@file` field's content, or an `--input` file, and the repo is the endpoint's `repos/<owner>/<name>` when it names one
- S-081-3: a write whose repo's `visibility` reads `private` or `internal` is not checked for terms; a repo whose visibility read fails, a remote not on github.com, and a write to no repo are checked as public
- S-081-4: with no `~/.config/shipmill/private.toml`, no term is checked and no visibility is read; a file with an unknown key, a wrong type, a term under 3 characters, invalid TOML, or an unreadable `secret_files` path makes every write and push exit 2 naming the key and the file
- S-081-5: a `shipmill gh` write to a private repo whose text holds the exact value of `API_TOKEN` from an untracked `.env` in the checkout's root, or of a secret in a `secret_files` file, exits 2 without running `gh`, naming the variable and its file and never the value; a value under 8 characters, a value whose name holds none of the secret words, and a tracked `.env.example`'s value are not secrets
- S-081-6: a `shipmill gh` write to any repo holding a GitHub token, an Anthropic key, an AWS access key id, a Slack token, a PEM private key block, or a URL with a literal password of 8 characters or more exits 2 naming the format and at most the first 4 characters; `https://x-access-token:${TOKEN}@github.com` passes
- S-081-7: with `gitleaks` on PATH, a finding it reports on the outgoing text is refused as `secret-format`, and a `gitleaks:allow` comment or the checked repo's `.gitleaks.toml` passes nothing; without it, the built-in formats alone decide
- S-081-8: a high-entropy string of 32 characters or more prints a `shipmill leaks: warning:` line and the write or push goes on with its own exit code; a 40-character hex string and a string in `uv.lock` print none
- S-081-9: `shipmill leaks push` exits 2 for a push to a public repo when an unpushed commit's added line, a path it adds or renames to, its message, or the destination ref name holds a listed term, naming the commit, the path and line or the part, and the term; a term only in a line the push doesn't add, or in a commit the remote already has, passes
- S-081-10: `shipmill leaks push` exits 2 for a push to a private repo when an unpushed commit's added line holds a secret's exact value or a known format, and still when a later unpushed commit removes that line
- S-081-11: `hooks/delivery.py pre`, for a `git push` in a repo with `[agents]` that the other rules allow, runs `uvx shipmill==<pinned> leaks push` with the push's remote and refspecs and exits 2 with its findings when it exits 2, and also when it can't be run or doesn't finish in 45 seconds; no command but a `git push` starts it, and `hooks/hooks.json`'s Bash PreToolUse timeout is 60
- S-081-12: `shipmill spec open` and `shipmill review record` exit 2 before their first write when their `--body-file` holds a refused finding, and `spec open` when the commit it would push does
- S-081-13: `shipmill leaks check` exits 2 with the findings for a file or stdin holding a refused finding for `--to <owner/name>`, and 0 with any warnings otherwise
- S-081-14: no refusal, warning, or `doctor` line prints a secret's value beyond a format's first 4 characters, and `doctor` prints the count of terms, never a term
- S-081-15: `shipmill doctor`, for a repo with `[agents]`, prints the `leaks` block: `terms` on with the count or off (WARN when the repo is public), `secrets` with each file and its count, `scanner` with gitleaks' version or its absence, and FAIL naming the fix for a private file that doesn't parse
- S-081-16: neither `SHIPMILL_`-prefixed environment variables, a flag of `shipmill gh`, a key of `.github/shipmill.toml`, nor a marker in the text turns a detector off or names another private file
- S-081-17: `docs/leaks.md` documents the private file, the four detectors, and both refusals, `docs/install.md` links it, and neither it nor any fixture under `tests/` names a term outside `Acme` and `example` hosts

## Out of scope

- A paraphrase or a name missing from the list: a deny list catches only what it lists. A skill rule to describe a case by its general traits, and a model pass over outgoing text, are #1219's two complements and wait for leaks past the list
- A live read of a secret store (a password manager's CLI): `secret_files` takes a dotenv export of it; see "Decisions for you" in the spec PR
- A list of private remotes outside github.com: such a remote is checked as public
- Pushes and writes shipmill composes from the default branch alone (the release commit, its tag, release notes): their text already passed this check on its way in
- A `git push` the hook doesn't parse (inside `bash -c`, a script, `$(...)`), and one from a person's terminal, as spec 026 leaves them
- Scanning the existing tree or history of a repo: only what a write or push sends is read
- Removing a leak already published: rotating the key and rewriting history stay a person's step

## Decisions relied on

- D-4
- D-50
- D-54
- D-94

## Issues

- shipmill/shipmill#1315: S-081-1, S-081-2, S-081-3, S-081-4, S-081-5, S-081-6, S-081-14, S-081-16
- shipmill/shipmill#1316: S-081-7, S-081-8
- shipmill/shipmill#1317: S-081-9, S-081-10, S-081-11
- shipmill/shipmill#1318: S-081-12, S-081-13
- shipmill/shipmill#1319: S-081-15, S-081-17

## Verification

- S-081-1: `tests/test_leaks.py` runs each listed `issue` and `pr` write with the term in its title, `--body`, `--body-file`, or stdin to a public repo through `main`; each raised the refusal naming the term and the field with the gh runner never called, and `AcmeRocketry` passed
- S-081-2: `tests/test_leaks.py` refused `gh api -X POST` writes with the term in a `-f`/`-F` value, an `@file` field, and an `--input` file, and read the visibility of the endpoint's `repos/<owner>/<name>`; a GET through `gh api` was not checked
- S-081-3: `tests/test_leaks.py` passed the term to repos read `private` and `internal`, and refused it when the visibility read failed, the remote was off github.com, and the write went to a gist
- S-081-4: `tests/test_leaks.py` read no visibility without the private file or without terms, and each malformed file (unknown key, wrong type, short term, invalid TOML, unreadable `secret_files`) exited 2 naming the key and the file for writes, `leaks push` (`tests/test_leak_push.py`), and `leaks check` (`tests/test_leaks_check.py`)
- S-081-5: `tests/test_leaks.py` refused an untracked `.env`'s `API_TOKEN` value and a `secret_files` value to a private repo naming the variable and file, never the value; short values, other names, and a tracked `.env.example` passed
- S-081-6: `tests/test_leaks.py` refused each built-in format in any repo naming the format and its first 4 characters; `https://x-access-token:${TOKEN}@github.com` passed
- S-081-7: `tests/test_leaks.py` with a stand-in gitleaks 8.19 or newer refused its finding as `secret-format`, and a `gitleaks:allow` comment, a repo `.gitleaks.toml`, and a `GITLEAKS_CONFIG` passed nothing; an older or absent gitleaks left the built-in formats alone
- S-081-8: `tests/test_leaks.py`, `tests/test_leak_push.py`, and `tests/test_leaks_check.py` printed `shipmill leaks: warning:` for a random 40-character string and kept the command's own exit code; a hex SHA and a string in `uv.lock` printed none
- S-081-9: `tests/test_leak_push.py` on temporary repos refused a term in an added line, an added or renamed path, a message, and a destination ref, naming the commit, path, and line; a term in an unchanged line or a pushed commit passed
- S-081-10: `tests/test_leak_push.py` refused a secret value and a GitHub token in a private repo's unpushed commit though a later unpushed commit removed the line
- S-081-11: `tests/test_leaks_hook.py` ran `hooks/delivery.py pre` on a `git push` in a repo with `[agents]`: it ran the pinned `leaks push` with the push's remote and refspecs, exited 2 on its exit 2, on a runner that couldn't start, and past 45 seconds, started nothing for other commands; `hooks/hooks.json`'s Bash timeout reads 60
- S-081-12: `tests/test_leaks_check.py` ran `spec open` and `review record` through `main` with a `--body-file` holding the term or a GitHub token: each exited 2 with the refusal, the fake checkout published nothing and gh saw no write (only the visibility read); `open_spec` on a real clone with the term in the spec refused the commit before its push and origin got no branch
- S-081-13: `tests/test_leaks_check.py` ran `leaks check --to acme/widgets` over a file and over stdin: a term, a token, and a `.env` value each exited 2 with the findings, a clean text exited 0 with its warning on stderr, and a malformed `--to` exited 2 before stdin or gh was read; run by hand, `uv run shipmill leaks check --field body` over a file holding an AWS key id exited 2 naming `the body, line 3`, and over `README.md` exited 0
- S-081-14: `tests/test_leaks.py` checked that no refusal or warning line holds a secret beyond 4 characters and that a refusal lists 10 findings then `and N more`; `tests/test_leaks_doctor.py` and `tests/test_leaks_check.py` print the count of terms or the found term only, never an unfound one
- S-081-15: `tests/test_leaks_doctor.py` printed the `leaks` block's `terms` (count, or off with a WARN for a public repo), `secrets` per file with counts, `scanner` with gitleaks' version or its absence, and a FAIL naming the fix for a private file that doesn't parse
- S-081-16: `tests/test_leaks.py` set `SHIPMILL_`-prefixed variables, `--as-host`, config keys, a marker in the text, and `$HOME` elsewhere: every detector still refused, and only the account's own private file was read
- S-081-17: `tests/test_leaks_doctor.py` read `docs/leaks.md` for the private file, the four detectors, and both refusals, `docs/install.md`'s link to it, and found no term outside `Acme` and `example` hosts in it or the test fixtures
