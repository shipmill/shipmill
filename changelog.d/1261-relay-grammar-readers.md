### Fixed

- Every reader of a relayed answer now follows the relay grammar: triage reads a relay out of its grammar as NEEDS_DECISION with the note `relay not counted: format` instead of DECIDED, product intake stops reading a plan relay at its `Note:` line, and the format check compares the words after an option's number with punctuation stripped, so `1. <option>: more` and `1. <option> and more` get the same reason (#1261)
