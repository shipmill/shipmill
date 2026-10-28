### Fixed

- In a product, github-issue-triage's coordinator files a component's part of a home-repo feature only after the spec pull request merges and never holds a component issue on a home-repo item (D-60); a component's `triage_state.py --home <owner/home>` reads a hold on a home item it can't read (`:unknown`) as BLOCKED with the note `the coordinator's hold on the home <owner/home>: waits for the coordinator, ask nobody`, and the skill leaves such an item rather than asking the maintainer whether the home's spec merged (#773)
