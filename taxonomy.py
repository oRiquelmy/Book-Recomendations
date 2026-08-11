from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Literal

from metadata_normalizer import contains_normalized_phrase, normalize_text

CategoryKind = Literal["genre", "audience", "form", "topic"]


@dataclass(frozen=True)
class Taxon:
    label: str
    kind: CategoryKind
    aliases: tuple[str, ...]
    search_terms: tuple[str, ...]
    parents: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    generic: bool = False


# A taxonomia é controlada: cobre categorias frequentes nas APIs, mantém aliases
# PT/EN e representa relações entre subgêneros sem apagar o metadado original.
TAXONOMY: dict[str, Taxon] = {
    "fiction": Taxon(
        "Ficção",
        "genre",
        ("fiction", "ficcao"),
        ("fiction",),
        families=("fiction",),
        generic=True,
    ),
    "literary_fiction": Taxon(
        "Ficção literária",
        "genre",
        ("literary fiction", "ficcao literaria", "literatura ficcional"),
        ("literary fiction",),
        parents=("fiction",),
        families=("fiction", "literary"),
    ),
    "historical_fiction": Taxon(
        "Ficção histórica",
        "genre",
        ("historical fiction", "ficcao historica", "romance historico", "period fiction"),
        ("historical fiction",),
        parents=("fiction",),
        families=("fiction", "historical"),
    ),
    "adventure": Taxon(
        "Aventura",
        "genre",
        ("adventure", "adventure fiction", "aventura", "ficcao de aventura"),
        ("adventure fiction", "adventure"),
        parents=("fiction",),
        families=("fiction", "adventure"),
    ),
    "fantasy": Taxon(
        "Fantasia",
        "genre",
        ("fantasy", "fantasia", "fantasy fiction", "ficcao fantastica"),
        ("fantasy",),
        parents=("fiction",),
        families=("fiction", "speculative"),
    ),
    "epic_fantasy": Taxon(
        "Fantasia épica",
        "genre",
        (
            "epic fantasy",
            "high fantasy",
            "fantasia epica",
            "alta fantasia",
            "fantasy epic",
        ),
        ("epic fantasy", "high fantasy"),
        parents=("fantasy",),
        families=("fiction", "speculative", "fantasy"),
    ),
    "dark_fantasy": Taxon(
        "Fantasia sombria",
        "genre",
        ("dark fantasy", "fantasia sombria", "grimdark"),
        ("dark fantasy", "grimdark"),
        parents=("fantasy",),
        families=("fiction", "speculative", "fantasy", "dark"),
    ),
    "urban_fantasy": Taxon(
        "Fantasia urbana",
        "genre",
        (
            "urban fantasy",
            "fantasia urbana",
            "contemporary fantasy",
            "fantasy urban",
        ),
        ("urban fantasy",),
        parents=("fantasy",),
        families=("fiction", "speculative", "fantasy", "contemporary"),
    ),
    "magical_realism": Taxon(
        "Realismo mágico",
        "genre",
        ("magical realism", "magic realism", "realismo magico", "realismo fantastico"),
        ("magical realism",),
        parents=("literary_fiction", "fantasy"),
        families=("fiction", "literary", "speculative"),
    ),
    "science_fiction": Taxon(
        "Ficção científica",
        "genre",
        (
            "science fiction",
            "science-fiction",
            "sci fi",
            "sci-fi",
            "scifi",
            "ficcao cientifica",
            "ficcao especulativa cientifica",
        ),
        ("science fiction",),
        parents=("fiction",),
        families=("fiction", "speculative"),
    ),
    "space_opera": Taxon(
        "Space opera",
        "genre",
        ("space opera", "opera espacial", "space adventure"),
        ("space opera",),
        parents=("science_fiction",),
        families=("fiction", "speculative", "science_fiction"),
    ),
    "cyberpunk": Taxon(
        "Cyberpunk",
        "genre",
        ("cyberpunk", "cyber punk", "tecno distopia", "tech noir"),
        ("cyberpunk",),
        parents=("science_fiction",),
        families=("fiction", "speculative", "science_fiction", "dystopian"),
    ),
    "dystopia": Taxon(
        "Distopia",
        "genre",
        ("dystopia", "dystopian", "dystopian fiction", "distopia", "ficcao distopica"),
        ("dystopian fiction", "dystopia"),
        parents=("science_fiction",),
        families=("fiction", "speculative", "science_fiction", "dystopian"),
    ),
    "romance": Taxon(
        "Romance",
        "genre",
        ("romance", "romance fiction", "romantic fiction", "ficcao romantica", "love stories"),
        ("romance fiction", "romance"),
        parents=("fiction",),
        families=("fiction", "romance"),
    ),
    "historical_romance": Taxon(
        "Romance de época",
        "genre",
        (
            "historical romance",
            "romance de epoca",
            "romance historico de epoca",
            "period romance",
            "romance historical",
        ),
        ("historical romance",),
        parents=("romance", "historical_fiction"),
        families=("fiction", "romance", "historical"),
    ),
    "contemporary_romance": Taxon(
        "Romance contemporâneo",
        "genre",
        (
            "contemporary romance",
            "romance contemporaneo",
            "modern romance",
            "romance contemporary",
        ),
        ("contemporary romance",),
        parents=("romance",),
        families=("fiction", "romance", "contemporary"),
    ),
    "paranormal_romance": Taxon(
        "Romance paranormal",
        "genre",
        ("paranormal romance", "romance paranormal", "supernatural romance"),
        ("paranormal romance",),
        parents=("romance", "fantasy"),
        families=("fiction", "romance", "speculative", "fantasy"),
    ),
    "mystery": Taxon(
        "Mistério",
        "genre",
        ("mystery", "mystery fiction", "misterio", "detective fiction", "detective stories"),
        ("mystery fiction", "detective fiction"),
        parents=("fiction",),
        families=("fiction", "crime_suspense"),
    ),
    "crime_fiction": Taxon(
        "Ficção policial",
        "genre",
        (
            "crime fiction",
            "crime novel",
            "policial",
            "ficcao policial",
            "romance policial",
            "noir fiction",
            "police procedural",
            "mystery detective police procedural",
            "thrillers crime",
        ),
        ("crime fiction", "detective fiction"),
        parents=("fiction",),
        families=("fiction", "crime_suspense"),
    ),
    "thriller": Taxon(
        "Thriller",
        "genre",
        (
            "thriller",
            "thrillers",
            "suspense",
            "suspense fiction",
            "thriller fiction",
        ),
        ("thriller", "suspense fiction"),
        parents=("fiction",),
        families=("fiction", "crime_suspense"),
    ),
    "psychological_thriller": Taxon(
        "Thriller psicológico",
        "genre",
        (
            "psychological thriller",
            "thriller psicologico",
            "psychological suspense",
            "thriller psychological",
            "thrillers psychological",
        ),
        ("psychological thriller",),
        parents=("thriller",),
        families=("fiction", "crime_suspense", "psychological"),
    ),
    "cozy_mystery": Taxon(
        "Mistério cozy",
        "genre",
        (
            "cozy mystery",
            "cosy mystery",
            "cozy mysteries",
            "cozy crime",
            "misterio cozy",
            "mystery cozy",
            "mystery detective cozy",
        ),
        ("cozy mystery",),
        parents=("mystery",),
        families=("fiction", "crime_suspense", "cozy"),
    ),
    "horror": Taxon(
        "Terror",
        "genre",
        ("horror", "horror fiction", "terror", "ficcao de terror", "supernatural horror"),
        ("horror fiction", "horror"),
        parents=("fiction",),
        families=("fiction", "speculative", "dark"),
    ),
    "gothic": Taxon(
        "Gótico",
        "genre",
        ("gothic", "gothic fiction", "ficcao gotica", "literatura gotica"),
        ("gothic fiction",),
        parents=("horror",),
        families=("fiction", "dark", "literary"),
    ),
    "humor": Taxon(
        "Humor",
        "genre",
        ("humor", "humour", "comic fiction", "satire", "satira", "comedia"),
        ("humorous fiction", "satire"),
        parents=("fiction",),
        families=("fiction", "humor"),
    ),
    "western": Taxon(
        "Faroeste",
        "genre",
        ("western", "western fiction", "faroeste", "old west fiction"),
        ("western fiction",),
        parents=("fiction",),
        families=("fiction", "adventure", "historical"),
    ),
    "young_adult": Taxon(
        "Jovem adulto",
        "audience",
        ("young adult", "young adult fiction", "ya fiction", "ficcao juvenil", "literatura juvenil", "teen fiction"),
        ("young adult fiction",),
        families=("young_readers",),
    ),
    "children": Taxon(
        "Infantil",
        "audience",
        (
            "children",
            "childrens fiction",
            "children's fiction",
            "kids",
            "infantil",
            "literatura infantil",
            "juvenile fiction",
        ),
        ("children's fiction", "juvenile fiction"),
        families=("young_readers",),
    ),
    "classics": Taxon(
        "Clássicos",
        "form",
        ("classics", "classic literature", "classic fiction", "classicos", "literatura classica"),
        ("classic literature",),
        families=("literary",),
    ),
    "short_stories": Taxon(
        "Contos",
        "form",
        ("short stories", "short story", "contos", "conto", "story collections"),
        ("short stories",),
        families=("literary",),
    ),
    "essays": Taxon(
        "Ensaios",
        "form",
        ("essays", "essay collections", "ensaios", "coletanea de ensaios"),
        ("essays",),
        families=("literary", "nonfiction"),
    ),
    "drama": Taxon(
        "Teatro e drama",
        "form",
        ("drama", "plays", "theater", "theatre", "teatro", "pecas teatrais"),
        ("drama", "plays"),
        families=("literary", "performing_arts"),
    ),
    "poetry": Taxon(
        "Poesia",
        "form",
        ("poetry", "poems", "poesia", "poemas"),
        ("poetry",),
        families=("literary",),
    ),
    "graphic_novel": Taxon(
        "Graphic novel",
        "form",
        (
            "graphic novel",
            "graphic novels",
            "quadrinhos",
            "historia em quadrinhos",
            "comics",
            "manga",
        ),
        ("graphic novels",),
        families=("visual_narrative",),
    ),
    "biography": Taxon(
        "Biografia",
        "topic",
        ("biography", "biographies", "biografia", "autobiography", "autobiografia"),
        ("biography",),
        families=("life_writing", "nonfiction"),
    ),
    "nonfiction": Taxon(
        "Não ficção",
        "topic",
        ("nonfiction", "non-fiction", "nao ficcao", "general nonfiction"),
        ("nonfiction",),
        families=("nonfiction",),
        generic=True,
    ),
    "memoir": Taxon(
        "Memórias",
        "topic",
        ("memoir", "memoirs", "memorias", "personal narrative"),
        ("memoir",),
        parents=("biography",),
        families=("life_writing", "nonfiction"),
    ),
    "history": Taxon(
        "História",
        "topic",
        ("history", "historia", "world history", "social history", "military history"),
        ("history",),
        families=("humanities", "nonfiction", "historical"),
    ),
    "philosophy": Taxon(
        "Filosofia",
        "topic",
        ("philosophy", "filosofia", "ethics", "etica", "metaphysics", "metafisica"),
        ("philosophy",),
        families=("humanities", "nonfiction"),
    ),
    "psychology": Taxon(
        "Psicologia",
        "topic",
        ("psychology", "psicologia", "behavioral science", "cognitive psychology", "social psychology"),
        ("psychology",),
        parents=("social_science",),
        families=("social_science", "nonfiction", "psychological"),
    ),
    "self_help": Taxon(
        "Autoajuda",
        "topic",
        ("self help", "self improvement", "autoajuda", "desenvolvimento pessoal", "personal development"),
        ("self-help", "personal development"),
        families=("personal_development", "nonfiction"),
    ),
    "business": Taxon(
        "Negócios",
        "topic",
        ("business", "negocios", "management", "gestao", "administracao", "entrepreneurship", "empreendedorismo"),
        ("business", "management"),
        families=("business", "nonfiction"),
    ),
    "economics": Taxon(
        "Economia",
        "topic",
        ("economics", "economia", "finance", "financas", "economic policy"),
        ("economics", "finance"),
        parents=("business", "social_science"),
        families=("business", "social_science", "nonfiction"),
    ),
    "science": Taxon(
        "Ciência",
        "topic",
        ("science", "ciencia", "popular science", "natural sciences", "scientific"),
        ("popular science", "science"),
        families=("stem", "nonfiction"),
    ),
    "technology": Taxon(
        "Tecnologia",
        "topic",
        ("technology", "tecnologia", "computer science", "computacao", "software", "programming", "programacao"),
        ("technology", "computer science"),
        families=("stem", "nonfiction"),
    ),
    "politics": Taxon(
        "Política",
        "topic",
        ("politics", "politica", "political science", "government", "governo", "public policy"),
        ("politics", "political science"),
        parents=("social_science",),
        families=("humanities", "social_science", "nonfiction"),
    ),
    "religion": Taxon(
        "Religião",
        "topic",
        ("religion", "religiao", "theology", "teologia"),
        ("religion", "theology"),
        families=("humanities", "nonfiction"),
    ),
    "spirituality": Taxon(
        "Espiritualidade",
        "topic",
        (
            "spirituality",
            "espiritualidade",
            "body mind spirit",
            "body mind and spirit",
            "corpo mente e espirito",
        ),
        ("spirituality",),
        families=("humanities", "personal_development", "nonfiction"),
    ),
    "true_crime": Taxon(
        "True crime",
        "topic",
        ("true crime", "crime real", "criminal cases", "casos criminais"),
        ("true crime",),
        families=("crime_suspense", "nonfiction"),
    ),
    "social_science": Taxon(
        "Ciências sociais",
        "topic",
        (
            "social science",
            "social sciences",
            "ciencias sociais",
            "sociology",
            "sociologia",
            "anthropology",
            "antropologia",
        ),
        ("social science",),
        families=("social_science", "nonfiction"),
    ),
    "education": Taxon(
        "Educação",
        "topic",
        ("education", "educacao", "teaching", "ensino", "pedagogy", "pedagogia"),
        ("education", "teaching"),
        families=("social_science", "nonfiction"),
    ),
    "law": Taxon(
        "Direito",
        "topic",
        ("law", "legal", "direito", "jurisprudence", "jurisprudencia", "legislation"),
        ("law",),
        families=("social_science", "nonfiction"),
    ),
    "health_medicine": Taxon(
        "Saúde e medicina",
        "topic",
        (
            "health",
            "medicine",
            "medical",
            "saude",
            "medicina",
            "wellness",
            "fitness",
            "health and fitness",
            "public health",
        ),
        ("health", "medicine"),
        families=("stem", "health", "nonfiction"),
    ),
    "mathematics": Taxon(
        "Matemática",
        "topic",
        ("mathematics", "math", "matematica", "statistics", "estatistica"),
        ("mathematics",),
        parents=("science",),
        families=("stem", "nonfiction"),
    ),
    "nature_environment": Taxon(
        "Natureza e meio ambiente",
        "topic",
        (
            "nature",
            "natural history",
            "environment",
            "environmental science",
            "natureza",
            "meio ambiente",
            "ecology",
            "ecologia",
        ),
        ("nature", "environment"),
        parents=("science",),
        families=("stem", "nature", "nonfiction"),
    ),
    "cooking": Taxon(
        "Culinária",
        "topic",
        ("cooking", "cookbooks", "cookery", "culinaria", "receitas", "gastronomy", "gastronomia"),
        ("cooking", "cookbooks"),
        families=("lifestyle", "nonfiction"),
    ),
    "travel": Taxon(
        "Viagem",
        "topic",
        ("travel", "travel writing", "travel guide", "viagem", "turismo", "guias de viagem"),
        ("travel",),
        families=("lifestyle", "places", "nonfiction"),
    ),
    "art_design": Taxon(
        "Arte e design",
        "topic",
        (
            "art",
            "arts",
            "arte",
            "design",
            "architecture",
            "arquitetura",
            "photography",
            "fotografia",
        ),
        ("art", "design"),
        families=("arts", "nonfiction"),
    ),
    "literary_criticism": Taxon(
        "Crítica literária",
        "topic",
        (
            "literary criticism",
            "critica literaria",
            "literary studies",
            "estudos literarios",
            "literature criticism",
        ),
        ("literary criticism",),
        families=("humanities", "literary", "nonfiction"),
    ),
    "music": Taxon(
        "Música",
        "topic",
        ("music", "musica", "music history", "music theory", "teoria musical"),
        ("music",),
        families=("arts", "performing_arts", "nonfiction"),
    ),
    "sports": Taxon(
        "Esportes",
        "topic",
        ("sports", "sport", "esportes", "esporte", "athletics"),
        ("sports",),
        families=("lifestyle", "health", "nonfiction"),
    ),
    "crafts_hobbies": Taxon(
        "Hobbies e artesanato",
        "topic",
        (
            "crafts",
            "hobbies",
            "handicrafts",
            "artesanato",
            "passatempos",
            "do it yourself",
            "diy",
        ),
        ("crafts", "hobbies"),
        families=("lifestyle", "nonfiction"),
    ),
    "language_linguistics": Taxon(
        "Idiomas e linguística",
        "topic",
        (
            "language",
            "languages",
            "linguistics",
            "idiomas",
            "linguistica",
            "grammar",
            "gramatica",
        ),
        ("linguistics", "language study"),
        families=("humanities", "nonfiction"),
    ),
    "parenting": Taxon(
        "Parentalidade",
        "topic",
        ("parenting", "parenthood", "parentalidade", "criacao de filhos", "family guidance"),
        ("parenting",),
        families=("personal_development", "family", "nonfiction"),
    ),
    "family_relationships": Taxon(
        "Família e relacionamentos",
        "topic",
        (
            "family and relationships",
            "family relationships",
            "familia e relacionamentos",
            "relationships",
            "relacionamentos",
        ),
        ("family relationships",),
        families=("personal_development", "family", "nonfiction"),
    ),
    "reference": Taxon(
        "Referência",
        "topic",
        (
            "reference",
            "reference books",
            "encyclopedias",
            "encyclopedia",
            "dictionaries",
            "dicionarios",
        ),
        ("reference",),
        families=("reference", "nonfiction"),
    ),
    "mythology_folklore": Taxon(
        "Mitologia e folclore",
        "topic",
        (
            "mythology",
            "myths",
            "folklore",
            "mitologia",
            "mitos",
            "folclore",
            "fairy tales",
            "contos de fadas",
        ),
        ("mythology", "folklore"),
        families=("humanities", "speculative", "nonfiction"),
    ),
}

