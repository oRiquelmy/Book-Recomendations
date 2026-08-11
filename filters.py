from __future__ import annotations

import math
from collections import Counter
from typing import Optional

from book_profile import extract_book_profile, profile_component_scores
from metadata_normalizer import (
    canonicalize_title,
    categories_match,
    normalize_language_code,
    normalize_person_name,
    normalize_text,
    tokenize_text,
)
from models import BookResponse, ScoredBook
from taxonomy import taxonomy_profile, taxonomy_similarity

_STOPWORDS = {
    "de", "a", "o", "e", "em", "um", "uma", "para", "com", "que", "do", "da",
    "dos", "das", "no", "na", "nos", "nas", "ao", "aos", "pelo", "pela", "ser",
    "foi", "ele", "ela", "seu", "sua", "como", "mais", "mas", "por", "se", "ou",
    "the", "an", "of", "in", "and", "to", "is", "it", "this", "that", "his", "her",
    "with", "for", "on", "are", "was", "he", "she", "at", "be", "have", "from",
    "not", "but", "they", "their", "when", "who", "which", "book", "livro", "story",
    "historia", "novel", "romance", "edition", "edicao", "volume", "collection",
}

_GENERIC_CATEGORY_TERMS = {
    "fiction",
    "ficcao",
    "general",
    "literature",
    "novel",
    "book",
    "books",
}

# O score final é uma compatibilidade calibrada, não a soma bruta dos sinais.
# Componentes ausentes não valem zero; o denominador usa somente evidência disponível,
# com um piso para impedir notas altas baseadas apenas em idioma, páginas ou ano.
_SCORE_WEIGHTS = {
    "taxonomy": 0.38,
    "themes": 0.22,
    "style": 0.12,
    "text": 0.14,
    "author": 0.07,
    "year": 0.03,
    "pages": 0.015,
    "title": 0.015,
    "language": 0.01,
}
_MIN_EVIDENCE_WEIGHT = 0.72
_CALIBRATION_EXPONENT = 0.70

_STYLE_COMPONENT_WEIGHTS = {
    "narrative_markers": 0.36,
    "tones": 0.30,
    "audiences": 0.24,
    "pace_markers": 0.10,
}


def keywords_from_description(description: str, top_n: int = 3) -> list[str]:
    words = [
        token
        for token in tokenize_text(description)
        if len(token) >= 4 and token not in _STOPWORDS and not token.isdigit()
    ]
    frequencies = Counter(words)
    return [word for word, _ in frequencies.most_common(top_n)]


def _token_counter(value: str) -> Counter[str]:
    return Counter(
        token
        for token in tokenize_text(value)
        if len(token) >= 3 and token not in _STOPWORDS and not token.isdigit()
    )


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def token_similarity(a: str, b: str) -> float:
    return _cosine_similarity(_token_counter(a), _token_counter(b))


def _book_keyword_counter(book: BookResponse) -> Counter[str]:
    counter: Counter[str] = Counter()
    weighted_sources = (
        (book.title or "", 2),
        (book.description or "", 1),
    )
    for text, weight in weighted_sources:
        for token, count in _token_counter(text).items():
            counter[token] += count * weight
    return counter


def keyword_overlap_score(reference: BookResponse, book: BookResponse) -> float:
    return _cosine_similarity(_book_keyword_counter(reference), _book_keyword_counter(book))


def _raw_category_similarity(reference_categories: list[str], candidate_categories: list[str]) -> float:
    reference = {normalize_text(category) for category in reference_categories if normalize_text(category)}
    candidates = {normalize_text(category) for category in candidate_categories if normalize_text(category)}
    if not reference or not candidates:
        return 0.0

    reference_specific = reference - _GENERIC_CATEGORY_TERMS
    candidate_specific = candidates - _GENERIC_CATEGORY_TERMS
    if not reference_specific and not candidate_specific:
        return 0.18 if reference & candidates else 0.0
    if not reference_specific or not candidate_specific:
        return 0.0
    reference = reference_specific
    candidates = candidate_specific

    matches = 0
    unmatched = set(candidates)
    for reference_category in reference:
        match = next(
            (
                candidate
                for candidate in unmatched
                if categories_match(reference_category, [candidate])
                or categories_match(candidate, [reference_category])
            ),
            None,
        )
        if match is not None:
            matches += 1
            unmatched.remove(match)

    union_size = len(reference) + len(candidates) - matches
    return matches / union_size if union_size else 0.0


