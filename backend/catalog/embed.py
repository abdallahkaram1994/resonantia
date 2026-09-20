from collections.abc import Callable
from dataclasses import dataclass

from catalog.embedding.base import Embedder, EmbeddingRateLimited
from catalog.models import Item


@dataclass
class EmbedStats:
    embedded: int = 0
    # Set when the provider's rate limit or quota stopped the run early. Progress is kept.
    stopped: EmbeddingRateLimited | None = None


def pending_items(embedder: Embedder):
    return Item.objects.needing_embedding(embedder.model, embedder.dimensions)


def embed_pending(
    embedder: Embedder,
    *,
    limit: int | None = None,
    chunk_size: int = 50,
    progress: Callable[[EmbedStats], None] | None = None,
) -> EmbedStats:
    """Embed items that have no vector, or one from another model or dimension.

    Each vector is saved as soon as it arrives, so a stopped run resumes where it left off.
    """
    stats = EmbedStats()
    while limit is None or stats.embedded < limit:
        size = chunk_size if limit is None else min(chunk_size, limit - stats.embedded)
        batch = list(pending_items(embedder).order_by("id")[:size])
        if not batch:
            break
        for item in batch:
            try:
                vector = embedder.embed([item.combined_text], "document")[0]
            except EmbeddingRateLimited as error:
                stats.stopped = error
                return stats
            item.set_embedding(vector, embedder.model)
            item.save(update_fields=["embedding", "embedding_model", "embedding_dim", "updated_at"])
            stats.embedded += 1
            if progress:
                progress(stats)
    return stats
