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

**Cosine Companion** is a cross-platform desktop application designed to help DJs find similar tracks and create seamless DJ sets from their music library. The application leverages deep learning audio embeddings and approximate nearest neighbor search to provide intelligent music recommendations based on sonic similarity, harmonic compatibility, and tempo matching.

### Key Characteristics

| Attribute | Value |
|-----------|-------|
| **Application Type** | Desktop GUI + CLI |
| **Platforms** | macOS (ARM64/Intel), Windows, Linux |
| **Primary Language** | Python 3.8+ |
| **Codebase Size** | ~5,244 lines of Python |
| **Architecture Style** | Layered architecture with mixin-based UI |
| **Data Storage** | File-based (Parquet, NumPy, JSON) |
| **ML Framework** | Essentia + TensorFlow |
| **Search Algorithm** | FAISS HNSW |

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
│  │   (Typer)   │    │  (Tkinter)  │    │   Wizard    │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│         └──────────────────┼──────────────────┘                         │
│                            ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    UI LAYER (ui/)                                │   │
│  │  ┌──────────────┬──────────────┬──────────────┬──────────────┐  │   │
│  │  │ Recommendations│ Set Creator │  Playlist   │   Library    │  │   │
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
│  │  │   Loader   │ Persistence│   FAISS    │    Duplicates/     │  │   │
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
│  │  (metadata)  │   parquet    │ (FAISS vec)  │  deleted_tracks.json │  │
│  └──────────────┴──────────────┴──────────────┴──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Workflows

#### Indexing Workflow
```
Rekordbox XML → Parse Metadata → Detect Duplicates → Filter New Tracks
    → Load Audio → Generate Embeddings → Build FAISS Index → Persist Data
```

#### Recommendation Workflow
```
Select Track → Query FAISS (top-k) → Score by Key/BPM → Rank Results → Display
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
| **GUI Framework** | Tkinter | Built-in | Cross-platform desktop UI |
| **CLI Framework** | Typer | Latest | Command-line interface |
| **Audio Analysis** | Essentia | 2.1b6+ | Audio embeddings via TensorFlow |
| **Vector Search** | FAISS | 1.7.0+ | Approximate nearest neighbor search |
| **Data Processing** | NumPy | Latest | Numerical computations |
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
| **pytest** | Testing framework |
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
    track_id: int
    artist: str
    title: str
    bpm: float
    key: str
    position: int
    is_anchor: bool
```

### 4.4 Lazy Import Pattern

Heavy dependencies are imported lazily to minimize startup time:

```python
def index_library(xml_path: str):
    # Heavy imports only when function is called
    from processing.pipeline import run_indexing_pipeline
    from processing.embeddings import DiscogsEffnetEmbedder
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
│   │   ├── index_builder.py             # FAISS index construction
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
└── PROGRAM_FLOW.md                      # Flow documentation
```

---

## 6. Component Deep Dive

### 6.1 Configuration Layer (`config/`)

#### paths.py
Handles platform-aware path resolution for data storage:

```python
def get_data_dir() -> Path:
    """Returns appropriate data directory based on runtime context."""
    if is_frozen():  # Running as compiled app
        if platform == 'darwin':
            return Path.home() / 'Library/Application Support/Cosine Companion'
        elif platform == 'win32':
            return Path.home() / 'AppData/Local/Cosine Companion'
        else:  # Linux
            return Path.home() / '.local/share/cosine-companion'
    else:  # Development mode
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
DEFAULT_TOPK = 200        # Candidates from FAISS
DEFAULT_FINAL_TOP = 15    # Final recommendations
```

### 6.2 Core Layer (`core/`)

#### loader.py
Loads existing indexed data and identifies new tracks:

