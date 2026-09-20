from datetime import UTC, datetime, timedelta

import pytest

from catalog.ingest import (
    ingest_films,
    oldest_tmdb_fetch,
    stale_cache_warning,
    upsert_film,
)
from catalog.models import ExternalId, Item, MediaType, Score
from tests.factories import NOW, FakeFilmSource, make_record

pytestmark = pytest.mark.django_db


def test_upsert_creates_the_item_with_ids_score_and_provenance() -> None:
    outcome = upsert_film(make_record(7, title="Neon Rain", genres=("Sci-Fi", "Thriller")))

    item = Item.objects.get()
    assert outcome == "created"
    assert item.media_type == MediaType.FILM
    assert item.title == "Neon Rain"
    assert item.release_year == 2001
    assert item.cover_url == "https://image.tmdb.org/t/p/w342/film7.jpg"
    assert item.summary == "Overview of film 7."
    assert item.details["genres"] == ["Sci-Fi", "Thriller"]
    assert item.details["keywords"] == ["rain"]
    assert item.combined_text == (
        "Neon Rain\nGenres: Sci-Fi, Thriller\nKeywords: rain\n\nOverview of film 7."
    )
    assert item.embedding is None
    assert ExternalId.objects.get().source == "tmdb"
    assert ExternalId.objects.get().external_id == "7"
    score = Score.objects.get()
    assert (score.source, score.value, score.vote_count) == ("tmdb", 7.0, 1500)
    for name in ("title", "release_year", "cover_url", "summary", "details"):
        assert item.provenance[name] == {"source": "tmdb", "fetched_at": NOW.isoformat()}


def test_a_missing_release_date_is_stored_as_null() -> None:
    upsert_film(make_record(release_year=None))

    assert Item.objects.get().release_year is None


def test_reingesting_unchanged_data_keeps_the_embedding_and_refreshes_provenance() -> None:
    upsert_film(make_record(1))
    item = Item.objects.get()
    item.set_embedding([0.5] * 768, "test-model")
    item.save()
    later = NOW + timedelta(days=30)

    outcome = upsert_film(make_record(1, fetched_at=later))

    item.refresh_from_db()
    assert outcome == "unchanged"
    assert Item.objects.count() == 1
    assert ExternalId.objects.count() == 1
    assert item.embedding is not None
    assert item.embedding_model == "test-model"
    assert item.provenance["title"]["fetched_at"] == later.isoformat()
    assert Score.objects.get().fetched_at == later


def test_changed_text_updates_the_item_and_clears_the_stale_embedding() -> None:
    upsert_film(make_record(1))
    item = Item.objects.get()
    item.set_embedding([0.5] * 768, "test-model")
    item.save()

    outcome = upsert_film(make_record(1, overview="A completely different story."))

    item.refresh_from_db()
    assert outcome == "updated"
    assert item.summary == "A completely different story."
    assert item.embedding is None
    assert item.embedding_model == ""


def test_a_change_that_does_not_touch_the_text_keeps_the_embedding() -> None:
    upsert_film(make_record(1))
    item = Item.objects.get()
    item.set_embedding([0.5] * 768, "test-model")
    item.save()

    outcome = upsert_film(make_record(1, cover_url="https://image.tmdb.org/t/p/w342/new.jpg"))

    item.refresh_from_db()
    assert outcome == "updated"
    assert item.cover_url.endswith("new.jpg")
    assert item.embedding is not None


def test_score_follows_the_source_and_is_removed_when_it_disappears() -> None:
    upsert_film(make_record(1, vote_average=7.0, vote_count=100))
    upsert_film(make_record(1, vote_average=8.5, vote_count=250))
    assert Score.objects.get().value == 8.5
    assert Score.objects.get().vote_count == 250

    upsert_film(make_record(1, vote_average=None, vote_count=None))
    assert Score.objects.count() == 0


