from collections.abc import Sequence
from typing import Literal, Protocol

EmbedKind = Literal["document", "query"]


class EmbeddingError(Exception):
    """Base class. Messages are safe to log: they never contain credentials."""


class EmbeddingRateLimited(EmbeddingError):
    def __init__(self, message: str, *, retry_after: float | None, quota_exhausted: bool) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        # True when the provider says the (daily) quota is used up, so waiting minutes won't help.
        self.quota_exhausted = quota_exhausted


class EmbeddingUnavailable(EmbeddingError):
    """The provider is down, unreachable, or returned something unusable. Try again later."""


class EmbeddingRequestError(EmbeddingError):
    """The provider rejected the request or the setup is wrong (key, model, dimension)."""


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        """One vector per text, in order. Raises EmbeddingError subclasses on failure."""
        ...
