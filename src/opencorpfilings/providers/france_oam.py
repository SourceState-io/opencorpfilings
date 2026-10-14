"""Individual filings from France's official Info-Financiere OAM.

The AMF/DILA record is the source event. An ESEF index row, if one exists,
is a separate record; neither identity nor chronology is inferred from it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import json
import re
from urllib.parse import urlencode, urlparse

from ..errors import (AmbiguousEntityError, EntityNotFoundError,
                      FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError)
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import best_reports
from ..raw_xbrl import parse_ixbrl_xhtml
from ..transport import HttpTransport
from . import _oam


_API = "https://info-financiere.gouv.fr/api/explore/v2.1/catalog/datasets/flux-amf-new-prod/records"
_DOWNLOAD_HOST = "fr.ftp.opendatasoft.com"
_ANNUAL_CODE = "003000"
_FORM_CODES = {"annual": (_ANNUAL_CODE,), "interim": ("004000",),
               "quarterly": ("005000", "005001", "005002")}
_CODE_CATEGORY = {code: category.upper() for category, codes in _FORM_CODES.items() for code in codes}
_NAME_FIELD = "identificationsociete_iso_nom_soc"
_ISIN_FIELD = "identificationsociete_iso_cd_isi"
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_LANGUAGES = {"français": "fr", "francais": "fr", "anglais": "en", "english": "en", "french": "fr"}
_LEI_FIELD = "identificationsociete_iso_cd_lei"
_NAME_SEARCH_LIMIT = 200


def _language(label: object) -> str | None:
    """ISO 639-1 for the source's language label; an unknown label is kept as given."""
    if not isinstance(label, str) or not label.strip():
        return None
    return _LANGUAGES.get(label.strip().casefold(), label.strip())


def _source_codes(row: dict) -> set[str]:
    codes = {str(row["informationdeposee_inf_stp_pri"])} if row.get("informationdeposee_inf_stp_pri") else set()
    secondary = row.get("informationdeposee_inf_stp_inf")
    if isinstance(secondary, str):
        try:
            secondary = json.loads(secondary)
        except json.JSONDecodeError:
            secondary = None
    if isinstance(secondary, list):
        codes.update(code for code in secondary if isinstance(code, str))
    return codes


