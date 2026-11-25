# Keep private names and secrets off GitHub

An agent that works in your public repos and your private ones from the same machine can
write a private project's name, a customer, an internal host, or a key into an issue, a
comment, a pull request, or a commit. Once that leaves the machine it is too late: GitHub
keeps an issue's edit history, watchers already got the email, and forks and clones keep a
pushed commit. So shipmill checks what an agent sends before it is sent, and refuses it
there (spec 081, D-94).

Every name and host on this page is invented: `Acme Rocket` stands for a private project
and `rocket.example` for a private host.

## The private file

The names to keep private and the files that hold secrets live in one file on your machine,
outside every repo, next to the App's key:

```toml
# ~/.config/shipmill/private.toml
terms = ["Acme Rocket", "acmerocket", "rocket.example"]
secret_files = ["~/work/acme-rocket/.env"]
repos = ["acme/rocket", "acme-labs/*"]
```

- `terms`: the private names, a list of strings of at least 3 characters each. A term
  matches in any case and only as a whole word: `Acme Rocket` finds `acme  rocket` (any run
  of whitespace matches its space) but not `AcmeRocketry`. List each spelling you use
- `secret_files`: dotenv files (`~` is your home) whose values are secrets, read beside the
  checkout's own `.env` files
- `repos`: your private repos on GitHub, each `owner/name`, or `owner/*` for every repo of
  an owner, matched in any case as GitHub matches them (`owner/name.git` reads as
  `owner/name`). A write naming one is refused
  whatever any token reads (`private-repo`, below), which matters most in a gate session:
  it writes with the App's installation token, which reads another installation's private
  repo as missing (D-107). An entry that is neither form is named by its place, never its
  text

All three keys are optional, and an empty file is a valid one. In a checkout whose
`.github/shipmill.toml` has `[agents]`, the file must exist: while it is missing, every
`shipmill gh` write to a public repo is refused with exit 2, so a new machine running agents
doesn't leak by default (D-102):

```
shipmill gh: refused, nothing was sent (acme/widgets is public)
  private-file: ~/.config/shipmill/private.toml is missing, and this checkout's .github/shipmill.toml has [agents]
Create it, an empty one is enough: `mkdir -p ~/.config/shipmill && touch ~/.config/shipmill/private.toml`; then list your
private names under terms, as docs/leaks.md describes
```

In a checkout without `[agents]`, a missing file means no term is checked, and the secrets
come from the checkout alone. A file shipmill can't read as this (an unknown key, a wrong type, a term
under 3 characters, a `repos` entry that isn't `owner/name` or `owner/*`, a file that isn't
TOML, or a `secret_files` path it can't read) stops
every check that reads it: each agent write and push is refused, with exit 2 naming the file
and the problem, until you fix it. An unknown key is named by its line, never its text, since
a misplaced term can be one.

Never put these in `.github/shipmill.toml` or any file of a repo: a public repo's config
would publish the very names it hides. The file's path is fixed: no environment variable,
flag, config key, or marker in a text names another file or turns a check off, so a session
can't switch the check off for itself.

## The detectors

| Detector | Finds | Where it applies | On a finding |
|---|---|---|---|
| `term` | A term from the private file | A write to a public repo | Refused |
| `secret-value` | The exact value of a secret from your machine | Any repo | Refused |
| `secret-format` | A known token format | Any repo | Refused |
| `private-repo` | An `owner/name` reference to a private repo | A `shipmill gh` write to a public repo | Refused |
| `high-entropy` | A long random-looking string | Any repo | A warning; the write goes on |

- **`term`.** A repo counts as public unless GitHub says it is `private` or `internal`: a
  visibility that can't be read, a remote off github.com, and a write that goes to no repo
  (a gist) are checked as public. With no term listed, the visibility isn't read
- **`secret-value`.** The secrets come from the `.env` and `.env.*` files in the checkout's
  root that git doesn't track, and from `secret_files`. A line `NAME=value` gives a secret
  when the value has at least 8 characters and the name holds `KEY`, `TOKEN`, `SECRET`,
  `PASSWORD`, `PASSWD`, `PWD`, `CREDENTIAL`, `AUTH`, `COOKIE`, `SESSION`, or `DSN`, in any
  case; a URL value with `user:password@` gives its password when that has at least 8
  characters. A tracked `.env.example` gives none. The comparison runs on your machine, and
  no value is sent anywhere or printed
