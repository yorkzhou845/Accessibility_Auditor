import math

from vector_store import _cosine_similarity


def test_cosine_similarity_identical_vectors():
    assert math.isclose(_cosine_similarity([1.0, 2.0], [1.0, 2.0]), 1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
