### Added

- `shipmill product add|edit|retire` and `shipmill review add-rule|protect|set-cap|retire`
  (`--dir DIR` for a subdirectory's `REVIEW.md`) edit one structured line of
  `docs/product.md` or a `REVIEW.md` and print it: an added id is one above any the file's
  git history held, a missing section is written in its fixed place, a moved section's file
  is edited, every other line stays byte for byte, and a file its check refuses exits 2
  without a write (#404)
