import pytest

from catalog.ingest import ingest_items, upsert_film, upsert_item
from catalog.models import ExternalId, Item, MediaType, Score
from catalog.sources.base import ScoreRecord
from tests.factories import NOW, FakeItemSource, make_item_record, make_record

pytestmark = pytest.mark.django_db


def album(source_id: str = "rg-1", **overrides: object):
    values: dict[str, object] = {
        "media_type": "album",
        "source": "musicbrainz",
        "title": "OK Computer",
        "summary": "The third studio album.",
        "genres": (),
        "keywords": ("alt rock", "art rock"),
        "byline": "Radiohead",
        "keywords_label": "Tags",
        "cover_url": "https://coverartarchive.org/release-group/rg-1/front-500",
        "details": {"artist": "Radiohead"},
        "score": None,
    }
    values.update(overrides)
    return make_item_record(source_id, **values)


def test_a_game_is_stored_with_its_own_id_score_and_provenance() -> None:
    outcome = upsert_item(make_item_record("42", title="The Witcher"))

    item = Item.objects.get()
    assert outcome == "created"
    assert item.media_type == MediaType.GAME
    assert item.title == "The Witcher"
    assert item.details == {"platforms": ["PC"]}
    assert item.combined_text == (
        "The Witcher\nGenres: Role-playing (RPG)\nKeywords: open world\n\nSummary of game 42."
    )
    external = ExternalId.objects.get()
    assert (external.source, external.external_id) == ("igdb", "42")
    score = Score.objects.get()
    assert (score.source, score.value, score.vote_count) == ("igdb", 84.2, 1500)
    assert item.provenance["title"] == {"source": "igdb", "fetched_at": NOW.isoformat()}


def test_an_album_gets_a_byline_tags_and_per_field_sources() -> None:
    upsert_item(
        album(
            extra_ids=(("musicbrainz-release", "rel-1"), ("wikidata", "Q202996")),
            field_sources={"summary": "wikipedia", "cover_url": "coverartarchive"},
        )
    )

    item = Item.objects.get()
    assert item.media_type == MediaType.ALBUM
    assert item.combined_text == (
        "OK Computer\nBy: Radiohead\nTags: alt rock, art rock\n\nThe third studio album."
    )
    assert item.provenance["title"]["source"] == "musicbrainz"
    assert item.provenance["summary"]["source"] == "wikipedia"
    assert item.provenance["cover_url"]["source"] == "coverartarchive"
    assert sorted(item.external_ids.values_list("source", "external_id")) == [
        ("musicbrainz", "rg-1"),
        ("musicbrainz-release", "rel-1"),
        ("wikidata", "Q202996"),
    ]
    assert Score.objects.count() == 0


def test_re_ingesting_an_album_through_a_release_id_finds_the_same_item() -> None:
    upsert_item(album(extra_ids=(("musicbrainz-release", "rel-1"),)))

    outcome = upsert_item(album(extra_ids=(("musicbrainz-release", "rel-1"),)))

    assert outcome == "unchanged"
    assert Item.objects.count() == 1
    assert ExternalId.objects.count() == 2


def test_an_extra_id_that_belongs_to_another_item_is_left_alone() -> None:
    upsert_item(album("rg-1", extra_ids=(("wikidata", "Q1"),)))

    upsert_item(album("rg-2", title="Another", extra_ids=(("wikidata", "Q1"),)))

    assert Item.objects.count() == 2
    assert ExternalId.objects.get(source="wikidata", external_id="Q1").item.title == "OK Computer"


def test_the_same_id_from_different_sources_is_two_items() -> None:
    upsert_item(make_item_record("7", source="igdb", title="From IGDB"))
    upsert_item(make_item_record("7", source="other", title="From elsewhere"))

    assert Item.objects.count() == 2


def test_unchanged_data_keeps_the_embedding_and_changed_text_clears_it() -> None:
    upsert_item(make_item_record("1"))
    item = Item.objects.get()
    item.set_embedding([0.5] * 768, "test-model")
    item.save()

    assert upsert_item(make_item_record("1")) == "unchanged"
    item.refresh_from_db()
    assert item.embedding is not None

    assert upsert_item(make_item_record("1", summary="A different summary.")) == "updated"
    item.refresh_from_db()
    assert item.embedding is None


def test_a_removed_score_is_deleted() -> None:
    upsert_item(make_item_record("1"))
    assert Score.objects.count() == 1

    upsert_item(make_item_record("1", score=None))

    assert Score.objects.count() == 0