_KIND_WEIGHTS: dict[CategoryKind, float] = {
    "genre": 0.58,
    "topic": 0.24,
    "audience": 0.11,
    "form": 0.07,
}

_EXPLICIT_RELATED: dict[frozenset[str], float] = {
    frozenset(("mystery", "crime_fiction")): 0.78,
    frozenset(("mystery", "thriller")): 0.66,
    frozenset(("crime_fiction", "thriller")): 0.70,
    frozenset(("fantasy", "gothic")): 0.58,
    frozenset(("dark_fantasy", "horror")): 0.68,
    frozenset(("literary_fiction", "historical_fiction")): 0.55,
    frozenset(("literary_fiction", "classics")): 0.68,
    frozenset(("biography", "history")): 0.45,
    frozenset(("psychology", "self_help")): 0.52,
    frozenset(("history", "politics")): 0.48,
    frozenset(("magical_realism", "literary_fiction")): 0.86,
    frozenset(("magical_realism", "fantasy")): 0.86,
    frozenset(("western", "adventure")): 0.60,
    frozenset(("cozy_mystery", "crime_fiction")): 0.72,
    frozenset(("health_medicine", "psychology")): 0.48,
    frozenset(("nature_environment", "science")): 0.72,
    frozenset(("mythology_folklore", "religion")): 0.58,
    frozenset(("mythology_folklore", "fantasy")): 0.62,
    frozenset(("education", "psychology")): 0.44,
    frozenset(("literary_fiction", "literary_criticism")): 0.52,
    frozenset(("religion", "spirituality")): 0.72,
    frozenset(("self_help", "spirituality")): 0.44,
    frozenset(("parenting", "family_relationships")): 0.76,
}


