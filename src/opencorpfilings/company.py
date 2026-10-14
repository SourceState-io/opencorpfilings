"""The shared issuer entry point."""

from __future__ import annotations

from datetime import date, datetime
from difflib import get_close_matches
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import ExperimentalRouteWarning, FilingNotFoundError, ProviderError, UnsupportedCapabilityError
from .models import FILING_CATEGORIES, Entity, Filing, FilingCollection, _bind_filing

if TYPE_CHECKING:
    from .provider import FilingProvider


def _parse_date(value: str | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _configure_cache(provider: FilingProvider, cache_dir: str | Path | None) -> None:
    if cache_dir is None:
        return
    from .transport import HttpTransport

    transport = getattr(provider, "transport", None)
    if not isinstance(transport, HttpTransport):
        raise UnsupportedCapabilityError(f"{provider.name} cannot use the local response cache")
    transport.configure_cache(cache_dir)


def search_companies(
    query: str, *, market: str, limit: int = 10,
    provider: FilingProvider | None = None, cache_dir: str | Path | None = None,
    **provider_options: object,
) -> list[Entity]:
    """Find issuer candidates within one market, retaining source identifiers."""
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    owns_provider = provider is None
    if provider is None:
        from .providers import provider_for_market

        provider = provider_for_market(market.upper(), **provider_options)
    elif provider_options:
        raise ValueError("provider options cannot be used with an explicit provider")
    try:
        if provider.market.upper() != market.upper():
            raise ValueError(f"provider {provider.name} serves {provider.market}, not {market}")
        _configure_cache(provider, cache_dir)
        if not provider.supports("entity_search"):
            raise UnsupportedCapabilityError(f"{provider.name} does not support entity search")
        candidates = provider.search_entities(query, limit=limit)[:limit]
        for candidate in candidates:
            provenance = candidate.provenance
            if provenance is None:
                raise ProviderError(f"search candidate {candidate.entity_id!r} lacks source provenance")
            if (candidate.jurisdiction.upper() != market.upper()
                    or candidate.provider != provider.name
                    or provenance.jurisdiction.upper() != market.upper()
                    or provenance.provider != provider.name):
                raise ProviderError(
                    f"search candidate {candidate.entity_id!r} does not match the selected market and provider"
                )
        return candidates
    finally:
        if owns_provider:
            provider.close()


def _check_route_request(
    provider: FilingProvider, *, form: str | None, dated: bool, include_amendments: bool | None,
) -> None:
    """Refuse what the route profile cannot serve, before resolving the issuer or paging a source."""
    route = f"{provider.market}/{provider.name}"
    if form is not None and provider.forms is not None:
        allowed = ", ".join(provider.forms)
        native = "exact native source forms are also accepted" if provider.native_forms else (
            "native source form codes are not accepted")
        if form.upper() in FILING_CATEGORIES:
            if form.lower() not in provider.forms:
                raise UnsupportedCapabilityError(
                    f"{route} cannot select form={form!r}; its categories are: {allowed} ({native})")
        elif not provider.native_forms:
            raise UnsupportedCapabilityError(
                f"{route} does not accept form={form!r}; use one of: {allowed} ({native})")
        elif close := get_close_matches(form.lower(), [name.lower() for name in FILING_CATEGORIES], n=1, cutoff=0.8):
            raise UnsupportedCapabilityError(
                f"{route} has no form {form!r}; did you mean {close[0]!r}? Categories: {allowed}")
    if dated and not provider.date_filters:
        raise UnsupportedCapabilityError(
            f"{route} has no source filing date to filter on; call filings() without start/end")
    if include_amendments is False and provider.forms is not None and not provider.identifies_amendments:
        raise UnsupportedCapabilityError(
            f"{route} cannot tell amendments apart; omit include_amendments")


# Built-in experimental routes warn once per process; a caller's own provider does not.
_WARNED_ROUTES: set[tuple[str, str]] = set()


def _warn_if_experimental(provider: FilingProvider) -> None:
    route = (provider.market, provider.name)
    if (provider.tier == "experimental" and type(provider).__module__.startswith("opencorpfilings.providers.")
            and route not in _WARNED_ROUTES):
        _WARNED_ROUTES.add(route)
        warnings.warn(
            f"{provider.market}/{provider.name} is an experimental route: it has not been qualified for this "
            f"release, so results may be incomplete. Supported routes: US, UK, JP, FR.",
            ExperimentalRouteWarning, stacklevel=3)


class Company:
    def __init__(
        self,
        identifier: str | Entity,
        *,
        market: str | None = None,
        provider: FilingProvider | None = None,
        cache_dir: str | Path | None = None,
        **provider_options: object,
    ) -> None:
        entity = identifier if isinstance(identifier, Entity) else None
        if entity is not None:
            if not entity.entity_id.strip() or not entity.jurisdiction.strip() or not entity.provider.strip():
                raise ValueError("entity must have a source identifier, jurisdiction, and provider")
            if market is not None and market.upper() != entity.jurisdiction.upper():
                raise ValueError(f"entity jurisdiction {entity.jurisdiction} does not match market {market}")
            market = entity.jurisdiction
            source = provider_options.get("source")
            if source is not None and (source == "esef_index") != (entity.provider == "esef_index"):
                raise ValueError(f"source route {source!r} does not match entity provider {entity.provider}")
            if entity.provider == "esef_index" and source is None and provider is None:
                provider_options["source"] = "esef_index"
            self.identifier = entity.entity_id
        else:
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("identifier must not be empty")
            if market is None:
                raise ValueError("market is required for a string identifier")
            self.identifier = identifier.strip()
        self.market = market.upper()
        owns_provider = provider is None
        if provider is None:
            from .providers import provider_for_market

            provider = provider_for_market(self.market, **provider_options)
        elif provider_options:
            raise ValueError("provider options cannot be used with an explicit provider")
        try:
            if provider.market.upper() != self.market:
                raise ValueError(f"provider {provider.name} serves {provider.market}, not {self.market}")
            if entity is not None and provider.name != entity.provider:
                raise ValueError(f"provider {provider.name} does not match entity provider {entity.provider}")
            _configure_cache(provider, cache_dir)
        except Exception:
            if owns_provider:
                provider.close()
            raise
        self.provider = provider
        self._owns_provider = owns_provider
        _warn_if_experimental(provider)
        self._search_result: Entity | None = entity
        self._entity: Entity | None = entity if entity is not None and not entity.requires_resolution else None

    def __repr__(self) -> str:
        """Never resolves the issuer: printing a company does not contact the source."""
        name = f" {self._entity.name!r}" if self._entity is not None else ""
        return f"<Company {self.identifier}{name} {self.market}/{self.provider.name}>"

    def close(self) -> None:
        """Close the provider this Company created; a provider you passed in stays open."""
        if self._owns_provider:
            self.provider.close()

    def __enter__(self) -> Company:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def entity(self) -> Entity:
        """The source-resolved issuer, resolved on first use."""
        if self._entity is None:
            resolved = (self.provider.resolve_search_result(self._search_result)
                        if self._search_result is not None else self.provider.resolve_entity(self.identifier))
            if resolved.provider != self.provider.name or resolved.jurisdiction.upper() != self.market:
                raise ValueError("resolved entity does not match the selected provider and market")
            self._entity = resolved
        return self._entity

    @property
    def search_result(self) -> Entity | None:
        """The originally selected source candidate, if one was provided."""
        return self._search_result

    def filings(
        self,
        *,
        form: str | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
        include_amendments: bool | None = None,
        limit: int | None = None,
    ) -> FilingCollection:
        """Filings newest first in the source's `order_basis`.

        A convenience category (`annual`, `interim`, ...) selects original
        reports by default where the source flags amendments; pass
        `include_amendments=True` to include them. An exact native form, or no
        form, lists every matching record.
        """
        _check_route_request(self.provider, form=form, dated=start is not None or end is not None,
                             include_amendments=include_amendments)
        if include_amendments is None:
            category = form is not None and form.upper() in FILING_CATEGORIES
            include_amendments = not (category and self.provider.identifies_amendments)
        start_date, end_date = _parse_date(start), _parse_date(end)
        if start_date and end_date and start_date > end_date:
            raise ValueError("start must not be after end")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        return FilingCollection(
            self.provider,
            self.entity,
            form=form.lower() if form else None,
            start=start_date,
            end=end_date,
            include_amendments=include_amendments,
            limit=limit,
        )

    def get_filing(
        self, filing_id: str, *, start: str | date | None = None,
        end: str | date | None = None, max_scan: int = 500,
    ) -> Filing:
        """Find one exact source ID, using a native record route when available."""
        if not filing_id:
            raise ValueError("filing_id must not be empty")
        if max_scan <= 0:
            raise ValueError("max_scan must be positive")
        start_date, end_date = _parse_date(start), _parse_date(end)
        if start_date and end_date and start_date > end_date:
            raise ValueError("start must not be after end")
        if not self.provider.supports("direct_filing_lookup"):
            return self.filings(start=start_date, end=end_date).get(filing_id, max_scan=max_scan)
        filing = self.provider.get_filing(self.entity, filing_id)
        if filing.filing_id != filing_id or filing.entity_id != self.entity.entity_id:
            raise FilingNotFoundError(f"filing {filing_id!r} does not belong to {self.entity.name}")
        _bind_filing(filing, self.provider, self.entity)
        if start_date or end_date:
            when = self.provider.filing_date_for_filter(filing)
            if when is None:
                raise UnsupportedCapabilityError(f"{self.provider.name} does not expose a source filing date for {filing_id}")
            if (start_date and when < start_date) or (end_date and when > end_date):
                raise FilingNotFoundError(f"filing {filing_id!r} is outside the selected date range")
        return filing
