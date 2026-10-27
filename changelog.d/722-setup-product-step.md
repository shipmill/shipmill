### Added

- shipmill-setup has a Product step under The gate: it asks whether the repo is one of several making up a product, writes this repo's half (`[product] repos` in the home, `[product] home` in a component, `[product] standalone = true` when it stands alone, or the `home` a `PRODUCT_LISTED` row names, with no question), prints the line each other repo needs to run `/shipmill:shipmill-setup <repo>` in its checkout, and relays doctor's product lines with their fixes; its description names connecting several repos as one product, and an eval case covers it (#722)
