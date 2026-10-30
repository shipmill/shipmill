### Fixed

- `shipmill gate` no longer reads a headless session as dead from an authentication failure when only a tool's result or an assistant message in its stream-json log quotes one, such as a session that read `src/shipmill/gate.py`: the check reads only the log's lines that aren't events and its `result` events' text; a text log written before spec 048 is read as before (#822)
