### Fixed

- `shipmill spec open` no longer commits a `--with` file, or the spec itself, over a change the default branch gained since the working tree was made: it exits 2 naming the file and asking to rebase first, before anything is written (#1623)
