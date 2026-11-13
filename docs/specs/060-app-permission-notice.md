# S-060: The App's owner gets an item when a release adds a permission to grant

status: approved
serves: G-4

## Problem

When a release adds a permission to the App's optional table (D-77), the owner of an existing
App has to act: add it in the App's settings, then accept it on each installation. Nothing
tells them to (shipmill/shipmill#1050, from #999). Every signal is one the owner has to go
and look at: the changelog entry, a WARN in `shipmill doctor`, a `warning:` line in the gate's
local tick log, a `DEPLOYMENTS_FORBIDDEN` row only with `[environments]`. `shipmill upgrade`
says nothing about permissions. GitHub asks installations to accept a permission only after
the owner has added it to the App, and that first step is the one nobody is told about.

#985 exists only because it was filed by hand for this project's own App. D-77 makes the
optional table the place every new permission goes, so each one passes the same way: the
feature quietly doesn't work for an existing App, while a new App gets it at creation.

## Behaviour

### What each optional permission serves

`OPTIONAL_PERMISSIONS` in `src/shipmill/app.py` gives each entry, beside its `serves` text, a
`needed(policy)` check saying whether the repo's config turns on what the permission serves.
The one entry today, Deployments: read, is needed when the config declares an environment
(`[environments]`). A new optional permission comes with its check, so the table stays the one
place a permission is added (D-77).

The warnings stay as they are: `shipmill doctor`'s `app` row and the gate preflight's
`warning:` line still name every optional permission the installation lacks, needed or not.

### The item

On a tick that sweeps (spec 046, every `[agents] sweep_hours`), after its config-upgrade
proposal (spec 047), the gate (`src/shipmill/gate.py`) runs a permission notice from a new
module, `src/shipmill/permission_notice.py`, writing as the App. It reads the installation's
permissions once, as minting a token does, and for each optional permission the installation
lacks whose `needed` check holds, it files one issue in the repo unless an issue for that
permission already exists, open or closed. The pattern is spec 014's proposal issue: one
issue per id, found by the marker on its first line and its label, and a close by the
maintainer ends it.

The issue:

- its first line is the marker `<!-- shipmill-permission: <key> <access> -->`, such as
  `<!-- shipmill-permission: deployments read -->`
- its title is `Grant the App <label>: <access> and accept it on this installation`
- it carries the labels `shipmill-permission`, which the gate finds it by, and
  `role:maintainer`, which makes it a person's item (spec 036), and is assigned at once to the
  users the maintainer role resolves to on that tick
- its body names the permission, what it serves (`serves`), and why this repo needs it (the
  config that turns it on), then the two steps, as #985 gives them:
  1. In the App's settings, set the permission, with the link to the App's permissions page:
     `https://github.com/settings/apps/<slug>/permissions` for an App a user owns,
     `https://github.com/organizations/<owner>/settings/apps/<slug>/permissions` for an
     organization's, read from the App's own record (`GET /app`)
  2. Accept the new permission on this installation's page (`Installation.settings`)
- it ends with a `## Check`: `shipmill doctor` in this repo shows the `app` row as PASS for the
  permission, not WARN

From there the item follows spec 036 and spec 017 unchanged: triage hands it off, which is
the comment that notifies the owner, waits for `done`, and runs its check.

### Later sweeps

- The installation grants the permission and the issue is open: the gate posts a comment
  whose first line is `<!-- shipmill:verified -->`, saying the installation grants it now, and
  closes the issue as completed. That is the item's check, done by the gate that can read it
- The issue is open and the permission is still missing: nothing is written
- The issue is closed, whatever its reason: nothing is filed again. A close as not planned is
  the owner's decline, for good. A close as completed while the permission is still missing
  reads VERIFY_CLOSED in triage, whose session runs the check and reopens the issue when it
  fails (D-79)
- The permission's `needed` check no longer holds and the issue is open: nothing is written;
  the item stays the owner's to close

### Where it shows

- The sweep's decision line gains a part, `permissions: filed #<n> <label>: <access>`, `closed
  #<n>`, or `permissions: none missing`, and `sweep.json` keeps it as it keeps the upgrade
  proposal's (S-047-10). A dry run files and closes nothing and says `permissions: would file
  <label>: <access>`
- A gate without `[agents] app_id` reads and writes nothing for this: there is no
  installation to read, and shipmill writes only as the App (D-54). Its line says
  `permissions: none read, [agents] sets no app_id`
- A failure of the notice (GitHub refusing the write) is the line's, never the tick's, as an
  upgrade proposal's is
- `skills/shipmill-setup/scripts/setup_state.py` wants the `shipmill-permission` label with
  `[agents] app_id`, so `LABELS_MISSING` names it

### Docs

`docs/install.md`, where it says Deployments is optional (D-77), adds that the gate files
this item in a repo that needs a permission its installation lacks, and that closing it as
not planned declines it. The changelog entry of a release that adds an optional permission
no longer needs to carry the owner's steps: the item does.

## Acceptance criteria

- S-060-1: Each entry of `OPTIONAL_PERMISSIONS` has a `needed` check; Deployments: read's holds for a config with `[environments]` and not for one without
- S-060-2: A sweeping tick of a gate with `[agents] app_id`, whose installation lacks Deployments: read on a config with `[environments]`, files one issue whose first line is `<!-- shipmill-permission: deployments read -->`, with the labels `shipmill-permission` and `role:maintainer`, assigned to the maintainer role's users
- S-060-3: That issue's body names the permission, its `serves` text, the config that needs it, the App's permissions page link for a user-owned and for an organization-owned App, the installation's page, and a `## Check` naming `shipmill doctor`'s `app` row
- S-060-4: A later sweep with the permission still missing files no second issue while one with the marker is open, closed as completed, or closed as not planned
- S-060-5: A sweep whose installation lacks Deployments: read on a config without `[environments]` files nothing
- S-060-6: A sweep whose installation grants the permission while its issue is open posts a comment whose first line is `<!-- shipmill:verified -->` and closes the issue as completed
- S-060-7: A tick that doesn't sweep reads no installation and writes nothing for this; a gate without `[agents] app_id` writes nothing and its line says so; a dry run writes nothing and its line names what it would file
- S-060-8: The sweep's decision line and `sweep.json` carry the notice's part; a GitHub refusal of the write ends up in that part, and the tick goes on to its walk as without it
- S-060-9: `shipmill doctor`'s `app` row and the gate preflight's `warning:` line still name each optional permission the installation lacks, needed or not
- S-060-10: `setup_state.py` reports `LABELS_MISSING` naming `shipmill-permission` for a config with `[agents] app_id` whose repo lacks it, and doesn't want it without `app_id`
- S-060-11: `docs/install.md` says the gate files the item for an optional permission the repo needs and its installation lacks, and that closing it as not planned declines it

## Out of scope

- `shipmill upgrade` printing or filing the step: it runs only when someone runs it, the same "go and look" gap; the gate already reads the installation on every sweep
- A permission `PERMISSIONS` requires: an installation that lacks one stops the gate at launch with its own fix (D-63), so no item is needed
- One item across every repo an App is installed on: an item lives in each repo whose installation lacks the permission, since each installation accepts it on its own page
- Reopening an issue the gate closed when the permission is later revoked: a revoke is the owner's own act
- The release workflow filing the item: it has no App and can't read the installation; the agent side files it (Q-6 holds, since the release side needs no optional permission)
- A `watch_state.py` row of its own: the item is a person's item, which the report already lists

## Decisions relied on

- D-9: an owner is asked about a permission only where the config needs it
- D-14: the gate writes the item as the App
- D-16: an issue the gate's App opened is trusted, so an unattended session hands it off
- D-54: without the App, nothing is written
- D-62: the item carries the agent marker, so it is no filing of the maintainer's
- D-63: a required permission stays out of this; a new one goes to the optional table
- D-79 (superseding D-76): an issue with a `## Check` closed as completed with no verified comment reads VERIFY_CLOSED, so its check runs
- D-77: the optional table names what each permission serves, and the warnings stay

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
