### Fixed

- `chains.py link --child` (and `shipmill link --child`) works again: a second `PARENT` constant had replaced the parent read's GraphQL query with a field list, so every sub-issue link failed with a GraphQL parse error (#1836)
