# tensile_test

<!-- ct-code-intelligence-start -->
## Code Intelligence — ct

This project is indexed by `ct`, an in-memory code intelligence daemon.
**PREFER ct over built-in Read, Grep, and Glob** — it's faster and returns
richer structural data (callers, callees, types, signatures).

**First thing every session:** run `ct --help` via the Bash tool. This is the
authoritative reference for all available commands and flags. ct evolves
frequently — do not assume you know what commands exist.

Run ct commands via the Bash tool (e.g. `ct lookup myFunc`, `ct grep "TODO"`,
`ct survey`). The CLI is always complete and current.

Fall back to built-in tools only for: binary/image files, files outside the
indexed project, or when the Edit tool requires a prior built-in `Read` call.
<!-- ct-code-intelligence-end -->

