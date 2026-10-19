"""Find a company across markets, and the identifier its route accepts, from official public lists.

`find_company("Toyota")` answers the question a user has before `Company()`:
which market, and which identifier. The index is built on the user's machine
from free official lists (each user downloads them; nothing is redistributed)
and cached for a week:

- US: SEC `company_tickers_exchange.json` (CIK, ticker, exchange)
- JP: EDINET code list, listed companies (EDINET and securities codes)
- FR: the AMF/DILA open `codes-lei` and `liste-code-isi` datasets (LEI, ISIN)
- BR: active CVM registrations (CVM code, CNPJ, legal/trade names), under ODbL
- CL: CMF active securities issuers (RUT, name), with source attribution
- ESEF index: filings.xbrl.org entities by country (LEI)

The UK has no list of listed companies; its name search runs live against
Companies House. Korea is not indexed: Open DART's terms are silent on reuse.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .errors import OpenCorpFilingsError

if TYPE_CHECKING:
    from .company import Company
    from .models import Entity

INDEX_FILE = "company-index.json"
INDEX_VERSION = 2
MAX_AGE = timedelta(days=7)
INCOMPLETE_MAX_AGE = timedelta(hours=1)  # an index missing a list is retried sooner
_NO_SEC_AGENT = "OPENCORPFILINGS_SEC_USER_AGENT is not set; the US list was skipped"
_SEC = "https://www.sec.gov/files/company_tickers_exchange.json"
_FR = "https://info-financiere.gouv.fr/api/explore/v2.1/catalog/datasets/{}/exports/json"
_ESEF = "https://filings.xbrl.org/api/filings"
_CVM_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]\Z")
_LEGAL_FORMS = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "plc", "ltd", "limited", "llc", "lp",
    "sa", "se", "ag", "nv", "bv", "spa", "oyj", "abp", "ab", "asa", "as", "a/s", "kk", "sas", "sca", "the",
})


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    """One search result: the market and the exact identifier to pass to `Company`."""

    name: str
    market: str
    identifier: str
    source: str | None
    tier: str
    tickers: tuple[str, ...] = ()
    isins: tuple[str, ...] = ()
    lei: str | None = None
    exchange: str | None = None
    aliases: tuple[str, ...] = ()
    listed_by: str = ""

    def __repr__(self) -> str:
        return f"<CompanyMatch {self.market} {self.identifier} {self.name!r} {self.tier}>"

    def company(self, **options: Any) -> Company:
        """Open this match's route: `Company(identifier, market=..., source=...)`."""
        from .company import Company

        if self.source is not None:
            options.setdefault("source", self.source)
        return Company(self.identifier, market=self.market, **options)


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^\w/]+", " ", text).split())


def _tokens(text: str) -> list[str]:
    return [token for token in _normal(text).split() if token not in _LEGAL_FORMS]


