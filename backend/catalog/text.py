import hashlib
import re
from collections.abc import Iterable

_WHITESPACE = re.compile(r"\s+")


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _unique_clean(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def build_combined_text(
    title: str,
    genres: Iterable[str],
    keywords: Iterable[str],
    summary: str,
) -> str:
    """One text per item: title, genres/tags, then summary. Ratings are never included.

    Source text is untrusted, so whitespace (including newlines) is collapsed inside every part.
    That keeps a summary from imitating the "Genres:" / "Keywords:" structure lines.
    """
    lines = [_clean(title)]
    genre_list = _unique_clean(genres)
    if genre_list:
        lines.append("Genres: " + ", ".join(genre_list))
    keyword_list = _unique_clean(keywords)
    if keyword_list:
        lines.append("Keywords: " + ", ".join(keyword_list))
    text = "\n".join(lines)
    summary_clean = _clean(summary)
    if summary_clean:
        text += "\n\n" + summary_clean
    return text


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