def test_the_score_never_enters_the_combined_text() -> None:
    upsert_film(make_record(1, vote_average=9.9, vote_count=98765))

    text = Item.objects.get().combined_text
    assert "9.9" not in text and "98765" not in text


def test_ingest_skips_films_without_minimum_metadata_and_does_not_count_them() -> None:
    source = FakeFilmSource(
        popular=[
            make_record(1, overview=""),
            make_record(2, genres=(), keywords=()),
            make_record(3),
            make_record(4, genres=(), keywords=("night",)),
        ]
    )

    stats = ingest_films(source, limit=2, mid_tail_percent=0)

    assert stats.skipped_not_embeddable == 2
    assert stats.created == 2
    assert stats.with_keywords == 2
    assert sorted(Item.objects.values_list("title", flat=True)) == ["Film 3", "Film 4"]


def test_limit_is_split_between_popular_and_mid_tail_and_no_extra_films_are_pulled() -> None:
    source = FakeFilmSource(
        popular=[make_record(i) for i in range(1, 21)],
        mid_tail=[make_record(i) for i in range(101, 111)],
    )

    stats = ingest_films(source, limit=10, mid_tail_percent=20)

    assert stats.created == 10
    assert source.popular_pulled == 8
    assert source.mid_tail_pulled == 2
    ids = set(ExternalId.objects.values_list("external_id", flat=True))
    assert ids == {str(i) for i in [*range(1, 9), 101, 102]}


def test_zero_percent_never_touches_the_mid_tail() -> None:
    source = FakeFilmSource(
        popular=[make_record(i) for i in range(1, 6)], mid_tail=[make_record(101)]
    )

    ingest_films(source, limit=5, mid_tail_percent=0)

    assert source.mid_tail_pulled == 0
    assert Item.objects.count() == 5


def test_a_short_popular_list_is_not_padded_from_the_mid_tail() -> None:
    source = FakeFilmSource(
        popular=[make_record(1), make_record(2)],
        mid_tail=[make_record(i) for i in range(101, 120)],
    )

    stats = ingest_films(source, limit=10, mid_tail_percent=20)

    assert stats.created == 4  # 2 popular available, plus the 2 reserved for the mid-tail


def test_a_film_in_both_streams_is_ingested_once() -> None:
    source = FakeFilmSource(popular=[make_record(1)], mid_tail=[make_record(1), make_record(2)])

    stats = ingest_films(source, limit=10, mid_tail_percent=50)

    assert stats.created == 2
    assert Item.objects.count() == 2


def test_running_ingest_twice_creates_no_duplicates() -> None:
    records = [make_record(i) for i in range(1, 6)]

    first = ingest_films(FakeFilmSource(popular=records), limit=5, mid_tail_percent=0)
    second = ingest_films(FakeFilmSource(popular=records), limit=5, mid_tail_percent=0)

    assert (first.created, second.created) == (5, 0)
    assert second.unchanged == 5
    assert Item.objects.count() == 5


def test_progress_is_reported_after_each_ingested_film() -> None:
    seen: list[int] = []
    source = FakeFilmSource(popular=[make_record(i) for i in range(1, 4)])

    ingest_films(source, limit=3, mid_tail_percent=0, progress=lambda s: seen.append(s.ingested))

    assert seen == [1, 2, 3]


def test_oldest_fetch_uses_the_oldest_score() -> None:
    assert oldest_tmdb_fetch() is None
    upsert_film(make_record(1, fetched_at=NOW))
    upsert_film(make_record(2, fetched_at=NOW - timedelta(days=40)))

    assert oldest_tmdb_fetch() == NOW - timedelta(days=40)


def test_stale_cache_warning_only_appears_past_the_window() -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)

    assert stale_cache_warning(None, 150, now) is None
    assert stale_cache_warning(now - timedelta(days=150), 150, now) is None
    warning = stale_cache_warning(now - timedelta(days=151), 150, now)
    assert warning is not None
    assert "151 days" in warning
    assert "6 months" in warning
