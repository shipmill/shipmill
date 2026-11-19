### Added

- github-ship-watch reads spec 068's milestone rows from `shipmill milestones`: MILESTONE_RELEASED, an action whose close a watch pass runs once as the App, and MILESTONE_MISSING, reported with the create for the maintainer and never run (D-32); `shipmill status` waits on the close and lists both on its milestone line (#1336)
