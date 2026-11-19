### Fixed

- `shipmill gh issue edit` and `shipmill gh pr edit`, as the App, refuse with exit 2 to add the `needs-decision` label when a person's reply, a relay by the App (counted or not), or a `<!-- shipmill:withdrawn -->` comment already follows the item's newest needs-decision question, naming what came and asking for a new question first, so after a relay that isn't counted the label goes back on only with the re-ask D-93 requires (#1331)
