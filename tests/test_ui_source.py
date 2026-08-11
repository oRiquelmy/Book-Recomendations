from pathlib import Path


def test_intro_cards_and_defensive_copy_were_removed() -> None:
    source = Path("cli.py").read_text(encoding="utf-8")
    assert "def render_intro" not in source
    assert "hero-block" not in source
    assert "chip-card" not in source
    assert "primeiro resultado" not in source.casefold()
    assert "escolhida explicitamente" not in source.casefold()
    assert "Você pode digitar para localizar opções" not in source
    assert "este texto tem prioridade" not in source
    assert "política mais permissiva" not in source


def test_recommendation_score_is_presented_as_affinity_percentage() -> None:
    source = Path("cli.py").read_text(encoding="utf-8")
    assert 'Afinidade {book["score"]:.0%}' in source
    assert '>Score ' not in source


def test_book_search_exposes_incremental_pagination() -> None:
    source = Path("cli.py").read_text(encoding="utf-8")
    assert 'st.button("Carregar mais resultados"' in source
    assert '"reference_offset": 0' in source
    assert "merge_reference_candidate_pages" in source
