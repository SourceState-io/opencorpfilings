---
title: 'Find companies across filing sources'
description: 'Find companies by name, ticker, company number, securities code, ISIN or LEI with OpenCorpFilings company search.'
---

# Finding companies

`Company` takes the identifier a market uses: a ticker or CIK in the US, a
company number in the UK, a securities code in Japan, an LEI in France. When
you do not have it, there are two ways to look it up.

| Function | Searches | Returns |
|---|---|---|
| `find_company(query)` | every indexed market at once, by name, ticker, securities code, ISIN or LEI | `list[CompanyMatch]`, best first |
| `search_companies(query, market=...)` | one market's own source search | `list[Entity]` |

To look one up without Python, the [Find a company](../find/index.md) page searches
the same lists in the browser (all but the live UK search).

Brazil and Chile are included in `find_company()` and the browser search.
You can also query each source register directly:

```python
from opencorpfilings import Company, search_companies

Company(search_companies("Petrobras", market="BR", limit=1)[0])
Company(search_companies("Copec", market="CL", limit=1)[0])
```

The index includes active CVM registrations for [Brazil](../markets/br.md)
and active CMF securities issuers for [Chile](../markets/cl.md). Legal/trade
names, CVM codes and CNPJs identify Brazilian matches; names and RUTs identify
Chilean matches. Neither list adds inferred stock tickers.

## `find_company`

```python
find_company(query, *, markets=None, limit=10, live=True, refresh=False, cache_dir=None)
```

```python
from opencorpfilings import find_company

find_company("Toyota", limit=4)
```

```text
[<CompanyMatch US 1094517 'TOYOTA MOTOR CORP/' supported>,
 <CompanyMatch JP 7203 'TOYOTA MOTOR CORPORATION' supported>,
 <CompanyMatch JP 8015 'TOYOTA TSUSHO CORPORATION' supported>,
 <CompanyMatch JP 3116 'TOYOTA BOSHOKU CORPORATION' supported>]
```

Toyota files with both the SEC and EDINET, so it appears in both markets.
Search by whatever you have:

```python
for query in ["AAPL", "9984", "E02144", "FR0010307819", "5299006UDSEJCTTEJS30"]:
    best = find_company(query, limit=1, live=False)[0]
    print(f"{query:22} -> {best.market} {best.identifier:22} {best.name}")
```

```text
AAPL                   -> US 320193                 Apple Inc.
9984                   -> JP 9984                   SoftBank Group Corp.
E02144                 -> JP 7203                   TOYOTA MOTOR CORPORATION
FR0010307819           -> FR 969500XXRPGD7HCAFA90   LEGRAND
5299006UDSEJCTTEJS30   -> AT 5299006UDSEJCTTEJS30   VERBUND AG
```

`CompanyMatch.company(**options)` opens the match's route; it is
`Company(identifier, market=..., source=...)` with the match's values:

```python
filing = find_company("FR0010307819")[0].company().filings(form="annual").latest()
```

### `CompanyMatch` fields

| Field | Meaning |
|---|---|
| `name` | the name in the source list |
| `market` | the market code to pass to `Company` |
| `identifier` | the identifier to pass to `Company` |
| `source` | `None` for the market's default route, `"esef_index"` for the ESEF index route |
| `tier` | the route's tier: `supported`, `limited` or `experimental` |
| `tickers`, `isins`, `lei`, `exchange`, `aliases` | other identifiers in the source list (aliases hold, for example, the Japanese name and EDINET code) |
| `listed_by` | which list the match came from |

```python
match = find_company("Legrand", limit=1)[0]
match.market, match.identifier, match.tier, match.lei, match.isins, match.listed_by
```

```text
('FR', '969500XXRPGD7HCAFA90', 'supported', '969500XXRPGD7HCAFA90', ('FR0010307819',), 'AMF/DILA codes-lei and liste-code-isi')
```

The same company can be reachable by more than one route. Results rank by
match quality, then by tier, so a supported route comes before the ESEF index:

```python
[(m.market, m.source, m.tier) for m in find_company("Legrand", markets=["FR"], live=False)]
```

```text
[('FR', None, 'supported'), ('FR', 'esef_index', 'limited')]
```

### Where the index comes from

The index is built on your machine from free official lists, downloaded on
first use:

| Market | List |
|---|---|
| US | SEC `company_tickers_exchange.json` (CIK, ticker, exchange); skipped with a warning unless `OPENCORPFILINGS_SEC_USER_AGENT` is set |
| JP | EDINET code list, listed companies (EDINET and securities codes) |
| FR | the AMF/DILA `codes-lei` and `liste-code-isi` datasets (LEI, ISIN) |
| BR | active CVM company register, one issuer per CVM code (legal/trade names, CNPJ); source data under ODbL |
| CL | CMF active securities issuer register (name, RUT), with source attribution |
| ESEF index countries | filings.xbrl.org entities by country (LEI) |

