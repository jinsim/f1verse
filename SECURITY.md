# Security

## Supported versions

Fixes go into the latest release on PyPI. There are no long-term support
branches — upgrade to the newest version before reporting.

## Reporting a vulnerability

Report privately through GitHub's
[security advisories](https://github.com/jinsim/f1verse/security/advisories/new).
Please do not open a public issue for a vulnerability.

Include what you can: the version, a minimal reproduction, and what an
attacker gets out of it. You should hear back within a week.

## What is in scope

f1verse is a standard-library-only client with no server component of its
own, so the interesting surface is what it does with untrusted input:

- Parsing of remote responses — malformed timing streams, oversized or
  hostile payloads from a source that has been compromised or spoofed.
- The on-disk HTTP cache — path handling, and anything a response header
  could make it write outside the cache directory.
- The MCP server (`f1verse-mcp`) — argument handling on the eight tools, and
  anything a crafted `tools/call` can reach beyond those tools.

## What is not

- The upstream Formula 1 endpoints themselves. Report those to their
  operators, not here.
- Rate limits or availability of those endpoints.
- Anything requiring an attacker to already control the machine running
  f1verse.
