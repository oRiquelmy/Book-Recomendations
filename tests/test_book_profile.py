from book_profile import extract_book_profile
from models import BookResponse


def make_book(title: str, categories: list[str] | None = None) -> BookResponse:
    return BookResponse(
        id=title,
        title=title,
        authors=["Example Author"],
        categories=categories or [],
        page_count=None,
        published_year=None,
        description="",
        thumbnail=None,
        language="en",
    )


def test_theme_matching_uses_words_not_substrings() -> None:
    assert "history" not in extract_book_profile(make_book("A General Introduction")).themes
    assert "family" not in extract_book_profile(make_book("Pure Reason")).themes
    assert "war" not in extract_book_profile(make_book("Forward Motion")).themes


def test_accented_portuguese_science_fiction_is_detected() -> None:
    profile = extract_book_profile(make_book("Ficção científica"))
    assert "science_fiction" in profile.themes
    assert "genre_fiction" in profile.category_kinds
