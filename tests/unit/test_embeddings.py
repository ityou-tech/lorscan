"""CardImageIndex unit tests — no model load, pure data + lookup."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lorscan.services.embeddings import EMBEDDING_DIM, CardImageIndex, Match


def _rand_embedding(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(EMBEDDING_DIM).astype(np.float32)


def test_index_normalizes_on_construction():
    raw = np.stack([_rand_embedding(s) for s in range(5)])
    index = CardImageIndex(card_ids=[f"c{i}" for i in range(5)], embeddings=raw)
    norms = np.linalg.norm(index.embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_index_construction_validates_shape():
    with pytest.raises(ValueError):
        CardImageIndex(card_ids=["a", "b"], embeddings=np.zeros((1, EMBEDDING_DIM)))


def test_index_self_match_is_perfect():
    """Querying with one of the index's own vectors returns it as the top match."""
    raw = np.stack([_rand_embedding(s) for s in range(8)])
    index = CardImageIndex(card_ids=[f"card-{i}" for i in range(8)], embeddings=raw)

    # Query is exactly one of the indexed vectors.
    matches = index.find_matches(raw[3], top_k=3)
    assert len(matches) == 3
    assert matches[0].card_id == "card-3"
    assert matches[0].similarity > 0.99


def test_index_find_matches_returns_top_k_in_descending_order():
    raw = np.stack([_rand_embedding(s) for s in range(20)])
    index = CardImageIndex(card_ids=[f"c{i}" for i in range(20)], embeddings=raw)
    matches = index.find_matches(raw[7], top_k=5)
    sims = [m.similarity for m in matches]
    assert sims == sorted(sims, reverse=True)


def test_empty_index_returns_no_matches():
    index = CardImageIndex.empty()
    matches = index.find_matches(_rand_embedding(0))
    assert matches == []


def test_save_and_load_roundtrip(tmp_path: Path):
    raw = np.stack([_rand_embedding(s) for s in range(6)])
    ids = [f"x-{i}" for i in range(6)]
    index = CardImageIndex(card_ids=ids, embeddings=raw)
    target = tmp_path / "index.npz"
    index.save(target)
    assert target.exists()

    loaded = CardImageIndex.load(target)
    assert loaded.size == 6
    assert loaded.card_ids == ids
    # Same self-match behavior.
    matches = loaded.find_matches(raw[2], top_k=1)
    assert matches[0].card_id == "x-2"


def test_match_tuple_fields():
    m = Match(card_id="abc", similarity=0.87)
    assert m.card_id == "abc"
    assert m.similarity == 0.87
