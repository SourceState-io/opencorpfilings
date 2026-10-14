# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's private vulnerability
reporting on this repository (**Security → Report a vulnerability**). Do not
open a public issue, and do not include API keys or other credentials in the
report.

Useful details: the affected version, the market route, a minimal
reproduction, and what an attacker could achieve. Maintainers will
acknowledge the report, investigate, and publish a fix and an advisory when
one is warranted. No response time is guaranteed.

## Supported versions

Security fixes go into the latest 1.x release.

## What the library does with untrusted content

Filings are documents written by third parties, so OpenCorpFilings treats
every downloaded byte as untrusted:

- it never executes content from a filing;
- archive members are read in place; no member path is written to disk under
  its own name, so a crafted path cannot escape the target folder;
- streamed downloads and archive reads are size-bounded, and a large archive
  member whose compression ratio exceeds 200:1 is refused;
- a file is replaced only after a complete download, so a failed save leaves
  the previous copy intact.

If you pass filing text to a language model or another automated agent, treat
it as data, never as instructions.
