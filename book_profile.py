from collections import Counter
from dataclasses import dataclass

from metadata_normalizer import contains_normalized_phrase, normalize_text, tokenize_text
from models import BookResponse
from taxonomy import taxonomy_profile

_STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "between",
    "book",
    "books",
    "chapter",
    "chapters",
    "classic",
    "classics",
    "collection",
    "como",
    "com",
    "conta",
    "contos",
    "da",
    "das",
    "de",
    "del",
    "des",
    "do",
    "dos",
    "during",
    "edition",
    "edicao",
    "editions",
    "entre",
    "essay",
    "essays",
    "esta",
    "este",
    "from",
    "historia",
    "historias",
    "into",
    "livro",
    "livros",
    "mais",
    "memoir",
    "memoirs",
    "nas",
    "nos",
    "novel",
    "novella",
    "novels",
    "numa",
    "num",
    "obra",
    "obras",
    "para",
    "pela",
    "pelas",
    "pelo",
    "pelos",
    "poem",
    "poems",
    "poesia",
    "poetry",
    "por",
    "sobre",
    "story",
    "stories",
    "through",
    "uma",
    "umas",
    "with",
}

_THEME_KEYWORDS = {
    "identity": {
        "ancestry", "autodescoberta", "autonomy", "belonging", "coming of age",
        "identidade", "identity", "origin", "origem", "self discovery", "selfhood",
    },
    "family": {
        "brother", "child", "daughter", "familia", "family", "father", "filho",
        "irma", "irmao", "mae", "marriage", "mother", "parent", "sister", "son",
    },
    "love": {
        "affair", "amor", "desire", "love", "paixao", "relationship", "romance",
    },
    "death": {
        "afterlife", "alem tumulo", "death", "dying", "funeral", "grief", "luto",
        "morte", "morto", "mourning",
    },
    "memory": {
        "lembranca", "memoria", "memoir", "memory", "nostalgia", "passado",
        "recordacao", "remembrance", "remembering",
    },
    "politics": {
        "activism", "ativismo", "estado", "government", "governo", "politica",
        "political", "politics", "revolution", "revolucao", "state",
    },
    "social_critique": {
        "bourgeois", "burguesia", "capitalism", "capitalismo", "class inequality",
        "classe", "critica social", "elite", "injustice", "satire of manners",
        "social criticism", "social critique", "sociedade", "society",
    },
    "race": {
        "black", "diaspora", "enslavement", "escravidao", "racial", "race",
        "racism", "racismo",
    },
    "colonialism": {
        "colonial", "colonialismo", "colonia", "colony", "empire", "imperial",
        "imperio", "postcolonial",
    },
    "philosophy": {
        "ethics", "existencial", "existential", "filosofia", "filosofico", "meaning",
        "metaphysical", "metaphysics", "moral", "morality", "philosophical", "philosophy",
    },
    "psychology": {
        "inner life", "madness", "mente", "mental", "obsessao", "obsession",
        "psychological", "psychology", "psicologico", "psyche", "trauma",
    },
    "history": {
        "historical", "historico", "historia", "history", "period drama",
        "period piece",
    },
    "war": {
        "battle", "batalha", "combat", "conflito", "conflict", "guerra", "military", "war",
    },
    "adventure": {
        "adventure", "aventura", "epic quest", "expedicao", "expedition", "journey", "quest", "viagem",
    },
    "mystery": {
        "crime", "detective", "investigacao", "investigation", "misterio", "mystery", "secret", "segredo",
    },
    "fantasy": {
        "dragon", "epic fantasy", "fantasia", "fantasy", "kingdom", "magic", "magia", "magical", "reino", "sorcery",
    },
    "science_fiction": {
        "alien", "android", "ciencia ficcao", "ficcao cientifica", "dystopian future",
        "future", "futuristic", "science fiction", "scifi", "space", "speculative fiction",
    },
    "dystopia": {
        "authoritarian", "distopia", "dystopia", "oppression", "opressao", "regime", "surveillance", "totalitarian",
    },
    "technology": {
        "algorithm", "computer", "dados", "data", "digital", "engineering", "software",
        "sistema", "system", "tecnologia", "technology",
    },
    "science": {
        "astronomy", "biology", "ciencia", "cientifico", "experiment", "mathematics",
        "physics", "science", "scientific",
    },
    "religion": {
        "church", "faith", "god", "mythology", "religiao", "religion", "sacred", "spiritual",
    },
}

_TONE_KEYWORDS = {
    "dark": {"bleak", "dark", "gloomy", "melancolico", "melancholic", "somber", "sombrio", "tragic", "tragico"},
    "hopeful": {"delicado", "gentle", "heartwarming", "hopeful", "inspiring", "leve", "optimistic", "uplifting"},
    "humorous": {"comic", "comico", "engracado", "funny", "humor", "humorous", "ironic", "ironia", "satirical"},
    "reflective": {"contemplative", "introspective", "meditacao", "meditative", "reflective", "reflexao", "reflexivo"},
    "tense": {"claustrophobic", "gripping", "suspense", "suspenseful", "tense", "thrilling", "urgency"},
    "lyrical": {"elegant prose", "evocative", "lirico", "lyrical", "poetic", "poetico"},
}