@dataclass(frozen=True)
class TaxonomyProfile:
    genre: frozenset[str] = frozenset()
    audience: frozenset[str] = frozenset()
    form: frozenset[str] = frozenset()
    topic: frozenset[str] = frozenset()

    @property
    def all_ids(self) -> frozenset[str]:
        return self.genre | self.audience | self.form | self.topic

    def by_kind(self, kind: CategoryKind) -> frozenset[str]:
        return getattr(self, kind)


@lru_cache(maxsize=512)
def _normalized_aliases(taxon_id: str) -> tuple[str, ...]:
    taxon = TAXONOMY[taxon_id]
    aliases = {
        normalize_text(taxon.label),
        *(normalize_text(alias) for alias in taxon.aliases),
    }
    return tuple(
        sorted(
            (alias for alias in aliases if alias),
            key=lambda value: (-len(value.split()), -len(value)),
        )
    )


def category_ids_from_text(value: object) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()

    matches: list[tuple[str, str]] = []
    for taxon_id in TAXONOMY:
        for alias in _normalized_aliases(taxon_id):
            if contains_normalized_phrase(normalized, alias):
                matches.append((taxon_id, alias))
                break

    # Mantém os rótulos mais específicos. Sem isso, "science fiction" também
    # viraria os taxons genéricos "science" e "fiction".
    maximal_matches: set[str] = set()
    for taxon_id, alias in matches:
        shadowed = any(
            other_alias != alias
            and len(other_alias.split()) > len(alias.split())
            and contains_normalized_phrase(other_alias, alias)
            for _, other_alias in matches
        )
        if not shadowed:
            maximal_matches.add(taxon_id)

    return maximal_matches


