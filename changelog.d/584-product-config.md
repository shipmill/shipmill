### Added

- Config: an optional `[product]` table (spec 038, D-47), `home = "owner/name"` in a component repo or `repos = [...]` in the product's home repo, read strictly by `shipmill plan` and the gate alike; `repos` needs `[agents] app_id`, and in a component `shipmill gh -R` and `shipmill app-token` for any repo but the checkout's origin exit 2 naming D-47 before a token is minted (#584)