def category_overlap_score(reference_categories: list[str], candidate_categories: list[str]) -> float:
    taxonomy_score = taxonomy_similarity(reference_categories, candidate_categories)
    reference_profile = taxonomy_profile(reference_categories)
    candidate_profile = taxonomy_profile(candidate_categories)
    if reference_profile.all_ids and candidate_profile.all_ids:
        return taxonomy_score
    return _raw_category_similarity(reference_categories, candidate_categories)


def _theme_similarity(reference_profile, candidate_profile) -> float:
    if not reference_profile.themes or not candidate_profile.themes:
        return 0.0
    intersection = len(reference_profile.themes & candidate_profile.themes)
    if not intersection:
        return 0.0
    jaccard = intersection / len(reference_profile.themes | candidate_profile.themes)
    dice = (2 * intersection) / (len(reference_profile.themes) + len(candidate_profile.themes))
    return jaccard * 0.62 + dice * 0.38


def _style_similarity(reference_profile, candidate_profile) -> tuple[float, bool]:
    component_scores = profile_component_scores(reference_profile, candidate_profile)
    weighted_sum = 0.0
    available_weight = 0.0

    for component, weight in _STYLE_COMPONENT_WEIGHTS.items():
        reference_values = getattr(reference_profile, component)
        candidate_values = getattr(candidate_profile, component)
        if not reference_values or not candidate_values:
            continue
        weighted_sum += component_scores[component] * weight
        available_weight += weight

    if not available_weight:
        return 0.0, False
    return weighted_sum / available_weight, True


def _author_similarity(reference: BookResponse, book: BookResponse) -> float:
    reference_authors = {
        normalize_person_name(author)
        for author in reference.authors
        if normalize_person_name(author)
    }
    candidate_authors = {
        normalize_person_name(author)
        for author in book.authors
        if normalize_person_name(author)
    }
    if not reference_authors or not candidate_authors:
        return 0.0
    if reference_authors & candidate_authors:
        return 1.0

    best = 0.0
    for reference_author in reference_authors:
        reference_tokens = set(reference_author.split())
        for candidate_author in candidate_authors:
            candidate_tokens = set(candidate_author.split())
            if not reference_tokens or not candidate_tokens:
                continue
            overlap = len(reference_tokens & candidate_tokens) / max(len(reference_tokens), len(candidate_tokens))
            best = max(best, overlap)
    return best if best >= 0.75 else 0.0


def _linear_proximity(reference_value: int, candidate_value: int, tolerance: int) -> float:
    return max(0.0, 1.0 - abs(reference_value - candidate_value) / tolerance)


def score_book_components(book: BookResponse, reference: BookResponse) -> dict[str, Optional[float]]:
    reference_profile = extract_book_profile(reference)
    candidate_profile = extract_book_profile(book)
    reference_taxonomy = taxonomy_profile(reference.categories)
    candidate_taxonomy = taxonomy_profile(book.categories)

    taxonomy_available = bool(
        (reference_taxonomy.all_ids and candidate_taxonomy.all_ids)
        or (reference.categories and book.categories)
    )
    themes_available = bool(reference_profile.themes and candidate_profile.themes)
    style_score, style_available = _style_similarity(reference_profile, candidate_profile)
    text_available = bool(_book_keyword_counter(reference) and _book_keyword_counter(book))
    author_available = bool(reference.authors and book.authors)
    year_available = reference.published_year is not None and book.published_year is not None
    pages_available = reference.page_count is not None and book.page_count is not None
    title_available = bool(reference.title and book.title)
    reference_language = normalize_language_code(reference.language)
    candidate_language = normalize_language_code(book.language)
    language_available = bool(reference_language and candidate_language)

    return {
        "taxonomy": category_overlap_score(reference.categories, book.categories) if taxonomy_available else None,
        "themes": _theme_similarity(reference_profile, candidate_profile) if themes_available else None,
        "style": style_score if style_available else None,
        "text": keyword_overlap_score(reference, book) if text_available else None,
        "author": _author_similarity(reference, book) if author_available else None,
        "year": (
            _linear_proximity(reference.published_year, book.published_year, 60)
            if year_available
            else None
        ),
        "pages": (
            _linear_proximity(reference.page_count, book.page_count, 600)
            if pages_available
            else None
        ),
        "title": token_similarity(reference.title, book.title) if title_available else None,
        "language": (1.0 if reference_language == candidate_language else 0.0) if language_available else None,
    }