```python
def load_all() -> Tuple[pd.DataFrame, pd.DataFrame, np.ndarray, List[int], FaissCosIndex, Set[int]]:
    """Load all index components from disk."""
    meta = pd.read_parquet(data_dir / 'meta.parquet')
    embeddings = pd.read_parquet(data_dir / 'embeddings.parquet')
    vectors = np.load(data_dir / 'index.npy')
    ids = json.load(open(data_dir / 'ids.json'))
    index = FaissCosIndex.load(vectors)
    deleted = load_deleted_tracks()
    return meta, embeddings, vectors, ids, index, deleted

def find_new_tracks(xml_tracks: pd.DataFrame, existing_meta: pd.DataFrame) -> pd.DataFrame:
    """Identify tracks in XML not yet indexed."""
    existing_ids = set(existing_meta['track_id'])
    return xml_tracks[~xml_tracks['track_id'].isin(existing_ids)]
```

#### persistence.py
Handles saving all data components:

```python
def save_index_data(
    meta: pd.DataFrame,
    embeddings: pd.DataFrame,
    vectors: np.ndarray,
    ids: List[int]
) -> None:
    """Persist all index data to disk."""
    meta.to_parquet(data_dir / 'meta.parquet')
    embeddings.to_parquet(data_dir / 'embeddings.parquet')
    np.save(data_dir / 'index.npy', vectors)
    json.dump(ids, open(data_dir / 'ids.json', 'w'))
```

#### index_builder.py
FAISS index wrapper with HNSW configuration:

```python
class FaissCosIndex:
    """FAISS index optimized for cosine similarity search."""

    def __init__(self, dim: int = 256):
        # HNSW index with cosine distance (via inner product on normalized vectors)
        self.index = faiss.IndexHNSWFlat(dim, 32)  # 32 neighbors per layer
        self.index.hnsw.efConstruction = 200       # Build quality
        self.index.hnsw.efSearch = 64              # Search quality

    def add(self, vectors: np.ndarray) -> None:
        """Add L2-normalized vectors to index."""
        self.index.add(vectors.astype('float32'))

    def search(self, query: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        """Search for k nearest neighbors."""
        distances, indices = self.index.search(query.reshape(1, -1).astype('float32'), k)
        return distances[0], indices[0]
```

### 6.3 Processing Layer (`processing/`)

#### xml_parser.py
Extracts track metadata from Rekordbox XML exports:

```python
def parse_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    """Parse Rekordbox XML and extract track metadata."""
    tree = etree.parse(xml_path)
    tracks = []

    for track in tree.xpath('//TRACK'):
        # Handle file:// URL decoding
        location = urllib.parse.unquote(track.get('Location', ''))
        if location.startswith('file://localhost'):
            location = location[16:]

        tracks.append({
            'track_id': int(track.get('TrackID')),
            'artist': track.get('Artist', ''),
            'title': track.get('Name', ''),
            'album': track.get('Album', ''),
            'bpm': float(track.get('AverageBpm', 0)),
            'key': convert_tonality(track.get('Tonality', '')),
            'path': location
        })

    return pd.DataFrame(tracks)
```

#### embeddings.py
Generates audio embeddings using Essentia:

```python
class DiscogsEffnetEmbedder:
    """Audio embedding generator using Discogs-EffNet model."""

    def __init__(self, model_path: str):
        self.model = TensorflowPredictEffnetDiscogs(
            graphFilename=model_path,
            output='PartitionedCall:1'  # Embedding output layer
        )
        self.sample_rate = 32000

    def embed(self, audio_path: str) -> np.ndarray:
        """Generate embedding for audio file."""
        # Load audio
        audio = MonoLoader(filename=audio_path, sampleRate=self.sample_rate)()

        # Get frame-wise embeddings
        embeddings = self.model(audio)

        # Aggregate: mean + std pooling
        pooled = np.concatenate([
            embeddings.mean(axis=0),
            embeddings.std(axis=0)
        ])

        # L2 normalize for cosine similarity
        return pooled / np.linalg.norm(pooled)
```

#### pipeline.py
Orchestrates the complete indexing workflow:

