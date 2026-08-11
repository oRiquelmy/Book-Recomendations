from filters import filter_books, score_books
from models import BookResponse


def make_book(**overrides) -> BookResponse:
    data = {
        "id": "book",
        "title": "Example",
        "authors": ["J. R. R. Tolkien"],
        "categories": ["Fantasy"],
        "page_count": 300,
        "published_year": 2000,
        "description": "A magical journey through an ancient kingdom.",
        "thumbnail": None,
        "language": "en",
    }
    data.update(overrides)
    return BookResponse(**data)


def test_numeric_filters_exclude_unknown_metadata_by_default() -> None:
    unknown = make_book(page_count=None, published_year=None)
    result = filter_books(
        [unknown],
        {"min_pages": 200, "max_pages": 400, "min_year": 1990, "max_year": 2010},
    )
    assert result == []


def test_unknown_metadata_can_be_kept_explicitly() -> None:
    unknown = make_book(page_count=None, published_year=None)
    result = filter_books(
        [unknown],
        {
            "min_pages": 200,
            "max_pages": 400,
            "min_year": 1990,
            "max_year": 2010,
            "include_unknown_metadata": True,
        },
    )
    assert result == [unknown]


def test_author_exclusion_normalizes_initials() -> None:
    candidate = make_book(authors=["J.R.R. Tolkien"])
    result = filter_books(
        [candidate],
        {"exclude_same_author": True, "reference_authors": ["J. R. R. Tolkien"]},
    )
    assert result == []


def test_category_filter_uses_aliases() -> None:
    candidate = make_book(categories=["Fantasy"])
    assert filter_books([candidate], {"category": "fantasia sombria"}) == [candidate]


def test_score_is_clamped_to_normalized_range() -> None:
    reference = make_book(id="reference")
    identical = make_book(id="candidate")
    scored = score_books([identical], reference)
    assert 0.0 <= scored[0].score <= 1.0


def test_same_title_by_different_author_is_not_removed_as_reference() -> None:
    candidate = make_book(title="Home", authors=["Marilynne Robinson"])
    result = filter_books(
        [candidate],
        {"exclude_title": "Home", "reference_authors": ["Toni Morrison"]},
    )
    assert result == [candidate]


def test_cross_language_category_alias_contributes_to_score() -> None:
    reference = make_book(id="reference", categories=["Ficção científica"])
    candidate = make_book(id="candidate", categories=["Science Fiction"])
    score = score_books([candidate], reference)[0].score
    unrelated = make_book(id="unrelated", categories=["Cooking"])
    unrelated_score = score_books([unrelated], reference)[0].score
    assert score > unrelated_score


def test_calibrated_score_separates_strong_and_unrelated_recommendations() -> None:
    reference = make_book(
        id="dune",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction", "Space Opera", "Dystopian Fiction"],
        page_count=412,
        published_year=1965,
        description=(
            "On a desert planet, political intrigue, ecology, religion and a struggle "
            "for power shape the destiny of a young heir."
        ),
    )
    strong = make_book(
        id="left-hand",
        title="The Left Hand of Darkness",
        authors=["Ursula K. Le Guin"],
        categories=["Science Fiction", "Space Opera"],
        page_count=304,
        published_year=1969,
        description="An envoy reaches an alien world and confronts politics, identity and society.",
    )
    unrelated = make_book(
        id="business",
        title="Good to Great",
        authors=["Jim Collins"],
        categories=["Business", "Management"],
        page_count=320,
        published_year=2001,
        description="Research on companies, leadership and management performance.",
    )

    scores = {book.id: book.score for book in score_books([strong, unrelated], reference)}
    assert scores["left-hand"] >= 0.70
    assert scores["business"] < 0.34


def test_sparse_but_semantically_close_book_is_not_punished_as_missing_metadata() -> None:
    reference = make_book(
        id="reference",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction", "Space Opera"],
        page_count=412,
        published_year=1965,
        description="A political and ecological struggle on a desert planet.",
    )
    sparse = make_book(
        id="sparse",
        title="Children of Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction"],
        page_count=None,
        published_year=None,
        description="",
    )

    score = score_books([sparse], reference)[0].score
    assert score >= 0.60