def _calibrate_score(components: dict[str, Optional[float]]) -> float:
    weighted_sum = 0.0
    available_weight = 0.0
    semantic_sum = 0.0

    for name, weight in _SCORE_WEIGHTS.items():
        value = components.get(name)
        if value is None:
            continue
        bounded_value = min(1.0, max(0.0, value))
        contribution = bounded_value * weight
        weighted_sum += contribution
        available_weight += weight
        if name in {"taxonomy", "themes", "style", "text"}:
            semantic_sum += contribution

    if not available_weight or not weighted_sum:
        return 0.0

    raw_score = weighted_sum / max(_MIN_EVIDENCE_WEIGHT, available_weight)
    calibrated = min(1.0, max(0.0, raw_score)) ** _CALIBRATION_EXPONENT

    # Sem qualquer relação temática/textual, contexto editorial não deve produzir
    # uma recomendação forte por coincidência de idioma, páginas ou período.
    if semantic_sum < 0.025:
        calibrated = min(calibrated, 0.32)

    return round(calibrated, 4)


def filter_books(books: list[BookResponse], filters: dict) -> list[BookResponse]:
    result: list[BookResponse] = []
    reference_authors = {
        normalize_person_name(author)
        for author in filters.get("reference_authors", [])
        if author
    }
    include_unknown_metadata = bool(filters.get("include_unknown_metadata", False))
    excluded_title = canonicalize_title(filters.get("exclude_title", ""))

    for book in books:
        if excluded_title and canonicalize_title(book.title) == excluded_title:
            candidate_authors = {
                normalize_person_name(author)
                for author in book.authors
                if author
            }
            if not reference_authors or candidate_authors & reference_authors:
                continue

        if filters.get("category") and not categories_match(filters["category"], book.categories):
            continue

        if filters.get("language"):
            requested_language = normalize_language_code(filters["language"])
            book_language = normalize_language_code(book.language)
            if requested_language and book_language != requested_language:
                continue

        if filters.get("exclude_same_author") and reference_authors:
            candidate_authors = {
                normalize_person_name(author)
                for author in book.authors
                if author
            }
            if candidate_authors & reference_authors:
                continue

        if filters.get("min_pages") is not None:
            if book.page_count is None and not include_unknown_metadata:
                continue
            if book.page_count is not None and book.page_count < filters["min_pages"]:
                continue
        if filters.get("max_pages") is not None:
            if book.page_count is None and not include_unknown_metadata:
                continue
            if book.page_count is not None and book.page_count > filters["max_pages"]:
                continue

        if filters.get("min_year") is not None:
            if book.published_year is None and not include_unknown_metadata:
                continue
            if book.published_year is not None and book.published_year < filters["min_year"]:
                continue
        if filters.get("max_year") is not None:
            if book.published_year is None and not include_unknown_metadata:
                continue
            if book.published_year is not None and book.published_year > filters["max_year"]:
                continue

        result.append(book)

    return result


def score_books(books: list[BookResponse], reference: BookResponse) -> list[ScoredBook]:
    """Pontua compatibilidade em 0.0-1.0, normalizando metadados ausentes."""
    scored: list[ScoredBook] = []
    total_weight = sum(_SCORE_WEIGHTS.values())

    for book in books:
        components = score_book_components(book, reference)
        score = _calibrate_score(components)
        available_weight = sum(
            _SCORE_WEIGHTS[name]
            for name, value in components.items()
            if value is not None
        )
        serialized_components = {
            name: round(min(1.0, max(0.0, value)), 4)
            for name, value in components.items()
            if value is not None
        }
        scored.append(
            ScoredBook(
                **book.model_dump(),
                score=score,
                score_components=serialized_components,
                score_coverage=round(available_weight / total_weight, 4),
            )
        )

    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    return scored