def build_rows(*, sec: dict | None = None, edinet: list[dict] | None = None, france_lei: list[dict] | None = None,
               france_isin: list[dict] | None = None, esef: list[dict] | None = None,
               brazil: list[Entity] | None = None, chile: list[Entity] | None = None) -> list[dict[str, Any]]:
    """Index rows from the raw official lists; any list may be absent."""
    rows: list[dict[str, Any]] = []
    if sec:
        position = {name: index for index, name in enumerate(sec["fields"])}
        by_cik: dict[str, dict[str, Any]] = {}
        for record in sec["data"]:
            cik = str(record[position["cik"]])
            row = by_cik.setdefault(cik, {
                "market": "US", "identifier": cik, "source": None, "name": record[position["name"]],
                "tickers": [], "isins": [], "lei": None, "exchange": record[position["exchange"]],
                "aliases": [], "listed_by": "SEC company_tickers_exchange.json"})
            if record[position["ticker"]]:
                row["tickers"].append(record[position["ticker"]])
        rows.extend(by_cik.values())
    for record in edinet or ():
        code = (record.get("証券コード") or "").strip()
        if record.get("上場区分") != "上場" or not code:
            continue
        english = (record.get("提出者名(英字)") or "").strip()
        japanese = (record.get("提出者名") or "").strip()
        rows.append({"market": "JP", "identifier": code[:4], "source": None, "name": english or japanese,
                     "tickers": [code[:4]], "isins": [], "lei": None, "exchange": None,
                     "aliases": [japanese, record.get("EDINETコード", "")] if english else [record.get("EDINETコード", "")],
                     "listed_by": "EDINET code list"})
    isins_by_name: dict[str, list[str]] = {}
    for record in france_isin or ():
        isin = str(record.get("identificationsociete_iso_cd_isi") or "")
        if _ISIN.fullmatch(isin):
            isins_by_name.setdefault(str(record.get("identificationsociete_iso_nom_soc")), []).append(isin)
    for record in france_lei or ():
        lei, name = record.get("identificationsociete_iso_cd_lei"), record.get("identificationsociete_iso_nom_soc")
        if lei and name:
            rows.append({"market": "FR", "identifier": lei, "source": None, "name": name, "tickers": [],
                         "isins": isins_by_name.get(name, []), "lei": lei, "exchange": None, "aliases": [],
                         "listed_by": "AMF/DILA codes-lei and liste-code-isi"})
    for record in esef or ():
        rows.append({"market": record["country"], "identifier": record["lei"], "source": "esef_index",
                     "name": record["name"], "tickers": [], "isins": [], "lei": record["lei"], "exchange": None,
                     "aliases": [], "listed_by": "filings.xbrl.org ESEF index"})
    for entity in brazil or ():
        records = entity.provider_metadata["source_rows"]
        if not any(record.get("SIT") == "ATIVO" for record in records):
            continue
        cnpj = entity.provider_metadata["CNPJ_CIA"]
        aliases = [cnpj, re.sub(r"\D", "", cnpj), *(record.get("DENOM_COMERC", "") for record in records)]
        rows.append({"market": "BR", "identifier": entity.entity_id, "source": None, "name": entity.name,
                     "tickers": [], "isins": [], "lei": None, "exchange": None,
                     "aliases": list(dict.fromkeys(aliases)), "listed_by": "CVM active company register (ODbL)"})
    for entity in chile or ():
        rows.append({"market": "CL", "identifier": entity.entity_id, "source": None, "name": entity.name,
                     "tickers": [], "isins": [], "lei": None, "exchange": None,
                     "aliases": [entity.provider_metadata["rut"]], "listed_by": "CMF active securities issuer register"})
    for row in rows:
        row["aliases"] = [alias for alias in row["aliases"] if alias]
    return rows


def _tier(row: dict[str, Any]) -> str:
    from .providers import provider_info

    try:
        return provider_info(row["market"], source=row["source"]).tier
    except OpenCorpFilingsError:
        return "experimental"


def _score(row: dict[str, Any], query: str, query_tokens: list[str]) -> int:
    raw = query.strip().casefold()
    exact = {row["identifier"], *(row["tickers"]), *(row["isins"]), row["lei"] or "", *row["aliases"]}
    if raw in {value.casefold() for value in exact if value}:
        return 100
    names = [row["name"], *row["aliases"]]
    best = 0
    for name in names:
        normal, tokens = _normal(name), _tokens(name)
        if tokens and tokens == query_tokens:
            best = max(best, 90)
        elif query_tokens and tokens[:len(query_tokens)] == query_tokens:
            best = max(best, 70)
        elif query_tokens and all(token in tokens for token in query_tokens):
            best = max(best, 50)
        elif raw and _normal(query) in normal:
            best = max(best, 30)
    return best


_TIER_ORDER = {"supported": 0, "limited": 1, "experimental": 2}


def search_rows(rows: Iterable[dict[str, Any]], query: str, *, markets: Iterable[str] | None = None,
                limit: int = 10) -> list[CompanyMatch]:
    """Rank index rows for a name, ticker, code, ISIN or LEI query."""
    wanted = {market.upper() for market in markets} if markets else None
    query_tokens = _tokens(query)
    scored = []
    for row in rows:
        if wanted is not None and row["market"] not in wanted:
            continue
        score = _score(row, query, query_tokens)
        if score:
            tier = _tier(row)
            scored.append((-score, _TIER_ORDER.get(tier, 3), len(row["name"]), row, tier))
    scored.sort(key=lambda item: item[:3])
    return [CompanyMatch(name=row["name"], market=row["market"], identifier=row["identifier"],
                         source=row["source"], tier=tier, tickers=tuple(row["tickers"]),
                         isins=tuple(row["isins"]), lei=row["lei"], exchange=row["exchange"],
                         aliases=tuple(row["aliases"]), listed_by=row["listed_by"])
            for *_, row, tier in scored[:limit]]