The index is saved as `company-index.json` in `cache_dir`, else
`OPENCORPFILINGS_CACHE_DIR`, else `~/.cache/opencorpfilings`, and reused for
seven days. `refresh=True` rebuilds it. Installing 1.1.1 automatically
refreshes the older index format so the new countries appear immediately.
CVM data carries its source URL and ODbL license in the cache metadata. A list that cannot be downloaded is
skipped and the others are still indexed. Every search warns while a list is
missing. An index missing a list that failed to download is rebuilt after an
hour; until a list downloads again, the rows the previous index had from it are
kept, and the warning names that copy's date. One built without `OPENCORPFILINGS_SEC_USER_AGENT` is rebuilt as soon as
the variable is set.

The UK has no list of listed companies. With `live=True` (the default), when
`markets` is omitted or includes `UK`, UK names are searched live at Companies
House. Those hits can be any registered company; they rank below an equally
named listed issuer. Korea is not indexed.

```python
[(m.market, m.identifier, m.name, m.listed_by) for m in find_company("Tesco", limit=3)]
```

```text
[('UK', '00445790', 'TESCO PLC', 'Companies House search (live)'),
 ('UK', '05888957', 'TESCO AQUA (FINCO2) LIMITED', 'Companies House search (live)'),
 ('US', '802257', 'Mitesco, Inc.', 'SEC company_tickers_exchange.json')]
```

`limit` must be between 1 and 100. `ocf find` is the command-line equivalent.

## `search_companies`

```python
search_companies(query, *, market, limit=10, provider=None, cache_dir=None, **provider_options)
```

Searches one market's own source and returns source-listed `Entity`
candidates with their provider-scoped IDs, source URLs and search provenance.
Pass a candidate straight to `Company`:

```python
from opencorpfilings import Company, search_companies

candidates = search_companies("Greggs", market="UK", limit=3)
[(entity.entity_id, entity.name) for entity in candidates]
```

```text
[('00502851', 'GREGGS PLC'), ('SC702856', 'GREGGS ACADEMIC SERVICES LTD'), ('16546851', 'GREGGS CARGO AND LOGISTICS UK LTD')]
```

```python
greggs = Company(candidates[0])
accounts = greggs.filings(form="annual").latest()
accounts, accounts.title
```

```text
(<Filing MzUyMjMwODYxMGFkaXF6a2N4 AA ANNUAL period=2025-12-27 filed=2026-05-19 UK/companies_house>,
 "Group of companies' accounts made up to 27 December 2025")
```

Routes with source search: US, UK, JP, FR, KR, ES, NL, DK, SE, PL and FI. The
ESEF index route raises `UnsupportedCapabilityError`. Provider options such as
`user_agent=` or `api_key=` pass through:

```python
matches = search_companies("Apple", market="US", limit=5, user_agent="Your Name you@example.com")
company = Company(matches[0], user_agent="Your Name you@example.com")
```

An empty list means no match in that source result, not that the issuer does
not exist. A candidate is not a full company profile: `Company` resolves the
profile on first use. Each route's search is described on its
[market page](../markets/index.md).

## `Entity`

An `Entity` is one issuer as a source identifies it.

| Field | Meaning |
|---|---|
| `entity_id` | the source's own issuer ID (CIK, company number, LEI, ...) |
| `name` | the source's name for it |
| `jurisdiction` | the market code |
| `provider` | the route that produced it, such as `sec` or `esef_index` |
| `source_url` | the source page or record for the issuer |
| `identifiers` | `Identifier(kind, value, source_url)` records the source supplied |
| `tickers`, `exchanges` | where the source lists them |
| `provider_metadata` | source fields passed through |
| `provenance` | a [`Provenance`](../concepts/identifiers-dates-provenance.md#provenance) record |
| `requires_resolution` | `True` when the candidate's source ID must be resolved before filings can be listed |

`company.entity` is the resolved issuer; `company.search_result` keeps the
candidate you passed in, with its original provenance.

## Opening a company directly

```python
Company(identifier, *, market=None, provider=None, cache_dir=None, **provider_options)
```

- A string identifier needs an explicit `market`. Tickers are not assumed to
  be globally unique.
- `market` accepts the codes in `supported_markets()`. A common alias raises
  `UnsupportedMarketError` with a hint: `GB` suggests `UK`.
- `source="esef_index"` selects the ESEF index route where a market has a
  national route as well; see [ESEF index](../markets/esef.md).
- Other keyword arguments go to the route's provider, for example
  `user_agent=` (US) or `api_key=` (UK, JP, KR).

```python
Company("AAPL", market="US", user_agent="Your Name you@example.com")
Company("WOCMU6HCI0OJWNPRZS33", market="IT", source="esef_index")
```

```text
<Company AAPL US/sec>
<Company WOCMU6HCI0OJWNPRZS33 IT/esef_index>
```

Ticker resolution identifies the current SEC registrant. A corporate
reorganization can put older filings under another CIK; the library does not
combine entities. See [United States](../markets/us.md#identifiers).
