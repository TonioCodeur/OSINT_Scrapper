# Rule 3 — Always check the official documentation

## Why this rule exists

An agent writing library code from memory produces plausible-looking APIs that do not exist: renamed parameters, removed methods, decorators from a previous major version. This fails at runtime, and the failure is often subtle. Model knowledge has a training cutoff; library APIs do not stop at it.

**Consult the official documentation before writing code against any library, framework, SDK, or CLI — including ones that feel obvious.**

## How to consult it

Preferred, in order:

1. **The docs MCP server** — `resolve-library-id` then `query-docs`. This returns current, version-accurate documentation and is the fastest path. Use it even when confident about the answer.
2. **The library's own documentation site or repository** via `WebFetch` / `WebSearch`, when the MCP server has no entry for it.
3. **The installed package itself** — read the source in `site-packages` or run `python -c "import x; help(x.y)"`. This is authoritative for the exact version pinned in this project, which the online docs may not match.

## When it applies

- Adding or upgrading a dependency.
- Calling an API you have not verified in this session.
- A runtime error that mentions a library symbol — check the current signature before guessing at a fix.
- Anything involving HTTP semantics, rate limiting, retry, or `robots.txt` parsing, where getting the behavior wrong has legal consequences for this project (see the compliance section in `CLAUDE.md`).

## What not to do

- Do not invent parameters, keyword arguments, or return shapes to make code look complete.
- Do not copy an idiom from an older major version without confirming it still exists.
- If the documentation is ambiguous or unreachable, say so explicitly and state the assumption made — do not present a guess as verified.