def test_a_new_score_value_replaces_the_old_one() -> None:
    upsert_item(make_item_record("1", score=ScoreRecord("igdb", 70.0, 10)))
    upsert_item(make_item_record("1", score=ScoreRecord("igdb", 90.0, 25)))

    score = Score.objects.get()
    assert (score.value, score.vote_count) == (90.0, 25)


@pytest.mark.parametrize(
    ("media_type", "overrides", "expected"),
    [
        ("film", {}, True),
        ("game", {}, True),
        ("game", {"summary": ""}, False),
        ("game", {"genres": (), "keywords": ()}, False),
        ("game", {"genres": (), "keywords": ("open world",)}, True),
        ("album", {"summary": "", "genres": (), "keywords": ("rock",)}, True),
        ("album", {"summary": "Has one.", "genres": ("Rock",), "keywords": ()}, False),
        ("album", {"summary": "", "genres": (), "keywords": ()}, False),
    ],
)
def test_minimum_metadata_depends_on_the_media_type(
    media_type: str, overrides: dict[str, object], expected: bool
) -> None:
    record = make_item_record("1", media_type=media_type, **overrides)

    assert record.is_embeddable is expected


def test_ingest_items_splits_the_limit_and_pulls_no_extra_records() -> None:
    source = FakeItemSource(
        popular=[make_item_record(str(i)) for i in range(1, 21)],
        mid_tail=[make_item_record(str(i)) for i in range(101, 111)],
    )

    stats = ingest_items(source, limit=10, mid_tail_percent=20)

    assert stats.created == 10
    assert source.popular_pulled == 8
    assert source.mid_tail_pulled == 2


def test_ingest_items_skips_thin_records_without_counting_them() -> None:
    source = FakeItemSource(
        popular=[
            make_item_record("1", summary=""),
            make_item_record("2", genres=(), keywords=()),
            make_item_record("3"),
        ]
    )

    stats = ingest_items(source, limit=1, mid_tail_percent=0)

    assert stats.skipped_not_embeddable == 2
    assert stats.created == 1
    assert Item.objects.get().title == "Game 3"


def test_ingest_items_dedupes_by_source_and_id_together() -> None:
    source = FakeItemSource(
        popular=[
            make_item_record("1"),
            make_item_record("1"),
            make_item_record("1", source="other"),
        ],
    )

    stats = ingest_items(source, limit=10, mid_tail_percent=0)

    assert stats.created == 2


def test_film_wrapper_stores_exactly_what_the_generic_path_stores() -> None:
    record = make_record(5, release_year=None, vote_average=None, vote_count=None)

    def snapshot() -> dict[str, object]:
        item = Item.objects.get()
        return {
            "media_type": item.media_type,
            "title": item.title,
            "release_year": item.release_year,
            "cover_url": item.cover_url,
            "summary": item.summary,
            "details": item.details,
            "combined_text": item.combined_text,
            "content_hash": item.content_hash,
            "provenance": item.provenance,
            "external_ids": sorted(item.external_ids.values_list("source", "external_id")),
            "scores": sorted(item.scores.values_list("source", "value", "vote_count")),
        }

    upsert_film(record)
    via_wrapper = snapshot()
    Item.objects.all().delete()
    upsert_item(record.to_item_record("tmdb"))

    assert snapshot() == via_wrapper
    assert via_wrapper["external_ids"] == [("tmdb", "5")]


def test_a_film_record_maps_to_the_generic_record() -> None:
    record = make_record(9, title="Heat", vote_average=8.1, vote_count=300)

    item = record.to_item_record("tmdb")

    assert (item.media_type, item.source, item.source_id) == ("film", "tmdb", "9")
    assert item.summary == "Overview of film 9."
    assert item.score == ScoreRecord("tmdb", 8.1, 300)
    assert item.details == {
        "original_title": "Film 9",
        "original_language": "en",
        "runtime": 100,
        "tagline": "",
        "genres": ["Drama"],
        "keywords": ["rain"],
    }
    assert item.is_embeddable is True


def test_a_source_that_wants_to_know_is_told_how_many_each_stream_needs() -> None:
    told: list[int] = []

    class Wanting(FakeItemSource):
        def set_target(self, count: int) -> None:
            told.append(count)

    source = Wanting(
        popular=[make_item_record(str(i)) for i in range(1, 30)],
        mid_tail=[make_item_record(str(i)) for i in range(101, 130)],
    )

    ingest_items(source, limit=20, mid_tail_percent=10)

    assert told == [18, 2]  # popular first, then the mid-tail slice


def test_a_source_without_targets_is_unaffected() -> None:
    source = FakeItemSource(popular=[make_item_record(str(i)) for i in range(1, 6)])

    stats = ingest_items(source, limit=5, mid_tail_percent=0)

    assert stats.created == 5