def _timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ParseError("France OAM publication time is not a string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParseError(f"invalid France OAM publication time {value!r}") from exc


def _has_inline_namespace(content: bytes | Path) -> bool:
    marker = b"inlineXBRL"
    if isinstance(content, bytes):
        return marker in content
    with content.open("rb") as source:
        tail = b""
        while chunk := source.read(1024 * 1024):
            if marker in tail + chunk:
                return True
            tail = chunk[-(len(marker) - 1):]
    return False


class FranceOAMProvider(FilingProvider):
    name = "france_oam"
    market = "FR"
    regulator = "AMF / DILA Info-Financiere OAM"
    identifies_amendments = True
    tier = "supported"
    identifier_kinds = ("LEI", "exact source issuer name")
    forms = ("annual", "interim", "quarterly")
    coverage_note = ("The OAM states no report period; period_end is None. A half-year report filed as an "
                     "update to the universal registration document (BNP Paribas) is not coded 004000, so "
                     "form='interim' does not select it.")
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download", "streamed_download",
                              "direct_filing_lookup", "source_package", "pdf", "html", "text", "raw_facts", "ixbrl"})
    order_basis = "published_at"

    def __init__(self, *, transport: HttpTransport | None = None, page_size: int = 100) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=0.25)
        self.page_size = page_size

    @staticmethod
    def _lei(identifier: str) -> str:
        lei = identifier.strip().upper()
        if len(lei) != 20 or not lei.isalnum():
            raise EntityNotFoundError("France OAM lookup requires a 20-character LEI")
        return lei

    @staticmethod
    def _isins(entity: Entity) -> tuple[str, ...]:
        """ISINs the issuer's own LEI-tagged record carries."""
        return tuple(sorted({identifier.value for identifier in entity.identifiers
                             if identifier.kind == "ISIN" and _ISIN.fullmatch(identifier.value)}))

    @staticmethod
    def _where(lei: str, form: str | None, start: date | None = None,
               end: date | None = None, isins: tuple[str, ...] = ()) -> str:
        # The OAM attaches LEIs inconsistently (SEB's annual reports carry none,
        # AXA's a second AXA LEI); the share ISIN identifies the issuer too.
        where = f"identificationsociete_iso_cd_lei = '{lei}'"
        if isins:
            where = f"({where} OR {_ISIN_FIELD} IN (" + ",".join(f"'{isin}'" for isin in isins) + "))"
        if form is not None:
            key = form.lower()
            codes = _FORM_CODES.get(key) or ((form,) if form in _CODE_CATEGORY else None)
            if codes is None:
                raise UnsupportedCapabilityError(
                    "France OAM supports annual, interim and quarterly source report categories"
                )
            primary = (f"informationdeposee_inf_stp_pri = '{codes[0]}'" if len(codes) == 1
                       else "informationdeposee_inf_stp_pri IN (" + ",".join(f"'{code}'" for code in codes) + ")")
            secondary = " OR ".join(
                f"informationdeposee_inf_stp_inf LIKE '%\"{code}\"%'" for code in codes
            )
            where += f" AND ({primary} OR {secondary})"
        if start is not None:
            where += f" AND uin_dat_amf >= '{start.isoformat()}'"
        if end is not None and end < date.max:
            where += f" AND uin_dat_amf < '{(end + timedelta(days=1)).isoformat()}'"
        return where

    def _page(self, lei: str, *, form: str | None, offset: int, size: int,
              start: date | None = None, end: date | None = None,
              isins: tuple[str, ...] = ()) -> tuple[list[dict], int]:
        params = {"where": self._where(lei, form, start, end, isins), "order_by": "uin_dat_amf DESC",
                  "limit": size, "offset": offset}
        response = self.transport.get_json(_API, params=params)
        rows = response.get("results") if isinstance(response, dict) else None
        count = response.get("total_count") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not isinstance(count, int) or any(not isinstance(row, dict) for row in rows):
            raise ParseError("France OAM returned an invalid records page")
        return rows, count

    def _name_rows(self, query: str) -> tuple[list[dict], int, str]:
        # ODSQL single-quoted strings escape both apostrophes and backslashes.
        literal = query.replace("\\", "\\\\").replace("'", "\\'")
        params = {
            "where": f"search({_NAME_FIELD}, '{literal}') AND {_LEI_FIELD} IS NOT NULL",
            "select": f"{_LEI_FIELD}, {_NAME_FIELD}, max(uin_dat_amf) as latest",
            "group_by": f"{_LEI_FIELD}, {_NAME_FIELD}",
            "order_by": "latest DESC",
            "limit": _NAME_SEARCH_LIMIT,
        }
        source_url = f"{_API}?{urlencode(params)}"
        response = self.transport.get_json(_API, params=params)
        rows = response.get("results") if isinstance(response, dict) else None
        count = response.get("total_count") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not isinstance(count, int) or any(not isinstance(row, dict) for row in rows):
            raise ParseError("France OAM returned invalid issuer search results")
        return rows, count, source_url

    @staticmethod
    def _name_rank(name: str, query: str) -> int:
        name_folded, query_folded = name.casefold(), query.casefold()
        if name_folded == query_folded:
            return 0
        if name_folded.startswith(query_folded):
            return 1
        if query_folded in name_folded:
            return 2
        return 3

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        rows, _, source_url = self._name_rows(query)
        ranked = sorted(enumerate(rows), key=lambda pair: (
            self._name_rank(str(pair[1].get(_NAME_FIELD, "")), query), pair[0]))
        matches: list[Entity] = []
        seen: set[str] = set()
        for _, row in ranked:
            lei, name = row.get(_LEI_FIELD), row.get(_NAME_FIELD)
            if not isinstance(lei, str) or not re.fullmatch(r"[A-Za-z0-9]{20}", lei):
                continue
            if not isinstance(name, str) or not name.strip() or lei in seen:
                continue
            seen.add(lei)
            matches.append(Entity(
                entity_id=lei, name=name, jurisdiction="FR", provider=self.name,
                source_url=source_url, identifiers=(Identifier("LEI", lei, source_url),),
                provider_metadata={**row, "search_query": query},
                provenance=Provenance(self.name, self.regulator, "FR", source_url, lei,
                                      datetime.now(timezone.utc), row),
                requires_resolution=True,  # the issuer's ISINs come from resolve_entity
            ))
            if len(matches) >= limit:
                break
        return matches

    def resolve_entity(self, identifier: str) -> Entity:
        candidate = identifier.strip()
        if len(candidate) == 20 and candidate.isalnum():
            lei = self._lei(candidate)
        else:
            if not candidate:
                raise ValueError("identifier must not be empty")
            rows, total, _ = self._name_rows(candidate)
            if total > len(rows):
                raise AmbiguousEntityError(
                    f"France OAM issuer search for {candidate!r} exceeds the candidate limit; use an LEI"
                )
            leis = {row.get(_LEI_FIELD) for row in rows
                    if isinstance(row.get(_NAME_FIELD), str)
                    and row[_NAME_FIELD].casefold() == candidate.casefold()
                    and isinstance(row.get(_LEI_FIELD), str)
                    and re.fullmatch(r"[A-Za-z0-9]{20}", row[_LEI_FIELD])}
            if not leis:
                raise EntityNotFoundError(f"No exact issuer name {candidate!r} in France OAM; use an LEI")
            if len(leis) > 1:
                raise AmbiguousEntityError(f"Issuer name {candidate!r} has multiple LEIs in France OAM; use an LEI")
            lei = next(iter(leis))
        rows, _ = self._page(lei, form=None, offset=0, size=1)
        if not rows:
            raise EntityNotFoundError(f"LEI {lei} is absent from France OAM")
        row = rows[0]
        if row.get("identificationsociete_iso_cd_lei") != lei:
            raise ProviderError("France OAM returned a different issuer LEI")
        name = row.get("identificationsociete_iso_nom_soc")
        if not isinstance(name, str) or not name.strip():
            raise ParseError(f"France OAM omitted the name for LEI {lei}")
        source_url = f"{_API}?{urlencode({'where': self._where(lei, None), 'limit': 1})}"
        identifiers = [Identifier("LEI", lei, source_url)]
        isin = row.get("identificationsociete_iso_cd_isi")
        if isinstance(isin, str) and isin:
            identifiers.append(Identifier("ISIN", isin, source_url))
        return Entity(
            entity_id=lei, name=name, jurisdiction="FR", provider=self.name,
            source_url=source_url, identifiers=tuple(identifiers),
            provider_metadata=row,
            provenance=Provenance(self.name, self.regulator, "FR", source_url, lei,
                                  datetime.now(timezone.utc), row),
        )

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        """Read one original UIN plus diffuser record without scanning an issuer list."""
        if entity.jurisdiction != "FR":
            raise ValueError("entity jurisdiction does not match France OAM")
        lei = self._lei(entity.entity_id)
        match = re.fullmatch(r"([A-Za-z0-9_-]{1,32}):([A-Za-z0-9_-]{1,64})", filing_id)
        if match is None:
            raise FilingNotFoundError(f"invalid France OAM filing ID {filing_id!r}")
        diffuser, uin = match.groups()
        isins = self._isins(entity)
        owner = self._where(lei, None, isins=isins)
        where = f"uin_idt_uin = '{uin}' AND identificationdiffuseur_idi_cod_dif = '{diffuser}' AND {owner}"
        response = self.transport.get_json(_API, params={"where": where, "limit": 2})
        rows = response.get("results") if isinstance(response, dict) else None
        count = response.get("total_count") if isinstance(response, dict) else None
        if not isinstance(rows, list) or not isinstance(count, int) or any(not isinstance(row, dict) for row in rows):
            raise ParseError("France OAM returned an invalid direct filing result")
        if count == 0 and not rows:
            raise FilingNotFoundError(f"filing {filing_id!r} is absent for LEI {lei}")
        if count != 1 or len(rows) != 1:
            raise ProviderError(f"France OAM returned inconsistent records for filing {filing_id!r}")
        row = rows[0]
        if self._owner_match(row, lei, isins) is None:
            raise FilingNotFoundError(f"filing {filing_id!r} does not belong to LEI {lei}")
        if row.get("uin_idt_uin") != uin or row.get("identificationdiffuseur_idi_cod_dif") != diffuser:
            raise ProviderError(f"France OAM returned a different filing for {filing_id!r}")
        return self._filing(row, lei, matched_by=self._owner_match(row, lei, isins))

    @staticmethod
    def _owner_match(row: dict, lei: str, isins: tuple[str, ...]) -> str | None:
        if row.get(_LEI_FIELD) == lei:
            return "lei"
        if row.get(_ISIN_FIELD) in isins:
            return "isin"
        return None

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        lei = self._lei(entity.entity_id)
        if entity.jurisdiction != "FR":
            raise ValueError("entity jurisdiction does not match France OAM")
        isins = self._isins(entity)
        yielded = offset = 0
        seen: set[str] = set()
        while True:
            rows, total = self._page(lei, form=form, offset=offset, size=self.page_size,
                                     start=start, end=end, isins=isins)
            if not rows:
                return
            for row in rows:
                matched_by = self._owner_match(row, lei, isins)
                if matched_by is None:
                    raise ProviderError("France OAM returned another issuer's filing")
                filing = self._filing(row, lei, matched_by=matched_by)
                if filing.filing_id in seen:
                    raise ProviderError(f"France OAM repeated UIN {filing.filing_id}")
                seen.add(filing.filing_id)
                if start and filing.filing_date and filing.filing_date < start:
                    return
                if end and filing.filing_date and filing.filing_date > end:
                    continue
                if not include_amendments and filing.amendment is True:
                    continue
                yield filing
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            offset += len(rows)
            if offset >= total:
                return
            if offset >= 10_000:
                raise UnsupportedCapabilityError(
                    "France OAM records API offsets stop at 10,000; narrow the date or form filter"
                )

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        """A native code matches a record carrying it as primary or secondary code, as the source query does."""
        return (super().filing_matches_form(filing, requested)
                or requested in _source_codes(dict(filing.provenance.raw)))

    def _filing(self, row: dict, lei: str, *, matched_by: str | None = "lei") -> Filing:
        uin = row.get("uin_idt_uin")
        diffuser = row.get("identificationdiffuseur_idi_cod_dif")
        if not isinstance(uin, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uin):
            raise ParseError("France OAM record lacks a valid UIN")
        if not isinstance(diffuser, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", diffuser):
            raise ParseError("France OAM record lacks a valid diffuser code")
        # The official portal defines UIN plus diffuser code as the source key.
        filing_id = f"{diffuser}:{uin}"
        record_where = f"uin_idt_uin = '{uin}' AND identificationdiffuseur_idi_cod_dif = '{diffuser}'"
        source_url = f"{_API}?{urlencode({'where': record_where, 'limit': 1})}"
        published = _timestamp(row.get("uin_dat_amf"))
        code = row.get("informationdeposee_inf_stp_pri")
        title = row.get("informationdeposee_inf_tit_inf")
        status = row.get("informationdeposee_inf_upg_inf_inf_upg_sts")
        related = row.get("informationdeposee_inf_upg_inf_inf_upg_rel")
        amendment = None if not status else str(status).upper() != "NEW"
        categories = {_CODE_CATEGORY[code] for code in _source_codes(row) if code in _CODE_CATEGORY}
        return Filing(
            filing_id=filing_id, entity_id=lei, jurisdiction="FR", provider=self.name,
            regulator=self.regulator, source_url=source_url,
            provenance=Provenance(self.name, self.regulator, "FR", source_url, filing_id,
                                  datetime.now(timezone.utc), row),
            filing_type_raw=str(code) if code is not None else None,
            filing_type_normalized=next(iter(categories)) if len(categories) == 1 else None,
            title=str(title) if title is not None else None,
            filing_date=published.date() if published else None,
            published_at=published, amendment=amendment,
            language=_language(row.get("informationdeposee_inf_lng_inf")),
            provider_metadata={**row, "_amendment_related": related, "matched_by": matched_by}, _provider=self,
        )

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        url = filing.provider_metadata.get("url_de_recuperation")
        if not isinstance(url, str) or not url:
            return []
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != _DOWNLOAD_HOST:
            raise ProviderError(f"France OAM returned an unexpected download host for {filing.filing_id}")
        filename = PurePosixPath(parsed.path).name
        if not filename:
            raise ParseError(f"France OAM omitted the filename for {filing.filing_id}")
        document_id = f"{filing.filing_id}:{filename}"
        return [FilingDocument(
            document_id=document_id, filing_id=filing.filing_id,
            filename=filename, source_url=url,
            provenance=Provenance(self.name, self.regulator, "FR", url, document_id,
                                  raw={"source_key": filing.filing_id, "filename": filename,
                                       "published_at": str(filing.published_at)}),
            media_type=_oam.media_type(url),document_type="original_oam_attachment",
            language=filing.language, is_primary=True,
            role="report" if filing.filing_type_normalized in {"ANNUAL", "INTERIM", "QUARTERLY"} else "other",
            provider_metadata={"source_key": filing.filing_id, "record_url": filing.source_url,
                               "original_filename": filing.provider_metadata.get("fichierdecontenu_inf_fic_nom")},
            _provider=self,
        )]

    def download_document(self, document: FilingDocument) -> bytes:
        _oam.require_https_host(document.source_url, _DOWNLOAD_HOST,
                                "France OAM attachment URL is outside the expected HTTPS host")
        return _oam.download(self.transport, document.source_url, label="France OAM attachment")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        _oam.require_https_host(document.source_url, _DOWNLOAD_HOST,
                                "France OAM attachment URL is outside the expected HTTPS host")
        return _oam.save(self.transport, document.source_url, path, document.media_type,
                         label="France OAM attachment")

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type in {"application/xhtml+xml", "text/html"}:
            return document._html_text()
        if document.media_type == "application/zip":
            reports = best_reports(document)
            if reports:
                return reports[0].text()
        raise UnsupportedCapabilityError(
            f"France OAM text extraction has no supported HTML/XHTML in {document.filename}"
        )

    def raw_facts(self, filing: Filing):
        for document in filing.documents:
            if document.media_type in {"application/xhtml+xml", "text/html"}:
                candidates = [(document.filename, document)]
            elif document.media_type == "application/zip":
                candidates = ((member.entry_path, member) for member in best_reports(document))
            else:
                continue
            for entry_path, source in candidates:
                # _parse_content streams a large member to a file (Michelin FY2025 is over 100 MB).
                with source._parse_content() as content:
                    if entry_path.lower().endswith((".html", ".htm")) and not _has_inline_namespace(content):
                        continue
                    facts = parse_ixbrl_xhtml(
                        content, document_url=document.source_url, entry_path=entry_path, provider=self.name,
                        regulator=self.regulator, jurisdiction="FR", filing_id=filing.filing_id,
                    )
                if facts:
                    return facts
        raise UnsupportedCapabilityError(f"France OAM filing {filing.filing_id} has no parsed inline XBRL facts")