- **`secret-format`.** GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`,
  `github_pat_`), Anthropic keys (`sk-ant-`), AWS access key ids (`AKIA`, `ASIA`), Slack
  tokens (`xox?-`), a PEM private key block, and a URL with a literal password of at least 8
  characters (`https://x-access-token:${TOKEN}@github.com` passes). With `gitleaks` 8.19 or
  newer on your PATH, the text also goes through its default rules, and a `gitleaks:allow`
  comment or a repo's `.gitleaks.toml` lets nothing through
- **`private-repo`.** Each `owner/name` reference in the text, a `github.com/<owner>/<name>`
  URL or a bare pair standing alone (not a path, a branch such as `fix/123-x`, an npm scope,
  or another host's URL), is a finding when the private file's `repos` lists it, without
  being read. Any other is read once with the token the write uses, and one GitHub reports
  `private` or `internal` is a finding too. One neither listed nor readable by that token
  counts as no private repo, and the write's own repo isn't read twice. The token's read
  needs no private file; the App's installation token reads no other installation's private
  repo, so list yours under `repos`
- **`high-entropy`.** A run of 32 or more characters that looks random (not a commit SHA or
  a checksum, and not in a lock file) prints a `shipmill leaks: warning:` line on stderr and
  changes nothing else

A finding names a term, so the agent can take it out, but a secret only by its variable and
file, or by its format and at most its first 4 characters.

## The two refusals

**A write through `shipmill gh`.** Before `shipmill gh` hands a write to `gh` (an issue, a
comment, a pull request, a review, an `api` call that writes), it checks every text the
write sends: its arguments and each file it reads, such as a `--body-file`. A finding exits
2 before `gh` runs, so nothing is sent:

```
shipmill gh: refused, nothing was sent (acme/widgets is public)
  term: the body, line 4, names the private term "Acme Rocket"
  secret-value: the title holds the value of STRIPE_API_KEY from .env
  secret-format: the field note, line 2, holds a GitHub token (ghp_…)
Rewrite the text in general terms: describe the case by its traits, never by the project,
customer, or host it came from, and take the secret out. A person can post it with plain gh
```

`shipmill spec open` and `shipmill review record` check their `--body-file` the same way
before their first write, and `spec open` also checks the commit it pushes, which no hook
sees.

**A `git push` by an agent.** In a repo with `[agents]`, the plugin's delivery hook checks
what a push would send before it runs: each unpushed commit's message, the paths it adds or
renames to, and the lines it adds, read commit by commit, so a line one commit adds and a
later one removes is still found; and the names of the refs it pushes. A finding refuses
the push with exit 2, naming the commit, the path and line or the part, and what it found;
rewrite the unpushed commits (amend or rebase them, never a pushed one) and push again. A
check that can't finish refuses the push too, so no push goes out unchecked.

Your own terminal isn't checked: a plain `gh` or `git push` there is the way through for a
finding you judge harmless.

## Check a text before you write it

`shipmill leaks check [--repo DIR] [--to <owner/name>] [--field NAME] [FILE]` runs the
detectors over a file, or stdin without one, as a write of it to `--to` would be checked
(without `--to`, the repo of the checkout's origin; outside a checkout, no repo, checked as
public). It exits 2 with the findings, as a refusal lists them, and 0 otherwise, after any
warnings; `--field body` names the text `the body` in a finding:

```bash
shipmill leaks check --to acme/widgets --field body tmp/pr-body.md
```

## Check the setup

`shipmill doctor` (`uvx shipmill doctor` without the install), in a repo with `[agents]`,
prints a `leaks` block:

```
PASS leaks: terms on: 3 terms from ~/.config/shipmill/private.toml
PASS leaks: repos on: 2 repos from ~/.config/shipmill/private.toml
PASS leaks: secrets: values by file: .env 2, ~/work/acme-rocket/.env 4
PASS leaks: scanner: built-in formats and gitleaks 8.21.2
```

- `terms` gives how many terms the file lists, never the terms. With none it reads `off`,
  a WARN when the repo is public or its visibility can't be read; with no file it also names
  the `touch` step, since `shipmill gh` refuses public writes from the checkout until it exists
- `repos` gives how many repos the file lists, never one. A file that lists none is a WARN
  (D-107); a missing file adds no `repos` line, since the `terms` line already names the step
- `secrets` names each secret file read and how many values it gave, never a name or a
  value
- `scanner` names gitleaks' version, or says it isn't on PATH and the built-in formats
  alone decide
- A private file that doesn't load, or a secret file that can't be read, is a FAIL naming
  the fix
