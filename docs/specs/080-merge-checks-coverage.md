# S-080: doctor says what the checks gating a merge prove

status: built
serves: G-2

## Problem

With `[autonomy] land = "act"`, a gate session merges a pull request once its checks are
green (spec 040). Green is only as strong as the checks behind it, and nothing in shipmill
looks at what they cover (#1154, grouped into #1231, which the maintainer accepted on
2026-11-18). `shipmill doctor` reads a repository's rulesets and classic branch protection
only to tell whether land's push gets through (`src/shipmill/landing.py`, spec 054).
`[agents] verify` (spec 064) proves a session can run the repo's verification commands, not
that CI runs them before a merge. `pr_gate.py` waits for every check that reported on the
head, but only a required check is sure to report: a job behind a path filter, or one a
workflow change dropped, is simply absent, and the pull request merges on what is left.

So a maintainer whose CI was set up for human authors can switch land to `act` on a check
that only builds, or on no required check at all, and every agent pull request then merges on
a green that proves almost nothing. `change_failure_rate` (spec 027) shows the cost after the
merges have happened; nothing shows the risk before the first one.

## Behaviour

**The reading.** A new module, `src/shipmill/merge_checks.py`, reads what gates a merge to
the default branch, from GitHub and the checkout only:

1. **The required checks.** The contexts of every active `required_status_checks` rule on the
   default branch (`GET repos/<repo>/rules/branches/<branch>`, which holds the repository's
   and its organization's rulesets), each with its ruleset's name, and the `contexts` and
   `checks[].context` of classic protection's `required_status_checks`
   (`GET repos/<repo>/branches/<branch>/protection`), read through `RulesReader` of
   `src/shipmill/landing.py` with the person's `gh`. A context both name is listed once, with
   both sources
2. **The jobs behind each.** The workflow files of `.github/workflows/` in the checkout whose
   `on:` names `pull_request`, `pull_request_target`, or `merge_group`, read from their text,
   not by a YAML parse, as `src/shipmill/workflows.py` reads jobs (spec 063). A job reports
   the check `<name>`, its display name as `workflows.jobs` gives it; a job with a
   `strategy:` matrix reports every `<name> (<values>)`; a job that calls a local reusable
   workflow (`uses: ./.github/workflows/<file>`) reports `<name> / <called job's name>` for
   each job of that file, followed one level. A required context is matched to the jobs that
   report it by these names. A context no job matches reads `no job in .github/workflows
   reports it by a name its text tells` (a status another app posts, a remote reusable
   workflow, or a `name:` holding an expression), and its kind is `unknown`
3. **The commands each job runs.** `workflows.py` gains the steps of a job: each step's
   `run:` text (one line, or a `|` or `>` block), or its `uses:` action. Each non-blank,
   non-comment line of a `run:` is split into parts on `&&`, `||`, `;`, and `|`, as spec 064
   splits a command. A `uses:` step is listed by its action's name and never read: it counts
   for no kind
4. **The kind of each part.** Leading `NAME=value` assignments and these wrappers, with their
   options, are skipped first: `uv run`, `uvx`, `npx`, `bunx`, `pnpm exec`, `pnpm dlx`,
   `yarn dlx`, `poetry run`, `pdm run`, `hatch run`, `pipenv run`, `bundle exec`, `python -m`,
   `python3 -m`, `sudo`, `time`, `timeout <n>`. What is left is looked up by its program, and
   its first argument where the table names one:

   | Kind | Programs |
   |---|---|
   | `tests` | `pytest`, `unittest`, `go test`, `cargo test`, `cargo nextest`, `jest`, `vitest`, `mocha`, `playwright test`, `cypress run`, `rspec`, `phpunit`, `dotnet test`, `swift test`, `mix test`, `deno test`, `mvn test`, `mvn verify`, `gradle test`, `gradle check`, `ctest` |
   | `type check` | `mypy`, `pyright`, `basedpyright`, `pyre`, `pytype`, `ty check`, `tsc`, `vue-tsc`, `flow`, `cargo check`, `srb tc`, `steep check` |
   | `lint` | `ruff`, `flake8`, `pylint`, `eslint`, `biome`, `oxlint`, `prettier`, `stylelint`, `golangci-lint`, `go vet`, `staticcheck`, `cargo clippy`, `cargo fmt`, `rubocop`, `shellcheck`, `actionlint`, `hadolint`, `yamllint`, `markdownlint`, `ktlint`, `swiftlint`, `clang-tidy`, `pre-commit run` |
   | `import boundaries` | `lint-imports`, `tach check`, `depcruise`, `dependency-cruiser` |
   | `build` | `uv build`, `build` (from `python -m build`), `hatch build`, `poetry build`, `pip wheel`, `cargo build`, `go build`, `docker build`, `docker buildx`, `mvn compile`, `mvn package`, `gradle assemble`, `dotnet build`, `next build`, `vite build`, `webpack` |

   `./gradlew` and `./mvnw` read as `gradle` and `mvn`. `npm`, `pnpm`, `yarn`, or `bun` with
   `test` or `run <script>` is resolved one level: the script's command in the `scripts` of
   `package.json` in the step's `working-directory` (the repository's root without one) is
   split and looked up the same way, and a missing file or script, or a script that runs
   another script, is `unknown`. Every other part is `unknown`, never guessed: a `make`,
   `just`, `task`, `tox`, or `nox` target, a script of the repo, a program the table doesn't
   hold. Extending the table is a contract tweak, not a change to this spec
