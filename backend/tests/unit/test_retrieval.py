from norte_legal.domain.retrieval import RRF_K, fuse, lexical_query


def test_lexical_query_keeps_useful_terms_only() -> None:
    assert lexical_query("¿Cuál es el plazo de PREAVISO para la terminación?") == (
        "plazo | preaviso | terminación"
    )
    assert lexical_query("¿Y de la que?") is None


def test_lexical_query_cannot_inject_tsquery_syntax() -> None:
    query = lexical_query("pago & !(multa) | 'x' <-> :*")
    assert query == "pago | multa"


def test_rrf_rewards_chunks_found_by_both_searches() -> None:
    fused = fuse([("a", 0.9), ("b", 0.8)], ["b", "c"], min_similarity=0.0)
    assert [c.chunk_id for c in fused] == ["b", "a", "c"]
    assert fused[0].score == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)


def test_vector_only_candidates_below_the_threshold_are_dropped() -> None:
    fused = fuse([("weak", 0.1), ("strong", 0.6)], ["lexical"], min_similarity=0.3)
    assert {c.chunk_id for c in fused} == {"strong", "lexical"}
