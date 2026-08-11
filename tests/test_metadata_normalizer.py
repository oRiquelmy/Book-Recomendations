from metadata_normalizer import (
    canonicalize_title,
    categories_match,
    normalize_person_name,
    normalize_text,
)


def test_normalize_text_removes_diacritics_and_punctuation() -> None:
    assert normalize_text("  Ficção—Científica! ") == "ficcao cientifica"


def test_author_initials_are_normalized_consistently() -> None:
    assert normalize_person_name("J. R. R. Tolkien") == normalize_person_name("J.R.R. Tolkien")


def test_canonical_title_preserves_legitimate_punctuation() -> None:
    assert canonicalize_title("Catch-22") == "catch 22"
    assert canonicalize_title("Spider-Man: Blue") == "spider man blue"


def test_canonical_title_removes_explicit_edition_markers_only() -> None:
    assert canonicalize_title("Dune: Deluxe Edition") == "dune"
    assert canonicalize_title("Dune (Special Edition)") == "dune"


def test_category_aliases_match_portuguese_and_english() -> None:
    assert categories_match("fantasia sombria", ["Fantasy"])
    assert categories_match("ficção científica", ["Science Fiction"])