5. **The kind of a check.** A required check's kinds are those among `tests`, `type check`,
   `lint`, and `import boundaries` that a part of its jobs has; a check with any of them
   **proves**. A check with none is `build only` when a part is a `build`, else `unknown`

**The command.** `shipmill merge-checks` (`src/shipmill/cli.py`) prints the reading, one line
per required check and a last line that sums it up:

```text
PASS merge-checks: `checks` (ruleset "main"): ci.yml job checks: tests (pytest -q -n auto), type check (mypy), lint (ruff check src tests skills, ruff format --check src tests skills, actionlint .github/workflows/*.yml); unknown: python skills/github-issue-triage/scripts/specs.py check; actions not read: actions/checkout, astral-sh/setup-uv
PASS merge-checks: main requires 1 check; 1 proves (tests, type check, lint); land is propose
```

A check's line names at most 5 commands per kind and 5 unknown ones, then `and N more`.
`--land <level>` judges the reading as if `[autonomy] land` were that level (`observe`,
`propose`, or `act`); without it the configured level counts, never the one an open hold
lowers it to, since the hold ends. `--json` prints one object: `branch`, `land`, `status`,
`summary`, `required` (a list of objects with `context`, `sources`, `jobs`, each job with its
`workflow`, `job`, and `commands`, each command with its text and `kind`, and the check's
`kinds`), and `unrequired` (the jobs of the same workflow files that prove and that no
required context matches, with their kinds). The command reads no `[agents]` key, so it works
before the agent side is configured. It exits 0 whatever the reading says, and 2 with the fix
for a `--land` that isn't a level or a config that doesn't load.

**The warning.** The last line is a WARN only when the level judged is `act`:

- **No check is required:** `no status check is required on <branch>, so a pull request can
  merge on whichever checks reported: require one that runs tests, a type check, or a lint,
  or set [autonomy] land = "propose"`, followed by the unrequired jobs that prove, when there
  are any (`these jobs run on pull requests and prove something: ci.yml job checks (tests,
  lint)`)
- **No required check proves:** `<branch> requires N checks and none runs tests, a type
  check, a lint, or an import-boundary check`, naming each as `build only` or `unknown`, with
  the same fix and the same unrequired jobs

Under `observe` and `propose` the same facts print as a PASS: the row informs and warns
about nothing. A read that fails is a WARN at every level, naming what couldn't be read and
that the checks stay unjudged, with whatever was read still printed: `gh` missing, an origin
that isn't a GitHub repository, or a rules or protection read that answers 403 or 404 (a
login without admin can't read classic protection). The row is never a FAIL.

**doctor.** `shipmill doctor` (`src/shipmill/doctor.py`) prints the same lines as its
`merge-checks` row when the config has `[agents]`, judged at the configured `land` level. A
config without `[agents]` gets no row and no read, since nothing merges there (D-9). The row
doesn't depend on the release mode or on a release workflow.

