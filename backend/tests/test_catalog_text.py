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