_NARRATIVE_KEYWORDS = {
    "first_person": {"diary", "eu", "first person", "journal", "memoir style", "my story", "narrated by"},
    "unreliable_narrator": {"contradicao", "ironia dramatica", "nao confiavel", "unreliable", "unreliable narrator"},
    "essayistic": {"digressao", "essayistic", "fragmentary reflection", "reflection", "reflexao"},
    "epic_scope": {"epic", "family saga", "generations", "geracoes", "multi generational", "saga"},
    "multiple_perspectives": {"alternating voices", "ensemble cast", "multiple perspectives", "multiple viewpoints"},
    "non_linear": {"dual timeline", "fragmented", "non linear", "out of order", "parallel timeline"},
}

_CATEGORY_KIND_KEYWORDS = {
    "literary_fiction": {
        "classic fiction", "classics", "contemporary literary fiction", "literary",
        "literary fiction", "literature",
    },
    "genre_fiction": {
        "crime fiction", "fantasy", "ficcao cientifica", "ficcao especulativa", "horror",
        "mystery", "science fiction", "speculative", "suspense", "thriller",
    },
    "nonfiction": {
        "autobiography", "biography", "essays", "history", "memoir", "nonfiction", "politics", "true crime",
    },
    "technical": {
        "computer science", "data science", "engineering", "mathematics", "medicine", "programming", "software", "technology",
    },
    "academic": {
        "academic", "analysis", "criticism", "reference", "research", "scholarship", "study", "theory",
    },
    "children_middle_grade": {
        "children", "juvenile", "kids", "middle grade", "young readers",
    },
    "young_adult": {
        "teen", "ya", "young adult",
    },
}

_AUDIENCE_KEYWORDS = {
    "children": {"children", "infantil", "kids", "juvenile", "young readers"},
    "young_adult": {"adolescente", "teen", "teens", "ya", "young adult"},
    "adult": {"adult fiction", "adult nonfiction", "mature readers"},
}

_PACE_KEYWORDS = {
    "fast_paced": {"action packed", "fast paced", "page turner", "propulsive", "rapid fire"},
    "slow_burn": {"atmospheric", "character driven", "gradual", "slow burn", "unfolds slowly"},
}

_SERIES_TERMS = {
    "book", "livro", "volume", "vol", "part", "parte", "series", "serie", "saga", "chronicles",
}

_THEME_BY_TAXON = {
    "adventure": "adventure",
    "fantasy": "fantasy",
    "epic_fantasy": "fantasy",
    "dark_fantasy": "fantasy",
    "urban_fantasy": "fantasy",
    "magical_realism": "fantasy",
    "science_fiction": "science_fiction",
    "space_opera": "science_fiction",
    "cyberpunk": "technology",
    "dystopia": "dystopia",
    "romance": "love",
    "historical_romance": "love",
    "contemporary_romance": "love",
    "paranormal_romance": "love",
    "mystery": "mystery",
    "crime_fiction": "mystery",
    "thriller": "mystery",
    "psychological_thriller": "psychology",
    "cozy_mystery": "mystery",
    "western": "adventure",
    "history": "history",
    "philosophy": "philosophy",
    "psychology": "psychology",
    "science": "science",
    "technology": "technology",
    "politics": "politics",
    "religion": "religion",
    "spirituality": "religion",
    "social_science": "social_critique",
    "law": "politics",
    "nature_environment": "science",
    "mythology_folklore": "religion",
    "family_relationships": "family",
}

_GENRE_FICTION_TAXONS = {
    "fantasy", "epic_fantasy", "dark_fantasy", "urban_fantasy", "magical_realism",
    "science_fiction", "space_opera", "cyberpunk", "dystopia", "romance",
    "historical_romance", "contemporary_romance", "paranormal_romance", "mystery",
    "crime_fiction", "thriller", "psychological_thriller", "cozy_mystery",
    "horror", "gothic", "adventure", "humor", "western",
}
_LITERARY_TAXONS = {"literary_fiction", "historical_fiction", "classics", "short_stories"}
_TECHNICAL_TAXONS = {"science", "technology", "mathematics", "health_medicine"}
_NONFICTION_TAXONS = {
    "biography", "memoir", "history", "philosophy", "psychology", "self_help",
    "nonfiction", "business", "economics", "science", "technology", "politics", "religion",
    "spirituality",
    "true_crime", "social_science", "education", "law", "health_medicine",
    "mathematics", "nature_environment", "cooking", "travel", "art_design",
    "music", "sports", "crafts_hobbies", "language_linguistics", "parenting",
    "family_relationships", "literary_criticism", "reference", "mythology_folklore", "essays",
}


