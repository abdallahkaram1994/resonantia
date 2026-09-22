from collections.abc import Sequence

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models import Q
from pgvector.django import VectorField

from catalog.text import content_hash

# The column width. Changing it needs a migration and a re-embed of the whole catalog.
EMBEDDING_DIMENSIONS = 768


class MediaType(models.TextChoices):
    FILM = "film", "Film"
    GAME = "game", "Game"
    ALBUM = "album", "Album"


class ItemQuerySet(models.QuerySet):
    def needing_embedding(self, model: str, dim: int) -> "ItemQuerySet":
        """Items with no vector, or one made by a different model or dimension."""
        return self.filter(
            Q(embedding__isnull=True) | ~Q(embedding_model=model) | ~Q(embedding_dim=dim)
        )


class Item(models.Model):
    media_type = models.CharField(max_length=16, choices=MediaType.choices)
    title = models.CharField(max_length=500)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    cover_url = models.URLField(max_length=1000, blank=True)
    summary = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    combined_text = models.TextField()
    content_hash = models.CharField(max_length=64)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True, default="")
    embedding_dim = models.PositiveSmallIntegerField(null=True, blank=True)
    # {field name: {"source": ..., "fetched_at": ISO 8601 UTC}} for every sourced field
    provenance = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ItemQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["media_type"], name="item_media_type_idx"),
            # Backs the Postgres full-text fallback (SPEC section 7.5): used only when the
            # embedding provider is unavailable. `combined_text` already holds the title, genres
            # or tags, and the summary, so nothing new needs to be tracked for it.
            GinIndex(
                SearchVector("combined_text", config="english"), name="item_combined_text_gin"
            ),
        ]
        constraints = [
            # A vector is never stored without the model and dimension that produced it.
            models.CheckConstraint(
                condition=(
                    Q(embedding__isnull=True, embedding_model="", embedding_dim__isnull=True)
                    | (
                        Q(embedding__isnull=False, embedding_dim__isnull=False)
                        & ~Q(embedding_model="")
                    )
                ),
                name="item_embedding_has_model_and_dim",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.media_type})"

    def set_combined_text(self, text: str) -> bool:
        """Store the text and its hash. A changed hash invalidates the stored vector."""
        new_hash = content_hash(text)
        changed = new_hash != self.content_hash
        self.combined_text = text
        self.content_hash = new_hash
        if changed:
            self.clear_embedding()
        return changed

    def set_embedding(self, vector: Sequence[float], model: str) -> None:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Expected {EMBEDDING_DIMENSIONS} dimensions, got {len(vector)}")
        self.embedding = list(vector)
        self.embedding_model = model
        self.embedding_dim = len(vector)

    def clear_embedding(self) -> None:
        self.embedding = None
        self.embedding_model = ""
        self.embedding_dim = None


class ExternalId(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="external_ids")
    source = models.CharField(max_length=50)
    external_id = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="externalid_source_external_id_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.external_id}"


class SkippedRecord(models.Model):
    """A source record that was checked and rejected (for example a live album), remembered so a
    re-run does not repeat the expensive lookups. Retry them with --retry-skipped."""

    source = models.CharField(max_length=50)
    external_id = models.CharField(max_length=100)
    reason = models.CharField(max_length=50)
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="skippedrecord_source_external_id_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.external_id} ({self.reason})"


class QueryEmbedding(models.Model):
    """A cached embedding of a search query, so repeating a search, or changing a filter on it,
    does not spend another provider request (the free tier allows about 1,000 a day).

    The key is a hash of the normalized query with the model and dimension, so a different model
    never gets another model's vector. The query text itself is not stored: searches are anonymous.
    """

    text_hash = models.CharField(max_length=64)
    embedding_model = models.CharField(max_length=100)
    embedding_dim = models.PositiveSmallIntegerField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    # For pruning old rows (M6).
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["text_hash", "embedding_model", "embedding_dim"],
                name="queryembedding_text_model_dim_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.text_hash[:8]} ({self.embedding_model})"


class Score(models.Model):
    """Display-only. Scores are never embedded and never affect ranking."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="scores")
    source = models.CharField(max_length=50)
    value = models.FloatField()
    vote_count = models.PositiveIntegerField(null=True, blank=True)
    fetched_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "source"], name="score_item_source_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.source}: {self.value}"
