### Fixed

- `shipmill gh`: a comment whose first line relays a decision naming its person bare (`Decision by @<login>, relayed by <agent>`) exits 2 before anything reaches GitHub, its error showing the line with the login in a code span, so a relay no longer emails the person who already answered (D-61); readers still take both forms (#1491)
