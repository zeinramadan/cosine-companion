import numpy as np
import pandas as pd
import pytest

from core.loader import _validate_index_data


def _embeddings(ids: list[str], dim: int = 2) -> pd.DataFrame:
    data = {"track_id": ids}
    data.update({f"v{i}": np.zeros(len(ids), dtype=np.float32) for i in range(dim)})
    return pd.DataFrame(data)


def test_validate_index_data_rejects_row_count_mismatch() -> None:
    with pytest.raises(ValueError, match="2 track IDs.*3 vector rows"):
        _validate_index_data(np.zeros((3, 2)), ["a", "b"], _embeddings(["a", "b"]))


def test_validate_index_data_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate track IDs"):
        _validate_index_data(np.zeros((2, 2)), ["a", "a"], _embeddings(["a", "b"]))


def test_validate_index_data_rejects_embedding_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="dimension is 3.*has 2 vector columns"):
        _validate_index_data(np.zeros((2, 3)), ["a", "b"], _embeddings(["a", "b"]))