**Setup.** `skills/shipmill-setup/SKILL.md`'s Autonomy step runs `$CR merge-checks --land
act` before it asks how far shipmill goes by itself, and shows its output under the
question's `land` lines, in a gate session inside the needs-decision question. When the last
line is a WARN, the "Ship by itself" profile and Custom's `land = "act"` are offered with that
warning beside them; the recommended profile stays as it is. `docs/install.md` names the row
in what `doctor` checks.

shipmill adds or changes no check, ruleset, or workflow in the repository, and the merge gate
(`pr_gate.py`) merges as before: the row tells the maintainer, who decides.

Touched areas: `src/shipmill/merge_checks.py`, `src/shipmill/workflows.py` (a job's steps),
`src/shipmill/landing.py` (`RulesReader`, read), `src/shipmill/doctor.py` (the `merge-checks`
row), `src/shipmill/cli.py` (`merge-checks`), `skills/shipmill-setup/SKILL.md` (the Autonomy
step), `docs/install.md`, and `tests/test_merge_checks.py`.

## Acceptance criteria

- S-080-1: `shipmill merge-checks` lists a context required by an active ruleset's `required_status_checks` rule on the default branch with that ruleset's name, and one required by classic protection's `contexts` or `checks` as `classic protection`; a context both require is listed once with both sources
- S-080-2: a required context is matched to the job whose display name equals it, to a matrix job named `<name>` for a context `<name> (<values>)`, and to a job of a local reusable workflow for a context `<caller's name> / <called job's name>`, only among workflow files whose `on:` names `pull_request`, `pull_request_target`, or `merge_group`; a context no such job matches is listed as `unknown` with `no job in .github/workflows reports it by a name its text tells`
- S-080-3: a job's commands are the parts of each `run:` step, one-line and block alike, split on `&&`, `||`, `;`, and `|`, with comment and blank lines left out; a `uses:` step is listed under `actions not read` and gives the check no kind
- S-080-4: a part is looked up after its leading `NAME=value` assignments and the listed wrappers with their options are skipped, so `uv run --locked pytest -q` and `python -m pytest` are `tests`, `uv run mypy` is `type check`, `npx eslint .` is `lint`, `uv run lint-imports` is `import boundaries`, and `uv build` is `build`
- S-080-5: `npm test` and `pnpm run lint` take the kind of the script's command in the `scripts` of the `package.json` in the step's `working-directory`; a missing `package.json` or script, and a script that runs another script, are `unknown`
- S-080-6: a part whose program the table doesn't hold (`make test`, `./scripts/check.sh`, `tox`) is `unknown` and is printed by its text, never given a kind
- S-080-7: a required check whose parts hold a `tests`, `type check`, `lint`, or `import boundaries` command lists those kinds; one whose only recognised parts are `build` reads `build only`; one with no recognised part reads `unknown`
- S-080-8: with `--land act`, the last line is a WARN naming the branch and the fix when no check is required, and a WARN naming each required check as `build only` or `unknown` when none proves; each names the unrequired pull-request jobs that prove, when there are any; it is a PASS when at least one required check proves
- S-080-9: with `--land observe` or `--land propose`, or without `--land` under a configured `land` of either, the same reading prints with a PASS last line for a repository with no required check
- S-080-10: without `--land`, the level judged is the configured `[autonomy] land` (its default `propose` when unset), also while a `shipmill-hold` issue is open
- S-080-11: `merge-checks --json` prints one object with `branch`, `land`, `status`, `summary`, `required` (each with `context`, `sources`, `jobs`, and `kinds`, each job with `workflow`, `job`, and `commands` holding each command's text and `kind`), and `unrequired`
- S-080-12: a check's line names at most 5 commands per kind and 5 unknown commands, then `and N more`
- S-080-13: with `gh` missing, an origin that isn't a GitHub repository, or a rules or protection read answering 403 or 404, the last line is a WARN at every level naming what couldn't be read, what was read is still printed, and the command exits 0
- S-080-14: `merge-checks` exits 2 naming the levels for a `--land` value that isn't `observe`, `propose`, or `act`, and runs with a config that has no `[agents]` section
- S-080-15: `shipmill doctor` prints the `merge-checks` lines, judged at the configured `land`, when the config has `[agents]`, and no `merge-checks` row and no rules read for it when it has none; a WARN on the row doesn't change doctor's exit code
- S-080-16: no code path of `merge_checks.py` writes to GitHub or to a file of the checkout: its reader has only read methods, and a run leaves `git status` clean
- S-080-17: `skills/shipmill-setup/SKILL.md`'s Autonomy step runs `merge-checks --land act` before its question, shows the output with the `land` lines, and names the warning beside every option that sets `land = "act"`; `docs/install.md` lists the row among doctor's checks

## Out of scope

- Adding, changing, or requiring a check, a ruleset, or a workflow in the repository: that stays the maintainer's (#1154)
- Refusing or holding a merge on this reading: `pr_gate.py` and `[autonomy] land` are unchanged, and the row only warns
- Reading what an action, a remote reusable workflow, a composite action, a Makefile, a justfile, or a tox or nox session runs: each is named and reads `unknown`
- A config key that declares the kind of a command the table doesn't hold; see "Decisions for you" in the spec PR
- Comparing the required checks with `[agents] verify` (spec 064), so doctor names a verification command no required check runs: a follow-up once this row exists
- Whether a required check really ran and passed on a given pull request: the merge gate reads that per pull request
- CI outside GitHub Actions: a status another system posts is listed as `unknown`

## Decisions relied on

- D-4
- D-9
- D-51

## Issues

- shipmill/shipmill#1297: S-080-3, S-080-4, S-080-5, S-080-6, S-080-7
- shipmill/shipmill#1298: S-080-1, S-080-2, S-080-8, S-080-9, S-080-10, S-080-11, S-080-12, S-080-13, S-080-14, S-080-16
- shipmill/shipmill#1299: S-080-15, S-080-17

## Verification

Checked on the default branch plus #1299's pull request, by running `shipmill merge-checks` and `shipmill doctor` on this repo's checkout (one required check, `check`, from the ruleset "shipmill: protected default branch"; classic protection answers 403 to a login without admin), besides the tests `specs.py coverage --spec 080` lists in `tests/test_merge_checks.py` and `tests/test_doctor_merge_checks.py`.

- S-080-1: this repo's line reads `` `check` (ruleset "shipmill: protected default branch") ``; a context both a ruleset and classic protection require is listed once with both sources in `test_s080_1_*`
- S-080-2: `check` matched `ci.yml job check`; matrix, local reusable workflow, push-only, expression-named, and remote-workflow contexts are asserted in `test_s080_2_*`, the unmatched ones with `no job in .github/workflows reports it by a name its text tells`
- S-080-3: `--json` lists ci.yml's `run:` blocks split into parts (`uv sync --locked`, `uv run ruff check ...`, the actionlint download's `curl`, `sha256sum`, `tar` parts) with no comment line, and `actions/checkout`, `astral-sh/setup-uv`, `actions/cache/restore`, `actions/cache/save` under `actions not read`
- S-080-4: `uv run pytest -q -n auto` reads `tests`, `uv run mypy` `type check`, `uv run ruff check src tests skills hooks` `lint`; the wrappers and assignments are asserted in `test_s080_4_*`
- S-080-5: `npm test` and `pnpm run lint` resolved through `package.json`, and a missing file or script and a script calling another as `unknown`, in `test_s080_5_*`
- S-080-6: `uv sync --locked`, `uv run shipmill product check`, and `uv run --no-project python skills/.../specs.py check` print by their text under `unknown`
- S-080-7: this repo's `check` lists `tests, type check, lint`; `build only` and `unknown` checks in `test_s080_7_*` and the `--land act` WARN of `test_s080_8_*`
- S-080-8: the two WARN texts and the PASS with a proving check are asserted in `test_s080_8_*`; this repo's check proves, so its last line under act names `1 proves (tests, type check, lint)`
- S-080-9: `--land propose` prints the same check line and `land is propose`; a repository with no required check passes under observe and propose in `test_s080_9_*`
- S-080-10: without `--land`, this repo's configured `land = "act"` is judged (`land is act`); under an open hold the configured level still counts in `test_s080_10_*`
- S-080-11: `--json` printed one object with `branch`, `land`, `status`, `summary`, `required` (with `context`, `sources`, `jobs` holding `workflow`, `job`, and `commands` of `text` and `kind`, and `kinds`), and `unrequired`
- S-080-12: this repo's line ends its lint list with `and 1 more` and its unknown list with `and 10 more`
- S-080-13: classic protection's 403 made the last line a WARN at act and at propose naming the read, with the ruleset's check still printed, exit 0; no `gh` and a non-GitHub origin in `test_s080_13_*`
- S-080-14: `--land merge` exited 2 with `--land 'merge' isn't a level: use one of observe, propose, act`; a config with no `[agents]` runs in `test_s080_14_*`
- S-080-15: `shipmill doctor` on this repo printed the two `merge-checks` lines after the `merge` row, its WARN with exit 0; without `[agents]` no row and no call to the rules reader, and with the row's WARN the exit code still following the FAIL rows alone, in `test_s080_15_*`
- S-080-16: `RulesReader` has only `branch_rules`, `ruleset`, `rulesets`, and `protection`; `git status --porcelain` was unchanged after the runs above, and `test_s080_16_*` asserts a clean `git status --ignored`
- S-080-17: shipmill-setup's Autonomy step runs `$CR merge-checks --land act` before its question, shows it with the `land` lines, and names its WARN beside "Ship by itself" and Custom's `land = "act"`; `docs/install.md` lists the row among doctor's checks; both read in `test_s080_17_*`
