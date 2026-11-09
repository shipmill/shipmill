### Fixed

- The weekly retro now learns whether a zoned question was answered with its recommended option when the question's zone line has no `answer=`: it reads the first answer after the question, a person's reply or the App's relay for the maintainer (pass `retro.py gather --decisions` the `--role` flags), and counts it only when it takes the recommended option as it stands, so the "ask to notify" proposal no longer starves (#997)
