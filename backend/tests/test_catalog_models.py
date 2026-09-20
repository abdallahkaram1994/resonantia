import datetime as dt

import pytest
from django.db import IntegrityError, transaction

from catalog.models import EMBEDDING_DIMENSIONS, ExternalId, Item, MediaType, Score

MODEL = "gemini-embedding-2"


def make_item(title: str = "Heat", **overrides: object) -> Item:
    item = Item(media_type=MediaType.FILM, title=title, **overrides)
    item.set_combined_text(f"{title}\nGenres: Crime")
    return item


def vector(value: float = 0.5) -> list[float]:
    return [value] * EMBEDDING_DIMENSIONS


@pytest.mark.django_db
def test_item_round_trips_with_null_year_and_no_embedding() -> None:
    item = make_item()
    item.save()

    saved = Item.objects.get(pk=item.pk)

    assert saved.release_year is None
    assert saved.embedding is None
    assert saved.embedding_model == ""
    assert saved.embedding_dim is None
    assert saved.provenance == {}
    assert saved.media_type == "film"


@pytest.mark.django_db
def test_embedding_round_trips_with_model_and_dim() -> None:
    item = make_item(release_year=1995)
    item.set_embedding(vector(0.25), MODEL)
    item.save()

    saved = Item.objects.get(pk=item.pk)

    assert saved.release_year == 1995
    assert list(saved.embedding) == pytest.approx(vector(0.25))
    assert saved.embedding_model == MODEL
    assert saved.embedding_dim == EMBEDDING_DIMENSIONS


def test_set_embedding_rejects_wrong_dimension() -> None:
    item = make_item()

    with pytest.raises(ValueError, match="768"):
        item.set_embedding([0.1, 0.2], MODEL)

    assert item.embedding is None


@pytest.mark.django_db
def test_db_refuses_a_vector_without_its_model() -> None:
    item = make_item()
    item.embedding = vector()
    item.embedding_dim = EMBEDDING_DIMENSIONS

    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()


@pytest.mark.django_db
def test_db_refuses_a_model_without_a_vector() -> None:
    item = make_item()
    item.embedding_model = MODEL

    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()


def test_unchanged_text_keeps_the_embedding() -> None:
    item = make_item()
    item.set_embedding(vector(), MODEL)

    changed = item.set_combined_text(item.combined_text)

    assert changed is False
    assert item.embedding is not None
    assert item.embedding_model == MODEL


def test_changed_text_clears_the_embedding() -> None:
    item = make_item()
    item.set_embedding(vector(), MODEL)
    old_hash = item.content_hash

    changed = item.set_combined_text("Heat\nGenres: Crime, Drama")

    assert changed is True
    assert item.content_hash != old_hash
    assert item.embedding is None
    assert item.embedding_model == ""
    assert item.embedding_dim is None


@pytest.mark.django_db
def test_needing_embedding_selects_missing_and_foreign_model_vectors() -> None:
    missing = make_item("Missing")
    missing.save()

    current = make_item("Current")
    current.set_embedding(vector(), MODEL)
    current.save()

    other_model = make_item("Other model")
    other_model.set_embedding(vector(), "gemini-embedding-001")
    other_model.save()

    other_dim = make_item("Other dim")
    other_dim.set_embedding(vector(), MODEL)
    other_dim.embedding_dim = 512
    other_dim.save()

    titles = set(
        Item.objects.needing_embedding(MODEL, EMBEDDING_DIMENSIONS).values_list("title", flat=True)
    )

    assert titles == {"Missing", "Other model", "Other dim"}


@pytest.mark.django_db
def test_external_id_is_unique_per_source() -> None:
    first = make_item("First")
    first.save()
    second = make_item("Second")
    second.save()
    ExternalId.objects.create(item=first, source="tmdb", external_id="949")

    ExternalId.objects.create(item=second, source="other", external_id="949")
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalId.objects.create(item=second, source="tmdb", external_id="949")


@pytest.mark.django_db
def test_score_is_unique_per_item_and_source() -> None:
    item = make_item()
    item.save()
    fetched_at = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
    Score.objects.create(item=item, source="tmdb", value=7.9, vote_count=100, fetched_at=fetched_at)

    with pytest.raises(IntegrityError), transaction.atomic():
        Score.objects.create(item=item, source="tmdb", value=8.0, fetched_at=fetched_at)

    assert item.scores.count() == 1


@pytest.mark.django_db
def test_deleting_an_item_removes_its_ids_and_scores() -> None:
    item = make_item()
    item.save()
    ExternalId.objects.create(item=item, source="tmdb", external_id="949")
    Score.objects.create(
        item=item, source="tmdb", value=7.9, fetched_at=dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
    )

    item.delete()

    assert ExternalId.objects.count() == 0
    assert Score.objects.count() == 0