def _fetch_rows(transport) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download every official list; a list that fails is skipped and reported."""
    from .providers.edinet import REGISTRY, _registry_rows
    from .providers.esef import INDEX_COUNTRIES
    from .providers.brazil_cvm import BrazilCVMProvider, _REGISTRY as cvm_registry
    from .providers.chile_cmf import ChileCMFProvider, _REGISTRY as cmf_registry

    status: dict[str, Any] = {}
    lists: dict[str, Any] = {}

    def attempt(name, fetch):
        try:
            lists[name] = fetch()
            status[name] = {"ok": True}
        except Exception as exc:  # one unavailable list must not hide the others
            status[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}

    agent = os.getenv("OPENCORPFILINGS_SEC_USER_AGENT")
    if agent:
        attempt("sec", lambda: transport.get_json(_SEC, headers={"User-Agent": agent}))
    else:
        status["sec"] = {"ok": False, "error": _NO_SEC_AGENT}
    attempt("edinet", lambda: _registry_rows(transport.get(REGISTRY)))
    attempt("france_lei", lambda: transport.get_json(_FR.format("codes-lei")))
    attempt("france_isin", lambda: transport.get_json(_FR.format("liste-code-isi")))
    attempt("brazil", lambda: BrazilCVMProvider(transport=transport)._registry())
    status["brazil"].update(source_url=cvm_registry, license_url=_CVM_LICENSE_URL)
    attempt("chile", lambda: ChileCMFProvider(transport=transport)._registry())
    status["chile"].update(source_url=cmf_registry,
                           terms_url="https://www.cmfchile.cl/portal/principal/623/w4-article-1833.html")

    def esef():
        records = []
        for country in sorted(INDEX_COUNTRIES):
            page = 1
            while True:
                data = transport.get_json(_ESEF, params={
                    "page[size]": 1000, "page[number]": page, "filter[country]": country,
                    "fields[filing]": "country,entity", "include": "entity"})
                names = {item["id"]: item["attributes"] for item in data.get("included", [])}
                for filing in data.get("data", []):
                    entity = names.get(filing["relationships"]["entity"]["data"]["id"])
                    if entity and _LEI_LIKE.fullmatch(entity["identifier"]):
                        records.append({"country": country, "lei": entity["identifier"], "name": entity["name"]})
                if len(data.get("data", [])) < 1000:
                    break
                page += 1
        unique = {(record["country"], record["lei"]): record for record in records}
        return list(unique.values())

    attempt("esef", esef)
    rows = build_rows(sec=lists.get("sec"), edinet=lists.get("edinet"), france_lei=lists.get("france_lei"),
                      france_isin=lists.get("france_isin"), esef=lists.get("esef"),
                      brazil=lists.get("brazil"), chile=lists.get("chile"))
    return rows, status


_LEI_LIKE = re.compile(r"[A-Z0-9]{20}")
#: the rows each official list contributes, by their `listed_by`
_LISTED_BY = {"sec": "SEC company_tickers_exchange.json", "edinet": "EDINET code list",
              "france_lei": "AMF/DILA codes-lei and liste-code-isi",
              "france_isin": "AMF/DILA codes-lei and liste-code-isi", "esef": "filings.xbrl.org ESEF index",
              "brazil": "CVM active company register (ODbL)", "chile": "CMF active securities issuer register"}
_UK_LIVE = "Companies House search (live)"
_LIVE_PENALTY = 25
_LOADED: dict[Path, tuple[float, list[dict[str, Any]]]] = {}


def _cache_dir(cache_dir: str | Path | None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    if configured := os.getenv("OPENCORPFILINGS_CACHE_DIR"):
        return Path(configured)
    return Path.home() / ".cache" / "opencorpfilings"


def _fresh(stored: dict[str, Any]) -> bool:
    """An index lasts a week. One missing a list it failed to download lasts an hour, and one built
    without the SEC contact is rebuilt as soon as the contact is set."""
    if stored.get("version") != INDEX_VERSION:
        return False
    age = datetime.now(timezone.utc) - datetime.fromisoformat(stored["built_at"])
    gaps = {name: entry for name, entry in stored.get("sources", {}).items() if not entry.get("ok", True)}
    if gaps.get("sec", {}).get("error") == _NO_SEC_AGENT:
        if os.getenv("OPENCORPFILINGS_SEC_USER_AGENT"):
            return False
        del gaps["sec"]  # retrying cannot help until the contact is set
    return age < (INCOMPLETE_MAX_AGE if gaps else MAX_AGE)


def _keep_previous(rows: list[dict[str, Any]], status: dict[str, Any],
                   previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    """For each list that failed to download, the previous index's rows from it, so a rebuild
    while a source is down never loses companies the index already had."""
    if previous is None:
        return rows
    for name, entry in status.items():
        label = _LISTED_BY.get(name)
        old = previous.get("sources", {}).get(name, {})
        kept = [row for row in previous["rows"] if row.get("listed_by") == label]
        if entry.get("ok", True) or not kept:
            continue
        rows = [row for row in rows if row.get("listed_by") != label] + kept
        entry["kept_from"] = old.get("kept_from") or previous["built_at"]
    return rows


def _load_rows(cache_dir: str | Path | None, refresh: bool) -> list[dict[str, Any]]:
    from .transport import HttpTransport

    path = _cache_dir(cache_dir) / INDEX_FILE
    previous = None
    if path.exists():
        try:
            mtime = path.stat().st_mtime
            if not refresh and path in _LOADED and _LOADED[path][0] == mtime and _fresh(_LOADED[path][1]):
                return _rows_reporting_gaps(_LOADED[path][1])
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored.get("version") in {1, INDEX_VERSION}:
                previous = stored
                if not refresh and _fresh(stored):
                    _LOADED[path] = (mtime, stored)
                    return _rows_reporting_gaps(stored)
        except (ValueError, KeyError, OSError):
            pass
    with HttpTransport(min_interval=0.25) as transport:
        rows, status = _fetch_rows(transport)
    rows = _keep_previous(rows, status, previous)
    stored = {"version": INDEX_VERSION, "built_at": datetime.now(timezone.utc).isoformat(),
              "sources": status, "rows": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return _rows_reporting_gaps(stored)


def _rows_reporting_gaps(stored: dict[str, Any]) -> list[dict[str, Any]]:
    """Warn on every search, not only the one that built the index, that a list is missing from it."""
    for name, entry in stored.get("sources", {}).items():
        if entry.get("kept_from"):
            warnings.warn(f"company index: {name} list could not be refreshed ({entry['error']}); "
                          f"using the copy from {entry['kept_from'][:10]}", stacklevel=4)
        elif not entry.get("ok", True):
            warnings.warn(f"company index: {name} list unavailable ({entry['error']})", stacklevel=4)
    return stored["rows"]


def find_company(query: str, *, markets: Iterable[str] | None = None, limit: int = 10, live: bool = True,
                 refresh: bool = False, cache_dir: str | Path | None = None) -> list[CompanyMatch]:
    """Search every market for a name, ticker, securities code, ISIN or LEI.

    Returns matches best first; each says which market and identifier to pass
    to `Company`. The official lists are downloaded on first use and cached
    for seven days (`refresh=True` rebuilds). With `live=True` the UK, which
    has no list of listed companies, is searched live at Companies House.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    matches = search_rows(_load_rows(cache_dir, refresh), query, markets=markets, limit=limit)
    wanted = {market.upper() for market in markets} if markets else None
    if live and (wanted is None or "UK" in wanted):
        from .company import search_companies

        try:
            for entity in search_companies(query, market="UK", limit=min(limit, 5)):
                matches.append(CompanyMatch(name=entity.name, market="UK", identifier=entity.entity_id, source=None,
                                            tier="supported", listed_by=_UK_LIVE))
        except OpenCorpFilingsError as exc:
            warnings.warn(f"company index: live UK search failed ({exc})", stacklevel=2)
        rank = {"supported": 0, "limited": 1, "experimental": 2}
        query_tokens = _tokens(query)

        def key(match: CompanyMatch) -> tuple[int, int]:
            score = _score({"identifier": match.identifier, "tickers": list(match.tickers),
                            "isins": list(match.isins), "lei": match.lei,
                            "aliases": list(match.aliases), "name": match.name}, query, query_tokens)
            # Live UK hits are any registered company, not listed issuers: an
            # equally named listed issuer ranks first ("TOYOTA LIMITED" vs Toyota Motor).
            return -(score - _LIVE_PENALTY if match.listed_by == _UK_LIVE else score), rank.get(match.tier, 3)

        matches.sort(key=key)
    return matches[:limit]