def taxonomy_profile(categories: Iterable[str] | str | None) -> TaxonomyProfile:
    if isinstance(categories, str):
        categories = [categories]

    grouped: dict[CategoryKind, set[str]] = {
        "genre": set(),
        "audience": set(),
        "form": set(),
        "topic": set(),
    }
    for category in categories or []:
        for taxon_id in category_ids_from_text(category):
            grouped[TAXONOMY[taxon_id].kind].add(taxon_id)

    for kind, taxon_ids in grouped.items():
        if any(not TAXONOMY[taxon_id].generic for taxon_id in taxon_ids):
            grouped[kind] = {
                taxon_id
                for taxon_id in taxon_ids
                if not TAXONOMY[taxon_id].generic
            }

    return TaxonomyProfile(
        genre=frozenset(grouped["genre"]),
        audience=frozenset(grouped["audience"]),
        form=frozenset(grouped["form"]),
        topic=frozenset(grouped["topic"]),
    )


def _ancestors(taxon_id: str) -> set[str]:
    found: set[str] = set()
    pending = list(TAXONOMY[taxon_id].parents)
    while pending:
        parent = pending.pop()
        if parent in found or parent not in TAXONOMY:
            continue
        found.add(parent)
        pending.extend(TAXONOMY[parent].parents)
    return found