```python
def run_indexing_pipeline(
    xml_path: str,
    force: bool = False,
    sample: int = None,
    progress_callback: Callable = None
) -> None:
    """
    Main indexing pipeline with incremental update support.

    Steps:
    1. Parse Rekordbox XML
    2. Load existing data (if not force)
    3. Detect and remove duplicates
    4. Identify new tracks
    5. Generate embeddings for new tracks
    6. Merge with existing data
    7. Build FAISS index
    8. Persist all data
    """
    # Parse XML
    xml_tracks = parse_rekordbox_xml(xml_path)

    if not force and data_exists():
        # Incremental update
        existing_meta, existing_emb, _, _, _, _ = load_all()
        new_tracks = find_new_tracks(xml_tracks, existing_meta)
    else:
        # Full reindex
        existing_meta = pd.DataFrame()
        existing_emb = pd.DataFrame()
        new_tracks = xml_tracks

    # Remove duplicates
    new_tracks = remove_duplicates(new_tracks)

    # Generate embeddings
    embedder = DiscogsEffnetEmbedder(get_model_path())
    new_embeddings = []

    for i, track in new_tracks.iterrows():
        if progress_callback:
            progress_callback(i, len(new_tracks))
        emb = embedder.embed(track['path'])
        new_embeddings.append({'track_id': track['track_id'], **dict(enumerate(emb))})

    # Merge data
    all_meta = pd.concat([existing_meta, new_tracks])
    all_emb = pd.concat([existing_emb, pd.DataFrame(new_embeddings)])

    # Build index
    vectors = all_emb.drop('track_id', axis=1).values
    ids = all_emb['track_id'].tolist()

    # Save
    save_index_data(all_meta, all_emb, vectors, ids)
```

### 6.4 Recommendations Layer (`recommendations/`)

#### engine.py
Core recommendation algorithm:

```python
def recommend_for(
    track_id: int,
    meta: pd.DataFrame,
    vectors: np.ndarray,
    ids: List[int],
    index: FaissCosIndex,
    deleted: Set[int],
    topk: int = 200,
    final_top: int = 15
) -> List[Dict]:
    """
    Generate recommendations for a track.

    Algorithm:
    1. Query FAISS for top-k nearest neighbors
    2. Filter out deleted tracks
    3. Compute exact cosine similarity
    4. Score key compatibility
    5. Score BPM compatibility
    6. Calculate weighted final score
    7. Return top results
    """
    # Get query vector
    query_idx = ids.index(track_id)
    query_vec = vectors[query_idx]
    query_row = meta[meta['track_id'] == track_id].iloc[0]

    # FAISS search
    _, neighbor_indices = index.search(query_vec, topk)

    results = []
    for idx in neighbor_indices:
        if idx < 0:  # FAISS returns -1 for missing
            continue

        neighbor_id = ids[idx]
        if neighbor_id == track_id or neighbor_id in deleted:
            continue

        neighbor_row = meta[meta['track_id'] == neighbor_id].iloc[0]
        neighbor_vec = vectors[idx]

        # Scoring
        cosine = np.dot(query_vec, neighbor_vec)
        key_score = key_compatibility(query_row['key'], neighbor_row['key'])
        bpm_score = bpm_compatibility(query_row['bpm'], neighbor_row['bpm'])

        # Weighted combination
        final_score = 0.7 * cosine + 0.2 * key_score + 0.1 * bpm_score

        results.append({
            'track_id': neighbor_id,
            'artist': neighbor_row['artist'],
            'title': neighbor_row['title'],
            'bpm': neighbor_row['bpm'],
            'key': neighbor_row['key'],
            'score': final_score,
            'cosine': cosine,
            'key_score': key_score,
            'bpm_score': bpm_score
        })

    # Sort by final score, return top results
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:final_top]
```

#### scoring.py
Musical compatibility scoring:

