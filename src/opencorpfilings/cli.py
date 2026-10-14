"""Small single-filing command line interface over the public Python API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ._version import __version__
from .company import Company, search_companies
from .directory import find_company
from .errors import OpenCorpFilingsError
from .providers import provider_info, supported_markets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocf", description="Inspect public company filings")
    parser.add_argument("--version", action="version", version=f"ocf {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("markets", help="list every market route with its tier, identifiers and forms")
    find = commands.add_parser("find", help="search all markets for a company; prints the identifier to use")
    find.add_argument("query", help="company name, ticker, securities code, ISIN or LEI")
    find.add_argument("--market", action="append", dest="markets", help="limit to a market (repeatable)")
    find.add_argument("--limit", type=int, default=10, help="maximum results (default: 10)")
    find.add_argument("--no-live", action="store_true", help="skip the live Companies House search")
    find.add_argument("--refresh", action="store_true", help="rebuild the cached company index first")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("identifier", help="company identifier, exact name, or search query")
    common.add_argument("--market", required=True, help="market code, such as US, UK or JP")
    common.add_argument("--source", help="explicit source route, such as esef_index")
    common.add_argument("--cache-dir", help="optional local metadata response cache")
    common.add_argument("--user-agent", help="identifying SEC User-Agent for this command")

    search = commands.add_parser("search", parents=[common], help="find source-listed companies")
    search.add_argument("--limit", type=int, default=10, help="maximum issuer candidates (default: 10)")
    commands.add_parser("company", parents=[common], help="show one source-resolved company")
    filings = commands.add_parser("filings", parents=[common], help="list a few filing records")
    filings.add_argument("--form", help="convenience category or exact source form")
    filings.add_argument("--start", help="filing date on or after YYYY-MM-DD")
    filings.add_argument("--end", help="filing date on or before YYYY-MM-DD")
    filings.add_argument("--limit", type=int, default=5, help="maximum filing records (default: 5)")

    select = argparse.ArgumentParser(add_help=False)
    choice = select.add_mutually_exclusive_group()
    choice.add_argument("--latest", action="store_true", help="select the latest matching filing (default)")
    choice.add_argument("--filing-id", help="select one exact source filing ID")
    select.add_argument("--form", help="category or source form when selecting the latest")
    select.add_argument("--start", help="filing date on or after YYYY-MM-DD")
    select.add_argument("--end", help="filing date on or before YYYY-MM-DD")

    commands.add_parser("documents", parents=[common, select],
                        help="list one filing's original documents without downloading them")
    download = commands.add_parser("download", parents=[common, select], help="save one original document")
    download.add_argument("--document-type", help="select one exact source document type")
    download.add_argument("--filename", help="select one exact source filename")
    download.add_argument("--output", help="destination path (default: source filename in current directory)")
    download.add_argument("--output-dir", help="save this company's selected filings into a folder with a manifest")
    download.add_argument("--limit", type=int, help="with --output-dir: the newest N matching filings")
    download.add_argument("--all-history", action="store_true",
                          help="with --output-dir: every matching filing when no --limit/--start/--end is given")
    download.add_argument("--all-documents", action="store_true",
                          help="with --output-dir: every document of each filing, not only the primary")
    download.add_argument("--file-type", action="append", dest="file_types",
                          help="with --output-dir: keep documents with this extension (repeatable), e.g. pdf")
    download.add_argument("--overwrite", action="store_true", help="replace an existing destination")
    return parser


def _filing_record(filing) -> dict[str, str | None]:
    return {
        "filing_id": filing.filing_id,
        "filing_date": filing.filing_date.isoformat() if filing.filing_date else None,
        "filing_type_raw": filing.filing_type_raw,
        "filing_type_normalized": filing.filing_type_normalized,
        "source_url": filing.source_url,
    }


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False))


def _routes() -> list[dict]:
    from .providers import _NATIONAL, _ORIGINAL
    from .providers.esef import INDEX_COUNTRIES

    routes = []
    for market in supported_markets():
        sources = [None] if market in _ORIGINAL or market in _NATIONAL else []
        if market in INDEX_COUNTRIES:
            sources.append("esef_index")
        for source in sources:
            info = provider_info(market, source=source)
            routes.append({
                "market": market, "source": source, "provider": info.provider, "tier": info.tier,
                "identifiers": list(info.identifiers), "forms": list(info.forms) if info.forms else None,
                "native_forms": info.native_forms, "date_filters": info.date_filters,
                "auth": info.auth, "coverage_note": info.coverage_note,
            })
    return routes


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "markets":
        _emit({"routes": _routes()})
        return 0
    if args.command == "find":
        try:
            matches = find_company(args.query, markets=args.markets, limit=args.limit,
                                   live=not args.no_live, refresh=args.refresh)
        except (OpenCorpFilingsError, ValueError) as exc:
            print(f"ocf: {exc}", file=sys.stderr)
            return 2
        _emit({"query": args.query, "results": [{
            "name": match.name, "market": match.market, "identifier": match.identifier,
            "source": match.source, "tier": match.tier, "tickers": list(match.tickers),
            "isins": list(match.isins), "lei": match.lei, "exchange": match.exchange,
            "listed_by": match.listed_by} for match in matches]})
        return 0
    options = {"source": args.source} if args.source else {}
    try:
        if args.user_agent is not None:
            if args.market.upper() != "US":
                raise ValueError("--user-agent applies to US SEC commands")
            options["user_agent"] = args.user_agent
        if args.command in {"search", "filings"} and args.limit <= 0:
            raise ValueError("--limit must be positive")
        if args.command == "download" and args.output_dir and (args.filing_id or args.output):
            raise ValueError("--output-dir downloads a set of filings; use --output for one --filing-id")
        if args.command == "download" and args.limit is not None and args.limit <= 0:
            raise ValueError("--limit must be positive")
        if (args.command == "download" and args.output_dir and not args.all_history
                and args.limit is None and args.start is None and args.end is None):
            raise ValueError("--output-dir needs a bound: --limit, --start/--end, or --all-history")
        if args.command in {"documents", "download"} and args.filing_id and args.form:
            raise ValueError("--form applies to --latest, not --filing-id")
        if args.command == "search":
            matches = search_companies(args.identifier, market=args.market, limit=args.limit,
                                       cache_dir=args.cache_dir, **options)
            _emit({"market": args.market.upper(), "results": [{
                "entity_id": item.entity_id, "name": item.name,
                "jurisdiction": item.jurisdiction, "provider": item.provider,
                "source_url": item.source_url,
                "search_source_url": item.provenance.source_url if item.provenance else None,
                "source_id": item.provenance.source_id if item.provenance else None,
                "requires_resolution": item.requires_resolution,
            } for item in matches]})
            return 0
        with Company(args.identifier, market=args.market, cache_dir=args.cache_dir, **options) as company:
            if args.command == "company":
                entity = company.entity
                _emit({"entity_id": entity.entity_id, "name": entity.name,
                       "jurisdiction": entity.jurisdiction, "provider": entity.provider,
                       "source_url": entity.source_url})
            elif args.command == "filings":
                collection = company.filings(form=args.form, start=args.start, end=args.end)
                _emit({"order_basis": collection.order_basis,
                       "filings": [_filing_record(filing) for filing in collection.head(args.limit)]})
            elif args.command == "download" and args.output_dir:
                collection = company.filings(form=args.form, start=args.start, end=args.end, limit=args.limit)
                _emit(collection.download(args.output_dir, all_history=args.all_history,
                                          documents="all" if args.all_documents else "primary",
                                          file_types=tuple(args.file_types) if args.file_types else None))
            else:
                filing = (company.get_filing(args.filing_id, start=args.start, end=args.end)
                          if args.filing_id else
                          company.filings(form=args.form, start=args.start, end=args.end).latest())
                if args.command == "documents":
                    _emit({"filing_id": filing.filing_id, "source_url": filing.source_url,
                           "documents": [document.to_dict() for document in filing.documents]})
                    return 0
                document = filing.select_document(document_type=args.document_type,
                                                  filename=args.filename)
                filename = document.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if not args.output and filename in {"", ".", ".."}:
                    raise ValueError("source filename is not usable; pass --output")
                target = Path(args.output) if args.output else Path(filename)
                if target.exists() and not args.overwrite:
                    raise FileExistsError(f"{target} already exists; pass --overwrite to replace it")
                saved = document.download(target)
                _emit({"filing_id": filing.filing_id, "document_id": document.document_id,
                       "source_url": document.source_url, "path": str(saved.resolve())})
    except OpenCorpFilingsError as exc:
        print(f"ocf: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"ocf: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
