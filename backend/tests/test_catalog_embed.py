import pytest

from catalog.embed import embed_pending
from catalog.embedding.base import EmbeddingRateLimited, EmbeddingUnavailable
from catalog.ingest import upsert_film
from catalog.models import Item
from tests.factories import FakeEmbedder, make_record

pytestmark = pytest.mark.django_db


def add_films(count: int) -> None:
    for i in range(1, count + 1):
        upsert_film(make_record(i))


def test_embeds_every_pending_item_as_a_document_and_saves_model_and_dim() -> None:
    add_films(3)
    embedder = FakeEmbedder()

    stats = embed_pending(embedder)

    assert stats.embedded == 3
    assert stats.stopped is None
    assert embedder.kinds == ["document"] * 3
    assert embedder.texts == [item.combined_text for item in Item.objects.order_by("id")]
    for item in Item.objects.all():
        assert item.embedding is not None
        assert item.embedding_model == "test-model"
        assert item.embedding_dim == 768


def test_texts_are_embedded_one_per_call() -> None:
    add_films(2)
    calls: list[int] = []

    class Recording(FakeEmbedder):
        def embed(self, texts, kind):
            calls.append(len(texts))
            return super().embed(texts, kind)

    embed_pending(Recording())

    assert calls == [1, 1]


def test_items_that_already_have_a_current_vector_are_not_embedded_again() -> None:
    add_films(3)
    embed_pending(FakeEmbedder())
    embedder = FakeEmbedder()

    stats = embed_pending(embedder)

    assert stats.embedded == 0
    assert embedder.texts == []


def test_a_new_model_re_embeds_everything() -> None:
    add_films(2)
    embed_pending(FakeEmbedder(model="old-model"))
    embedder = FakeEmbedder(model="new-model")

    stats = embed_pending(embedder)

    assert stats.embedded == 2
    assert set(Item.objects.values_list("embedding_model", flat=True)) == {"new-model"}


def test_only_items_whose_text_changed_are_re_embedded() -> None:
    add_films(3)
    embed_pending(FakeEmbedder())
    upsert_film(make_record(2, overview="A different story entirely."))
    embedder = FakeEmbedder()

    stats = embed_pending(embedder)

    assert stats.embedded == 1
    assert "A different story entirely." in embedder.texts[0]


def test_limit_caps_the_run_across_chunks() -> None:
    add_films(5)

    stats = embed_pending(FakeEmbedder(), limit=3, chunk_size=2)

    assert stats.embedded == 3
    assert Item.objects.filter(embedding__isnull=False).count() == 3


def test_chunking_covers_every_item() -> None:
    add_films(5)

    stats = embed_pending(FakeEmbedder(), chunk_size=2)

    assert stats.embedded == 5
    assert Item.objects.filter(embedding__isnull=True).count() == 0


def test_a_rate_limit_stops_cleanly_keeps_progress_and_the_next_run_resumes() -> None:
    add_films(5)
    limited = EmbeddingRateLimited("daily quota", retry_after=None, quota_exhausted=True)

    first = embed_pending(FakeEmbedder(fail_on=3, error=limited))

    assert first.embedded == 2
    assert first.stopped is limited
    assert Item.objects.filter(embedding__isnull=False).count() == 2

    resumed = FakeEmbedder()
    second = embed_pending(resumed)

    assert second.embedded == 3
    assert len(resumed.texts) == 3
    assert Item.objects.filter(embedding__isnull=True).count() == 0


def test_other_provider_errors_propagate_but_earlier_vectors_are_kept() -> None:
    add_films(4)

    with pytest.raises(EmbeddingUnavailable):
        embed_pending(FakeEmbedder(fail_on=3, error=EmbeddingUnavailable("down")))

    assert Item.objects.filter(embedding__isnull=False).count() == 2


def test_progress_callback_sees_each_saved_vector() -> None:
    add_films(3)
    seen: list[int] = []

    embed_pending(FakeEmbedder(), progress=lambda stats: seen.append(stats.embedded))

    assert seen == [1, 2, 3]
