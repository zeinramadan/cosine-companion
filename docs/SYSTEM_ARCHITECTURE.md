# Cosine Companion - System Design Architecture

> **Related Documentation:**
> - [Embeddings Guide](EMBEDDINGS_GUIDE.md) - Audio embedding extraction and similarity search
> - [Program Flow](PROGRAM_FLOW.md) - Detailed execution flow and data pipelines
> - [Build Instructions](BUILD_INSTRUCTIONS.md) - Building standalone applications

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Technology Stack](#3-technology-stack)
4. [Architecture Patterns](#4-architecture-patterns)
5. [Directory Structure](#5-directory-structure)
6. [Component Deep Dive](#6-component-deep-dive)
7. [Data Flow & Pipeline](#7-data-flow--pipeline)
8. [Data Storage Layer](#8-data-storage-layer)
9. [Recommendation Engine](#9-recommendation-engine)
10. [User Interface Architecture](#10-user-interface-architecture)
11. [Build & Distribution](#11-build--distribution)
12. [External Integrations](#12-external-integrations)
13. [Configuration Management](#13-configuration-management)
14. [Performance Considerations](#14-performance-considerations)
15. [Security Considerations](#15-security-considerations)

---

## 1. Executive Summary

**Cosine Companion** is a cross-platform desktop application designed to help DJs find similar tracks and create seamless DJ sets from their music library. The current supported release target is Apple Silicon macOS; Intel macOS, Windows, and Linux paths remain documented for the existing build and path infrastructure. The application combines deep learning audio embeddings with exact, full-collection cosine search to provide intelligent music recommendations based on sonic similarity, harmonic compatibility, and tempo matching.

### Key Characteristics

| Attribute | Value |
|-----------|-------|
| **Application Type** | Desktop GUI + CLI |
| **Platforms** | Apple Silicon macOS (supported); Intel macOS, Windows, Linux infrastructure retained |
| **Primary Language** | Python 3.8+ |
| **Codebase Size** | A few thousand lines of Python (see repository) |
| **Architecture Style** | Layered architecture with mixin-based UI |
| **Data Storage** | File-based (Parquet, NumPy, JSON) |
| **ML Framework** | Essentia + TensorFlow |
| **Search Algorithm** | Exact NumPy cosine similarity |

---

## 2. System Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         COSINE COMPANION                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  CLI Entry  │    │  GUI Entry  │    │  Onboarding │                 │
│  │   (Typer)   │    │ (pywebview) │    │ Tk fallback │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│         └──────────────────┼──────────────────┘                         │
│                            ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    UI LAYER (ui/)                                │   │
│  │  ┌──────────────┬──────────────┬──────────────┬──────────────┐  │   │
│  │  │   Explore     │ Set Creator │  Playlist   │   Library    │  │   │
│  │  │     Tab       │     Tab     │ Export Tab  │     Tab      │  │   │
│  │  └──────────────┴──────────────┴──────────────┴──────────────┘  │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              RECOMMENDATION ENGINE (recommendations/)            │   │
│  │  ┌────────────┬────────────┬────────────┬────────────────────┐  │   │
│  │  │   Engine   │  Scoring   │    Set     │  Playlist Exporter │  │   │
│  │  │            │  (Key/BPM) │ Generator  │      (M3U)         │  │   │
│  │  └────────────┴────────────┴────────────┴────────────────────┘  │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                   CORE LAYER (core/)                             │   │
│  │  ┌────────────┬────────────┬────────────┬────────────────────┐  │   │
│  │  │   Loader   │ Persistence│Exact Cosine│    Duplicates/     │  │   │
│  │  │            │            │   Index    │   Deleted Tracks   │  │   │
│  │  └────────────┴────────────┴────────────┴────────────────────┘  │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                PROCESSING LAYER (processing/)                    │   │
│  │  ┌────────────┬────────────┬────────────────────────────────┐   │   │
│  │  │ XML Parser │  Pipeline  │    Embeddings (Essentia)       │   │   │
│  │  │ (Rekordbox)│            │    DiscogsEffnetEmbedder       │   │   │
│  │  └────────────┴────────────┴────────────────────────────────┘   │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                 CONFIGURATION (config/)                          │   │
│  │  ┌─────────────────────────┬────────────────────────────────┐   │   │
│  │  │        paths.py         │          defaults.py           │   │   │
│  │  │  (Platform-aware paths) │    (Weights, thresholds)       │   │   │
│  │  └─────────────────────────┴────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATA STORAGE LAYER                                │
│  ┌──────────────┬──────────────┬──────────────┬──────────────────────┐  │
│  │ meta.parquet │ embeddings.  │  index.npy   │ ids.json, settings,  │  │
│  │  (metadata)  │   parquet    │(NumPy vectors)│ deleted_tracks.json │  │
│  └──────────────┴──────────────┴──────────────┴──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Workflows

#### Indexing Workflow
```
Rekordbox XML → Parse Metadata → Detect Duplicates → Filter New Tracks
    → Load Audio → Generate Embeddings → Persist Vectors and IDs
```

#### Recommendation Workflow
```
Select Track → Exact Cosine Search (top-k) → Score by Key/BPM → Rank Results → Display
```

#### Set Generation Workflow
```
Set Anchor Tracks → Position Anchors → Fill Slots (Context-Aware) → Export M3U
```

---

## 3. Technology Stack

### 3.1 Core Technologies

| Category | Technology | Version | Purpose |
|----------|------------|---------|---------|
| **Language** | Python | 3.8+ | Primary development language |
| **GUI Frameworks** | pywebview + WKWebView; Tkinter | Current; built-in | Default web desktop UI; classic startup fallback |
| **CLI Framework** | Typer | Latest | Command-line interface |
| **Audio Analysis** | Essentia | 2.1b6+ | Audio embeddings via TensorFlow |
| **Vector Search / Data Processing** | NumPy | Latest | Exact cosine search and numerical computations |
| **Data Processing** | Pandas | Latest | Metadata management |
| **Data Storage** | PyArrow | Latest | Parquet file support |
| **XML Processing** | lxml | Latest | Rekordbox XML parsing |
| **Audio I/O** | Soundfile | Latest | Reading audio files |
| **Packaging** | PyInstaller | 5.0+ | Standalone executables |

### 3.2 Deep Learning Model

| Attribute | Value |
|-----------|-------|
| **Model** | Discogs-EffNet |
| **Architecture** | EfficientNet-based |
| **Training Data** | Discogs music database |
| **Embedding Dimension** | 256 |
| **Output** | L2-normalized embeddings |
| **File Size** | ~300MB |

### 3.3 Development & Build Tools

| Tool | Purpose |
|------|---------|
| **GitHub Actions** | CI/CD for multi-platform builds |
| **PyInstaller** | Creates standalone executables |
| **pip** | Dependency management |

---

## 4. Architecture Patterns

### 4.1 Layered Architecture

The application follows a **strict layered architecture** with unidirectional dependencies:

```
        ┌─────────────────────┐
        │     UI Layer        │  ← Depends on all layers below
        ├─────────────────────┤
        │  Recommendations    │  ← Depends on Core + Config
        ├─────────────────────┤
        │   Core + Processing │  ← Depends on Config only
        ├─────────────────────┤
        │   Configuration     │  ← Zero dependencies
        └─────────────────────┘
```

**Benefits:**
- Clear separation of concerns
- Testable components in isolation
- Easy to modify one layer without affecting others

### 4.2 Mixin Pattern (UI)

The GUI uses a **mixin-based composition** pattern to organize tab functionality:

```python
class App(
    RecommendationsTabMixin,   # Explore tab
    SetCreatorTabMixin,        # Set creation tab
    PlaylistExportTabMixin,    # Export tab
    LibraryTabMixin,           # Library management tab
    tk.Tk
):
    """Main application window composed of mixins."""
    pass
```

**Benefits:**
- Avoids monolithic 2000+ line App class
- Each mixin is self-contained
- Easy to add/remove features

### 4.3 Data Class Pattern

Track representations use Python dataclasses for type safety:

```python
@dataclass
class SetTrack:
    track_id: str
    position: int
    is_anchor: bool
    score: float = 0.0
    artist: str = ""
    title: str = ""
```

### 4.4 Lazy Import Pattern

Heavy dependencies are imported lazily to minimize startup time:

```python
def index_library(xml_path: str):
    # Heavy imports only when function is called
    from processing.pipeline import index_library
    ...
```

---

## 5. Directory Structure

```
dj-cosine/
│
├── src/                                 # Source code root
│   ├── cosine_companion.py              # CLI entry point (Typer app)
│   │
│   ├── config/                          # Configuration layer
│   │   ├── __init__.py
│   │   ├── paths.py                     # Platform-aware path resolution
│   │   └── defaults.py                  # Default parameters & constants
│   │
│   ├── core/                            # Core data management
│   │   ├── __init__.py
│   │   ├── loader.py                    # Load existing index data
│   │   ├── persistence.py               # Save data to disk
│   │   ├── index_builder.py             # Exact NumPy cosine index
│   │   ├── duplicates.py                # Duplicate track detection
│   │   └── deleted_tracks.py            # Track deletion management
│   │
│   ├── processing/                      # Audio processing pipeline
│   │   ├── __init__.py
│   │   ├── xml_parser.py                # Rekordbox XML extraction
│   │   ├── embeddings.py                # Audio embedding generation
│   │   └── pipeline.py                  # Indexing orchestration
│   │
│   ├── recommendations/                 # Recommendation engine
│   │   ├── __init__.py
│   │   ├── engine.py                    # Main recommendation logic
│   │   ├── scoring.py                   # Key/BPM compatibility
│   │   ├── set_generator.py             # DJ set generation
│   │   ├── transitions.py               # Track transition scoring
│   │   ├── search.py                    # Track search
│   │   ├── models.py                    # Data classes
│   │   └── playlist_exporter.py         # M3U export
│   │
│   ├── ui/                              # User interface
│   │   ├── __init__.py                  # UI initialization
│   │   ├── app.py                       # Main application window
│   │   ├── recommendations_tab.py       # Explore tab mixin
│   │   ├── set_creator_tab.py           # Set creator tab mixin
│   │   ├── playlist_export_tab.py       # Export tab mixin
│   │   ├── library_tab.py               # Library tab mixin
│   │   ├── onboarding.py                # First-run wizard
│   │   ├── dialogs.py                   # Common dialogs
│   │   ├── settings_window.py           # Settings UI
│   │   ├── reindex_window.py            # Reindex progress UI
│   │   └── track_selector_dialog.py     # Track picker dialog
│   │
│   └── utils/                           # Utilities
│       └── icon.py                      # Application icon handling
│
├── models/                              # ML models (downloaded)
│   └── discogs_multi_embeddings-effnet-bs64-1.pb
│
├── data/                                # Generated data (gitignored)
│   ├── meta.parquet
│   ├── embeddings.parquet
│   ├── index.npy
│   ├── ids.json
│   ├── deleted_tracks.json
│   └── settings.json
│
├── assets/                              # Application assets
│   ├── coco_logo.png                    # Full-size logo
│   ├── coco_logo_small.png              # Small logo for UI
│   └── coco_logo.icns                   # macOS icon
│
├── .github/workflows/                   # CI/CD pipelines
│   ├── build-macos.yml                  # Apple Silicon build
│   ├── build-macos-intel.yml            # Intel Mac build
│   └── build-windows.yml                # Windows build
│
├── setup.py                             # Package configuration
├── requirements.txt                     # Dependencies
├── cosine-companion.spec                # PyInstaller spec
├── build_app.py                         # Build script
├── README.md                            # User documentation
└── docs/PROGRAM_FLOW.md                 # Flow documentation
```

---

## 6. Component Deep Dive

### 6.1 Configuration Layer (`config/`)

#### paths.py
Handles platform-aware path resolution for data storage:

```python
def _get_data_dir() -> Path:
    """Return writable data directory depending on runtime context."""
    if getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS'):
        system = platform.system()
        if system == 'Darwin':
            return Path.home() / 'Library' / 'Application Support' / 'Cosine Companion'
        if system == 'Windows':
            return Path.home() / 'AppData' / 'Local' / 'Cosine Companion'
        return Path.home() / '.local' / 'share' / 'cosine-companion'
    return project_root / 'data'
```

#### defaults.py
Centralizes algorithm parameters:

```python
# Audio processing
DEFAULT_SAMPLE_RATE = 32000

# Scoring weights (must sum to 1.0)
DEFAULT_SCORING_WEIGHTS = (0.7, 0.2, 0.1)  # cosine, key, bpm

# Recommendation parameters
DEFAULT_TOPK = 200        # Exact cosine candidates
DEFAULT_FINAL_TOP = 15    # Final recommendations
```

### 6.2 Core Layer (`core/`)

#### loader.py
Loads existing indexed data and identifies new tracks:

```python
def load_all() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, NumpyCosIndex, np.ndarray, List[str]]:
    """Load all index components from disk."""
    meta = pd.read_parquet(META_PQ)
    emb = pd.read_parquet(EMB_PQ)
    V = np.load(IDX_NPY)
    with open(IDS_JSON) as f:
        ids = json.load(f)
    validate_index_data(V, ids, emb)
    idx = NumpyCosIndex(V.shape[1])
    for tid, v in zip(ids, V):
        idx.add(tid, v)
    meta_ix = meta.set_index("track_id")
    emb_ix = emb.set_index("track_id")
    return meta, meta_ix, emb_ix, idx, V, ids

def find_new_tracks(current_meta: pd.DataFrame, existing_meta: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Identify tracks in XML not yet indexed."""
    if existing_meta is None:
        return current_meta
    existing_ids = set(existing_meta["track_id"])
    return current_meta[~current_meta["track_id"].isin(existing_ids)]
```

#### persistence.py
Handles saving all data components:

```python
def save_index_data(
    meta: pd.DataFrame,
    embeddings: pd.DataFrame,
    vectors: np.ndarray,
    ids: List[str]
) -> None:
    """Persist all index data to disk."""
    meta.to_parquet(data_dir / 'meta.parquet')
    embeddings.to_parquet(data_dir / 'embeddings.parquet')
    np.save(data_dir / 'index.npy', vectors)
    json.dump(ids, open(data_dir / 'ids.json', 'w'))
```

#### index_builder.py
Exact cosine index over one normalized float32 matrix:

```python
class NumpyCosIndex:
    """Brute-force cosine search over a float32 matrix."""

    def __init__(self, dim: int = 2560):
        self.dim = dim
        self.ids: List[str] = []
        self._rows: List[np.ndarray] = []
        self._matrix: Optional[np.ndarray] = None

    @property
    def matrix(self) -> np.ndarray:
        if self._matrix is None:
            self._matrix = (np.vstack(self._rows) if self._rows
                            else np.empty((0, self.dim), dtype=np.float32))
        return self._matrix

    def add(self, track_id: str, v: np.ndarray) -> None:
        """Add a normalized vector to index."""
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        self._rows.append(v)
        self._matrix = None
        self.ids.append(track_id)

    def search(self, v: np.ndarray, k: int) -> List[Tuple[str, float]]:
        """Search all vectors for the exact top-k neighbors."""
        k = min(k, len(self.ids))
        if k <= 0:
            return []
        v = v.astype("float32")
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        scores = self.matrix @ v
        ranked = np.argsort(-scores, kind="stable")[:k]
        return [(self.ids[i], float(scores[i])) for i in ranked]
```

### 6.3 Processing Layer (`processing/`)

#### xml_parser.py
Extracts track metadata from Rekordbox XML exports:

```python
def read_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    """Parse Rekordbox XML and extract track metadata."""
    tree = etree.parse(xml_path)
    rows = []

    for t in tree.xpath("//COLLECTION/TRACK"):
        loc = t.get("Location") or ""
        parsed = urlparse(loc)
        path_local = ""
        if parsed.scheme == "file":
            path_with_fragment = parsed.path + ("#" + parsed.fragment if parsed.fragment else "")
            if parsed.netloc and parsed.netloc != "localhost":
                path_local = "/" + parsed.netloc + unquote(path_with_fragment)
            else:
                path_local = unquote(path_with_fragment)

        rows.append({
            "track_id": t.get("TrackID") or loc,
            "path": loc,
            "path_local": path_local,
            "artist": t.get("Artist") or "",
            "title": t.get("Name") or "",
            "album": t.get("Album") or "",
            "bpm": float(t.get("AverageBpm") or t.get("Tempo") or 0) or None,
            "key": t.get("Tonality") or "",
        })

    df = pd.DataFrame(rows)
    return df[df["path_local"].astype(str).str.len() > 0].copy()
```

#### embeddings.py
Generates audio embeddings using Essentia:

```python
class DiscogsEffnetEmbedder:
    """Audio embedding generator using Discogs-EffNet model."""

    def __init__(self, model_path: Optional[str] = None, sr: int = 32000):
        self.sr = sr
        model_path = model_path or (MODELS / "discogs_multi_embeddings-effnet-bs64-1.pb")
        self.pred = es.TensorflowPredictEffnetDiscogs(
            graphFilename=str(model_path),
            output='PartitionedCall:1'  # Embedding output layer
        )

    def embed_file(self, audio_path: str) -> np.ndarray:
        """Generate embedding for audio file."""
        audio = es.MonoLoader(filename=audio_path, sampleRate=self.sr, resampleQuality=4)()
        embeddings = np.asarray(self.pred(audio))

        # Aggregate: mean + std pooling
        if embeddings.ndim == 1:
            pooled = embeddings
        else:
            pooled = np.concatenate([embeddings.mean(axis=0), embeddings.std(axis=0)])

        # L2 normalize for cosine similarity
        return pooled / np.linalg.norm(pooled)
```

#### pipeline.py
Orchestrates the complete indexing workflow:

```python
def index_library(
    xml_path: str,
    force_full: bool = False,
    sample_size: int | None = None,
    cancel_check: Optional[Callable] = None,
) -> None:
    """
    Main indexing pipeline with incremental update support.

    Steps:
    1. Parse Rekordbox XML
    2. Load existing data (unless force)
    3. Remove duplicates
    4. Filter manually deleted tracks
    5. Identify new tracks
    6. Generate embeddings for new tracks
    7. Merge embeddings and metadata
    8. Persist all data
    """
    existing_meta, existing_emb = (None, None) if force_full else load_existing_data()
    current_meta = read_rekordbox_xml(xml_path)
    current_meta, _ = remove_simple_duplicates(current_meta)
    current_meta = filter_deleted_tracks(current_meta)
    new_tracks = find_new_tracks(current_meta, existing_meta)
    if sample_size:
        new_tracks = new_tracks.head(sample_size)

    embedder = DiscogsEffnetEmbedder()
    new_vectors, new_track_ids = [], []
    for _, row in new_tracks.iterrows():
        if cancel_check and cancel_check():
            raise KeyboardInterrupt("User cancelled indexing")
        vec = embedder.embed_file(row["path_local"])
        if vec is None:
            continue
        new_track_ids.append(row["track_id"])
        new_vectors.append(vec)

    new_vectors_array = np.vstack(new_vectors).astype("float32")
    v_cols = [f"v{i}" for i in range(new_vectors_array.shape[1])]
    new_emb_df = pd.concat([
        pd.DataFrame({"track_id": new_track_ids}),
        pd.DataFrame(new_vectors_array, columns=v_cols)
    ], axis=1)

    # Merge embeddings and metadata, then save
    combined_emb, combined_vectors, combined_track_ids = merge_embeddings(
        existing_emb, new_emb_df, new_track_ids, new_vectors_array
    )
    if existing_meta is not None:
        current_meta_dict = {row["track_id"]: row for _, row in current_meta.iterrows()}
        combined_meta_rows = []
        seen_ids = set()
        for tid in combined_track_ids:
            if tid in current_meta_dict:
                combined_meta_rows.append(current_meta_dict[tid])
                seen_ids.add(tid)
        for _, row in existing_meta.iterrows():
            tid = row["track_id"]
            if tid in combined_track_ids and tid not in seen_ids:
                combined_meta_rows.append(row.to_dict())
                seen_ids.add(tid)
        combined_meta = pd.DataFrame(combined_meta_rows)
    else:
        combined_meta = current_meta
    save_index_data(combined_meta, combined_emb, combined_vectors, combined_track_ids)
```

### 6.4 Recommendations Layer (`recommendations/`)

#### engine.py
Core recommendation algorithm:

```python
def recommend_for(
    track_id: str,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    topk: int = DEFAULT_TOPK,
    final_top: int = DEFAULT_FINAL_TOP
) -> List[Dict]:
    """
    Generate recommendations for a track.

    Algorithm:
    1. Compute exact cosine for the full collection and select top-k
    2. Score key compatibility
    3. Score BPM compatibility
    4. Calculate weighted final score
    5. Return top results
    """
    v = vector_for(track_id, emb_ix)
    if v is None:
        return []
    src = meta_ix.loc[track_id]
    nbrs = idx.search(v, k=topk + 1)

    results = []
    for tid, cosine in nbrs:
        if tid == track_id:
            continue
        m = meta_ix.loc[tid]
        key_score = key_compat(src.get("key"), m.get("key"))
        bpm_score = bpm_compat(src.get("bpm"), m.get("bpm"))
        score = final_score(cosine, key_score, bpm_score)

        results.append({
            "track_id": tid,
            "artist": m.get("artist", ""),
            "title": m.get("title", ""),
            "bpm": m.get("bpm", None),
            "key": m.get("key", ""),
            "score": score,
            "cosine": cosine,
            "key_score": key_score,
            "bpm_score": bpm_score
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:final_top]
```

#### scoring.py
Musical compatibility scoring:

```python
def key_compat(src: Optional[str], dst: Optional[str]) -> float:
    """
    Score key compatibility using Camelot wheel.

    Returns:
        1.0  - Same key (perfect match)
        0.8  - Adjacent on Camelot wheel (+/-1)
        0.6  - Relative major/minor (same number)
        0.4  - Two steps away
        0.0  - Incompatible or unknown keys
    """
    s = to_camelot(src)
    d = to_camelot(dst)
    if not s or not d:
        return 0.0
    sn, sm = int(s[:-1]), s[-1]
    dn, dm = int(d[:-1]), d[-1]
    if s == d:
        return 1.0
    if sm == dm and ((sn - dn) % 12 in (1, 11)):
        return 0.8
    if sn == dn and sm != dm:
        return 0.6
    if sm == dm and ((sn - dn) % 12 in (2, 10)):
        return 0.4
    return 0.0

def bpm_compat(sbpm: Optional[float], dbpm: Optional[float], pct: float = 0.06) -> float:
    """
    Score BPM compatibility with half/double time support.

    Returns:
        1.0  - Within 6% of each other
        0.7  - Half or double time (within 6%)
        0.0  - Incompatible or unknown BPM
    """
    if not sbpm or not dbpm:
        return 0.0
    lo, hi = sbpm * (1 - pct), sbpm * (1 + pct)
    if lo <= dbpm <= hi:
        return 1.0
    for mult in (0.5, 2.0):
        b = sbpm * mult
        lo, hi = b * (1 - pct), b * (1 + pct)
        if lo <= dbpm <= hi:
            return 0.7
    return 0.0
```

#### set_generator.py
DJ set generation with anchor track support:

```python
def generate_set(
    anchor_tracks: Dict[int, str],  # {position: track_id} (1-indexed)
    total_tracks: int,
    meta_ix: pd.DataFrame,
    emb_ix: pd.DataFrame,
    idx: NumpyCosIndex,
    exclude_tracks: Optional[List[str]] = None
) -> List[SetTrack]:
    """
    Generate a DJ set with anchor tracks at specified positions.

    Algorithm:
    1. Place anchor tracks at their positions
    2. For each empty slot:
       a. Find context tracks (previous and next anchors)
       b. Query recommendations based on context
       c. Score candidates by transition quality
       d. Select best track that isn't already in set
    3. Return complete set
    """
    set_tracks = [None] * total_tracks
    exclude_set = set(exclude_tracks or [])
    exclude_set.update(anchor_tracks.values())

    # Place anchors
    for position, track_id in anchor_tracks.items():
        track_row = meta_ix.loc[track_id]
        set_tracks[position - 1] = SetTrack(
            track_id=track_id,
            artist=track_row['artist'],
            title=track_row['title'],
            position=position,
            is_anchor=True
        )

    # Fill empty slots
    for i in range(total_tracks):
        if set_tracks[i] is not None:
            continue

        # Find context
        prev_track = find_previous_track(set_tracks, i)
        next_track = find_next_track(set_tracks, i)

        # Get candidates
        if prev_track:
            candidates = recommend_for(prev_track, meta_ix, emb_ix, idx, topk=100, final_top=50)
        elif next_track:
            candidates = recommend_for(next_track, meta_ix, emb_ix, idx, topk=100, final_top=50)
        else:
            first_anchor = list(anchor_tracks.values())[0]
            candidates = recommend_for(first_anchor, meta_ix, emb_ix, idx, topk=100, final_top=50)

        # Filter out excluded tracks
        used_tracks = {track.track_id for track in set_tracks if track is not None}
        all_excluded = exclude_set.union(used_tracks)
        filtered_candidates = [c for c in candidates if c["track_id"] not in all_excluded]

        # Score candidates by transition quality
        best_candidate = None
        best_score = -1.0
        for candidate in filtered_candidates[:20]:
            track_id = candidate["track_id"]
            if prev_track:
                score = calculate_transition_score(prev_track, track_id, next_track, emb_ix)
            else:
                score = candidate.get("cosine", 0.0)
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            set_tracks[i] = SetTrack(
                track_id=best_candidate["track_id"],
                artist=best_candidate.get("artist", ""),
                title=best_candidate.get("title", ""),
                position=i + 1,
                is_anchor=False,
                score=best_score
            )
            exclude_set.add(best_candidate["track_id"])

    return set_tracks
```

---

## 7. Data Flow & Pipeline

### 7.1 Indexing Data Flow

```
                    ┌─────────────────────┐
                    │  Rekordbox Export   │
                    │     (XML file)      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    XML Parser       │
                    │  (xml_parser.py)    │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Track Metadata    │
                    │   - track_id        │
                    │   - artist, title   │
                    │   - bpm, key        │
                    │   - path, path_local│
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
    │  Duplicate      │ │ Load Exist- │ │ Filter Deleted  │
    │  Detection      │ │ ing Data    │ │ Tracks          │
    └────────┬────────┘ └──────┬──────┘ └────────┬────────┘
             │                 │                  │
             └─────────────────┼──────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Find New Tracks    │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  New Tracks Only    │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Audio Loader     │
                    │   (MonoLoader)      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Discogs-EffNet     │
                    │   (TensorFlow)      │
                    │                     │
                    │  Audio → Embeddings │
                    │ (2,560-dim vector)  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   L2 Normalize      │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
    │ meta.parquet    │ │embeddings.  │ │  NumPy Matrix   │
    │ (metadata)      │ │parquet      │ │ (exact cosine)  │
    └─────────────────┘ └─────────────┘ └─────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
    │ index.npy       │ │ ids.json    │ │ (in memory for  │
    │ (vectors)       │ │ (id mapping)│ │  queries)       │
    └─────────────────┘ └─────────────┘ └─────────────────┘
```

### 7.2 Recommendation Data Flow

```
    ┌─────────────────────┐
    │  User Selects Track │
    │     (track_id)      │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Lookup Query Vector│
    │  from index.npy     │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │ Exact Cosine Search │
    │ (full collection)   │
    │                     │
    │  Query → Top-200    │
    │  neighbor indices   │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Filter & Score     │
    │                     │
    │  For each neighbor: │
    │  - Deleted tracks are filtered at index time │
    │  - Cosine similarity│
    │  - Key compatibility│
    │  - BPM compatibility│
    │                     │
    │  final = 0.7*cos    │
    │        + 0.2*key    │
    │        + 0.1*bpm    │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Sort by Score      │
    │  Return Top-N       │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Display in UI      │
    │  (Explore Tab)      │
    └─────────────────────┘
```

---

## 8. Data Storage Layer

### 8.1 Storage Overview

The application uses a **file-based storage** approach with no external database:

| File | Format | Purpose | Typical Size |
|------|--------|---------|--------------|
| `meta.parquet` | Apache Parquet | Track metadata | ~175KB (4K tracks) |
| `embeddings.parquet` | Apache Parquet | Audio embeddings | ~19MB (4K tracks) |
| `index.npy` | NumPy binary | Search vectors | ~39MB (4K tracks) |
| `ids.json` | JSON | Track ID mapping | ~16KB (4K tracks) |
| `deleted_tracks.json` | JSON | User deletions | ~2KB |
| `settings.json` | JSON | User preferences | ~1KB |

### 8.2 Data Schemas

#### meta.parquet
```
Column      Type      Description
──────────────────────────────────────
track_id    string    Unique identifier (from Rekordbox or fallback path)
artist      string    Artist name
title       string    Track title
album       string    Album name
bpm         float64   Beats per minute
key         string    Musical key (e.g., "Am", "C")
path        string    Rekordbox Location URL
path_local  string    Local filesystem path to audio file
```

#### embeddings.parquet
```
Column      Type      Description
──────────────────────────────────────
track_id    string    Foreign key to meta
v0-v2559    float32   2,560-dimensional embedding vector
```

#### index.npy
```
Shape: (N, 2560) where N = number of tracks
Type: float32
Content: L2-normalized embedding vectors
Note: Same order as ids.json
```

### 8.3 Data Directory Locations

| Environment | Platform | Location |
|-------------|----------|----------|
| Development | All | `<project_root>/data/` |
| Production | macOS | `~/Library/Application Support/Cosine Companion/` |
| Production | Windows | `~/AppData/Local/Cosine Companion/` |
| Production | Linux | `~/.local/share/cosine-companion/` |

---

## 9. Recommendation Engine

### 9.1 Algorithm Overview

The recommendation system combines three similarity signals:

```
Final Score = 0.7 × Cosine Similarity
            + 0.2 × Key Compatibility
            + 0.1 × BPM Compatibility
```

### 9.2 Cosine Similarity (Sonic)

Based on audio embeddings from the Discogs-EffNet model:

- **Model Architecture**: EfficientNet trained on Discogs
- **Embedding Dimension**: 256
- **Pooling Strategy**: Mean + Standard Deviation across time
- **Normalization**: L2 (enables cosine via dot product)

The embeddings capture:
- Timbre and texture
- Genre characteristics
- Energy levels
- Instrumentation patterns

### 9.3 Key Compatibility (Harmonic)

Uses the **Camelot Wheel** system for DJ-friendly key matching:

```
     ┌─────────────────────────────────────────┐
     │           CAMELOT WHEEL                 │
     │                                         │
     │         1A ←→ 1B (Abm ↔ B)             │
     │        /           \                    │
     │      12A            2A                  │
     │     /                 \                 │
     │   11A                   3A              │
     │    |                     |              │
     │   10A                   4A              │
     │     \                 /                 │
     │      9A             5A                  │
     │        \           /                    │
     │         8A ←→ 7A ←→ 6A                 │
     │                                         │
     │  Inner ring (A) = Minor keys           │
     │  Outer ring (B) = Major keys           │
     │                                         │
     │  Compatible transitions:                │
     │  - Same position: Perfect (1.0)         │
     │  - +/- 1 position: Good (0.8)          │
     │  - A ↔ B same number: Relative (0.6)   │
     │  - +/- 2 positions: Usable (0.4)       │
     └─────────────────────────────────────────┘
```

### 9.4 BPM Compatibility (Tempo)

```
┌─────────────────────────────────────────────────┐
│              BPM MATCHING RULES                  │
├─────────────────────────────────────────────────┤
│                                                 │
│  Within 6% → Perfect (1.0)                      │
│    Example: 128 BPM matches 121-135 BPM         │
│                                                 │
│  Half-time (within 6%) → Good (0.7)             │
│    Example: 128 BPM matches 61-68 BPM           │
│                                                 │
│  Double-time (within 6%) → Good (0.7)           │
│    Example: 64 BPM matches 121-135 BPM          │
│                                                 │
│  Otherwise → Incompatible (0.0)                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 9.5 Exact Cosine Search

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Matrix type | NumPy float32 | One normalized row per track |
| Dimension | 2,560 | 1,280 mean + 1,280 standard-deviation features |
| Candidate selection | Stable descending sort | Exact top-k with positional tie order |
| Metric | Inner product | Exact cosine on normalized vectors |

**Performance Characteristics:**
- Add: O(d) buffered row append
- Matrix materialization: O(n × d), only after additions
- Query score calculation: O(n × d)
- Result ordering: O(n log n) stable sort
- Memory: O(n × d × 4 bytes), with no graph overhead

---

## 10. User Interface Architecture

### 10.1 UI Component Hierarchy

```
┌──────────────────────────────────────────────────────────────┐
│                        Tk Root                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                   App (Main Window)                    │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │                   Menu Bar                       │  │  │
│  │  │  File | Library | Help                           │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │               Notebook (Tabs)                    │  │  │
│  │  │  ┌────────────┬────────────┬─────────┬────────┐  │  │  │
│  │  │  │  Explore   │  Set       │ Export  │Library │  │  │  │
│  │  │  │  (Recs)    │  Creator   │         │        │  │  │  │
│  │  │  └────────────┴────────────┴─────────┴────────┘  │  │  │
│  │  │  ┌──────────────────────────────────────────────┐│  │  │
│  │  │  │                                              ││  │  │
│  │  │  │              Tab Content                     ││  │  │
│  │  │  │                                              ││  │  │
│  │  │  │  (Treeview tables, buttons, labels, etc.)    ││  │  │
│  │  │  │                                              ││  │  │
│  │  │  └──────────────────────────────────────────────┘│  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │                  Status Bar                      │  │  │
│  │  │  "Current Track: Artist - Title"                 │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 10.2 Mixin Composition

```python
# ui/app.py

class App(
    RecommendationsTabMixin,   # ~300 lines
    SetCreatorTabMixin,        # ~350 lines
    PlaylistExportTabMixin,    # ~150 lines
    LibraryTabMixin,           # ~400 lines
    tk.Tk                      # Tkinter base
):
    """
    Main application window.

    Each mixin provides:
    - create_X_tab() method
    - Event handlers for that tab
    - Tab-specific state variables
    """

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("Cosine Companion")

        # Load all data
        self.meta, self.meta_ix, self.emb_ix, self.idx, self.V, self.ids = load_all()

        # Create UI structure
        self.create_menu_bar()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, pady=8)
        self.status = tk.Label(self, text="...", anchor="w")
        self.status.pack(fill="x", side="bottom")

        # Initialize tabs (from mixins)
        self.create_recommendations_tab()
        self.create_set_creator_tab()
        self.create_playlist_export_tab()
        self.create_library_tab()
```

### 10.3 Tab Responsibilities

| Tab | Mixin | Primary Functions |
|-----|-------|-------------------|
| **Explore** | `RecommendationsTabMixin` | Browse recommendations, set current track, view similarity scores |
| **Set Creator** | `SetCreatorTabMixin` | Build DJ sets with anchor tracks, auto-fill remaining slots |
| **Export** | `PlaylistExportTabMixin` | Export recommendations as M3U playlists |
| **Library** | `LibraryTabMixin` | Search all tracks, delete tracks, multi-select operations |

### 10.4 Onboarding Flow

```
                    ┌──────────────────────┐
                    │     App Launch       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Check for existing  │
                    │  index data          │
                    └──────────┬───────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
    ┌─────────────────┐               ┌─────────────────┐
    │   Data exists   │               │   First run     │
    │   Open main app │               │   Show wizard   │
    └─────────────────┘               └────────┬────────┘
                                               │
                                               ▼
                                    ┌─────────────────┐
                                    │  Welcome screen │
                                    │  explaining app │
                                    └────────┬────────┘
                                               │
                                               ▼
                                    ┌─────────────────┐
                                    │  Select XML     │
                                    │  file dialog    │
                                    └────────┬────────┘
                                               │
                                               ▼
                                    ┌─────────────────┐
                                    │  Ensure model   │
                                    │  file exists    │
                                    └────────┬────────┘
                                               │
                                               ▼
                                    ┌─────────────────┐
                                    │  Index library  │
                                    │  (progress bar) │
                                    └────────┬────────┘
                                               │
                                               ▼
                                    ┌─────────────────┐
                                    │  Launch main    │
                                    │  application    │
                                    └─────────────────┘
```

---

## 11. Build & Distribution

### 11.1 Build System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     BUILD PIPELINE                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Source Code (Python)                                       │
│        │                                                    │
│        ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PyInstaller                             │   │
│  │                                                      │   │
│  │  - Bundles Python interpreter                        │   │
│  │  - Collects all dependencies                         │   │
│  │  - Includes native libraries (.so, .dylib, .dll)     │   │
│  │  - Packages assets and models                        │   │
│  └─────────────────────────────────────────────────────┘   │
│        │                                                    │
│        ├───────────────┬───────────────┐                   │
│        ▼               ▼               ▼                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐           │
│  │  macOS   │   │ Windows  │   │    Linux     │           │
│  │  .app    │   │  .exe    │   │   Binary     │           │
│  │ bundle   │   │          │   │              │           │
│  └────┬─────┘   └────┬─────┘   └──────┬───────┘           │
│       │              │                │                    │
│       ▼              ▼                ▼                    │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐           │
│  │   DMG    │   │Installer │   │  AppImage    │           │
│  │ package  │   │  (.exe)  │   │  (optional)  │           │
│  └──────────┘   └──────────┘   └──────────────┘           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 PyInstaller Configuration

Key settings from `cosine-companion.spec`:

Key points (see `cosine-companion.spec` for the full, up-to-date list):
- Collects dynamic libraries for numpy/pandas/essentia/pyarrow
- Includes `models/`, `assets/`, and `LICENSE` in the bundle
- Enumerates submodules for major dependencies and UI modules

### 11.3 CI/CD Pipelines

#### macOS Build (Apple Silicon)
```yaml
# .github/workflows/build-macos.yml
name: Build macOS

on:
  workflow_dispatch:
  push:
    tags: ['v*']

jobs:
  build-macos:
    runs-on: macos-latest

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
        with:
          python-version-file: .python-version   # never state it inline
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python build_app.py
      - run: |
          brew install create-dmg
          create-dmg --volname "Cosine Companion" \
            --volicon "assets/coco_logo.icns" \
            "Cosine-Companion-macOS.dmg" \
            "dist/Cosine Companion.app"
```

### 11.4 Platform-Specific Considerations

| Platform | Considerations |
|----------|----------------|
| **macOS ARM64** | Native Apple Silicon build, notarization recommended |
| **macOS Intel** | Separate build on x86_64 runner, Rosetta fallback |
| **Windows** | Code signing recommended, Windows Defender exceptions |
| **Linux** | Multiple distro support via AppImage or static linking |

---

## 12. External Integrations

### 12.1 Rekordbox Integration

**Input**: Rekordbox XML library export

```xml
<!-- Example Rekordbox XML structure -->
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="rekordbox" Version="6.x"/>
  <COLLECTION Entries="1234">
    <TRACK TrackID="123"
           Name="Track Title"
           Artist="Artist Name"
           Album="Album Name"
           AverageBpm="128.00"
           Tonality="Am"
           Location="file://localhost/path/to/file.mp3"/>
    <!-- More tracks... -->
  </COLLECTION>
</DJ_PLAYLISTS>
```

**Parsing Details**:
- Uses `lxml` for efficient XML processing
- Handles `file://localhost` URL encoding
- Extracts track IDs for deduplication

### 12.2 Essentia Model

**Model Source**: Essentia Models Repository

```
URL: https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs_multi_embeddings-effnet-bs64-1.pb
File: discogs_multi_embeddings-effnet-bs64-1.pb
Size: 16,367,182 bytes
SHA-256: 2c964064951217e1e345461cf88884086a21f4bca2ae0d48187ee75edc263cd7
Format: TensorFlow frozen graph (.pb)
```

**Model Capabilities**:
- Genre classification
- Mood detection
- Musical style embeddings
- Instrument recognition

### 12.3 M3U Playlist Export

**Output Format**: Extended M3U

```m3u
#EXTM3U
#EXTINF:240,Artist Name - Track Title
/path/to/audio/file.mp3
#EXTINF:180,Another Artist - Another Track
/path/to/another/file.mp3
```

**Compatibility**:
- Rekordbox (import playlists)
- VLC, iTunes, foobar2000
- Any M3U-compatible player

---

## 13. Configuration Management

### 13.1 Configuration Hierarchy

```
┌─────────────────────────────────────────────────────┐
│                CONFIGURATION SOURCES                 │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Hardcoded Defaults (config/defaults.py)         │
│     └─ Scoring weights, sample rate, thresholds    │
│                                                     │
│  2. User Settings (data/settings.json)              │
│     └─ Per-user preferences                        │
│                                                     │
│  3. Runtime Arguments (CLI flags)                   │
│     └─ --force, --sample, etc.                     │
│                                                     │
│  Priority: Runtime > User > Defaults                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 13.2 Default Parameters

```python
# config/defaults.py

# Audio Processing
DEFAULT_SAMPLE_RATE = 32000  # Hz

# Recommendation Scoring
DEFAULT_SCORING_WEIGHTS = (
    0.7,  # Cosine similarity weight
    0.2,  # Key compatibility weight
    0.1,  # BPM compatibility weight
)

# Exact Cosine Search Parameters
DEFAULT_TOPK = 200          # Initial candidates
DEFAULT_FINAL_TOP = 15      # Final recommendations

```

### 13.3 Path Resolution

```python
# config/paths.py

def _get_data_dir() -> Path:
    """Platform-aware data directory resolution."""
    if getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS'):
        system = platform.system()
        if system == 'Darwin':
            return Path.home() / 'Library' / 'Application Support' / 'Cosine Companion'
        if system == 'Windows':
            return Path.home() / 'AppData' / 'Local' / 'Cosine Companion'
        return Path.home() / '.local' / 'share' / 'cosine-companion'
    return Path(__file__).parent.parent.parent / 'data'

def _get_models_dir() -> Path:
    """Returns path to Essentia model directory."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'models'
    return Path(__file__).parent.parent.parent / 'models'
```

---

## 14. Performance Considerations

### 14.1 Embedding Generation

| Metric | Value | Notes |
|--------|-------|-------|
| Time per track | ~2-5 seconds | Depends on track length |
| Memory usage | ~500MB | Model + audio buffer |
| Parallelization | Single-threaded | TensorFlow session limitation |

**Optimization Strategies**:
- Incremental indexing (only new tracks)
- Progress callbacks for UI feedback
- Sample mode for debugging (--sample N)

### 14.2 Exact NumPy Search

| Metric | Value |
|--------|-------|
| Add | O(2,560) buffered row append |
| Matrix materialization | O(n × 2,560), only after additions |
| Query score calculation | O(n × 2,560) |
| Result ordering | O(n log n) stable sort |
| Memory per track | 10KB (2,560 × float32) |

Every query scores and stably sorts every track. The stable sort makes both
ordering and top-k membership deterministic when duplicate embeddings tie.

### 14.3 Memory Management

```
Application Memory Footprint (4,000 tracks):
├── Metadata DataFrame:        ~5 MB
├── Embeddings DataFrame:      ~20 MB
├── NumPy cosine matrix:      ~39 MB
├── Persisted NumPy vectors:  ~39 MB
├── Essentia Model:           ~300 MB
├── Tkinter UI:               ~50 MB
└── Python Runtime:           ~100 MB
────────────────────────────────────
Total:                        ~500 MB
```

### 14.4 Startup Optimization

- **Lazy imports**: Heavy libraries loaded on demand
- **Data preloading**: All data loaded once at startup
- **UI rendering**: Deferred population of large lists

---

## 15. Security Considerations

### 15.1 Data Security

| Aspect | Implementation |
|--------|----------------|
| **Local Storage** | All data stored locally, no cloud sync |
| **File Paths** | Stored as-is, no encryption |
| **API Keys** | None (no external API keys required) |
| **User Data** | No personally identifiable information collected |

### 15.2 Input Validation

```python
# XML Parsing (current behavior)
def read_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    # lxml will raise if the file is missing or invalid
    tree = etree.parse(xml_path)
    ...
```

### 15.3 File System Access

- Application only accesses:
  - User-selected XML files
  - Audio files referenced in XML
  - Application data directory
- No network access (except optional model download)
- No system modifications outside data directory

---

## Appendix A: File Size Estimates

| Component | Size (1K tracks) | Size (10K tracks) | Size (100K tracks) |
|-----------|------------------|-------------------|-------------------|
| meta.parquet | ~50KB | ~500KB | ~5MB |
| embeddings.parquet | ~5MB | ~50MB | ~500MB |
| index.npy | ~3MB | ~30MB | ~300MB |
| ids.json | ~5KB | ~50KB | ~500KB |
| **Total** | ~8MB | ~80MB | ~800MB |

---

## Appendix B: Key File References

| File | Line Count | Primary Responsibility |
|------|------------|------------------------|
| `cosine_companion.py` | ~150 | CLI entry point |
| `ui/app.py` | ~300 | Main window |
| `ui/recommendations_tab.py` | ~300 | Explore tab |
| `ui/set_creator_tab.py` | ~350 | Set creation |
| `ui/library_tab.py` | ~400 | Library management |
| `recommendations/engine.py` | ~150 | Core algorithm |
| `recommendations/scoring.py` | ~100 | Key/BPM scoring |
| `processing/pipeline.py` | ~200 | Indexing pipeline |
| `processing/embeddings.py` | ~100 | Audio embeddings |
| `core/index_builder.py` | ~50 | Exact NumPy cosine index |

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Camelot Wheel** | Circular key notation system for DJ mixing compatibility |
| **Embedding** | Dense vector representation of audio characteristics |
| **Cosine similarity** | Dot product of two L2-normalized vectors |
| **Rekordbox** | Pioneer DJ's music management software |
| **M3U** | Multimedia playlist file format |
| **Parquet** | Columnar storage format for efficient data analytics |

---

*Document generated for Cosine Companion v1.x*
*Last updated: December 2024*
