import re
import unicodedata
from html import unescape
from typing import Iterable, Optional

from models import BookResponse

_LANGUAGE_ALIASES = {
    "pt": "pt",
    "por": "pt",
    "pt-br": "pt",
    "pt-pt": "pt",
    "en": "en",
    "eng": "en",
    "es": "es",
    "spa": "es",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "de": "de",
    "deu": "de",
    "ger": "de",
    "it": "it",
    "ita": "it",
    "ja": "ja",
    "jpn": "ja",
    "ko": "ko",
    "kor": "ko",
    "zh": "zh",
    "zho": "zh",
    "chi": "zh",
    "ru": "ru",
    "rus": "ru",
}

_EDITION_MARKER_PATTERN = (
    r"edition|edicao|revised edition|updated edition|illustrated edition|"
    r"anniversary edition|special edition|deluxe edition|collector'?s edition|"
    r"box set|paperback|hardcover"
)


def _strip_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def normalize_text(value: Optional[object]) -> str:
    """Normaliza texto para comparação sem alterar o valor exibido ao usuário."""
    if value is None:
        return ""

    text = _strip_diacritics(unescape(str(value)).casefold())
    text = text.replace("_", " ")
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_person_name(value: Optional[str]) -> str:
    """Normaliza pontuação e iniciais: J. R. R. Tolkien == J.R.R. Tolkien."""
    return normalize_text(value)


def tokenize_text(value: Optional[object]) -> list[str]:
    return [token for token in normalize_text(value).split(" ") if token]


def contains_normalized_phrase(text: Optional[object], phrase: Optional[object]) -> bool:
    normalized_text = normalize_text(text)
    normalized_phrase = normalize_text(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def has_text(value: Optional[str]) -> bool:
    return bool(value and value.strip())


def normalize_language_code(value: Optional[str]) -> str:
    normalized = normalize_text(value)
    return _LANGUAGE_ALIASES.get(normalized, normalized)


def normalize_categories(categories: Iterable[str], limit: int = 6) -> list[str]:
    if isinstance(categories, str):
        categories = [categories]

    normalized_categories: list[str] = []
    seen: set[str] = set()

    for category in categories or []:
        raw_parts = re.split(r"\s*/\s*|\s*>\s*|\s+\|\s+", str(category))
        for part in raw_parts:
            cleaned = re.sub(r"\s+", " ", part).strip(" -:/")
            if not cleaned:
                continue
            normalized = normalize_text(cleaned)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_categories.append(cleaned)
            if len(normalized_categories) >= limit:
                return normalized_categories

    return normalized_categories


def categories_match(requested: Optional[str], categories: Iterable[str]) -> bool:
    """Compara categorias usando a taxonomia canônica e fallback textual."""
    from taxonomy import category_filter_match

    return category_filter_match(requested, categories)


def clean_description(value: Optional[object], max_length: int = 900) -> str:
    if not value:
        return ""

    if isinstance(value, dict):
        value = value.get("value", "")
    elif isinstance(value, list):
        parts = [str(part).strip() for part in value if part]
        value = " ".join(parts)

    text = unescape(str(value))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)<li\s*>", "- ", text)
    text = re.sub(r"(?i)</li\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if len(text) <= max_length:
        return text

    cutoff = text.rfind(" ", 0, max_length)
    if cutoff < max_length * 0.6:
        cutoff = max_length
    return text[:cutoff].rstrip(" ,;:-") + "..."


def canonicalize_title(title: str) -> str:
    """
    Remove apenas marcadores explícitos de edição.

    Não corta todo texto depois de ':' ou '-', pois esses caracteres fazem parte
    de títulos legítimos como "Catch-22" e "Spider-Man: Blue".
    """
    structured = _strip_diacritics(unescape(title or "").casefold())
    structured = re.sub(r"\s+", " ", structured).strip()

    structured = re.sub(
        rf"\((?=[^)]*\b(?:{_EDITION_MARKER_PATTERN})\b)[^)]*\)",
        " ",
        structured,
    )
    structured = re.sub(
        rf"\[(?=[^]]*\b(?:{_EDITION_MARKER_PATTERN})\b)[^]]*\]",
        " ",
        structured,
    )
    structured = re.sub(
        rf"\s*(?::|\||\s-\s)\s*(?=[^:|]*\b(?:{_EDITION_MARKER_PATTERN})\b).*$",
        "",
        structured,
    )
    structured = re.sub(
        rf"\s+(?:\d+[a-z]?\s+)?(?:{_EDITION_MARKER_PATTERN})\s*$",
        "",
        structured,
    )
    return normalize_text(structured)


def normalize_isbn(value: Optional[str]) -> str:
    normalized = re.sub(r"[^0-9Xx]", "", value or "").upper()
    return normalized if len(normalized) in {10, 13} else ""


def normalize_book_signature(book: BookResponse) -> str:
    authors = "|".join(
        sorted(normalize_person_name(author) for author in book.authors if normalize_person_name(author))
    )
    return f"{canonicalize_title(book.title)}::{authors}"
