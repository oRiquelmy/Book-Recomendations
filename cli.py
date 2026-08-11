import os
from html import escape

import httpx
import streamlit as st

from taxonomy import category_options

BASE_URL = os.getenv("BOOKIT_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("BOOKIT_REQUEST_TIMEOUT_SECONDS", "30"))
CATEGORY_OPTIONS = ["", *category_options()]
LANGUAGE_OPTIONS = {
    "": "Qualquer idioma",
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "ja": "Japonês",
    "ko": "Coreano",
    "zh": "Chinês",
    "ru": "Russo",
}
DECADE_OPTIONS = {
    "": "Qualquer década",
    "2020": "Anos 2020",
    "2010": "Anos 2010",
    "2000": "Anos 2000",
    "1990": "Anos 1990",
    "1980": "Anos 1980",
    "1970": "Anos 1970",
    "1960": "Anos 1960",
    "1950": "Anos 1950",
    "1940": "Anos 1940",
    "1930": "Anos 1930",
    "1920": "Anos 1920",
    "1910": "Anos 1910",
    "1900": "Anos 1900",
    "pre-1900": "Antes de 1900",
}
PAGE_RANGE_MIN = 0
PAGE_RANGE_MAX = 1500
PAGE_RANGE_STEP = 100
DEFAULT_RECOMMENDATION_LIMIT = 5
BOOK_SEARCH_PAGE_SIZE = 8


def format_language_label(language_code: str | None) -> str:
    if not language_code:
        return "N/A"
    normalized = language_code.strip().casefold()
    aliases = {
        "por": "pt",
        "pt-br": "pt",
        "pt-pt": "pt",
        "eng": "en",
        "spa": "es",
        "fra": "fr",
        "fre": "fr",
        "deu": "de",
        "ger": "de",
        "ita": "it",
        "jpn": "ja",
        "kor": "ko",
        "zho": "zh",
        "chi": "zh",
        "rus": "ru",
    }
    canonical = aliases.get(normalized, normalized)
    return LANGUAGE_OPTIONS.get(canonical, canonical.upper())


def format_pages_label(book: dict) -> str:
    pages = book.get("page_count")
    return f"{pages} páginas" if pages else "Páginas N/A"


def format_year_label(book: dict) -> str:
    year = book.get("published_year")
    return str(year) if year else "Ano N/A"


def decade_to_year_bounds(decade: str) -> tuple[int | None, int | None]:
    if not decade:
        return None, None
    if decade == "pre-1900":
        return None, 1899

    decade_start = int(decade)
    return decade_start, decade_start + 9


def format_page_range_value(value: int) -> str:
    if value <= PAGE_RANGE_MIN:
        return "0"
    if value >= PAGE_RANGE_MAX:
        return f"{PAGE_RANGE_MAX}+"
    return str(value)


def get_active_filter_labels(filters: dict) -> list[str]:
    labels: list[str] = []
    if filters.get("category"):
        labels.append(f"Categoria: {filters['category']}")
    if filters.get("language"):
        labels.append(f"Idioma: {format_language_label(filters['language'])}")
    if filters.get("min_pages") or filters.get("max_pages"):
        page_start = filters.get("min_pages") or PAGE_RANGE_MIN
        page_end = filters.get("max_pages") or PAGE_RANGE_MAX
        labels.append(f"Tamanho: {format_page_range_value(page_start)}-{format_page_range_value(page_end)} páginas")
    if filters.get("decade"):
        labels.append(f"Década: {DECADE_OPTIONS.get(filters['decade'], filters['decade'])}")
    if filters.get("exclude_same_author"):
        labels.append("Sem obras do mesmo autor")
    if filters.get("include_unknown_metadata"):
        labels.append("Mantém resultados com páginas/ano desconhecidos")
    if filters.get("limit") and filters["limit"] != DEFAULT_RECOMMENDATION_LIMIT:
        labels.append(f"{filters['limit']} recomendações")
    return labels


def build_match_reasons(book: dict, reference: dict | None = None) -> list[str]:
    components = book.get("score_components") or {}
    if components:
        reasons: list[str] = []
        taxonomy_score = components.get("taxonomy", 0.0)
        if taxonomy_score >= 0.85:
            reasons.append("Categoria ou subgênero muito próximo")
        elif taxonomy_score >= 0.55:
            reasons.append("Categoria relacionada")

        themes_score = components.get("themes", 0.0)
        if themes_score >= 0.65:
            reasons.append("Temas muito próximos")
        elif themes_score >= 0.40:
            reasons.append("Temas em comum")

        if components.get("style", 0.0) >= 0.65:
            reasons.append("Estilo narrativo semelhante")
        if components.get("text", 0.0) >= 0.45:
            reasons.append("Descrição e vocabulário próximos")
        if components.get("author", 0.0) >= 0.95:
            reasons.append("Mesmo autor")
        if components.get("year", 0.0) >= 0.85:
            reasons.append("Período próximo")
        if components.get("pages", 0.0) >= 0.85:
            reasons.append("Extensão parecida")
        return reasons[:3]

    if not reference:
        return []

    reasons: list[str] = []
    reference_categories = {category.casefold() for category in reference.get("categories", []) if category}
    book_categories = {category.casefold() for category in book.get("categories", []) if category}
    if reference_categories & book_categories:
        reasons.append("Categoria em comum")

    reference_authors = {author.casefold() for author in reference.get("authors", []) if author}
    book_authors = {author.casefold() for author in book.get("authors", []) if author}
    if reference_authors & book_authors:
        reasons.append("Mesmo autor")
    return reasons[:3]


def apply_page_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(194, 154, 108, 0.10), transparent 34%),
                    radial-gradient(circle at top right, rgba(108, 128, 109, 0.10), transparent 28%);
            }

            .section-card {
                padding: 1.05rem 1.1rem 1.15rem 1.1rem;
                border-radius: 20px;
                border: 1px solid rgba(126, 99, 76, 0.16);
                background: linear-gradient(180deg, rgba(255, 252, 247, 0.90), rgba(247, 239, 228, 0.76));
                box-shadow: 0 12px 34px rgba(55, 43, 35, 0.08);
                margin-bottom: 1rem;
            }

            .section-kicker {
                display: inline-block;
                padding: 0.18rem 0.58rem;
                border-radius: 999px;
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                background: rgba(164, 126, 84, 0.12);
                color: #8a6238;
                margin-bottom: 0.6rem;
            }

            .section-title {
                font-size: 1.18rem;
                font-weight: 700;
                color: #3f332b;
                margin-bottom: 0.2rem;
            }


            .result-card {
                padding: 1rem 1rem 1.05rem 1rem;
                border-radius: 20px;
                border: 1px solid rgba(126, 99, 76, 0.16);
                background: linear-gradient(180deg, rgba(255, 252, 247, 0.96), rgba(245, 236, 223, 0.80));
                margin-bottom: 1rem;
            }

            .book-cover-frame,
            .reference-cover-frame {
                width: 100%;
                aspect-ratio: 2 / 3;
                overflow: hidden;
                border-radius: 18px;
                border: 1px solid rgba(126, 99, 76, 0.16);
                background:
                    linear-gradient(180deg, rgba(255, 252, 247, 0.96), rgba(242, 232, 219, 0.88));
                box-shadow: 0 14px 28px rgba(55, 43, 35, 0.10);
            }

            .book-cover-frame img,
            .reference-cover-frame img {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }

            .book-cover-empty,
            .reference-cover-empty {
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 1rem;
                text-align: center;
                color: rgba(63, 51, 43, 0.72);
                font-size: 0.84rem;
            }

            .meta-row {
                display: flex;
                flex-wrap: wrap;
                gap: 0.45rem;
                margin: 0.45rem 0 0.75rem 0;
            }

            .meta-pill {
                padding: 0.28rem 0.64rem;
                border-radius: 999px;
                background: rgba(85, 106, 86, 0.10);
                border: 1px solid rgba(85, 106, 86, 0.12);
                color: #3e5846;
                font-size: 0.8rem;
            }

            .score-pill {
                display: inline-block;
                margin-bottom: 0.6rem;
                padding: 0.24rem 0.62rem;
                border-radius: 999px;
                background: rgba(182, 133, 72, 0.14);
                color: #8c5f22;
                font-size: 0.8rem;
                font-weight: 700;
            }

            .filter-summary {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin: 0.15rem 0 1rem 0;
            }

            .filter-chip {
                padding: 0.34rem 0.7rem;
                border-radius: 999px;
                background: rgba(128, 89, 43, 0.10);
                border: 1px solid rgba(128, 89, 43, 0.14);
                color: #6e4d2c;
                font-size: 0.82rem;
            }

            .insight-row {
                display: flex;
                flex-wrap: wrap;
                gap: 0.42rem;
                margin: 0 0 0.8rem 0;
            }

            .insight-pill {
                padding: 0.28rem 0.62rem;
                border-radius: 999px;
                background: rgba(182, 133, 72, 0.10);
                border: 1px solid rgba(182, 133, 72, 0.15);
                color: #8b5d24;
                font-size: 0.78rem;
            }

            div[data-testid="stExpander"] {
                border: 1px solid rgba(126, 99, 76, 0.16);
                border-radius: 18px;
                background: rgba(255, 252, 247, 0.72);
            }

            .shelf-strip {
                height: 18px;
                border-radius: 999px;
                background: linear-gradient(180deg, #7d5a3b, #5f4129);
                box-shadow: inset 0 2px 4px rgba(255,255,255,0.18), 0 8px 18px rgba(48, 34, 23, 0.16);
                margin: 0.4rem 0 1rem 0;
            }

            .reference-choice {
                min-height: 176px;
                padding: 0.75rem 0.75rem 0.65rem 0.75rem;
                border-radius: 18px;
                background: linear-gradient(180deg, rgba(255, 252, 247, 0.96), rgba(242, 232, 219, 0.88));
                border: 1px solid rgba(126, 99, 76, 0.16);
                box-shadow: 0 12px 24px rgba(55, 43, 35, 0.08);
                margin-top: 0.55rem;
                display: flex;
                flex-direction: column;
                gap: 0.32rem;
            }

            .reference-card-shell {
                display: flex;
                flex-direction: column;
                height: 100%;
                gap: 0.55rem;
            }

            .reference-card-body {
                flex: 1;
                display: flex;
                flex-direction: column;
            }

            .reference-card-action {
                margin-top: auto;
            }

            .reference-choice.is-selected {
                border: 2px solid rgba(128, 89, 43, 0.55);
                box-shadow: 0 14px 28px rgba(89, 59, 29, 0.16);
            }

            .reference-choice-title {
                font-size: 0.96rem;
                font-weight: 700;
                color: #3f332b;
                margin-bottom: 0.1rem;
                min-height: 2.8em;
                display: -webkit-box;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 2;
                line-clamp: 2;
                overflow: hidden;
            }

            .reference-choice-meta {
                font-size: 0.83rem;
                color: rgba(63, 51, 43, 0.82);
                line-height: 1.45;
                min-height: 2.35em;
                display: -webkit-box;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 2;
                line-clamp: 2;
                overflow: hidden;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_api_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
        follow_redirects=True,
        headers={"User-Agent": "Book-it-Streamlit/0.2"},
    )


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        return str(payload.get("detail") or payload)
    return str(payload)


def _get_json(path: str, params: dict, context: str) -> dict | list | None:
    try:
        response = get_api_client().get(path, params=params)
    except httpx.ConnectError:
        st.error(
            f"Não foi possível conectar ao backend em `{BASE_URL}`. "
            "Verifique se o FastAPI está em execução."
        )
        return None
    except httpx.ReadTimeout:
        st.error(f"{context} demorou mais do que o esperado. Refine a consulta e tente novamente.")
        return None
    except httpx.RequestError as exc:
        st.error(f"Falha de comunicação com a API: {exc}")
        return None

    if response.status_code != 200:
        detail = _response_detail(response)
        if response.status_code in {404, 422}:
            st.warning(detail)
        else:
            st.error(f"Erro da API ({response.status_code}): {detail}")
        return None
    return response.json()


def get_recommendations(title: str, author: str, filters: dict, reference_id: str = "") -> dict | None:
    allowed_filter_keys = {
        "min_pages",
        "max_pages",
        "min_year",
        "max_year",
        "category",
        "language",
        "exclude_same_author",
        "include_unknown_metadata",
        "limit",
    }
    cleaned_filters = {
        key: value
        for key, value in filters.items()
        if key in allowed_filter_keys and value not in (None, "", False)
    }
    params = {
        "q": title.strip(),
        "author": author.strip(),
        "reference_id": reference_id.strip(),
        **cleaned_filters,
    }
    params = {key: value for key, value in params.items() if value not in ("", None)}
    payload = _get_json("/recommend", params, "A busca de recomendações")
    return payload if isinstance(payload, dict) else None


def search_reference_books(title: str, author: str = "", max_results: int = 8, offset: int = 0) -> list[dict]:
    if not title.strip():
        return []
    payload = _get_json(
        "/search",
        {
            "q": title.strip(),
            "author": author.strip() or None,
            "max_results": max_results,
            "offset": offset,
        },
        "A busca de obras-base",
    )
    return payload if isinstance(payload, list) else []


def search_authors(query: str, limit: int = 12, offset: int = 0) -> list[dict]:
    if not query.strip():
        return []
    payload = _get_json(
        "/authors/search",
        {"q": query.strip(), "limit": limit, "offset": offset},
        "A busca de autores",
    )
    return payload if isinstance(payload, list) else []


def get_author_works(author_id: str, author_name: str, limit: int = 24, offset: int = 0) -> list[dict]:
    if not author_id.strip() or not author_name.strip():
        return []
    payload = _get_json(
        f"/authors/{author_id.strip()}/works",
        {
            "author_name": author_name.strip(),
            "limit": limit,
            "offset": offset,
        },
        "A busca das obras do autor",
    )
    return payload if isinstance(payload, list) else []

def _reference_candidate_key(book: dict) -> str:
    isbn_13 = next((value for value in book.get("isbn_13", []) if value), "")
    if isbn_13:
        return f"isbn13:{isbn_13}"
    if book.get("work_id"):
        return f"work:{book['work_id']}"
    return f"{book.get('provider', 'unknown')}:{book.get('id', '')}"


def merge_reference_candidate_pages(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = list(existing)
    seen = {_reference_candidate_key(book) for book in existing}
    for book in incoming:
        key = _reference_candidate_key(book)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(book)
    return merged


def clear_reference_candidates() -> None:
    st.session_state["reference_candidates"] = []
    st.session_state["reference_query"] = ""
    st.session_state["reference_offset"] = 0
    st.session_state["reference_has_more"] = False
    st.session_state["selected_reference_id"] = ""


def render_section_header(kicker: str, title: str) -> None:
    safe_kicker = escape(kicker)
    safe_title = escape(title)
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-kicker">{safe_kicker}</div>
            <div class="section-title">{safe_title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_filter_summary(filters: dict) -> None:
    labels = get_active_filter_labels(filters)
    if not labels:
        return

    chips = "".join(f'<div class="filter-chip">{escape(label)}</div>' for label in labels)
    st.markdown(
        f'<div class="filter-summary">{chips}</div>',
        unsafe_allow_html=True,
    )


def build_filters() -> dict:
    with st.expander("Filtros de recomendação", expanded=False):
        top_left, top_right = st.columns([1.6, 1], gap="large")
        with top_left:
            selected_category = st.selectbox(
                "Gênero ou tema",
                options=CATEGORY_OPTIONS,
                index=0,
            )
            custom_category = st.text_input(
                "Ou digite uma categoria",
                placeholder="Ex.: fantasia sombria, romance, filosofia",
            )
        with top_right:
            limit = st.number_input(
                "Quantidade de recomendações",
                min_value=1,
                max_value=20,
                value=DEFAULT_RECOMMENDATION_LIMIT,
                step=1,
            )

        col1, col2 = st.columns(2, gap="large")
        with col1:
            selected_language = st.selectbox(
                "Idioma",
                options=list(LANGUAGE_OPTIONS.keys()),
                format_func=lambda code: LANGUAGE_OPTIONS[code],
                index=0,
            )
            selected_decade = st.selectbox(
                "Década preferida",
                options=list(DECADE_OPTIONS.keys()),
                format_func=lambda value: DECADE_OPTIONS[value],
                index=0,
            )
            exclude_same_author = st.checkbox(
                "Ignorar obras do mesmo autor",
                value=False,
            )
            include_unknown_metadata = st.checkbox(
                "Manter livros sem páginas ou ano informados",
                value=False,
            )
        with col2:
            page_range = st.select_slider(
                "Quantidade de páginas",
                options=list(range(PAGE_RANGE_MIN, PAGE_RANGE_MAX + PAGE_RANGE_STEP, PAGE_RANGE_STEP)),
                value=(PAGE_RANGE_MIN, PAGE_RANGE_MAX),
                format_func=format_page_range_value,
            )

    category = custom_category.strip() or selected_category.strip()
    min_year, max_year = decade_to_year_bounds(selected_decade)
    min_pages = page_range[0] if page_range[0] > PAGE_RANGE_MIN else None
    max_pages = page_range[1] if page_range[1] < PAGE_RANGE_MAX else None

    filters: dict = {}

    if min_pages is not None:
        filters["min_pages"] = min_pages
    if max_pages is not None:
        filters["max_pages"] = max_pages
    if min_year is not None:
        filters["min_year"] = min_year
    if max_year is not None:
        filters["max_year"] = max_year
    if selected_decade:
        filters["decade"] = selected_decade
    if category:
        filters["category"] = category
    if selected_language:
        filters["language"] = selected_language
    if exclude_same_author:
        filters["exclude_same_author"] = True
    if include_unknown_metadata:
        filters["include_unknown_metadata"] = True
    if int(limit) != DEFAULT_RECOMMENDATION_LIMIT:
        filters["limit"] = int(limit)

    return filters


def render_book_card(
    book: dict,
    show_score: bool = False,
    position: int | None = None,
    reference: dict | None = None,
) -> None:
    st.markdown('<div class="result-card">', unsafe_allow_html=True)
    image_col, content_col = st.columns([1, 3.2], gap="large")

    with image_col:
        render_cover_image(book, frame_class="book-cover-frame", empty_class="book-cover-empty")

    with content_col:
        if position is not None:
            st.caption(f"Recomendação {position}")
        if show_score and isinstance(book.get("score"), (int, float)):
            st.markdown(
                f'<div class="score-pill">Afinidade {book["score"]:.0%}</div>',
                unsafe_allow_html=True,
            )
        st.subheader(book.get("title") or "Sem título")
        reasons = build_match_reasons(book, reference=reference)
        if reasons:
            reason_chips = "".join(f'<div class="insight-pill">{escape(reason)}</div>' for reason in reasons)
            st.markdown(f'<div class="insight-row">{reason_chips}</div>', unsafe_allow_html=True)

        authors = escape(", ".join(book.get("authors", [])) or "Desconhecido")
        categories = escape(", ".join(book.get("categories", [])) or "N/A")
        language = escape(format_language_label(book.get("language")))
        pages = escape(format_pages_label(book))
        year = escape(format_year_label(book))
        st.markdown(
            f"""
            <div class="meta-row">
                <div class="meta-pill">Autores: {authors}</div>
                <div class="meta-pill">Categorias: {categories}</div>
                <div class="meta-pill">Idioma: {language}</div>
                <div class="meta-pill">{pages}</div>
                <div class="meta-pill">{year}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if book.get("description"):
            with st.expander("Ver descrição"):
                st.write(book["description"])

    st.markdown("</div>", unsafe_allow_html=True)


def render_reference_shelf(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    st.markdown('<div class="shelf-strip"></div>', unsafe_allow_html=True)
    columns = st.columns(min(4, len(candidates)), gap="large")

    for index, book in enumerate(candidates):
        selected_id = st.session_state.get("selected_reference_id", "")
        is_selected = selected_id == book.get("id")
        with columns[index % len(columns)]:
            st.markdown('<div class="reference-card-shell">', unsafe_allow_html=True)
            render_cover_image(book, frame_class="reference-cover-frame", empty_class="reference-cover-empty")

            title = escape(book.get("title", "Sem título"))
            authors = escape(", ".join(book.get("authors", [])[:2]) or "Autor desconhecido")
            year = escape(format_year_label(book))
            categories = escape(", ".join(book.get("categories", [])[:2]) or "Gênero N/A")
            language = escape(format_language_label(book.get("language")))
            selected_class = " is-selected" if is_selected else ""
            st.markdown(
                f"""
                <div class="reference-card-body">
                    <div class="reference-choice{selected_class}">
                    <div class="reference-choice-title">{title}</div>
                    <div class="reference-choice-meta">{authors}</div>
                    <div class="reference-choice-meta">{year}</div>
                    <div class="reference-choice-meta">{categories}</div>
                    <div class="reference-choice-meta">Idioma: {language}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown('<div class="reference-card-action">', unsafe_allow_html=True)
            if st.button(
                "Selecionado" if is_selected else "Selecionar",
                key=f"select-reference-{book.get('id', index)}",
                width="stretch",
                disabled=is_selected,
            ):
                st.session_state["selected_reference_id"] = book.get("id", "")
                st.rerun()
            st.markdown("</div></div>", unsafe_allow_html=True)

    selected_id = st.session_state.get("selected_reference_id", "")
    if not selected_id:
        return None

    for book in candidates:
        if book.get("id") == selected_id:
            return book

    return None


def render_cover_image(book: dict, frame_class: str, empty_class: str) -> None:
    thumbnail = (book.get("thumbnail") or "").strip()
    title = escape(book.get("title", "Livro"), quote=True)
    if thumbnail:
        safe_thumbnail = escape(thumbnail, quote=True)
        image_markup = (
            f'<div class="{frame_class}"><img src="{safe_thumbnail}" '
            f'alt="Capa de {title}" loading="lazy" '
            'referrerpolicy="no-referrer"></div>'
        )
        st.markdown(image_markup, unsafe_allow_html=True)
        return

    st.markdown(
        f'<div class="{frame_class}"><div class="{empty_class}">Sem capa disponível</div></div>',
        unsafe_allow_html=True,
    )


def initialize_session_state() -> None:
    defaults = {
        "reference_candidates": [],
        "reference_query": "",
        "reference_offset": 0,
        "reference_has_more": False,
        "selected_reference_id": "",
        "author_candidates": [],
        "author_query": "",
        "author_works": [],
        "author_works_owner_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_recommendation_results(data: dict, filters: dict) -> None:
    reference = data["reference"]
    recommendations = data["recommendations"]

    render_filter_summary(filters)
    render_section_header("Referência", "Obra usada como base")
    render_book_card(reference)

    render_section_header("Resultados", f"{len(recommendations)} recomendações encontradas")
    if not recommendations:
        st.info("Nenhum resultado encontrado com os filtros aplicados.")
        return

    for index, book in enumerate(recommendations, start=1):
        render_book_card(book, show_score=True, position=index, reference=reference)


def render_book_search_mode() -> None:
    render_section_header("Livro", "Buscar livro")

    with st.form("book-search-form"):
        input_col1, input_col2 = st.columns(2, gap="large")
        with input_col1:
            title = st.text_input(
                "Título ou ISBN",
                placeholder="Ex.: Duna, 1984, O Hobbit, No Longer Human",
                key="book_title_input",
            )
        with input_col2:
            author = st.text_input(
                "Autor (opcional)",
                placeholder="Ex.: Frank Herbert, George Orwell",
                key="book_author_input",
            )
        submitted = st.form_submit_button("Buscar livros", width="stretch")

    current_query = f"{title.strip()}::{author.strip()}"
    if current_query != st.session_state.get("reference_query") and not submitted:
        clear_reference_candidates()

    if submitted:
        if not title.strip():
            st.warning("Informe um título ou ISBN.")
            clear_reference_candidates()
        else:
            with st.spinner("Buscando livros..."):
                candidates = search_reference_books(
                    title.strip(),
                    author.strip(),
                    max_results=BOOK_SEARCH_PAGE_SIZE,
                )
            st.session_state["reference_candidates"] = candidates
            st.session_state["reference_query"] = current_query
            st.session_state["reference_offset"] = BOOK_SEARCH_PAGE_SIZE
            st.session_state["reference_has_more"] = bool(candidates)
            st.session_state["selected_reference_id"] = ""

    candidates = st.session_state.get("reference_candidates", [])
    if not candidates:
        return

    if st.session_state.get("reference_has_more"):
        if st.button("Carregar mais resultados", width="stretch"):
            offset = int(st.session_state.get("reference_offset", BOOK_SEARCH_PAGE_SIZE))
            with st.spinner("Buscando mais livros..."):
                incoming = search_reference_books(
                    title.strip(),
                    author.strip(),
                    max_results=BOOK_SEARCH_PAGE_SIZE,
                    offset=offset,
                )
            candidates = merge_reference_candidate_pages(candidates, incoming)
            st.session_state["reference_candidates"] = candidates
            st.session_state["reference_offset"] = offset + BOOK_SEARCH_PAGE_SIZE
            st.session_state["reference_has_more"] = bool(incoming)

    render_section_header("Referência", "Escolha a obra")
    selected_reference = render_reference_shelf(candidates)
    if not selected_reference:
        return

    filters = build_filters()
    render_filter_summary(filters)
    if not st.button("Buscar recomendações com esta obra", type="primary", width="stretch"):
        return

    authors = selected_reference.get("authors", [])
    with st.spinner("Buscando recomendações..."):
        data = get_recommendations(
            selected_reference.get("title", ""),
            authors[0] if authors else author.strip(),
            filters,
            reference_id=selected_reference.get("id", ""),
        )
    if data:
        render_recommendation_results(data, filters)


def render_author_search_mode() -> None:
    render_section_header("Autor", "Buscar autor")

    with st.form("author-search-form"):
        query = st.text_input(
            "Nome do autor",
            placeholder="Ex.: Clarice Lispector, Machado de Assis, Ursula K. Le Guin",
            key="author_search_input",
        )
        submitted = st.form_submit_button("Buscar autor", width="stretch")

    if submitted:
        if not query.strip():
            st.warning("Informe o nome do autor.")
        else:
            with st.spinner("Buscando autores..."):
                authors = search_authors(query.strip())
            st.session_state["author_candidates"] = authors
            st.session_state["author_query"] = query.strip()
            st.session_state["author_works"] = []
            st.session_state["author_works_owner_id"] = ""
            st.session_state["selected_reference_id"] = ""
            if authors:
                st.session_state["selected_author_id"] = authors[0].get("id", "")
            else:
                st.session_state.pop("selected_author_id", None)

    authors = st.session_state.get("author_candidates", [])
    if not authors:
        return

    author_by_id = {author["id"]: author for author in authors if author.get("id")}
    author_ids = list(author_by_id)
    selected_author_id = st.selectbox(
        "Autor encontrado",
        options=author_ids,
        format_func=lambda author_id: (
            f'{author_by_id[author_id].get("name", "Autor desconhecido")} '
            f'({author_by_id[author_id].get("work_count", 0)} obras)'
        ),
        key="selected_author_id",
    )
    selected_author = author_by_id[selected_author_id]
    details = []
    if selected_author.get("birth_date"):
        details.append(f'Nascimento: {selected_author["birth_date"]}')
    if selected_author.get("top_work"):
        details.append(f'Obra em destaque: {selected_author["top_work"]}')
    if details:
        st.caption(" | ".join(details))

    if st.button("Carregar obras deste autor", width="stretch"):
        with st.spinner("Carregando bibliografia..."):
            st.session_state["author_works"] = get_author_works(
                selected_author_id,
                selected_author.get("name", ""),
            )
            st.session_state["author_works_owner_id"] = selected_author_id
        st.session_state["selected_reference_id"] = ""

    works = (
        st.session_state.get("author_works", [])
        if st.session_state.get("author_works_owner_id") == selected_author_id
        else []
    )
    if not works:
        return

    render_section_header(
        "Bibliografia",
        f'{len(works)} obras de {selected_author.get("name", "Autor")}',
    )
    selected_work = render_reference_shelf(works)
    if not selected_work:
        return

    filters = build_filters()
    render_filter_summary(filters)
    if not st.button("Recomendar a partir da obra selecionada", type="primary", width="stretch"):
        return

    with st.spinner("Buscando recomendações..."):
        data = get_recommendations(
            selected_work.get("title", ""),
            selected_author.get("name", ""),
            filters,
            reference_id=selected_work.get("id", ""),
        )
    if data:
        render_recommendation_results(data, filters)


def main() -> None:
    st.set_page_config(
        page_title="Book-it Babi",
        page_icon="./assets/Book-it Babi Logo 2.png",
        layout="wide",
    )

    st.logo("./assets/Book-it Babi Logo 2.png", size="large")
    st.title("Book-it")
    st.caption("Por Babi :)")
    apply_page_styles()
    initialize_session_state()

    search_mode = st.radio(
        "O que você quer buscar?",
        options=["Livro", "Autor"],
        horizontal=True,
        key="search_mode",
    )
    if search_mode == "Autor":
        render_author_search_mode()
    else:
        render_book_search_mode()

if __name__ == "__main__":
    main()