def test_score_exposes_component_breakdown_and_metadata_coverage() -> None:
    reference = make_book(id="reference", categories=["Science Fiction"])
    candidate = make_book(id="candidate", categories=["Space Opera"])

    scored = score_books([candidate], reference)[0]
    assert scored.score_components["taxonomy"] >= 0.80
    assert 0.0 < scored.score_coverage <= 1.0


def test_generic_fiction_alone_stays_below_recommendation_cutoff() -> None:
    reference = make_book(
        id="reference",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction", "Space Opera"],
        page_count=412,
        published_year=1965,
        description="A political and ecological struggle on a desert planet.",
    )
    generic = make_book(
        id="generic",
        title="An Unrelated Novel",
        authors=["Another Author"],
        categories=["Fiction"],
        page_count=410,
        published_year=1966,
        description="A domestic story about an ordinary family in a small town.",
    )

    score = score_books([generic], reference)[0].score
    assert score < 0.34


def test_shared_nonfiction_umbrella_does_not_make_topics_recommendable() -> None:
    reference = make_book(
        id="business",
        title="Business Strategy",
        authors=["Author One"],
        categories=["Business"],
        page_count=300,
        published_year=2000,
        description="Leadership, companies, management and competitive strategy.",
    )
    candidate = make_book(
        id="cookbook",
        title="Home Cooking",
        authors=["Author Two"],
        categories=["Cooking"],
        page_count=300,
        published_year=2000,
        description="Recipes, ingredients and kitchen techniques for home cooks.",
    )

    scored = score_books([candidate], reference)[0]
    assert scored.score < 0.34
    assert scored.score_components["taxonomy"] <= 0.12


def test_raw_general_category_is_weak_evidence() -> None:
    reference = make_book(
        id="reference",
        title="First Book",
        authors=["Author One"],
        categories=["General"],
        description="A first unrelated description.",
    )
    candidate = make_book(
        id="candidate",
        title="Second Book",
        authors=["Author Two"],
        categories=["General"],
        description="A completely different subject and vocabulary.",
    )

    scored = score_books([candidate], reference)[0]
    assert scored.score_components["taxonomy"] == 0.18
    assert scored.score < 0.34


def test_calibration_orders_same_series_subgenre_adjacent_and_unrelated() -> None:
    reference = make_book(
        id="reference",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction", "Space Opera"],
        page_count=412,
        published_year=1965,
        description=(
            "A political and ecological struggle on a desert planet involving "
            "religion, empire and a young heir."
        ),
    )
    candidates = [
        make_book(
            id="same-series",
            title="Dune Messiah",
            authors=["Frank Herbert"],
            categories=["Science Fiction", "Space Opera"],
            page_count=256,
            published_year=1969,
            description=(
                "Political intrigue, religion, empire and the consequences of power "
                "on a desert world."
            ),
        ),
        make_book(
            id="same-subgenre",
            title="Foundation",
            authors=["Isaac Asimov"],
            categories=["Science Fiction", "Space Opera"],
            page_count=255,
            published_year=1951,
            description=(
                "A galactic empire collapses while scientists preserve civilization "
                "through history and politics."
            ),
        ),
        make_book(
            id="adjacent",
            title="The Fifth Season",
            authors=["N. K. Jemisin"],
            categories=["Fantasy", "Science Fiction"],
            page_count=468,
            published_year=2015,
            description=(
                "A world of catastrophic ecology, oppression and power follows a "
                "woman across a broken continent."
            ),
        ),
        make_book(
            id="unrelated",
            title="Good to Great",
            authors=["Jim Collins"],
            categories=["Business"],
            page_count=320,
            published_year=2001,
            description="Research on management, leadership and successful companies.",
        ),
    ]

    scored = score_books(candidates, reference)
    scores = {book.id: book.score for book in scored}

    assert scores["same-series"] > scores["same-subgenre"] > scores["adjacent"]
    assert scores["adjacent"] >= 0.55
    assert scores["unrelated"] < 0.34
