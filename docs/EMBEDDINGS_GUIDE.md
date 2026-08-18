# Embeddings Extraction, Storage & Similarity Search

> **Related Documentation:**
> - [System Architecture](SYSTEM_ARCHITECTURE.md) - High-level architecture and component design
> - [Program Flow](PROGRAM_FLOW.md) - Detailed execution flow and data pipelines

Technical documentation for Cosine Companion's audio embedding pipeline and vector similarity search system.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Embedding Extraction](#2-embedding-extraction)
3. [Storage Format](#3-storage-format)
4. [Exact NumPy Index](#4-exact-numpy-index)
5. [Similarity Search](#5-similarity-search)
6. [Scoring System](#6-scoring-system)
7. [Code Reference](#7-code-reference)

---

## 1. Overview

The system uses a three-stage pipeline to find similar tracks:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Audio File  │ ──▶ │  Essentia   │ ──▶ │   Storage   │ ──▶ │ Exact NumPy │
│   (.mp3)    │     │  Embedding  │     │  (Parquet)  │     │   Search    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

| Stage | Technology | Output |
|-------|------------|--------|
| Extraction | Essentia + TensorFlow | 2,560-dim float32 vector |
| Storage | Parquet + NumPy | Columnar files on disk |
| Search | NumPy matrix multiplication | Exact top-k nearest neighbors |

---

## 2. Embedding Extraction

### 2.1 Model

| Attribute | Value |
|-----------|-------|
| **Model** | Discogs-EffNet |
| **File** | `discogs_multi_embeddings-effnet-bs64-1.pb` |
| **Size** | ~300 MB |
| **Architecture** | EfficientNet (TensorFlow) |
| **Source** | [Essentia Models](https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/) |

The model was trained on the Discogs music database and captures:
- Genre/style characteristics
- Timbre and texture
- Energy and mood
- Instrumentation patterns

### 2.2 Extraction Process

**Location:** `src/processing/embeddings.py`

```
Audio File
    │
    ▼
┌─────────────────────────────────┐
│  MonoLoader (Essentia)          │
│  - Resample to 32kHz            │
│  - Convert to mono              │
│  - Quality level: 4             │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  TensorflowPredictEffnetDiscogs │
│  - Output: frame-wise embeddings│
│  - Shape: (frames, features)    │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  Temporal Pooling               │
│  - Mean across time axis        │
│  - Std across time axis         │
│  - Concatenate: [mean, std]     │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  L2 Normalization               │
│  - v = v / ||v||                │
│  - Enables cosine via dot prod  │
└─────────────────────────────────┘
    │
    ▼
  2,560-dim float32 vector (1,280 mean + 1,280 std)
```

### 2.3 Implementation

```python
class DiscogsEffnetEmbedder:
    def __init__(self, model_path=None, sr=32000):
        self.sr = sr
        self.pred = es.TensorflowPredictEffnetDiscogs(
            graphFilename=str(model_path),
            output="PartitionedCall:1"  # Embedding layer
        )

    def embed_file(self, path_local: str) -> np.ndarray:
        # Load and resample audio
        audio = es.MonoLoader(
            filename=path_local,
            sampleRate=self.sr,
            resampleQuality=4
        )()

        # Get frame-wise predictions
        Y = np.asarray(self.pred(audio))

        # Pool across time dimension
        if Y.ndim == 2:
            pooled = np.concatenate([Y.mean(axis=0), Y.std(axis=0)])
        else:
            pooled = Y

        # L2 normalize for cosine similarity
        pooled = pooled / (np.linalg.norm(pooled) + 1e-9)
        return pooled.astype("float32")
```

### 2.4 Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `sampleRate` | 32000 Hz | Model's expected sample rate |
| `resampleQuality` | 4 | High-quality resampling |
| `output` | `PartitionedCall:1` | TensorFlow output node for embeddings |

---

## 3. Storage Format

### 3.1 File Structure

```
data/
├── meta.parquet          # Track metadata
├── embeddings.parquet    # Embedding vectors
├── index.npy             # NumPy vector array
└── ids.json              # Track ID ordering
```

### 3.2 Embeddings Parquet Schema

**File:** `embeddings.parquet`

| Column | Type | Description |
|--------|------|-------------|
| `track_id` | string | Unique track identifier |
| `v0` | float32 | Embedding dimension 0 |
| `v1` | float32 | Embedding dimension 1 |
| ... | ... | ... |
| `v2559` | float32 | Embedding dimension 2559 |

**Total columns:** 2,561 (1 ID + 2,560 embedding dimensions)

### 3.3 Vector Array

**File:** `index.npy`

```python
# Shape: (num_tracks, 2560)
# Dtype: float32
# Content: L2-normalized embedding vectors

vectors = np.load("data/index.npy")
# vectors.shape → (4000, 2560) for 4000 tracks
```

### 3.4 Track ID Mapping

**File:** `ids.json`

```json
["track_123", "track_456", "track_789", ...]
```

The order matches the row order in `index.npy`, enabling index-to-ID lookup.

### 3.5 Storage Sizes

| Tracks | embeddings.parquet | index.npy | Total |
|--------|-------------------|-----------|-------|
| 1,000 | ~5 MB | ~1 MB | ~6 MB |
| 5,000 | ~25 MB | ~5 MB | ~30 MB |
| 10,000 | ~50 MB | ~10 MB | ~60 MB |
| 50,000 | ~250 MB | ~50 MB | ~300 MB |

### 3.6 Persistence Code

**Location:** `src/core/persistence.py`

```python
def save_index_data(meta_df, embeddings_df, vectors, track_ids):
    # Metadata
    meta_df.to_parquet(META_PQ, index=False)

    # Embeddings (for recomputation/verification)
    embeddings_df.to_parquet(EMB_PQ, index=False)

    # Vectors (for exact cosine index rebuilding)
    np.save(IDX_NPY, vectors)

    # ID mapping
    with open(IDS_JSON, "w") as f:
        json.dump(track_ids, f)
```

---

## 4. Exact NumPy Index

The in-memory index is one normalized float32 matrix. Every query computes
cosine similarity against the entire collection, so candidate selection has no
approximation or recall loss.

### 4.1 Configuration

**Location:** `src/core/index_builder.py`

| Parameter | Value | Description |
|-----------|-------|-------------|
| `dim` | 2,560 | Vector dimension |
| `dtype` | float32 | Matrix and query representation |
| `metric` | Inner product | Exact cosine on normalized vectors |
| `selection` | `argpartition` + sort | Select top-k, then order descending |

### 4.2 Implementation

```python
class NumpyCosIndex:
    def __init__(self, dim: int):
        self.dim = dim
        self.matrix = np.empty((0, dim), dtype=np.float32)
        self.ids: List[str] = []

    def add(self, track_id: str, v: np.ndarray) -> None:
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        self.matrix = np.concatenate((self.matrix, v[np.newaxis, :]))
        self.ids.append(track_id)

    def search(self, v: np.ndarray, k: int = 50) -> List[Tuple[str, float]]:
        k = min(k, len(self.ids))
        if k <= 0:
            return []
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        scores = self.matrix @ v
        candidates = np.argpartition(scores, len(scores) - k)[-k:]
        ranked = candidates[np.lexsort((candidates, -scores[candidates]))]
        return [(self.ids[i], float(scores[i])) for i in ranked]
```

### 4.3 Performance Characteristics

| Operation | Complexity | Accuracy |
|-----------|------------|----------|
| Add | O(n × d) matrix copy | Exact stored vector |
| Query scores | O(n × d) | 100% of collection scored |
| Top-k selection | O(n) average + O(k log k) sort | Exact top-k |
| Memory | O(n × d) | No graph/index overhead |

---

## 5. Similarity Search

### 5.1 Search Flow

```
┌─────────────────┐
│  Query Track    │
│  (track_id)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Load Vector    │
│  from emb_ix    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Exact Cosine    │
│ Search k=200+1  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Filter Self    │
│  (deleted tracks are removed at index time) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Score Key/BPM  │
│  Compatibility  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Final Score    │
│  & Rank         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Return Top 15  │
└─────────────────┘
```

### 5.2 Implementation

**Location:** `src/recommendations/engine.py`

```python
def recommend_for(
    track_id: str,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    topk: int = 200,
    final_top: int = 15
) -> List[Dict]:

    # Get query vector
    v = vector_for(track_id, emb_ix)
    if v is None:
        return []

    src = meta_ix.loc[track_id]

    # Exact cosine search over the full collection
    nbrs = idx.search(v, k=topk + 1)

    out = []
    for tid, cos in nbrs:
        if tid == track_id:
            continue

        m = meta_ix.loc[tid]

        # Musical compatibility
        ks = key_compat(src.get("key"), m.get("key"))
        bs = bpm_compat(src.get("bpm"), m.get("bpm"))

        # Weighted final score
        score = final_score(cos, ks, bs)

        out.append({
            "track_id": tid,
            "artist": m.get("artist"),
            "title": m.get("title"),
            "bpm": m.get("bpm"),
            "key": m.get("key"),
            "score": score,
            "cosine": cos,
            "key_score": ks,
            "bpm_score": bs,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:final_top]
```

### 5.3 Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `topk` | 200 | Exact cosine candidates |
| `final_top` | 15 | Results returned by default |

**Why 200 → 15?**
- Every collection vector is scored before the top 200 are selected
- Key/BPM scoring reranks candidates; diverse pool needed
- Final 15 provides good UX without overwhelming user

**UI override:** The Explore tab requests more candidates (`topk=500`, `final_top=200`) and then sorts by cosine similarity, truncating the list based on the Top-N selector.

---

## 6. Scoring System

### 6.1 Final Score Formula

```
final_score = 0.7 × cosine + 0.2 × key_score + 0.1 × bpm_score
```

| Component | Weight | Range | Source |
|-----------|--------|-------|--------|
| Cosine | 70% | [0, 1] | Audio similarity |
| Key | 20% | [0, 1] | Harmonic compatibility |
| BPM | 10% | [0, 1] | Tempo compatibility |

### 6.2 Cosine Similarity

Measures sonic similarity between tracks:

```python
cosine = np.dot(v1, v2)  # Both L2-normalized
# Range: [-1, 1], typically [0.3, 0.95] for music
```

| Cosine Value | Interpretation |
|--------------|----------------|
| > 0.85 | Very similar (same genre/style) |
| 0.70 - 0.85 | Similar (good for mixing) |
| 0.50 - 0.70 | Somewhat related |
| < 0.50 | Different styles |

### 6.3 Key Compatibility (Camelot Wheel)

**Location:** `src/recommendations/scoring.py`

```
        ┌─────────────────────────────────┐
        │        CAMELOT WHEEL            │
        │                                 │
        │     12A        1A        2A     │
        │       ╲       /  ╲      /       │
        │   11A   ╲   /      ╲  /   3A    │
        │     │    ╲/    ●    ╲/    │     │
        │   10A ───── center ───── 4A     │
        │     │    /╲         /╲    │     │
        │    9A  /    ╲     /    ╲ 5A     │
        │       /      ╲   /      ╲       │
        │     8A        7A        6A      │
        │                                 │
        │   Inner (A) = Minor keys        │
        │   Outer (B) = Major keys        │
        └─────────────────────────────────┘
```

| Relationship | Score | Example |
|--------------|-------|---------|
| Same key | 1.0 | 8A → 8A |
| Adjacent (±1) | 0.8 | 8A → 7A or 9A |
| Relative (A↔B) | 0.6 | 8A → 8B |
| Two steps (±2) | 0.4 | 8A → 6A or 10A |
| Incompatible | 0.0 | 8A → 3A |

```python
def key_compat(src: str, dst: str) -> float:
    s = to_camelot(src)  # "Am" → "8A"
    d = to_camelot(dst)

    if s == d:
        return 1.0

    sn, sm = int(s[:-1]), s[-1]  # 8, "A"
    dn, dm = int(d[:-1]), d[-1]

    # Adjacent on wheel
    if sm == dm and ((sn - dn) % 12 in (1, 11)):
        return 0.8

    # Relative major/minor
    if sn == dn and sm != dm:
        return 0.6

    # Two steps away
    if sm == dm and ((sn - dn) % 12 in (2, 10)):
        return 0.4

    return 0.0
```

### 6.4 BPM Compatibility

**Location:** `src/recommendations/scoring.py`

| Relationship | Score | Example |
|--------------|-------|---------|
| Within 6% | 1.0 | 128 ↔ 121-135 BPM |
| Half-time (within 6%) | 0.7 | 128 ↔ 61-68 BPM |
| Double-time (within 6%) | 0.7 | 64 ↔ 121-135 BPM |
| Outside tolerance | 0.0 | 128 ↔ 90 BPM |

```python
def bpm_compat(sbpm: float, dbpm: float, pct: float = 0.06) -> float:
    if not sbpm or not dbpm:
        return 0.0

    lo, hi = sbpm * (1 - pct), sbpm * (1 + pct)

    # Direct match
    if lo <= dbpm <= hi:
        return 1.0

    # Half or double time
    for mult in (0.5, 2.0):
        b = sbpm * mult
        lo, hi = b * (1 - pct), b * (1 + pct)
        if lo <= dbpm <= hi:
            return 0.7

    return 0.0
```

---

## 7. Code Reference

### 7.1 Key Files

| File | Purpose |
|------|---------|
| `src/processing/embeddings.py` | `DiscogsEffnetEmbedder` class |
| `src/core/index_builder.py` | `NumpyCosIndex` class |
| `src/core/persistence.py` | Save/load functions |
| `src/recommendations/engine.py` | `recommend_for()` function |
| `src/recommendations/scoring.py` | Key/BPM scoring functions |
| `src/config/defaults.py` | Default parameters |

### 7.2 Key Functions

```python
# Embedding extraction
embedder = DiscogsEffnetEmbedder(model_path)
vector = embedder.embed_file("/path/to/audio.mp3")

# Index building
index = NumpyCosIndex(dim=2560)
index.add(track_id, vector)

# Similarity search
neighbors = index.search(query_vector, k=200)

# Recommendations
results = recommend_for(track_id, meta_ix, emb_ix, index)

# Scoring
key_score = key_compat("Am", "Gm")  # → 0.8
bpm_score = bpm_compat(128.0, 126.0)  # → 1.0
score = final_score(0.85, 0.8, 1.0)  # → 0.855
```

### 7.3 Data Flow Summary

```
                         INDEXING
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Audio   │───▶│ Essentia │───▶│  Store   │───▶│  NumPy   │
│  Files   │    │ Embedder │    │ Parquet  │    │  Matrix  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘

                         QUERYING
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Track   │───▶│  Exact   │───▶│  Score   │───▶│  Top 15  │
│  Select  │    │  Cosine  │    │ Key/BPM  │    │ Results  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

---

*Document generated for Cosine Companion*
