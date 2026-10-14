"""The narrow adapter boundary. Source-specific semantics stay in adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import UnsupportedCapabilityError

if TYPE_CHECKING:
    from .models import Entity, Filing, FilingDocument, FilingFact, FilingSection


# A capability means an adapter can perform the operation for qualifying source
# records. Individual filings/documents can have narrower availability.
CAPABILITY_NAMES = frozenset({
    "entity_lookup", "entity_search", "filing_discovery", "document_download",
    "text", "raw_facts", "html", "pdf", "xbrl", "ixbrl", "source_package",
    "streamed_download",
    "direct_filing_lookup",
    "document_listing_embeds_originals",
    "sections", "printed_pages",
})


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Declared market route; individual records may have fewer usable formats.

    `forms` lists the convenience categories the route can select (None when
    undeclared); `native_forms` says whether an exact source form is accepted.
    """

    market: str
    provider: str
    regulator: str
    capabilities: frozenset[str]
    tier: str = "experimental"
    identifiers: tuple[str, ...] = ()
    forms: tuple[str, ...] | None = None
    native_forms: bool = True
    date_filters: bool = True
    amendment_filter: bool = False
    order_basis: str = "filing_date"
    auth: str | None = None
    coverage_note: str | None = None


class FilingProvider(ABC):
    """Base class for one market's source route.

    A provisional extension point: subclass it to serve a market the package does
    not, and pass an instance as `Company(..., provider=...)`. Its hook methods are
    outside the version 1 compatibility promise and may change in a minor release.
    """

    name: str
    market: str
    regulator: str
    capabilities: frozenset[str] = frozenset()
    order_basis: str = "filing_date"
    # True when iter_filings(include_amendments=False) can drop source-flagged
    # amendments; category requests then default to original reports.
    identifies_amendments: bool = False
    # Route profile, checked by Company.filings() before any source request.
    tier: str = "experimental"
    identifier_kinds: tuple[str, ...] = ()
    forms: tuple[str, ...] | None = None
    native_forms: bool = True
    date_filters: bool = True
    auth: str | None = None
    coverage_note: str | None = None

    @classmethod
    def info(cls, market: str | None = None) -> ProviderInfo:
        """This route's declared profile: tier, identifiers, forms, filters, auth."""
        return ProviderInfo(
            market or cls.market, cls.name, cls.regulator, cls.capabilities, tier=cls.tier,
            identifiers=cls.identifier_kinds, forms=cls.forms, native_forms=cls.native_forms,
            date_filters=cls.date_filters, amendment_filter=cls.identifies_amendments,
            order_basis=cls.order_basis, auth=cls.auth, coverage_note=cls.coverage_note,
        )

    def supports(self, capability: str) -> bool:
        """True when the route declares the named capability."""
        return capability in self.capabilities

    def close(self) -> None:
        """Release any provider-owned HTTP connection."""
        transport = getattr(self, "transport", None)
        if transport is not None:
            transport.close()

    @abstractmethod
    def resolve_entity(self, identifier: str) -> Entity:
        """Resolve a market-scoped identifier to one regulator issuer."""

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        """Return source-listed issuer candidates without resolving each profile."""
        raise UnsupportedCapabilityError(f"{self.name} does not support entity search")

    def resolve_search_result(self, candidate: Entity) -> Entity:
        """Prepare a selected candidate whose source ID is not filing-ready."""
        return self.resolve_entity(candidate.entity_id)

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        """Retrieve one source record directly when a verified native route exists."""
        raise UnsupportedCapabilityError(f"{self.name} does not support direct filing lookup")

    @abstractmethod
    def iter_filings(
        self,
        entity: Entity,
        *,
        form: str | None = None,
        start: date | None = None,
        end: date | None = None,
        include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        """Yield newest first in the documented order_basis."""

    def filing_date_for_filter(self, filing: Filing) -> date | None:
        """Return the source date used by start/end filters."""
        return filing.filing_date

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        """Match a common category or one exact native source form."""
        return (filing.filing_type_normalized == requested.upper()
                or (filing.filing_type_raw is not None
                    and filing.filing_type_raw.casefold() == requested.casefold()))

    @abstractmethod
    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        """List original source documents or packages for one filing."""

    def get_primary_document(self, filing: Filing) -> FilingDocument | None:
        """Use an already source-listed primary file when full enumeration is unnecessary."""
        return None

    @abstractmethod
    def download_document(self, document: FilingDocument) -> bytes:
        """Return the original bytes of exactly one selected source document."""

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        """Stream one original document to disk when the provider supports it."""
        raise UnsupportedCapabilityError(f"{self.name} does not support streamed document saving")

    def extract_text(self, document: FilingDocument) -> str:
        """Text of one document, where its format supports it."""
        raise UnsupportedCapabilityError(
            f"{self.name} cannot extract text from {document.media_type or 'this format'}"
        )

    def raw_facts(self, filing: Filing) -> list[FilingFact]:
        """Raw structured facts of one filing, where its original carries them."""
        raise UnsupportedCapabilityError(f"{self.name} does not expose raw facts for this filing")

    def extract_sections(self, filing: Filing) -> list[FilingSection]:
        """Verified source sections for one filing, where the adapter supports them."""
        raise UnsupportedCapabilityError(f"{self.name} does not expose verified sections for this filing")
