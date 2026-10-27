### Changed

- A `Depends on` line holds only on the references of its strict shape (`Depends on[:] #1, #2 and owner/repo#3`, issue or pull URLs, `#{B1}` placeholders), never on one in a note after ` (`, `;`, or ` — `, and never inside a code fence; a line that names a reference in any other shape still holds on all of them and reads the new triage state MALFORMED_DEPENDS, an action, until a session rewrites it, and `chains.py link` appends a strict line when the only mention is in a note (spec 041) (#714)
