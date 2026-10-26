### Fixed

- `chains.py link --product` links a report in the product's home repo: a home-repo parent's link is written through the session's own `shipmill gh`, a listed repo's through `shipmill gh --product <its repo>`, and every read of a listed repo goes through `shipmill gh --product <that repo>`, never plain gh (S-038-29) (#596)
