### Fixed

- The gate no longer exits 2 on every tick when an untracked file in its checkout sits where origin's new head adds a file: in its own linked worktree it moves the file aside, keeping its path, under the worktree's git dir (`shipmill-displaced/<UTC stamp>/`) and says so in one line; in a person's main working tree it moves nothing and names the files and the fix instead of git's raw message (#956)
