---
title: 'Handle filing source errors in Python'
description: 'Handle authentication, rate limits, unavailable sources, unsupported capabilities and missing documents in OpenCorpFilings.'
---

# Errors

Every library error derives from `OpenCorpFilingsError`. Source failures are
`ProviderError` subclasses; requests the route or format cannot serve are
`UnsupportedCapabilityError`.

```text
OpenCorpFilingsError
├── ProviderError                  a source rejected or could not complete an operation
│   ├── SourceUnavailableError     temporarily unavailable after bounded retries
│   ├── AuthenticationError        credentials are absent or invalid
│   ├── EntityNotFoundError        no issuer matches the identifier
│   ├── AmbiguousEntityError       an identifier matches multiple issuers
│   ├── FilingNotFoundError        no filing matches the request
│   ├── RateLimitError             the source has limited requests (HTTP 429)
│   ├── DownloadError              a selected original could not be retrieved
│   └── ParseError                 a source document could not be parsed
├── UnsupportedCapabilityError     the route or format cannot provide an operation
└── UnsupportedMarketError         no route exists for the market code (also a ValueError)

UserWarning
└── ExperimentalRouteWarning       a Company was opened on an unqualified route
```

All are importable from `opencorpfilings`.

## When each is raised

| Error | Typical cause |
|---|---|
| `AuthenticationError` | a US `Company` without `user_agent=` or `OPENCORPFILINGS_SEC_USER_AGENT`; a missing or rejected EDINET or Open DART key |
| `EntityNotFoundError` | the identifier does not resolve at the source, or has the wrong shape (France needs a 20-character LEI or an exact source name) |
| `AmbiguousEntityError` | an exact name maps to more than one issuer, such as a French name associated with several LEIs |
| `FilingNotFoundError` | `latest()` on an empty collection; `get()` or `get_filing()` with an ID that is not the company's, or outside the filters or scan bound |
| `RateLimitError` | the source returned HTTP 429 |
| `SourceUnavailableError` | HTTP 500, 502, 503 or 504 after bounded retries; Open DART maintenance status `800` |
| `DownloadError` | an empty or mismatched document body (an HTML error page where a PDF or ZIP was expected, a corrupt ZIP); a document or member whose source URL changed after selection |
| `ParseError` | a source record or document that does not have the expected structure; an undecodable table source |
| `UnsupportedCapabilityError` | a form, date filter or amendment filter outside the route profile; text, Markdown, tables, sections or facts the format cannot supply; a missing optional extra; entity search on a route without it |
| `UnsupportedMarketError` | an unknown market code; a common alias carries a hint, such as `GB` → `UK` |

Some argument errors are ordinary Python exceptions:

- `ValueError`: an empty identifier or query, `limit` out of range,
  `start` after `end`, an unbounded `download()`, more than one document
  matching `select_document()`, a 10-Q Item that needs `part=`.
- `KeyError`: `filing.section(item)` for an Item the filing does not have.
- `UnicodeDecodeError`: `html()` on bytes that are not valid in the chosen
  encoding.

## Handling them

```python
from opencorpfilings import (Company, FilingNotFoundError, OpenCorpFilingsError,
                             RateLimitError, SourceUnavailableError,
                             UnsupportedCapabilityError)

try:
    filing = Company("00185647", market="UK").filings(form="annual").latest()
    text = filing.text()
except FilingNotFoundError:
    ...  # nothing matched
except (RateLimitError, SourceUnavailableError):
    ...  # retry later
except UnsupportedCapabilityError:
    ...  # the format or route cannot provide this; download() still returns the original
except OpenCorpFilingsError:
    ...  # any other library error
```

Requests are bounded, with timeouts, retries, `Retry-After` handling and
pacing per source. Error messages name the source origin and the failure type
or status; they do not echo request paths, query parameters or client
exception text that could contain credentials.

## Experimental route warning

Opening a `Company` on a built-in experimental route emits one
`ExperimentalRouteWarning` per route and process:

```text
ExperimentalRouteWarning: ES/spain_cnmv is an experimental route: it has not been qualified for this release, so results may be incomplete. Supported routes: US, UK, JP, FR.
```

Silence it with the standard `warnings` module when you have decided to use
the route:

```python
import warnings
from opencorpfilings import ExperimentalRouteWarning

warnings.filterwarnings("ignore", category=ExperimentalRouteWarning)
```

A provider you write yourself and pass with `provider=` does not warn.
