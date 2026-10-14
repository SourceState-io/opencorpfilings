"""One Python interface to source-preserving public company filings."""

from ._version import __version__ as __version__
from .company import Company, search_companies
from .directory import CompanyMatch, find_company
from .errors import (
    AmbiguousEntityError,
    AuthenticationError,
    DownloadError,
    EntityNotFoundError,
    FilingNotFoundError,
    ParseError,
    ProviderError,
    RateLimitError,
    OpenCorpFilingsError,
    SourceUnavailableError,
    UnsupportedCapabilityError,
    UnsupportedMarketError,
    ExperimentalRouteWarning,
)
from .models import FILING_CATEGORIES, Entity, Filing, FilingArchiveMember, FilingCollection, FilingDocument, FilingFact, FilingPage, FilingPrintedPage, FilingSection, FilingSectionReference, FilingTable, FilingTableCell, Identifier, Provenance
from .provider import FilingProvider, ProviderInfo
from .providers import provider_info, supported_markets

__all__ = [
    "AmbiguousEntityError",
    "AuthenticationError",
    "Company",
    "CompanyMatch",
    "DownloadError",
    "Entity",
    "EntityNotFoundError",
    "FILING_CATEGORIES",
    "Filing",
    "FilingArchiveMember",
    "FilingCollection",
    "FilingDocument",
    "FilingFact",
    "FilingPage",
    "FilingPrintedPage",
    "FilingSection",
    "FilingSectionReference",
    "FilingTable",
    "FilingTableCell",
    "FilingNotFoundError",
    "FilingProvider",
    "ProviderInfo",
    "Identifier",
    "ParseError",
    "Provenance",
    "ProviderError",
    "RateLimitError",
    "search_companies",
    "find_company",
    "provider_info",
    "supported_markets",
    "OpenCorpFilingsError",
    "SourceUnavailableError",
    "UnsupportedCapabilityError",
    "UnsupportedMarketError",
    "ExperimentalRouteWarning",
]