def taxon_pair_similarity(left_id: str, right_id: str) -> float:
    if left_id == right_id:
        if left_id not in TAXONOMY:
            return 0.0
        return 0.22 if TAXONOMY[left_id].generic else 1.0
    if left_id not in TAXONOMY or right_id not in TAXONOMY:
        return 0.0

    left = TAXONOMY[left_id]
    right = TAXONOMY[right_id]
    if left.kind != right.kind:
        return _EXPLICIT_RELATED.get(frozenset((left_id, right_id)), 0.0)

    left_ancestors = _ancestors(left_id)
    right_ancestors = _ancestors(right_id)
    if right_id in left_ancestors or left_id in right_ancestors:
        ancestor_id = right_id if right_id in left_ancestors else left_id
        return 0.18 if TAXONOMY[ancestor_id].generic else 0.86

    explicit = _EXPLICIT_RELATED.get(frozenset((left_id, right_id)))
    if explicit is not None:
        return explicit

    common_ancestors = left_ancestors & right_ancestors
    if common_ancestors:
        if any(not TAXONOMY[ancestor].generic for ancestor in common_ancestors):
            return 0.66
        shared_specific_families = (
            set(left.families) & set(right.families)
        ) - {"fiction", "nonfiction"}
        return 0.52 if shared_specific_families else 0.16

    shared_families = (set(left.families) & set(right.families)) - {
        "fiction",
        "nonfiction",
    }
    if not shared_families:
        return 0.12 if set(left.families) & set(right.families) else 0.0
    if left.kind == "genre":
        return 0.46 if "speculative" in shared_families or "crime_suspense" in shared_families else 0.34
    return 0.38


