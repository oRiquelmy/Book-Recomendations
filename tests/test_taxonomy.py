from taxonomy import (
    category_filter_match,
    taxonomy_profile,
    taxonomy_search_terms,
    taxonomy_similarity,
)


def test_taxonomy_normalizes_portuguese_english_and_subgenres() -> None:
    profile = taxonomy_profile(
        ["Ficção científica", "Space Opera", "Literatura juvenil"]
    )
    assert "science_fiction" in profile.genre
    assert "space_opera" in profile.genre
    assert "young_adult" in profile.audience


def test_subgenre_filter_matches_parent_genre_in_both_directions() -> None:
    assert category_filter_match("fantasia sombria", ["Fantasy"])
    assert category_filter_match("fantasia", ["Dark Fantasy"])


def test_related_genres_score_higher_than_unrelated_topics() -> None:
    related = taxonomy_similarity(["Science Fiction"], ["Dystopian Fiction"])
    unrelated = taxonomy_similarity(["Science Fiction"], ["Business"])
    assert related >= 0.80
    assert unrelated == 0.0


def test_taxonomy_generates_provider_friendly_search_terms() -> None:
    terms = taxonomy_search_terms(["Ficção científica"], include_related=True, limit=5)
    assert terms[0] == "science fiction"
    assert any(term in terms for term in {"space opera", "dystopian fiction", "cyberpunk"})


def test_specific_alias_does_not_add_generic_or_unrelated_taxons() -> None:
    profile = taxonomy_profile(["Science Fiction"])
    assert profile.genre == frozenset({"science_fiction"})
    assert not profile.topic


def test_portuguese_historical_romance_label_is_unambiguous() -> None:
    from taxonomy import category_options

    profile = taxonomy_profile(["Romance de época"])
    assert profile.genre == frozenset({"historical_romance"})
    assert "Romance de época" in category_options()


def test_common_nonfiction_categories_are_canonicalized() -> None:
    profile = taxonomy_profile(
        ["Cookbooks", "Public Health", "Environmental Science", "Social Sciences"]
    )
    assert profile.topic == frozenset(
        {"cooking", "health_medicine", "nature_environment", "social_science"}
    )


def test_specific_multword_category_shadows_generic_science() -> None:
    assert taxonomy_profile(["Computer Science"]).topic == frozenset({"technology"})
    assert taxonomy_profile(["Environmental Science"]).topic == frozenset(
        {"nature_environment"}
    )


def test_new_subgenres_keep_parent_relationships() -> None:
    assert taxonomy_similarity(["Urban Fantasy"], ["Dark Fantasy"]) >= 0.60
    assert taxonomy_similarity(["Cozy Mystery"], ["Mystery"]) >= 0.80
    assert taxonomy_similarity(["Romance paranormal"], ["Fantasy"]) >= 0.80


def test_provider_categories_do_not_collapse_into_adjacent_topics() -> None:
    assert taxonomy_profile(["Literary Criticism"]).topic == frozenset(
        {"literary_criticism"}
    )
    assert taxonomy_profile(["Health & Fitness"]).topic == frozenset(
        {"health_medicine"}
    )
    assert taxonomy_profile(["Family & Relationships"]).topic == frozenset(
        {"family_relationships"}
    )
    assert taxonomy_profile(["Body, Mind & Spirit"]).topic == frozenset(
        {"spirituality"}
    )


def test_generic_nonfiction_is_removed_when_specific_topic_exists() -> None:
    assert taxonomy_profile(["Nonfiction / Psychology"]).topic == frozenset(
        {"psychology"}
    )


def test_common_provider_hierarchies_resolve_to_specific_subgenres() -> None:
    cases = {
        "FICTION / Fantasy / Epic": {"epic_fantasy"},
        "FICTION / Fantasy / Urban": {"urban_fantasy"},
        "FICTION / Romance / Historical / General": {"historical_romance"},
        "FICTION / Romance / Contemporary": {"contemporary_romance"},
        "FICTION / Thrillers / Psychological": {"psychological_thriller"},
        "FICTION / Mystery & Detective / Cozy": {"cozy_mystery"},
        "FICTION / Mystery & Detective / Police Procedural": {"crime_fiction"},
    }

    for raw_category, expected in cases.items():
        profile = taxonomy_profile([raw_category])
        assert expected.issubset(profile.genre), (raw_category, profile)


def test_curated_cross_kind_bridges_are_weaker_than_same_kind_matches() -> None:
    fantasy_mythology = taxonomy_similarity(["Fantasy"], ["Mythology"])
    exact_fantasy = taxonomy_similarity(["Fantasy"], ["Fantasy"])
    literary_criticism = taxonomy_similarity(
        ["Literary Fiction"],
        ["Literary Criticism"],
    )

    assert 0.40 <= fantasy_mythology < exact_fantasy
    assert 0.0 < literary_criticism < fantasy_mythology
