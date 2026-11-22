### Changed

- Product intake's `intake_state.py` reads its issues 70 to a page, its discussions, open pull requests, and comments 100 to a page, so a run on shipmill/shipmill costs GitHub 5 rate-limit points instead of 8, each query still 1: GitHub charges a query by its worst-case requests, one per connection times the nodes of the connections it sits in, so a smaller page only adds queries; every item, closed discussions and declined opportunities among them, is still read (#1459)
