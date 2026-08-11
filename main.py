import asyncio
import json
import os
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from itertools import zip_longest
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from book_profile import extract_book_profile
from filters import filter_books, score_books
from metadata_normalizer import (
    canonicalize_title,
    clean_description,
    has_text,
    normalize_book_signature,
    normalize_categories,
    normalize_isbn,
    normalize_language_code,
    normalize_person_name,
    normalize_text,
)
from models import AuthorResponse, BookResponse, RecommendationResponse
from taxonomy import taxonomy_search_terms

_HTTP_CLIENT: Optional[httpx.AsyncClient] = None


async def _get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            verify=HTTP_SSL_VERIFY,
            headers={"User-Agent": "Book-it/0.3 (book discovery application)"},
        )
    return _HTTP_CLIENT


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await _get_http_client()
    try:
        yield
    finally:
        global _HTTP_CLIENT
        if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
            await _HTTP_CLIENT.aclose()
        _HTTP_CLIENT = None


app = FastAPI(
    title="Book-it API",
    description="Busca de livros, autores e recomendações via Google Books e Open Library",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_SEARCH_API = "https://openlibrary.org/search.json"
OPEN_LIBRARY_AUTHOR_SEARCH_API = "https://openlibrary.org/search/authors.json"
OPEN_LIBRARY_BOOK_FIELDS = (
    "key,title,author_name,author_key,first_publish_year,cover_i,isbn,edition_key,"
    "subject,language,number_of_pages_median,first_sentence"
)
API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
CACHE_TTL_SECONDS = int(os.getenv("BOOKIT_CACHE_TTL_SECONDS", "21600"))
CACHE_MAX_ITEMS = int(os.getenv("BOOKIT_CACHE_MAX_ITEMS", "512"))
GOOGLE_COOLDOWN_SECONDS = int(os.getenv("BOOKIT_GOOGLE_COOLDOWN_SECONDS", "900"))
MIN_RECOMMENDATION_SCORE = float(os.getenv("BOOKIT_MIN_RECOMMENDATION_SCORE", "0.34"))
MAX_SEARCH_TERMS = int(os.getenv("BOOKIT_MAX_SEARCH_TERMS", "6"))
COVER_FETCH_TIMEOUT_SECONDS = float(os.getenv("BOOKIT_COVER_FETCH_TIMEOUT_SECONDS", "8"))
MAX_CONCURRENT_COVER_TASKS = int(os.getenv("BOOKIT_MAX_CONCURRENT_COVER_TASKS", "4"))
MAX_CONCURRENT_PROVIDER_CALLS = int(os.getenv("BOOKIT_MAX_CONCURRENT_PROVIDER_CALLS", "6"))
HTTP_SSL_VERIFY = os.getenv("BOOKIT_HTTP_SSL_VERIFY", "true").strip().lower() not in {"0", "false", "no", "off"}
GENERIC_SUBJECTS = {
    "fiction",
    "ficcao",
    "general",
    "literature",
    "novel",
    "book",
    "books",
}

_SEARCH_NOISE_TERMS = {
    "analysis",
    "companion",
    "journal",
    "notebook",
    "quiz",
    "summary",
    "study guide",
    "teacher guide",
    "unofficial",
    "workbook",
}


class GoogleBooksUnavailable(Exception):
    pass


_google_unavailable_until = 0.0
_CACHE: "OrderedDict[str, tuple[float, object]]" = OrderedDict()
_COVER_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_COVER_TASKS)
_PROVIDER_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_PROVIDER_CALLS)


@asynccontextmanager
async def _build_async_client(
    *,
    timeout: float,
    headers: Optional[dict] = None,
    follow_redirects: bool = False,
) -> AsyncIterator[httpx.AsyncClient]:
    # Mantém a assinatura usada pelos providers, mas reaproveita um único pool.
    # timeout/headers específicos são passados nas chamadas quando necessários.
    del timeout, headers, follow_redirects
    yield await _get_http_client()


def upgrade_thumbnail_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    normalized = url.replace("http://", "https://")
    if "covers.openlibrary.org" in normalized:
        return normalized.replace("-S.jpg", "-L.jpg").replace("-M.jpg", "-L.jpg")

    parts = urlsplit(normalized)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("edge", None)
    if "zoom" in query:
        query["zoom"] = "2"
    elif "books.google." in parts.netloc:
        query["zoom"] = "2"

    upgraded_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, upgraded_query, parts.fragment))


def build_open_library_cover_url(identifier_type: str, identifier: str) -> Optional[str]:
    cleaned_identifier = (identifier or "").strip()
    if not cleaned_identifier:
        return None

    return upgrade_thumbnail_url(
        f"https://covers.openlibrary.org/b/{identifier_type}/{cleaned_identifier}-L.jpg?default=false"
    )


def _google_thumbnail_candidates(volume_info: dict) -> list[str]:
    image_links = volume_info.get("imageLinks", {}) or {}
    ordered_keys = [
        "extraLarge",
        "large",
        "medium",
        "small",
        "thumbnail",
        "smallThumbnail",
    ]
    candidates: list[str] = []
    seen: set[str] = set()

    for key in ordered_keys:
        upgraded = upgrade_thumbnail_url(image_links.get(key))
        if upgraded and upgraded not in seen:
            seen.add(upgraded)
            candidates.append(upgraded)

    return candidates


def _cache_get(key: str):
    if CACHE_TTL_SECONDS <= 0:
        return None

    entry = _CACHE.get(key)
    if not entry:
        return None

    timestamp, value = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None

    _CACHE.move_to_end(key)
    return value


def _cache_set(key: str, value: object) -> None:
    if CACHE_TTL_SECONDS <= 0:
        return

    _CACHE[key] = (time.time(), value)
    _CACHE.move_to_end(key)

    if CACHE_MAX_ITEMS <= 0:
        return

    while len(_CACHE) > CACHE_MAX_ITEMS:
        _CACHE.popitem(last=False)


def _cache_key(prefix: str, params: dict) -> str:
    return f"{prefix}:{json.dumps(params, sort_keys=True, separators=(',', ':'))}"


def _google_books_available() -> bool:
    return time.time() >= _google_unavailable_until


def _mark_google_unavailable() -> None:
    global _google_unavailable_until
    _google_unavailable_until = time.time() + GOOGLE_COOLDOWN_SECONDS


