"""Turning a stored Item into what the detail page needs (SPEC section 8).

Only a curated, per-type slice of the raw provider data in `Item.details` is exposed: that JSON
blob also carries internal plumbing (MusicBrainz release ids, and similar) that is not meant for
API consumers and may change shape as sources evolve.
"""

from catalog.models import Item, MediaType


def _film_details(details: dict) -> dict[str, object]:
    return {
        "genres": list(details.get("genres") or []),
        "keywords": list(details.get("keywords") or []),
        "tagline": details.get("tagline") or "",
        "runtime": details.get("runtime"),
    }


def _game_details(details: dict) -> dict[str, object]:
    return {
        "genres": list(details.get("genres") or []),
        "themes": list(details.get("themes") or []),
        "keywords": list(details.get("keywords") or []),
    }


def _wikipedia_credit(details: dict) -> dict[str, str] | None:
    wikipedia = details.get("wikipedia")
    if not isinstance(wikipedia, dict):
        return None
    title, url = wikipedia.get("title"), wikipedia.get("url")
    return {"title": title, "url": url} if title and url else None


def _album_details(details: dict) -> dict[str, object]:
    return {
        "artist": details.get("artist") or "",
        "tags": list(details.get("tags") or []),
        # CC BY-SA requires attribution per use, not just once in the footer. None means the
        # album has no Wikipedia article; the page shows "No summary available for this album."
        "wikipedia": _wikipedia_credit(details),
    }


_BUILDERS = {
    MediaType.FILM: _film_details,
    MediaType.GAME: _game_details,
    MediaType.ALBUM: _album_details,
}


def item_details(item: Item) -> dict[str, object]:
    """Type-specific metadata, picked from the raw provider data stored on the item."""
    builder = _BUILDERS.get(item.media_type)
    return builder(item.details) if builder else {}


def item_scores(item: Item) -> list[dict[str, object]]:
    """Display-only scores (SPEC sections 4 and 7.4): never used for ranking. Albums have none, so
    this is naturally empty for them without any special-casing."""
    return [
        {"source": score.source, "value": score.value, "vote_count": score.vote_count}
        for score in item.scores.all()
    ]


def item_detail(item: Item) -> dict[str, object]:
    return {
        "id": item.id,
        "media_type": item.media_type,
        "title": item.title,
        "release_year": item.release_year,
        "cover_url": item.cover_url,
        "summary": item.summary,
        "details": item_details(item),
        "scores": item_scores(item),
    }
