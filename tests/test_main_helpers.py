import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

import main
from models import BookResponse


def make_book(**overrides) -> BookResponse:
    data = {
        "id": "book",
        "title": "Sparse Reference",
        "authors": ["Example Author"],
        "categories": [],
        "page_count": None,
        "published_year": None,
        "description": "A journey through memory and identity.",
        "thumbnail": None,
        "language": "en",
    }
    data.update(overrides)
    return BookResponse(**data)


def test_open_library_parser_keeps_work_edition_isbn_and_description() -> None:
    book = main.parse_open_library_doc(
        {
            "key": "/works/OL1W",
            "edition_key": ["OL2M"],
            "title": "Example",
            "author_name": ["Author"],
            "isbn": ["978-0-306-40615-7"],
            "first_sentence": ["A useful description."],
        }
    )
    assert book is not None
    assert book.provider == "open_library"
    assert book.work_id == "/works/OL1W"
    assert book.edition_id == "/books/OL2M"
    assert book.isbn_13 == ["9780306406157"]
    assert book.description == "A useful description."


def test_google_parser_keeps_provider_edition_and_isbn() -> None:
    book = main.parse_book(
        {
            "id": "google-volume",
            "volumeInfo": {
                "title": "Example",
                "authors": ["Author"],
                "publishedDate": "2001-05-10",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "978-0-306-40615-7"}
                ],
            },
        }
    )
    assert book is not None
    assert book.provider == "google_books"
    assert book.edition_id == "google-volume"
    assert book.published_year == 2001
    assert book.isbn_13 == ["9780306406157"]


def test_search_terms_have_metadata_fallback() -> None:
    terms = main.build_search_terms(None, make_book(), None, [])
    assert terms
    assert any(term in {"adventure", "identity", "memory", "journey"} for term in terms)


def test_deduplication_prefers_strong_identifiers_across_providers() -> None:
    google = make_book(
        id="google",
        provider="google_books",
        edition_id="google",
        isbn_13=["9780306406157"],
    )
    open_library = make_book(
        id="/works/OL1W",
        provider="open_library",
        work_id="/works/OL1W",
        isbn_13=["9780306406157"],
    )
    assert len(main.dedupe_books([google, open_library])) == 1


def test_author_only_recommendation_is_rejected_explicitly() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.recommend_books(q=None, author="Clarice Lispector", reference_id=None))
    assert error.value.status_code == 422
    assert "busca por autor" in str(error.value.detail).casefold()


