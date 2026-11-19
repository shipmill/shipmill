### Added

- `shipmill milestones` reports MILESTONE_RELEASED for an open milestone its tagged release shipped, with the command that closes it, and MILESTONE_MISSING when no open milestone is above the newest stable tag, naming the next version and the command that creates its milestone; a milestone whose open issues each carry `shipmill-hold` or `needs-decision` reads MILESTONE_WAITING with one reason per issue, and `shipmill plan` names them (spec 068) (#1333)
