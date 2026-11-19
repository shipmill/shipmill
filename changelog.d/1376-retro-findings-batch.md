### Fixed

- `retro.py findings` reads the reviews, review threads, and conversation of up to 50 closed pull requests per GraphQL query instead of two or three REST reads per pull request, paging on alone only a connection longer than its page, so a 28-day window over hundreds of pull requests takes a handful of queries, not hours; the findings it lists are unchanged (#1376)
