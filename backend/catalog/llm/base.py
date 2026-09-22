from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Base class. Messages are safe to log: they never contain credentials."""


class LLMRateLimited(LLMError):
    def __init__(self, message: str, *, retry_after: float | None, quota_exhausted: bool) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        # True when the provider says the (daily) quota is used up, so waiting minutes won't help.
        self.quota_exhausted = quota_exhausted


class LLMUnavailable(LLMError):
    """The provider is down, unreachable, blocked the response, or returned something unusable."""


class LLMRequestError(LLMError):
    """The provider rejected the request or the setup is wrong (key, model)."""


@dataclass(frozen=True)
class ParsedQuery:
    """SPEC section 7.1 step 3: what a raw search query is parsed into."""

    vibe_text: str
    # One of MediaType.values, or None when the query does not clearly name one type.
    media_type_hint: str | None


class LLM(Protocol):
    def parse_query(self, query: str) -> ParsedQuery:
        """Extract the vibe text and an optional media-type hint from a raw, untrusted query.

        Raises LLMError subclasses on failure; the caller falls back to the raw query with no
        hint (SPEC section 7.5), so this never needs to be retried by hand.
        """
        ...

    def explain_match(self, query: str, item_text: str) -> str:
        """One short sentence explaining why an item matches a search, grounded only in
        `item_text` (the item's own stored metadata, never other candidates). `query` is the
        visitor's own, untrusted, raw text. Raises LLMError subclasses on failure; the caller
        just shows the item with no explanation (SPEC section 8), never fails the page.
        """
        ...