def _set_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0

    left_best = [max(taxon_pair_similarity(item, other) for other in right) for item in left]
    right_best = [max(taxon_pair_similarity(item, other) for other in left) for item in right]
    return (sum(left_best) / len(left_best) + sum(right_best) / len(right_best)) / 2


def _cross_kind_similarity(left: TaxonomyProfile, right: TaxonomyProfile) -> float:
    best = 0.0
    for left_id in left.all_ids:
        for right_id in right.all_ids:
            if TAXONOMY[left_id].kind == TAXONOMY[right_id].kind:
                continue
            best = max(best, taxon_pair_similarity(left_id, right_id))
    # Relações entre eixos diferentes são úteis, mas não equivalem a compartilhar
    # o mesmo gênero/tema. O redutor impede que uma ponte isolada domine o score.
    return best * 0.70


def taxonomy_similarity(
    left_categories: Iterable[str] | str | None,
    right_categories: Iterable[str] | str | None,
) -> float:
    left = taxonomy_profile(left_categories)
    right = taxonomy_profile(right_categories)

    weighted_sum = 0.0
    available_weight = 0.0
    for kind, weight in _KIND_WEIGHTS.items():
        left_values = left.by_kind(kind)
        right_values = right.by_kind(kind)
        if not left_values or not right_values:
            continue
        weighted_sum += _set_similarity(left_values, right_values) * weight
        available_weight += weight

    same_kind_score = weighted_sum / available_weight if available_weight else 0.0
    return max(same_kind_score, _cross_kind_similarity(left, right))