@dataclass(frozen=True)
class BookProfile:
    themes: frozenset[str]
    tones: frozenset[str]
    narrative_markers: frozenset[str]
    category_kinds: frozenset[str]
    audiences: frozenset[str]
    pace_markers: frozenset[str]
    keywords: frozenset[str]


def _build_corpus_parts(book: BookResponse) -> list[str]:
    # Nome de autor não é sinal temático e pode gerar falsos positivos.
    return [
        book.title or "",
        book.description or "",
        *book.categories,
    ]


def _build_corpus(book: BookResponse) -> str:
    return " ".join(part for part in _build_corpus_parts(book) if part)


def _tokenize(text: str) -> list[str]:
    return [token for token in tokenize_text(text) if len(token) >= 3]


def _is_keyword_candidate(token: str) -> bool:
    if len(token) < 4:
        return False
    if token in _STOPWORDS:
        return False
    if token.isdigit():
        return False
    if token in _SERIES_TERMS:
        return False
    return True


def _extract_keywords(book: BookResponse, limit: int = 16) -> frozenset[str]:
    weighted_sources = [
        (book.title or "", 4),
        (" ".join(book.categories), 3),
        (book.description or "", 2),
    ]

    scores: Counter[str] = Counter()
    for text, weight in weighted_sources:
        for token in _tokenize(text):
            if _is_keyword_candidate(token):
                scores[token] += weight

    keywords = [
        token
        for token, _ in scores.most_common()
        if len(token) > 4 or scores[token] > 2
    ]
    return frozenset(keywords[:limit])


def _match_labels(corpus: str, mapping: dict[str, set[str]]) -> frozenset[str]:
    matches: set[str] = set()
    for label, keywords in mapping.items():
        if any(contains_normalized_phrase(corpus, keyword) for keyword in keywords):
            matches.add(label)
    return frozenset(matches)


def extract_book_profile(book: BookResponse) -> BookProfile:
    corpus = normalize_text(_build_corpus(book))
    taxonomy = taxonomy_profile(book.categories)

    themes = set(_match_labels(corpus, _THEME_KEYWORDS))
    for taxon_id in taxonomy.all_ids:
        mapped_theme = _THEME_BY_TAXON.get(taxon_id)
        if mapped_theme:
            themes.add(mapped_theme)

    category_kinds = set(_match_labels(corpus, _CATEGORY_KIND_KEYWORDS))
    if taxonomy.all_ids & _GENRE_FICTION_TAXONS:
        category_kinds.add("genre_fiction")
    if taxonomy.all_ids & _LITERARY_TAXONS:
        category_kinds.add("literary_fiction")
    if taxonomy.all_ids & _NONFICTION_TAXONS:
        category_kinds.add("nonfiction")
    if taxonomy.all_ids & _TECHNICAL_TAXONS:
        category_kinds.add("technical")

    audiences = set(_match_labels(corpus, _AUDIENCE_KEYWORDS))
    if "young_adult" in taxonomy.audience:
        audiences.add("young_adult")
    if "children" in taxonomy.audience:
        audiences.add("children")

    return BookProfile(
        themes=frozenset(themes),
        tones=_match_labels(corpus, _TONE_KEYWORDS),
        narrative_markers=_match_labels(corpus, _NARRATIVE_KEYWORDS),
        category_kinds=frozenset(category_kinds),
        audiences=frozenset(audiences),
        pace_markers=_match_labels(corpus, _PACE_KEYWORDS),
        keywords=_extract_keywords(book),
    )


def _set_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Compara conjuntos esparsos sem a penalidade excessiva do Jaccard puro."""
    if not left or not right:
        return 0.0

    intersection = len(left & right)
    if not intersection:
        return 0.0

    overlap = intersection / min(len(left), len(right))
    dice = (2 * intersection) / (len(left) + len(right))
    return 0.65 * overlap + 0.35 * dice


def profile_component_scores(reference: BookProfile, candidate: BookProfile) -> dict[str, float]:
    return {
        "themes": _set_overlap(reference.themes, candidate.themes),
        "tones": _set_overlap(reference.tones, candidate.tones),
        "narrative_markers": _set_overlap(reference.narrative_markers, candidate.narrative_markers),
        "category_kinds": _set_overlap(reference.category_kinds, candidate.category_kinds),
        "audiences": _set_overlap(reference.audiences, candidate.audiences),
        "pace_markers": _set_overlap(reference.pace_markers, candidate.pace_markers),
        "keywords": _set_overlap(reference.keywords, candidate.keywords),
    }


def profile_overlap_score(reference: BookProfile, candidate: BookProfile) -> float:
    component_scores = profile_component_scores(reference, candidate)
    return (
        component_scores["themes"] * 0.34
        + component_scores["tones"] * 0.14
        + component_scores["narrative_markers"] * 0.14
        + component_scores["category_kinds"] * 0.14
        + component_scores["audiences"] * 0.08
        + component_scores["pace_markers"] * 0.06
        + component_scores["keywords"] * 0.10
    )
