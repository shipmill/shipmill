### Added

- `chains.py link` reads the checkout's `[product]` table (spec 038): in a component (`[product] home`) it exits 2 before any write when a reference names another repo than its own, and the coordinator's new `link --product P --child C` writes through `shipmill gh --product <P's repo>`, exiting 2 without `[product] repos` or for a reference outside the listed repos and the home repo (#587)
