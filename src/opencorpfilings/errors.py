"""Errors shared by all filing providers."""


class OpenCorpFilingsError(Exception):
    """Base public error."""


class ProviderError(OpenCorpFilingsError):
    """A source rejected or could not complete an operation."""


class SourceUnavailableError(ProviderError):
    """A source is temporarily unavailable after bounded retries."""


class AuthenticationError(ProviderError):
    """Credentials are absent or invalid."""


class EntityNotFoundError(ProviderError):
    """No issuer matches the supplied identifier."""


class AmbiguousEntityError(ProviderError):
    """An identifier matches multiple issuers."""


class FilingNotFoundError(ProviderError):
    """No filing matches the request."""


class RateLimitError(ProviderError):
    """The source has limited requests."""


class UnsupportedCapabilityError(OpenCorpFilingsError):
    """The selected source or format cannot provide an operation."""


class UnsupportedMarketError(OpenCorpFilingsError, ValueError):
    """No source route exists for the requested market code."""


class ExperimentalRouteWarning(UserWarning):
    """A Company was opened on a route that has not been qualified for release."""


class DownloadError(ProviderError):
    """A selected original document could not be retrieved."""


class ParseError(ProviderError):
    """A source document could not be parsed."""
