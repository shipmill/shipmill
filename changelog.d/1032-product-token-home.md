### Fixed

- `chains.py link --product` can make a listed repo's issue a sub-issue of a report in the product's home repo: the coordinator's product token now also covers the home repo when it has the listed repos' owner, with the same permissions (D-83), and such a link writes through `shipmill gh --product <the child's repo>`, so GitHub's `addSubIssue` sees both issues instead of failing with `Could not resolve to a node with the global id`; a product token cached without the home is minted again on its next use, and a home of another owner keeps today's token (#1032)