```python
# Camelot wheel positions
CAMELOT = {
    'C': '8B', 'Am': '8A', 'G': '9B', 'Em': '9A',
    'D': '10B', 'Bm': '10A', 'A': '11B', 'F#m': '11A',
    # ... full mapping
}

def key_compatibility(key1: str, key2: str) -> float:
    """
    Score key compatibility using Camelot wheel.

    Returns:
        1.0  - Same key (perfect match)
        0.8  - Adjacent on Camelot wheel (+/-1)
        0.6  - Relative major/minor (same number)
        0.4  - Two steps away
        0.0  - Incompatible
    """
    if key1 == key2:
        return 1.0

    c1, c2 = CAMELOT.get(key1), CAMELOT.get(key2)
    if not c1 or not c2:
        return 0.5  # Unknown keys

    num1, letter1 = int(c1[:-1]), c1[-1]
    num2, letter2 = int(c2[:-1]), c2[-1]

    num_diff = min(abs(num1 - num2), 12 - abs(num1 - num2))

    if num_diff == 0 and letter1 != letter2:
        return 0.6  # Relative major/minor
    elif num_diff == 1 and letter1 == letter2:
        return 0.8  # Adjacent
    elif num_diff == 2 and letter1 == letter2:
        return 0.4  # Two steps
    else:
        return 0.0  # Incompatible

def bpm_compatibility(bpm1: float, bpm2: float) -> float:
    """
    Score BPM compatibility with half/double time support.

    Returns:
        1.0  - Within 6% of each other
        0.7  - Half or double time (within 6%)
        0.0  - Incompatible
    """
    if bpm1 == 0 or bpm2 == 0:
        return 0.5

    ratio = bpm1 / bpm2

    # Direct match (within 6%)
    if 0.94 <= ratio <= 1.06:
        return 1.0

    # Half time
    if 0.47 <= ratio <= 0.53:
        return 0.7

    # Double time
    if 1.88 <= ratio <= 2.12:
        return 0.7

    return 0.0
```

#### set_generator.py
DJ set generation with anchor track support:

```python
def generate_set(
    anchor_tracks: List[Tuple[int, int]],  # (track_id, position)
    set_length: int,
    meta: pd.DataFrame,
    vectors: np.ndarray,
    ids: List[int],
    index: FaissCosIndex,
    deleted: Set[int]
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
    set_tracks = [None] * set_length
    used_ids = set()

    # Place anchors
    for track_id, position in anchor_tracks:
        track_row = meta[meta['track_id'] == track_id].iloc[0]
        set_tracks[position] = SetTrack(
            track_id=track_id,
            artist=track_row['artist'],
            title=track_row['title'],
            bpm=track_row['bpm'],
            key=track_row['key'],
            position=position,
            is_anchor=True
        )
        used_ids.add(track_id)

    # Fill empty slots
    for i in range(set_length):
        if set_tracks[i] is not None:
            continue

        # Find context
        prev_track = find_previous_track(set_tracks, i)
        next_track = find_next_track(set_tracks, i)

        # Get candidates
        candidates = get_contextual_recommendations(
            prev_track, next_track,
            meta, vectors, ids, index, deleted
        )

        # Select best unused
        for candidate in candidates:
            if candidate['track_id'] not in used_ids:
                set_tracks[i] = SetTrack(
                    track_id=candidate['track_id'],
                    artist=candidate['artist'],
                    title=candidate['title'],
                    bpm=candidate['bpm'],
                    key=candidate['key'],
                    position=i,
                    is_anchor=False
                )
                used_ids.add(candidate['track_id'])
                break

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
                    │   - file path       │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
    │  Duplicate      │ │ Load Exist- │ │  Find New       │
    │  Detection      │ │ ing Data    │ │  Tracks         │
    └────────┬────────┘ └──────┬──────┘ └────────┬────────┘
             │                 │                  │
             └─────────────────┼──────────────────┘
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
                    │  (256-dim vector)   │
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
    │ meta.parquet    │ │embeddings.  │ │  FAISS Index    │
    │ (metadata)      │ │parquet      │ │  (HNSW)         │
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
    │   FAISS Search      │
    │   (HNSW k-NN)       │
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
    │  - Skip deleted     │
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
    │  Return Top-15      │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Display in UI      │
    │  (Recommendations   │
    │   Tab)              │
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
| `index.npy` | NumPy binary | FAISS vectors | ~13MB (4K tracks) |
| `ids.json` | JSON | Track ID mapping | ~16KB (4K tracks) |
| `deleted_tracks.json` | JSON | User deletions | ~2KB |
| `settings.json` | JSON | User preferences | ~1KB |

### 8.2 Data Schemas

#### meta.parquet
```
Column      Type      Description
──────────────────────────────────────
track_id    int64     Unique identifier (from Rekordbox)
artist      string    Artist name
title       string    Track title
album       string    Album name
bpm         float64   Beats per minute
key         string    Musical key (e.g., "Am", "C")
path        string    Full file path to audio file
```

#### embeddings.parquet
```
Column      Type      Description
──────────────────────────────────────
track_id    int64     Foreign key to meta
v0-v255     float64   256-dimensional embedding vector
```

#### index.npy
```
Shape: (N, 256) where N = number of tracks
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