def dedupe_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


async def fetch_google_books(
    query: str,
    max_results: int = 20,
    start_index: int = 0,
    language: Optional[str] = None,
) -> list[dict]:
    if not _google_books_available():
        raise GoogleBooksUnavailable("Google Books temporariamente indisponível")

    requested_results = max(1, max_results)
    normalized_language = normalize_language_code(language)
    cache_key = _cache_key(
        "google_books",
        {
            "q": query,
            "max": requested_results,
            "start": start_index,
            "language": normalized_language,
            "keyed": bool(API_KEY),
        },
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    collected: list[dict] = []
    current_index = max(0, start_index)

    while len(collected) < requested_results:
        page_size = min(40, requested_results - len(collected))
        params = {
            "q": query,
            "maxResults": page_size,
            "startIndex": current_index,
            "printType": "books",
        }
        if normalized_language:
            params["langRestrict"] = normalized_language
        if API_KEY:
            params["key"] = API_KEY

        try:
            async with _PROVIDER_SEMAPHORE:
                async with _build_async_client(timeout=10.0) as client:
                    response = await client.get(GOOGLE_BOOKS_API, params=params)
        except httpx.RequestError as exc:
            _mark_google_unavailable()
            raise GoogleBooksUnavailable(
                "Google Books temporariamente indisponível por falha de conexão"
            ) from exc

        if response.status_code in (403, 429):
            _mark_google_unavailable()
            raise GoogleBooksUnavailable("Google Books quota excedida")
        if response.status_code >= 500:
            _mark_google_unavailable()
            raise GoogleBooksUnavailable("Google Books temporariamente indisponível")
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Falha ao contatar Google Books API")

        page_items = response.json().get("items", [])
        collected.extend(page_items)
        if len(page_items) < page_size:
            break
        current_index += len(page_items)

    _cache_set(cache_key, collected)
    return collected


async def fetch_google_book_by_id(volume_id: str) -> Optional[dict]:
    if not _google_books_available():
        raise GoogleBooksUnavailable("Google Books temporariamente indisponível")

    params = {}
    if API_KEY:
        params["key"] = API_KEY

    cache_key = _cache_key("google_book_by_id", {"id": volume_id, "keyed": bool(API_KEY)})
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with _PROVIDER_SEMAPHORE:
            async with _build_async_client(timeout=10.0) as client:
                response = await client.get(f"{GOOGLE_BOOKS_API}/{volume_id}", params=params)
    except httpx.RequestError:
        _mark_google_unavailable()
        raise GoogleBooksUnavailable("Google Books temporariamente indisponivel por falha de conexao")

    if response.status_code in (403, 429):
        _mark_google_unavailable()
        raise GoogleBooksUnavailable("Google Books quota excedida")
    if response.status_code == 404:
        return None
    if response.status_code >= 500:
        _mark_google_unavailable()
        raise GoogleBooksUnavailable("Google Books temporariamente indisponível")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Falha ao consultar Google Books por id")

    item = response.json()
    _cache_set(cache_key, item)
    return item


async def fetch_open_library_search(params: dict) -> list[dict]:
    cache_key = _cache_key("open_library_search", params)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    headers = {"User-Agent": "Book-it/0.3 (Open Library search)"}
    try:
        async with _PROVIDER_SEMAPHORE:
            async with _build_async_client(timeout=10.0, headers=headers) as client:
                response = await client.get(OPEN_LIBRARY_SEARCH_API, params=params)
                response.raise_for_status()
    except httpx.HTTPError:
        return []

    docs = response.json().get("docs", [])
    _cache_set(cache_key, docs)
    return docs


async def fetch_open_library_authors(
    query: str,
    limit: int = 10,
    offset: int = 0,
) -> list[AuthorResponse]:
    params = {
        "q": query.strip(),
        "limit": limit,
        "offset": offset,
    }
    cache_key = _cache_key("open_library_authors", params)
    cached = _cache_get(cache_key)
    if cached is not None:
        return [AuthorResponse.model_validate(author) for author in cached]

    headers = {"User-Agent": "Book-it/0.3 (author search)"}
    try:
        async with _PROVIDER_SEMAPHORE:
            async with _build_async_client(timeout=10.0, headers=headers) as client:
                response = await client.get(OPEN_LIBRARY_AUTHOR_SEARCH_API, params=params)
                response.raise_for_status()
    except httpx.HTTPError:
        return []

    authors: list[AuthorResponse] = []
    for doc in response.json().get("docs", []):
        author_id = str(doc.get("key", "")).removeprefix("/authors/")
        name = str(doc.get("name") or "").strip()
        if not author_id or not name:
            continue

        alternate_names = doc.get("alternate_names") or []
        if isinstance(alternate_names, str):
            alternate_names = [alternate_names]
        top_subjects = doc.get("top_subjects") or []
        if isinstance(top_subjects, str):
            top_subjects = [top_subjects]
        birth_date = doc.get("birth_date")
        if isinstance(birth_date, list):
            birth_date = birth_date[0] if birth_date else None

        authors.append(
            AuthorResponse(
                id=author_id,
                name=name,
                alternate_names=[str(value) for value in alternate_names[:8]],
                birth_date=str(birth_date) if birth_date else None,
                top_work=str(doc.get("top_work")) if doc.get("top_work") else None,
                work_count=_safe_int(doc.get("work_count")),
                top_subjects=[str(value) for value in top_subjects[:8]],
            )
        )

    _cache_set(cache_key, [author.model_dump() for author in authors])
    return authors


def _open_library_key(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw or raw.startswith("/"):
        return raw
    suffix = raw[-1:].upper()
    collection = {"W": "works", "M": "books", "A": "authors"}.get(suffix)
    return f"/{collection}/{raw}" if collection else raw


def _extract_year(value: Optional[object]) -> Optional[int]:
    match = re.search(r"\b(1[0-9]{3}|20[0-9]{2}|2100)\b", str(value or ""))
    return int(match.group(1)) if match else None


def _safe_int(value: Optional[object], default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_isbns(values: list[str] | str) -> tuple[list[str], list[str]]:
    if isinstance(values, str):
        values = [values]

    isbn_10: list[str] = []
    isbn_13: list[str] = []
    for value in values or []:
        normalized = normalize_isbn(value)
        if len(normalized) == 13 and normalized not in isbn_13:
            isbn_13.append(normalized)
        elif len(normalized) == 10 and normalized not in isbn_10:
            isbn_10.append(normalized)
    return isbn_10, isbn_13

def parse_open_library_author_work(entry: dict, author_name: str) -> Optional[BookResponse]:
    try:
        work_id = _open_library_key(entry.get("key"))
        if not work_id:
            return None
        covers = entry.get("covers") or []
        if not isinstance(covers, list):
            covers = [covers]
        cover_id = next((cover for cover in covers if _safe_int(cover, -1) > 0), None)
        subjects = entry.get("subjects") or []
        if isinstance(subjects, str):
            subjects = [subjects]

        return BookResponse(
            id=work_id,
            provider="open_library",
            work_id=work_id if work_id.startswith("/works/") else None,
            edition_id=None,
            isbn_10=[],
            isbn_13=[],
            title=entry.get("title", "Sem título"),
            authors=[author_name] if author_name else [],
            categories=normalize_categories(subjects, limit=6),
            page_count=None,
            published_year=_extract_year(entry.get("first_publish_date")),
            description=clean_description(entry.get("description")),
            thumbnail=build_open_library_cover_url("id", str(cover_id)) if cover_id else None,
            language="",
        )
    except (TypeError, ValueError):
        return None


async def fetch_open_library_author_works(
    author_id: str,
    author_name: str,
    limit: int = 50,
    offset: int = 0,
) -> list[BookResponse]:
    clean_author_id = author_id.strip().removeprefix("/authors/")
    params = {"limit": limit, "offset": offset}
    cache_key = _cache_key(
        "open_library_author_works",
        {"author_id": clean_author_id, "author_name": author_name, **params},
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return [BookResponse.model_validate(book) for book in cached]

    headers = {"User-Agent": "Book-it/0.3 (author works)"}
    try:
        async with _PROVIDER_SEMAPHORE:
            async with _build_async_client(timeout=10.0, headers=headers) as client:
                response = await client.get(
                    f"https://openlibrary.org/authors/{clean_author_id}/works.json",
                    params=params,
                )
                response.raise_for_status()
    except httpx.HTTPError:
        return []

    books = [
        parse_open_library_author_work(entry, author_name)
        for entry in response.json().get("entries", [])
    ]
    valid_books = [book for book in books if book is not None]
    _cache_set(cache_key, [book.model_dump() for book in valid_books])
    return valid_books


async def probe_cover_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    cache_key = _cache_key("cover_probe", {"url": url})
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or None

    try:
        async with _COVER_SEMAPHORE:
            async with _build_async_client(
                timeout=COVER_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                response = await client.head(url)
                content_type = response.headers.get("content-type", "")
                if response.status_code >= 400 or not content_type.startswith("image/"):
                    response = await client.get(url)
                    content_type = response.headers.get("content-type", "")
                if response.status_code >= 400 or not content_type.startswith("image/"):
                    _cache_set(cache_key, "")
                    return None
    except httpx.HTTPError:
        _cache_set(cache_key, "")
        return None

    _cache_set(cache_key, url)
    return url


async def fetch_google_cover_candidates(title: str, authors: list[str]) -> list[str]:
    queries = []
    cleaned_title = title.strip()
    primary_author = authors[0].strip() if authors else ""

    if cleaned_title and primary_author:
        queries.append(f'intitle:"{cleaned_title}" inauthor:"{primary_author}"')
    if cleaned_title:
        queries.append(f'intitle:"{cleaned_title}"')
    queries = dedupe_preserve_order(queries)

    candidates: list[str] = []
    seen: set[str] = set()

    try:
        batches = await asyncio.gather(
            *[fetch_google_books(query, max_results=5) for query in queries],
            return_exceptions=True,
        )
    except Exception:
        return []

    for batch in batches:
        if isinstance(batch, Exception):
            continue
        for item in batch:
            volume_info = item.get("volumeInfo", {})
            item_title = normalize_text(volume_info.get("title"))
            normalized_title = normalize_text(cleaned_title)
            if (
                normalized_title
                and item_title
                and normalized_title not in item_title
                and item_title not in normalized_title
            ):
                continue

            item_authors = {normalize_text(author) for author in volume_info.get("authors", []) if author}
            if primary_author:
                normalized_author = normalize_text(primary_author)
                if item_authors and normalized_author not in item_authors and not any(
                    normalized_author in author or author in normalized_author for author in item_authors
                ):
                    continue

            for candidate in _google_thumbnail_candidates(volume_info):
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)

    return candidates


def parse_open_library_doc(doc: dict) -> Optional[BookResponse]:
    try:
        work_id = _open_library_key(doc.get("key"))
        if not work_id:
            return None

        cover_id = doc.get("cover_i")
        thumbnail = build_open_library_cover_url("id", str(cover_id)) if cover_id else None
        raw_subjects = doc.get("subject", []) or []
        subjects = normalize_categories(raw_subjects, limit=6)
        languages = doc.get("language") or []
        if isinstance(languages, str):
            languages = [languages]
        language = languages[0] if languages else ""
        edition_keys = doc.get("edition_key") or []
        if isinstance(edition_keys, str):
            edition_keys = [edition_keys]
        edition_id = _open_library_key(edition_keys[0]) if edition_keys else None
        isbn_10, isbn_13 = _extract_isbns(doc.get("isbn") or [])

        return BookResponse(
            id=work_id,
            provider="open_library",
            work_id=work_id if work_id.startswith("/works/") else None,
            edition_id=edition_id,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            title=doc.get("title", "Sem título"),
            authors=(
                [doc.get("author_name")]
                if isinstance(doc.get("author_name"), str)
                else (doc.get("author_name", []) or [])
            ),
            categories=subjects,
            page_count=doc.get("number_of_pages_median"),
            published_year=_extract_year(doc.get("first_publish_year")),
            description=clean_description(doc.get("first_sentence")),
            thumbnail=thumbnail,
            language=language,
        )
    except (TypeError, ValueError):
        return None

def choose_cover_doc(
    docs: list[dict],
    title: str,
    authors: list[str],
    published_year: Optional[int],
) -> Optional[dict]:
    normalized_title = normalize_text(title)
    normalized_authors = {normalize_text(author) for author in authors if author}
    best_doc = None
    best_score = -1.0

    for doc in docs:
        score = 0.0
        doc_title = normalize_text(doc.get("title"))
        if doc_title == normalized_title:
            score += 3.0
        elif normalized_title and normalized_title in doc_title:
            score += 1.5

        doc_authors = {normalize_text(author) for author in doc.get("author_name", []) if author}
        if normalized_authors and doc_authors and normalized_authors & doc_authors:
            score += 2.0

        doc_year = doc.get("first_publish_year")
        if published_year and isinstance(doc_year, int):
            score += max(0.0, 1.0 - abs(published_year - doc_year) / 15)

        if doc.get("cover_i"):
            score += 1.5
        if doc.get("isbn"):
            score += 0.5

        if score > best_score:
            best_score = score
            best_doc = doc

    return best_doc


async def resolve_thumbnail_fallback(book: BookResponse) -> Optional[str]:
    lookup_cache_key = thumbnail_lookup_signature(book)
    cached_thumbnail = _cache_get(lookup_cache_key)
    if cached_thumbnail is not None:
        return cached_thumbnail or None

    if book.thumbnail:
        thumbnail = upgrade_thumbnail_url(book.thumbnail)
        _cache_set(lookup_cache_key, thumbnail or "")
        return thumbnail

    candidate_urls: list[str] = []
    seen: set[str] = set()

    def add_candidate(url: Optional[str]) -> None:
        upgraded = upgrade_thumbnail_url(url)
        if upgraded and upgraded not in seen:
            seen.add(upgraded)
            candidate_urls.append(upgraded)

    for isbn in [*book.isbn_13, *book.isbn_10]:
        isbn_cover = build_open_library_cover_url("isbn", isbn)
        thumbnail = await probe_cover_url(isbn_cover)
        if thumbnail:
            _cache_set(lookup_cache_key, thumbnail)
            return thumbnail

    params = {
        "title": book.title.strip(),
        "limit": 5,
        "fields": "key,title,author_name,first_publish_year,cover_i,isbn",
    }
    if book.authors:
        params["author"] = book.authors[0]

    try:
        docs = await fetch_open_library_search(params)
    except httpx.HTTPError:
        docs = []

    best_doc = choose_cover_doc(docs, book.title, book.authors, book.published_year)
    if best_doc:
        cover_id = best_doc.get("cover_i")
        if cover_id:
            add_candidate(build_open_library_cover_url("id", str(cover_id)))

        for isbn in best_doc.get("isbn", []) or []:
            add_candidate(build_open_library_cover_url("isbn", str(isbn)))

    google_candidates = await fetch_google_cover_candidates(book.title, book.authors)
    for candidate in google_candidates:
        add_candidate(candidate)

    for candidate_url in candidate_urls:
        thumbnail = await probe_cover_url(candidate_url)
        if thumbnail:
            _cache_set(lookup_cache_key, thumbnail)
            return thumbnail

    _cache_set(lookup_cache_key, "")
    return None


async def enrich_book_thumbnail(book: BookResponse) -> BookResponse:
    if not book:
        return book

    fallback_thumbnail = await resolve_thumbnail_fallback(book)
    if fallback_thumbnail:
        book.thumbnail = fallback_thumbnail
    return book


async def enrich_books_thumbnails(books: list[BookResponse]) -> list[BookResponse]:
    if not books:
        return books

    await asyncio.gather(*(enrich_book_thumbnail(book) for book in books if book))
    return books


async def fetch_open_library_books_by_author(
    author: str,
    title: Optional[str] = None,
    max_results: int = 20,
    offset: int = 0,
) -> list[BookResponse]:
    params = {
        "author": author.strip(),
        "limit": max_results,
        "offset": offset,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    if has_text(title):
        params["title"] = title.strip()

    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    return [book for book in books if book is not None]


async def fetch_open_library_books_by_query(
    query: str,
    max_results: int = 20,
    offset: int = 0,
) -> list[BookResponse]:
    params = {
        "q": query.strip(),
        "limit": max_results,
        "offset": offset,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    return [book for book in books if book is not None]


async def fetch_open_library_books_by_title(
    title: str,
    author: Optional[str] = None,
    max_results: int = 20,
    offset: int = 0,
) -> list[BookResponse]:
    params = {
        "title": title.strip(),
        "limit": max_results,
        "offset": offset,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    if has_text(author):
        params["author"] = author.strip()

    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    return [book for book in books if book is not None]


async def fetch_open_library_books_by_isbn(
    isbn: str,
    max_results: int = 20,
    offset: int = 0,
) -> list[BookResponse]:
    normalized_isbn = normalize_isbn(isbn)
    if not normalized_isbn:
        return []

    params = {
        "isbn": normalized_isbn,
        "limit": max_results,
        "offset": offset,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    return [book for book in books if book is not None]


async def fetch_open_library_book_by_id(book_id: str) -> Optional[BookResponse]:
    normalized_key = _open_library_key(book_id)
    search_olid = normalized_key.rsplit("/", 1)[-1]
    params = {
        "q": search_olid,
        "limit": 10,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    for book in books:
        if not book:
            continue
        identifiers = {book.id, book.work_id or "", book.edition_id or ""}
        if normalized_key in identifiers:
            return await enrich_book_thumbnail(book)
    return None

async def fetch_open_library_books_by_subject(
    subject: str,
    author: Optional[str] = None,
    language: Optional[str] = None,
    max_results: int = 20,
) -> list[BookResponse]:
    params = {
        "subject": subject.strip(),
        "limit": max_results,
        "fields": OPEN_LIBRARY_BOOK_FIELDS,
    }
    if has_text(author):
        params["author"] = author.strip()
    if has_text(language):
        params["lang"] = normalize_language_code(language)

    docs = await fetch_open_library_search(params)
    books = [parse_open_library_doc(doc) for doc in docs]
    return [book for book in books if book is not None]


async def fetch_open_library_subjects(
    title: str,
    authors: list[str],
    published_year: Optional[int],
) -> list[str]:
    params = {
        "title": title,
        "limit": 5,
        "fields": "key,title,author_name,first_publish_year",
    }
    if authors:
        params["author"] = authors[0]

    headers = {"User-Agent": "Book-it/0.3 (Open Library enrichment)"}

    try:
        docs = await fetch_open_library_search(params)
        work_key = choose_open_library_work(docs, title, authors, published_year)
        if not work_key:
            return []

        work_cache_key = _cache_key("open_library_work", {"key": work_key})
        cached = _cache_get(work_cache_key)
        if cached is not None:
            return select_specific_subjects(cached.get("subjects", []))

        async with _build_async_client(timeout=10.0, headers=headers) as client:
            work_response = await client.get(f"https://openlibrary.org{work_key}.json")
            work_response.raise_for_status()
            work_data = work_response.json()
            _cache_set(work_cache_key, work_data)
    except httpx.HTTPError:
        return []

    return select_specific_subjects(work_data.get("subjects", []))


def choose_open_library_work(
    docs: list[dict],
    title: str,
    authors: list[str],
    published_year: Optional[int],
) -> Optional[str]:
    normalized_title = normalize_text(title)
    normalized_authors = {normalize_text(author) for author in authors}
    best_key = None
    best_score = -1.0

    for doc in docs:
        score = 0.0
        doc_title = normalize_text(doc.get("title"))
        if doc_title == normalized_title:
            score += 2.0
        elif normalized_title and normalized_title in doc_title:
            score += 1.0

        doc_authors = {normalize_text(author) for author in doc.get("author_name", [])}
        if normalized_authors and doc_authors and normalized_authors & doc_authors:
            score += 1.0

        doc_year = doc.get("first_publish_year")
        if published_year and isinstance(doc_year, int):
            score += max(0.0, 1.0 - abs(published_year - doc_year) / 20)

        if score > best_score:
            best_score = score
            best_key = doc.get("key")

    return best_key


def select_specific_subjects(subjects: list[str], limit: int = 3) -> list[str]:
    selected = []
    seen = set()

    for subject in subjects:
        normalized = normalize_text(subject)
        if not normalized or normalized in seen:
            continue
        if normalized in GENERIC_SUBJECTS:
            continue
        subject_tokens = set(normalized.split())
        if subject_tokens & {"fiction", "general", "ficcao"} and len(normalized) < 18:
            continue

        selected.append(subject.strip())
        seen.add(normalized)
        if len(selected) >= limit:
            break

    return selected


def thumbnail_lookup_signature(book: BookResponse) -> str:
    return _cache_key(
        "thumbnail_lookup_signature",
        {
            "title": canonicalize_title(book.title),
            "author": normalize_person_name(book.authors[0]) if book.authors else "",
            "year": book.published_year,
            "language": normalize_text(book.language),
        },
    )


async def resolve_reference_book(reference_id: str) -> Optional[BookResponse]:
    if not has_text(reference_id):
        return None

    if reference_id.startswith("/works/") or reference_id.startswith("/books/"):
        return await fetch_open_library_book_by_id(reference_id)

    try:
        item = await fetch_google_book_by_id(reference_id)
    except GoogleBooksUnavailable:
        item = None

    if item:
        book = parse_book(item)
        return await enrich_book_thumbnail(book) if book else None

    return await fetch_open_library_book_by_id(reference_id)


def build_search_terms(
    q: Optional[str],
    reference: BookResponse,
    category: Optional[str],
    enriched_subjects: list[str],
) -> list[str]:
    ordered_terms: list[str] = []

    if has_text(category):
        ordered_terms.extend(
            taxonomy_search_terms([category.strip()], include_related=False, limit=3)
        )
        ordered_terms.append(category.strip())

    combined_categories = [*reference.categories, *enriched_subjects]
    ordered_terms.extend(
        taxonomy_search_terms(
            combined_categories,
            include_related=True,
            limit=MAX_SEARCH_TERMS,
        )
    )
    ordered_terms.extend(select_specific_subjects(enriched_subjects, limit=4))
    ordered_terms.extend(select_specific_subjects(reference.categories, limit=4))

    profile = extract_book_profile(reference)
    ordered_terms.extend(theme.replace("_", " ") for theme in sorted(profile.themes))
    ordered_terms.extend(sorted(profile.keywords)[:5])

    deduped_terms: list[str] = []
    seen: set[str] = set()
    for term in ordered_terms:
        normalized = normalize_text(term)
        if not normalized or normalized in seen or normalized in GENERIC_SUBJECTS:
            continue
        seen.add(normalized)
        deduped_terms.append(term)
        if len(deduped_terms) >= MAX_SEARCH_TERMS:
            break

    if not deduped_terms:
        fallback = canonicalize_title(q or reference.title)
        if fallback:
            deduped_terms.append(fallback)

    return deduped_terms


def interleave_book_batches(batches: list[list[BookResponse]]) -> list[BookResponse]:
    """Distribui resultados entre consultas para evitar domínio do primeiro termo."""
    interleaved: list[BookResponse] = []
    for row in zip_longest(*batches):
        interleaved.extend(book for book in row if book is not None)
    return interleaved


async def fetch_candidate_books(
    search_terms: list[str],
    reference: Optional[BookResponse] = None,
    max_results: int = 40,
    language: Optional[str] = None,
) -> list[BookResponse]:
    if not search_terms:
        return []

    per_query_limit = max(6, min(20, max_results // max(1, len(search_terms))))
    queries: list[str] = []
    for index, term in enumerate(search_terms):
        cleaned = term.strip()
        if not cleaned:
            continue
        queries.append(f'subject:"{cleaned}"')
        if index < 2:
            queries.append(f'"{cleaned}"')
    queries = dedupe_preserve_order(queries)

    batches = await asyncio.gather(
        *(
            fetch_google_books(
                query,
                max_results=per_query_limit,
                language=language,
            )
            for query in queries
        ),
        return_exceptions=True,
    )

    parsed_batches: list[list[BookResponse]] = []
    unavailable_count = 0
    for batch in batches:
        if isinstance(batch, GoogleBooksUnavailable):
            unavailable_count += 1
            continue
        if isinstance(batch, Exception):
            continue
        parsed_batches.append(
            [book for item in batch if (book := parse_book(item)) is not None]
        )

    if batches and unavailable_count == len(batches):
        raise GoogleBooksUnavailable("Google Books temporariamente indisponível")

    candidates = dedupe_books(interleave_book_batches(parsed_batches))
    if len(candidates) < 10 and reference and reference.authors:
        try:
            author_items = await fetch_google_books(
                f'inauthor:"{reference.authors[0]}"',
                max_results=min(20, max_results),
                language=language,
            )
        except GoogleBooksUnavailable:
            author_items = []
        candidates.extend(
            book for item in author_items if (book := parse_book(item)) is not None
        )
        candidates = dedupe_books(candidates)

    return candidates[:max_results]


async def fetch_open_library_candidates(
    search_terms: list[str],
    reference: Optional[BookResponse] = None,
    max_results: int = 40,
    language: Optional[str] = None,
) -> list[BookResponse]:
    if not search_terms:
        return []

    per_term_limit = max(6, min(20, max_results // max(1, len(search_terms))))
    batches = await asyncio.gather(
        *(
            fetch_open_library_books_by_subject(
                term.strip(),
                language=language,
                max_results=per_term_limit,
            )
            for term in search_terms
            if term.strip()
        ),
        return_exceptions=True,
    )

    valid_batches = [batch for batch in batches if isinstance(batch, list)]
    candidates = dedupe_books(interleave_book_batches(valid_batches))

    if len(candidates) < 10 and reference and reference.authors:
        fallback_books = await fetch_open_library_books_by_author(
            reference.authors[0],
            max_results=min(20, max_results),
        )
        candidates = dedupe_books([*candidates, *fallback_books])

    return candidates[:max_results]


def _book_identity_keys(book: BookResponse) -> list[str]:
    keys: list[str] = []
    keys.extend(f"isbn13:{isbn}" for isbn in book.isbn_13 if isbn)
    keys.extend(f"isbn10:{isbn}" for isbn in book.isbn_10 if isbn)
    if book.work_id:
        keys.append(f"work:{book.work_id}")
    if book.edition_id:
        keys.append(f"edition:{book.edition_id}")
    if book.id:
        keys.append(f"provider:{book.provider}:{book.id}")

    signature = normalize_book_signature(book)
    if signature.strip(":"):
        keys.append(f"signature:{signature}")
    return keys


def _merge_unique_strings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*primary, *secondary]:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(value)
    return merged


def merge_book_metadata(primary: BookResponse, secondary: BookResponse) -> BookResponse:
    """Une metadados complementares sem trocar a identidade do resultado ranqueado."""
    merged = primary.model_copy(deep=True)
    merged.authors = _merge_unique_strings(primary.authors, secondary.authors)
    merged.categories = _merge_unique_strings(primary.categories, secondary.categories)
    merged.isbn_10 = _merge_unique_strings(primary.isbn_10, secondary.isbn_10)
    merged.isbn_13 = _merge_unique_strings(primary.isbn_13, secondary.isbn_13)

    if not merged.work_id:
        merged.work_id = secondary.work_id
    if not merged.edition_id:
        merged.edition_id = secondary.edition_id
    if merged.page_count is None:
        merged.page_count = secondary.page_count
    if merged.published_year is None:
        merged.published_year = secondary.published_year
    if not has_text(merged.language):
        merged.language = secondary.language
    if not merged.thumbnail:
        merged.thumbnail = secondary.thumbnail
    if len(secondary.description or "") > len(merged.description or ""):
        merged.description = secondary.description

    return merged


def dedupe_books(books: list[BookResponse]) -> list[BookResponse]:
    deduped: list[BookResponse] = []
    key_to_index: dict[str, int] = {}

    for book in books:
        identity_keys = set(_book_identity_keys(book))
        duplicate_index = next(
            (key_to_index[key] for key in identity_keys if key in key_to_index),
            None,
        )
        if duplicate_index is None:
            duplicate_index = len(deduped)
            deduped.append(book.model_copy(deep=True))
        else:
            deduped[duplicate_index] = merge_book_metadata(deduped[duplicate_index], book)

        for key in _book_identity_keys(deduped[duplicate_index]):
            key_to_index[key] = duplicate_index
        for key in identity_keys:
            key_to_index[key] = duplicate_index

    return deduped


def _author_match_score(authors: list[str], author_query: Optional[str]) -> float:
    if not has_text(author_query):
        return 0.0

    normalized_query = normalize_person_name(author_query)
    query_tokens = set(normalized_query.split())
    best = 0.0
    for author in authors or []:
        normalized_author = normalize_person_name(author)
        if not normalized_author:
            continue
        if normalized_author == normalized_query:
            return 1.0
        if normalized_query in normalized_author or normalized_author in normalized_query:
            best = max(best, 0.82)
            continue
        author_tokens = set(normalized_author.split())
        if query_tokens and author_tokens:
            overlap = len(query_tokens & author_tokens) / max(len(query_tokens), len(author_tokens))
            if overlap >= 0.75:
                best = max(best, overlap)
    return best


def _query_isbn(value: str) -> str:
    normalized = normalize_isbn(value)
    compact_input = re.sub(r"[^0-9Xx]", "", value or "")
    return normalized if normalized and len(compact_input) in {10, 13} else ""


def build_book_search_queries(title_query: str, author_query: Optional[str] = None) -> list[str]:
    title = re.sub(r'\s+', ' ', (title_query or '').replace('"', ' ')).strip()
    author = re.sub(r'\s+', ' ', (author_query or '').replace('"', ' ')).strip()
    isbn = _query_isbn(title)
    if isbn:
        return [f'isbn:{isbn}']

    queries: list[str] = []
    if author:
        queries.append(f'intitle:"{title}" inauthor:"{author}"')
    queries.append(f'intitle:"{title}"')
    if author:
        queries.append(f'"{title}" inauthor:"{author}"')
    queries.append(f'"{title}"')
    queries.append(title)
    return dedupe_preserve_order(queries)


def _search_noise_penalty(title: str, query: str) -> float:
    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)
    penalty = 0.0
    for term in _SEARCH_NOISE_TERMS:
        normalized_term = normalize_text(term)
        if normalized_term in normalized_title and normalized_term not in normalized_query:
            penalty += 0.18 if " " in normalized_term else 0.12
    return min(penalty, 0.42)


def _book_search_score(
    book: BookResponse,
    title_query: str,
    author_query: Optional[str] = None,
) -> float:
    query_isbn = _query_isbn(title_query)
    if query_isbn:
        return 2.0 if query_isbn in {*book.isbn_10, *book.isbn_13} else 0.0

    title_score = _title_similarity(book.title, title_query)
    author_score = _author_match_score(book.authors, author_query)
    metadata_quality = sum(
        (
            bool(book.thumbnail),
            bool(book.description),
            bool(book.categories),
            book.published_year is not None,
            bool(book.isbn_10 or book.isbn_13),
        )
    ) / 5

    if has_text(author_query):
        score = title_score * 0.70 + author_score * 0.25 + metadata_quality * 0.05
    else:
        score = title_score * 0.92 + metadata_quality * 0.08

    if canonicalize_title(book.title) == canonicalize_title(title_query):
        score += 0.12
    if has_text(author_query) and author_score == 1.0:
        score += 0.06

    score -= _search_noise_penalty(book.title, title_query)
    return max(0.0, score)


def _search_result_score(item: dict, title_query: str, author_query: Optional[str] = None) -> float:
    book = parse_book(item)
    return _book_search_score(book, title_query, author_query) if book else 0.0


def _open_library_search_score(
    book: BookResponse,
    title_query: str,
    author_query: Optional[str] = None,
) -> float:
    return _book_search_score(book, title_query, author_query)


async def _search_google_book_candidates(
    title_query: str,
    author_query: Optional[str],
    max_results: int,
    offset: int,
) -> list[BookResponse]:
    queries = build_book_search_queries(title_query, author_query)
    per_query_limit = max(6, min(20, max_results * 2))
    batches = await asyncio.gather(
        *(
            fetch_google_books(
                query,
                max_results=per_query_limit,
                start_index=offset,
            )
            for query in queries
        ),
        return_exceptions=True,
    )

    books: list[BookResponse] = []
    unavailable_count = 0
    for batch in batches:
        if isinstance(batch, GoogleBooksUnavailable):
            unavailable_count += 1
            continue
        if isinstance(batch, Exception):
            continue
        books.extend(book for item in batch if (book := parse_book(item)) is not None)

    if batches and unavailable_count == len(batches):
        raise GoogleBooksUnavailable("Google Books temporariamente indisponível")
    return books


async def _search_open_library_book_candidates(
    title_query: str,
    author_query: Optional[str],
    max_results: int,
    offset: int,
) -> list[BookResponse]:
    isbn = _query_isbn(title_query)
    if isbn:
        return await fetch_open_library_books_by_isbn(
            isbn,
            max_results=max_results,
            offset=offset,
        )

    query = f"{title_query.strip()} {author_query.strip()}" if has_text(author_query) else title_query.strip()
    batches = await asyncio.gather(
        fetch_open_library_books_by_title(
            title_query,
            author=author_query,
            max_results=max_results * 2,
            offset=offset,
        ),
        fetch_open_library_books_by_query(
            query,
            max_results=max_results * 2,
            offset=offset,
        ),
        return_exceptions=True,
    )
    books: list[BookResponse] = []
    for batch in batches:
        if isinstance(batch, Exception):
            continue
        books.extend(batch)
    return books

@app.get("/")
async def root():
    return {"service": "Book-it API", "version": "0.3.0"}


@app.get("/search", response_model=list[BookResponse])
async def search_books(
    q: str = Query(..., description="Título, termo ou ISBN"),
    author: Optional[str] = Query(None, description="Autor opcional para desambiguar o título"),
    max_results: int = Query(10, ge=1, le=40),
    offset: int = Query(0, ge=0, le=1000),
):
    if not has_text(q):
        raise HTTPException(status_code=422, detail="Informe um título ou ISBN")

    google_result, open_library_result = await asyncio.gather(
        _search_google_book_candidates(q.strip(), author, max_results, offset),
        _search_open_library_book_candidates(q.strip(), author, max_results, offset),
        return_exceptions=True,
    )

    candidates: list[BookResponse] = []
    if not isinstance(google_result, Exception):
        candidates.extend(google_result)
    if not isinstance(open_library_result, Exception):
        candidates.extend(open_library_result)

    candidates.sort(
        key=lambda book: _book_search_score(book, q.strip(), author),
        reverse=True,
    )
    ranked = dedupe_books(candidates)[:max_results]
    return await enrich_books_thumbnails(ranked)


@app.get("/authors/search", response_model=list[AuthorResponse])
async def search_authors(
    q: str = Query(..., description="Nome do autor"),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0, le=1000),
):
    if not has_text(q):
        raise HTTPException(status_code=422, detail="Informe o nome do autor")
    return await fetch_open_library_authors(q.strip(), limit=limit, offset=offset)


@app.get("/authors/{author_id}/works", response_model=list[BookResponse])
async def author_works(
    author_id: str,
    author_name: str = Query(..., description="Nome exibido do autor"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000),
):
    if not has_text(author_id) or not has_text(author_name):
        raise HTTPException(status_code=422, detail="Informe autor e identificador válidos")
    books = await fetch_open_library_author_works(
        author_id=author_id,
        author_name=author_name.strip(),
        limit=limit,
        offset=offset,
    )
    return await enrich_books_thumbnails(dedupe_books(books))

@app.get("/recommend", response_model=RecommendationResponse)
async def recommend_books(
    q: Optional[str] = Query(None, description="Título de referência para recomendação"),
    author: Optional[str] = Query(None, description="Autor opcional para desambiguar o título"),
    reference_id: Optional[str] = Query(None, description="Id explícito da obra-base selecionada"),
    min_pages: Optional[int] = Query(None, ge=1),
    max_pages: Optional[int] = Query(None, ge=1),
    min_year: Optional[int] = Query(None, ge=1000, le=2100),
    max_year: Optional[int] = Query(None, ge=1000, le=2100),
    category: Optional[str] = Query(None, description="Gênero/categoria desejada"),
    language: Optional[str] = Query(None, description="Idioma desejado"),
    exclude_same_author: bool = Query(False, description="Ignora obras do mesmo autor"),
    include_unknown_metadata: bool = Query(
        False,
        description="Mantém livros sem páginas/ano mesmo quando esses filtros estão ativos",
    ),
    limit: int = Query(5, ge=1, le=20),
):
    if not has_text(q) and not has_text(reference_id):
        detail = (
            "A busca por autor é separada. Use /authors/search, escolha uma obra e envie reference_id."
            if has_text(author)
            else "Informe um título ou uma obra-base selecionada"
        )
        raise HTTPException(status_code=422, detail=detail)
    if min_pages is not None and max_pages is not None and min_pages > max_pages:
        raise HTTPException(status_code=422, detail="min_pages não pode ser maior que max_pages")
    if min_year is not None and max_year is not None and min_year > max_year:
        raise HTTPException(status_code=422, detail="min_year não pode ser maior que max_year")

    google_available = True
    reference: Optional[BookResponse] = None
    if has_text(reference_id):
        reference = await resolve_reference_book(reference_id.strip())

    if reference is None and has_text(q):
        try:
            reference = await pick_best_reference(q.strip(), author)
        except GoogleBooksUnavailable:
            google_available = False

        if reference is None:
            if has_text(author):
                reference_candidates = await fetch_open_library_books_by_author(
                    author.strip(),
                    q.strip(),
                    max_results=10,
                )
            else:
                reference_candidates = await fetch_open_library_books_by_query(q.strip(), max_results=10)
            reference_candidates.sort(
                key=lambda book: _open_library_search_score(book, q.strip(), author),
                reverse=True,
            )
            reference = reference_candidates[0] if reference_candidates else None

    if not reference:
        raise HTTPException(
            status_code=404,
            detail="Não foi possível localizar uma obra de referência",
        )

    reference = await enrich_book_thumbnail(reference)

    enriched_subjects = await fetch_open_library_subjects(
        reference.title,
        reference.authors,
        reference.published_year,
    )
    if enriched_subjects:
        reference.categories = list(dict.fromkeys(reference.categories + enriched_subjects))

    search_terms = build_search_terms(q, reference, category, enriched_subjects)
    provider_tasks = [
        fetch_open_library_candidates(
            search_terms,
            reference=reference,
            max_results=60,
            language=language,
        )
    ]
    if google_available:
        provider_tasks.append(
            fetch_candidate_books(
                search_terms,
                reference=reference,
                max_results=60,
                language=language,
            )
        )

    provider_results = await asyncio.gather(*provider_tasks, return_exceptions=True)
    thematic_candidates: list[BookResponse] = []
    for provider_result in provider_results:
        if isinstance(provider_result, Exception):
            continue
        thematic_candidates.extend(provider_result)

    candidates = dedupe_books(thematic_candidates)
    reference_keys = set(_book_identity_keys(reference))
    candidates = [
        book
        for book in candidates
        if reference_keys.isdisjoint(_book_identity_keys(book))
    ]

    filters = {
        "min_pages": min_pages,
        "max_pages": max_pages,
        "min_year": min_year,
        "max_year": max_year,
        "category": category,
        "language": normalize_language_code(language),
        "exclude_same_author": exclude_same_author,
        "include_unknown_metadata": include_unknown_metadata,
        "reference_authors": reference.authors,
        "exclude_title": reference.title,
    }
    filtered = filter_books(candidates, filters)
    scored = score_books(filtered, reference)
    scored = [book for book in scored if book.score >= MIN_RECOMMENDATION_SCORE]
    final_recommendations = await enrich_books_thumbnails(scored[:limit])

    return RecommendationResponse(reference=reference, recommendations=final_recommendations)


def parse_book(item: dict) -> Optional[BookResponse]:
    try:
        info = item.get("volumeInfo", {}) or {}
        volume_id = str(item.get("id") or "").strip()
        if not volume_id:
            return None

        raw_identifiers = info.get("industryIdentifiers", []) or []
        if isinstance(raw_identifiers, dict):
            raw_identifiers = [raw_identifiers]
        isbn_10, isbn_13 = _extract_isbns(
            [
                identifier.get("identifier", "")
                for identifier in raw_identifiers
                if isinstance(identifier, dict) and identifier.get("identifier")
            ]
        )
        raw_authors = info.get("authors", []) or []
        if isinstance(raw_authors, str):
            raw_authors = [raw_authors]

        return BookResponse(
            id=volume_id,
            provider="google_books",
            work_id=None,
            edition_id=volume_id,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            title=info.get("title", "Sem título"),
            authors=raw_authors,
            categories=normalize_categories(info.get("categories", []) or [], limit=6),
            page_count=info.get("pageCount"),
            published_year=_extract_year(info.get("publishedDate")),
            description=clean_description(info.get("description")),
            thumbnail=upgrade_thumbnail_url((info.get("imageLinks") or {}).get("thumbnail")),
            language=info.get("language", ""),
        )
    except (TypeError, ValueError):
        return None


def _title_similarity(a: str, b: str) -> float:
    normalized_a = canonicalize_title(a)
    normalized_b = canonicalize_title(b)
    if not normalized_a or not normalized_b:
        return 0.0
    if normalized_a == normalized_b:
        return 1.0

    tokens_a = set(normalized_a.split())
    tokens_b = set(normalized_b.split())
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    jaccard = intersection / union if union else 0.0
    containment = intersection / min(len(tokens_a), len(tokens_b)) if intersection else 0.0
    sequence_ratio = SequenceMatcher(None, normalized_a, normalized_b).ratio()

    subset_score = 0.0
    if tokens_a.issubset(tokens_b) or tokens_b.issubset(tokens_a):
        extra_tokens = abs(len(tokens_a) - len(tokens_b))
        subset_score = max(0.72, 0.92 - extra_tokens * 0.04)

    return min(1.0, max(jaccard, containment * 0.84, sequence_ratio * 0.90, subset_score))


def _reference_score(item: dict, query: str) -> float:
    book = parse_book(item)
    return _book_search_score(book, query) if book else 0.0


async def pick_best_reference(
    query: str,
    author: Optional[str] = None,
) -> Optional[BookResponse]:
    """Resolve a melhor obra do Google Books com o mesmo ranking usado em /search."""
    books = await _search_google_book_candidates(
        query,
        author,
        max_results=20,
        offset=0,
    )
    if not books:
        return None

    books.sort(
        key=lambda book: _book_search_score(book, query, author),
        reverse=True,
    )
    return await enrich_book_thumbnail(books[0])

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0", "api_key_set": bool(API_KEY)}