def test_google_fetch_paginates_with_start_index(monkeypatch) -> None:
    calls: list[int] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, items: list[dict]) -> None:
            self._items = items

        def json(self) -> dict:
            return {"items": self._items}

    class FakeClient:
        async def get(self, _url: str, params: dict) -> FakeResponse:
            start_index = int(params["startIndex"])
            page_size = int(params["maxResults"])
            calls.append(start_index)
            items = [{"id": str(index)} for index in range(start_index, start_index + page_size)]
            return FakeResponse(items)

    @asynccontextmanager
    async def fake_client(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr(main, "_build_async_client", fake_client)
    main._CACHE.clear()
    main._google_unavailable_until = 0.0

    items = asyncio.run(main.fetch_google_books("pagination-test", max_results=45))
    assert len(items) == 45
    assert calls == [0, 40]


def test_book_search_builds_isbn_query_before_title_queries() -> None:
    assert main.build_book_search_queries("978-0-306-40615-7") == ["isbn:9780306406157"]


def test_book_search_penalizes_study_guides_and_prefers_exact_author() -> None:
    original = make_book(
        id="original",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction"],
        description="A desert planet and a struggle for power.",
    )
    study_guide = make_book(
        id="guide",
        title="Dune Study Guide and Workbook",
        authors=["Other Author"],
        categories=["Study Aids"],
        description="Questions and summaries for students.",
    )

    original_score = main._book_search_score(original, "Dune", "Frank Herbert")
    guide_score = main._book_search_score(study_guide, "Dune", "Frank Herbert")
    assert original_score > guide_score


def test_book_search_combines_google_and_open_library(monkeypatch) -> None:
    calls: list[str] = []
    google = make_book(
        id="google",
        provider="google_books",
        title="Dune",
        authors=["Frank Herbert"],
        categories=["Science Fiction"],
    )
    open_library = make_book(
        id="/works/OL1W",
        provider="open_library",
        work_id="/works/OL1W",
        title="Dune Messiah",
        authors=["Frank Herbert"],
        categories=["Science Fiction"],
    )

    async def fake_google(*_args, **_kwargs):
        calls.append("google")
        return [google]

    async def fake_open_library(*_args, **_kwargs):
        calls.append("open_library")
        return [open_library]

    async def passthrough(books):
        return books

    monkeypatch.setattr(main, "_search_google_book_candidates", fake_google)
    monkeypatch.setattr(main, "_search_open_library_book_candidates", fake_open_library)
    monkeypatch.setattr(main, "enrich_books_thumbnails", passthrough)

    books = asyncio.run(
        main.search_books(q="Dune", author="Frank Herbert", max_results=10, offset=0)
    )
    assert calls == ["google", "open_library"]
    assert [book.id for book in books] == ["google", "/works/OL1W"]


def test_deduplication_merges_complementary_provider_metadata() -> None:
    google = make_book(
        id="google",
        provider="google_books",
        edition_id="google",
        isbn_13=["9780306406157"],
        categories=["Science Fiction"],
        description="Short description.",
        thumbnail=None,
        page_count=None,
    )
    open_library = make_book(
        id="/works/OL1W",
        provider="open_library",
        work_id="/works/OL1W",
        edition_id="/books/OL2M",
        isbn_13=["9780306406157"],
        categories=["Space Opera"],
        description="A longer and more useful description from the second provider.",
        thumbnail="https://example.test/cover.jpg",
        page_count=412,
    )

    merged = main.dedupe_books([google, open_library])
    assert len(merged) == 1
    assert merged[0].id == "google"
    assert merged[0].work_id == "/works/OL1W"
    assert merged[0].page_count == 412
    assert merged[0].categories == ["Science Fiction", "Space Opera"]
    assert merged[0].description == open_library.description
    assert merged[0].thumbnail == open_library.thumbnail


def test_candidate_language_is_only_restricted_when_user_requests_it(monkeypatch) -> None:
    google_languages: list[str | None] = []
    open_library_languages: list[str | None] = []

    async def fake_google(_query, max_results=20, start_index=0, language=None):
        del max_results, start_index
        google_languages.append(language)
        return []

    async def fake_open_library(_subject, author=None, language=None, max_results=20):
        del author, max_results
        open_library_languages.append(language)
        return []

    monkeypatch.setattr(main, "fetch_google_books", fake_google)
    monkeypatch.setattr(main, "fetch_open_library_books_by_subject", fake_open_library)

    asyncio.run(main.fetch_candidate_books(["science fiction"], language=None))
    asyncio.run(main.fetch_candidate_books(["science fiction"], language="pt"))
    asyncio.run(main.fetch_open_library_candidates(["science fiction"], language=None))
    asyncio.run(main.fetch_open_library_candidates(["science fiction"], language="pt"))

    assert google_languages == [None, None, "pt", "pt"]
    assert open_library_languages == [None, "pt"]


def test_open_library_uses_two_letter_language_as_result_preference(monkeypatch) -> None:
    captured: list[dict] = []

    async def fake_search(params: dict):
        captured.append(params)
        return []

    monkeypatch.setattr(main, "fetch_open_library_search", fake_search)
    asyncio.run(
        main.fetch_open_library_books_by_subject(
            "science fiction",
            language="por",
            max_results=5,
        )
    )

    assert captured[0]["lang"] == "pt"
    assert "language" not in captured[0]


def test_open_library_isbn_search_uses_isbn_field(monkeypatch) -> None:
    captured: dict = {}

    async def fake_search(params: dict) -> list[dict]:
        captured.update(params)
        return []

    monkeypatch.setattr(main, "fetch_open_library_search", fake_search)
    books = asyncio.run(
        main.fetch_open_library_books_by_isbn(
            "978-0-306-40615-7",
            max_results=7,
            offset=3,
        )
    )

    assert books == []
    assert captured["isbn"] == "9780306406157"
    assert captured["limit"] == 7
    assert captured["offset"] == 3


def test_interleave_book_batches_preserves_query_diversity() -> None:
    first = [make_book(id=f"first-{index}") for index in range(3)]
    second = [make_book(id=f"second-{index}") for index in range(2)]
    third = [make_book(id="third-0")]

    interleaved = main.interleave_book_batches([first, second, third])

    assert [book.id for book in interleaved] == [
        "first-0",
        "second-0",
        "third-0",
        "first-1",
        "second-1",
        "first-2",
    ]