### 9.5 FAISS Index Configuration

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Index Type | HNSW | Hierarchical Navigable Small World graph |
| Dimension | 256 | Embedding vector size |
| M (neighbors) | 32 | Connections per node |
| efConstruction | 200 | Index build quality (higher = better) |
| efSearch | 64 | Query quality (higher = more accurate) |
| Metric | Inner Product | Cosine on normalized vectors |

**Performance Characteristics:**
- Index build: O(n log n)
- Query time: O(log n)
- Memory: O(n × M × 4 bytes)

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
│  │  │  File | Edit | View | Help                       │  │  │
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
        self.meta, self.emb, self.vec, self.ids, self.index, self.deleted = load_all()

        # Create UI structure
        self.create_menu()
        self.create_notebook()
        self.create_status_bar()

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
| **Export** | `PlaylistExportTabMixin` | Export recommendations or sets as M3U playlists |
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
                                    │  Download model │
                                    │  (if needed)    │
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

```python
# Hidden imports (not automatically detected)
hiddenimports = [
    'numpy',
    'pandas',
    'faiss',
    'essentia',
    'essentia.standard',
    'soundfile',
    'PIL',
    'lxml',
    'pyarrow',
    'tkinter',
    'tkinter.ttk',
]

# Data files to include
datas = [
    ('models/', 'models/'),      # ML model
    ('assets/', 'assets/'),       # Icons
]

# Binary libraries to collect
binaries = collect_dynamic_libs('numpy')
binaries += collect_dynamic_libs('pandas')
binaries += collect_dynamic_libs('faiss')
binaries += collect_dynamic_libs('essentia')
```

### 11.3 CI/CD Pipelines