def category_filter_match(requested: str | None, categories: Iterable[str] | str | None) -> bool:
    requested_normalized = normalize_text(requested)
    if not requested_normalized:
        return True

    requested_ids = category_ids_from_text(requested_normalized)
    candidate_profile = taxonomy_profile(categories)
    candidate_ids = candidate_profile.all_ids
    if requested_ids and candidate_ids:
        for requested_id in requested_ids:
            for candidate_id in candidate_ids:
                if requested_id == candidate_id:
                    return True
                if requested_id in _ancestors(candidate_id) or candidate_id in _ancestors(requested_id):
                    return True
        return False

    raw_categories = [categories] if isinstance(categories, str) else categories or []
    candidate_values = [normalize_text(category) for category in raw_categories]
    requested_tokens = set(requested_normalized.split())
    for category in candidate_values:
        if contains_normalized_phrase(category, requested_normalized):
            return True
        category_tokens = set(category.split())
        if requested_tokens and requested_tokens.issubset(category_tokens):
            return True
    return False


def taxonomy_search_terms(
    categories: Iterable[str] | str | None,
    *,
    include_related: bool = True,
    limit: int = 8,
) -> list[str]:
    profile = taxonomy_profile(categories)
    ids = list(profile.genre) + list(profile.topic) + list(profile.audience) + list(profile.form)
    ids.sort(key=lambda taxon_id: (TAXONOMY[taxon_id].generic, len(_ancestors(taxon_id)), taxon_id), reverse=True)

    terms: list[str] = []
    seen: set[str] = set()

    def add_term(term: str) -> None:
        normalized = normalize_text(term)
        if not normalized or normalized in seen or len(terms) >= limit:
            return
        seen.add(normalized)
        terms.append(term)

    for taxon_id in ids:
        taxon = TAXONOMY[taxon_id]
        if taxon.generic:
            continue
        for term in taxon.search_terms[:2]:
            add_term(term)

    if include_related and len(terms) < limit:
        for taxon_id in ids:
            related = sorted(
                (
                    (other_id, taxon_pair_similarity(taxon_id, other_id))
                    for other_id, other in TAXONOMY.items()
                    if other.kind == TAXONOMY[taxon_id].kind and other_id != taxon_id
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            for other_id, similarity in related:
                if similarity < 0.64:
                    break
                for term in TAXONOMY[other_id].search_terms[:1]:
                    add_term(term)
                if len(terms) >= limit:
                    break
            if len(terms) >= limit:
                break

    return terms[:limit]


def category_labels(categories: Iterable[str] | str | None) -> list[str]:
    profile = taxonomy_profile(categories)
    ids = list(profile.genre) + list(profile.topic) + list(profile.audience) + list(profile.form)
    return [TAXONOMY[taxon_id].label for taxon_id in ids]


def category_options() -> list[str]:
    """Rótulos canônicos disponíveis para filtros na interface."""
    return [
        taxon.label
        for taxon in TAXONOMY.values()
        if not taxon.generic
    ]
