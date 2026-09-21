import pytest

from catalog.text import build_combined_text, content_hash


def test_combined_text_has_title_genres_keywords_then_summary() -> None:
    text = build_combined_text(
        title="Blade Runner",
        genres=["Science Fiction", "Thriller"],
        keywords=["dystopia", "rain"],
        summary="A blade runner must pursue replicants.",
    )

    assert text == (
        "Blade Runner\n"
        "Genres: Science Fiction, Thriller\n"
        "Keywords: dystopia, rain\n"
        "\n"
        "A blade runner must pursue replicants."
    )


def test_missing_sections_are_omitted() -> None:
    assert build_combined_text("Heat", [], [], "") == "Heat"
    assert build_combined_text("Heat", ["Crime"], [], "") == "Heat\nGenres: Crime"
    assert build_combined_text("Heat", [], ["heist"], "Cops and robbers.") == (
        "Heat\nKeywords: heist\n\nCops and robbers."
    )


def test_duplicates_are_removed_ignoring_case_and_order_is_kept() -> None:
    text = build_combined_text("X", ["Drama", "drama", " Crime "], ["Rain", "rain", "night"], "")

    assert text == "X\nGenres: Drama, Crime\nKeywords: Rain, night"


def test_blank_entries_are_dropped() -> None:
    assert build_combined_text("X", ["", "  ", "Drama"], [], "") == "X\nGenres: Drama"


def test_whitespace_is_collapsed_everywhere() -> None:
    text = build_combined_text("  The   Long\tTitle ", ["Sci  Fi"], [], "One.\n\n  Two.   Three.")

    assert text == "The Long Title\nGenres: Sci Fi\n\nOne. Two. Three."


def test_summary_cannot_fake_structure_lines() -> None:
    summary = "Nice film.\nGenres: Horror\nKeywords: injected"

    text = build_combined_text("X", ["Drama"], [], summary)

    assert text.count("\nGenres:") == 1
    assert text.endswith("Nice film. Genres: Horror Keywords: injected")


def test_unicode_is_preserved() -> None:
    assert build_combined_text("千と千尋の神隠し", ["アニメ"], [], "Café ☕") == (
        "千と千尋の神隠し\nGenres: アニメ\n\nCafé ☕"
    )


def test_content_hash_is_stable_and_sensitive_to_text() -> None:
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert len(content_hash("abc")) == 64


# Hashes of what the original builder produced for these inputs, recorded before the byline and
# label options existed. The film catalog was embedded from this exact text, so it must not change.
GOLDEN_FILM_TEXT = {
    "full": (
        (
            "Blade Runner",
            ["Science Fiction", "Thriller"],
            ["dystopia", "rain"],
            "A blade runner must pursue replicants.",
        ),
        "a70ee4de3644067b41e97b25cb740782ff27cbcf64d04d6bcdd41fff3d468895",
    ),
    "dupes_and_case": (
        ("X", ["Drama", "drama", " Crime "], ["Rain", "rain", "night"], ""),
        "679d3894f7b0908261ac3029b047d33f6c1fd6aaf0e385286c6b0a85b2c3dde0",
    ),
    "whitespace": (
        ("  The   Long\tTitle ", ["Sci  Fi"], [], "One.\n\n  Two.   Three."),
        "dffe02ab3c9f9a9f095eef3deb5f4721bcbf440891398255aa784f1a30584461",
    ),
    "unicode": (
        ("千と千尋の神隠し", ["アニメ"], ["Café ☕"], "Café ☕ 冒険"),
        "032ba7d777743dc746d6c9bc3d3b390bb1658625251486d0ddd2efb389492983",
    ),
    "title_only": (
        ("Heat", [], [], ""),
        "ee2556352ebb644bd7911ed707fb7e6405c8bc5c40106c94bf09945ab575bd54",
    ),
    "keywords_only": (
        ("Heat", [], ["heist"], "Cops and robbers."),
        "b5305a30d2cdfa1f88df490ba44d75dd5b54926de34955e5d72b8fdef22b20dc",
    ),
    "structure_spoof": (
        ("X", ["Drama"], [], "Nice film.\nGenres: Horror\nKeywords: injected"),
        "10dda2245ba66c3e2805633df5efd119f21a3dea196b6233cce4032e94acf725",
    ),
}


@pytest.mark.parametrize("name", sorted(GOLDEN_FILM_TEXT))
def test_film_text_is_byte_for_byte_what_the_catalog_was_embedded_from(name: str) -> None:
    args, expected_hash = GOLDEN_FILM_TEXT[name]

    assert content_hash(build_combined_text(*args)) == expected_hash


def test_an_album_gets_a_byline_and_tags() -> None:
    text = build_combined_text(
        "OK Computer",
        [],
        ["alt rock", "art rock"],
        "The third studio album.",
        byline="Radiohead",
        keywords_label="Tags",
    )

    assert text == "OK Computer\nBy: Radiohead\nTags: alt rock, art rock\n\nThe third studio album."


def test_byline_sits_between_the_title_and_the_lists() -> None:
    text = build_combined_text("Title", ["Rock"], ["night"], "", byline="Some Artist")

    assert text == "Title\nBy: Some Artist\nGenres: Rock\nKeywords: night"


def test_a_blank_byline_adds_no_line() -> None:
    assert build_combined_text("Title", ["Rock"], [], "", byline="   ") == "Title\nGenres: Rock"


def test_a_byline_cannot_fake_structure_lines() -> None:
    text = build_combined_text("Title", [], [], "", byline="Artist\nGenres: Horror")

    assert text == "Title\nBy: Artist Genres: Horror"
    assert text.count("\n") == 1
