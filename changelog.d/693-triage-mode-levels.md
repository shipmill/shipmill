### Fixed

- The ship watch's `TRIAGE_MODE` row names the effective `triage`, `fix`, and `land` levels with their source, as `shipmill autonomy` reads them (`triage act (default), fix act (default), land propose (hold)`), instead of the `[agents]` prompt's words, so an `[agents]` table holding only `prs` no longer gives an empty row; an invalid `[autonomy] triage` or `fix` exits 2 as an invalid `land` does (#693)
