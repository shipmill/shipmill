### Added

- In a component (`[product] home`), triage, product intake, and the PR reviewer treat a non-goal of the product as the component's own: a request that hits one is **won't fix** citing `<owner/home> N-n`, an opportunity says `hits <owner/home> N-n` on its `Serves` line and is never proposed on demand, and a change that hits one is a review finding; while `shipmill product show` can't read the home's direction, none of them gives a verdict, opportunity, or finding on new behaviour (#1256)