#### macOS Build (Apple Silicon)
```yaml
# .github/workflows/build-macos.yml
name: Build macOS (ARM64)

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build:
    runs-on: macos-14  # Apple Silicon runner

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Download model
        run: |
          mkdir -p models
          curl -o models/discogs_multi_embeddings-effnet-bs64-1.pb \
            https://essentia.upf.edu/models/...

      - name: Build with PyInstaller
        run: python build_app.py

      - name: Create DMG
        run: |
          hdiutil create -volname "Cosine Companion" \
            -srcfolder dist/Cosine\ Companion.app \
            -ov -format UDZO \
            Cosine-Companion-macOS-arm64.dmg

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: macos-arm64
          path: '*.dmg'
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
- Converts Rekordbox tonality to standard key notation
- Extracts track IDs for deduplication

### 12.2 Essentia Model

**Model Source**: Essentia Models Repository

```
URL: https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/
File: discogs_multi_embeddings-effnet-bs64-1.pb
Size: ~300MB
Format: TensorFlow frozen graph (.pb)
```

**Model Capabilities**:
- Genre classification
- Mood detection
- Musical style embeddings
- Instrument recognition

### 12.3 M3U Playlist Export

**Output Format**: Extended M3U (M3U8)

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
│  2. Environment Variables (.env)                    │
│     └─ API keys, debug flags                       │
│                                                     │
│  3. User Settings (data/settings.json)              │
│     └─ Per-user preferences                        │
│                                                     │
│  4. Runtime Arguments (CLI flags)                   │
│     └─ --force, --sample, etc.                     │
│                                                     │
│  Priority: Runtime > User > Environment > Defaults  │
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

# FAISS Search Parameters
DEFAULT_TOPK = 200          # Initial candidates
DEFAULT_FINAL_TOP = 15      # Final recommendations

# Key Compatibility Scores
KEY_SCORES = {
    'same': 1.0,
    'adjacent': 0.8,
    'relative': 0.6,
    'two_step': 0.4,
    'incompatible': 0.0,
}

# BPM Tolerance
BPM_TOLERANCE = 0.06  # 6% tolerance
```

### 13.3 Path Resolution

```python
# config/paths.py

def get_data_dir() -> Path:
    """Platform-aware data directory resolution."""

    if getattr(sys, 'frozen', False):
        # Running as compiled application
        if sys.platform == 'darwin':
            base = Path.home() / 'Library' / 'Application Support'
        elif sys.platform == 'win32':
            base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
        else:  # Linux
            base = Path.home() / '.local' / 'share'

        return base / 'Cosine Companion'
    else:
        # Development mode
        return Path(__file__).parent.parent.parent / 'data'

def get_model_path() -> Path:
    """Returns path to Essentia model file."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'models' / 'discogs_multi_embeddings-effnet-bs64-1.pb'
    else:
        return Path(__file__).parent.parent.parent / 'models' / 'discogs_multi_embeddings-effnet-bs64-1.pb'
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

### 14.2 FAISS Search

| Metric | Value |
|--------|-------|
| Index build time | O(n log n) |
| Query time | O(log n) |
| Memory per track | ~1KB (256 × float32) |

**Scaling Characteristics**:
- 1,000 tracks: <10ms query time
- 10,000 tracks: ~20ms query time
- 100,000 tracks: ~50ms query time

### 14.3 Memory Management

```
Application Memory Footprint (4,000 tracks):
├── Metadata DataFrame:        ~5 MB
├── Embeddings DataFrame:      ~20 MB
├── FAISS Index:              ~15 MB
├── NumPy Vectors:            ~13 MB
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
| **API Keys** | Environment variables (`.env` file) |
| **User Data** | No personally identifiable information collected |

### 15.2 Input Validation

```python
# XML Parsing Safety
def parse_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    # Validate file exists and is readable
    if not Path(xml_path).exists():
        raise FileNotFoundError(f"XML file not found: {xml_path}")

    # Use lxml with safe defaults (no external entities)
    parser = etree.XMLParser(resolve_entities=False)
    tree = etree.parse(xml_path, parser)
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
| `core/index_builder.py` | ~80 | FAISS wrapper |

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Camelot Wheel** | Circular key notation system for DJ mixing compatibility |
| **Embedding** | Dense vector representation of audio characteristics |
| **FAISS** | Facebook AI Similarity Search - library for efficient similarity search |
| **HNSW** | Hierarchical Navigable Small World - graph-based approximate nearest neighbor algorithm |
| **Rekordbox** | Pioneer DJ's music management software |
| **M3U** | Multimedia playlist file format |
| **Parquet** | Columnar storage format for efficient data analytics |

---

*Document generated for Cosine Companion v1.x*
*Last updated: December 2024*
