# DJ Companion - Complete Program Flow Documentation

This document provides a comprehensive overview of how the DJ Companion system works, including exact execution flow, component interactions, and data flow diagrams.

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        DJ COMPANION SYSTEM                      │
├─────────────────────────────────────────────────────────────────┤
│  CLI Entry Point: dj_companion.py                               │
│  ├── index command → pipeline.py                                │
│  └── ui command → ui.py                                         │
└─────────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────┐                 ┌───────────────────────┐
│  INDEXING FLOW  │                 │   UI/APP FLOW         │
│                 │                 │                       │
│ pipeline.py     │                 │ ui.py                 │
│ ├─ rekordbox.py │                 │ ├─ recommendations.py │
│ ├─ embeddings.py│                 │ ├─ indexing.py        │
│ ├─ indexing.py  │                 │ └─ scoring.py         │
│ └─ config.py    │                 │                       │
└─────────────────┘                 └───────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SHARED DATA LAYER                           │
│  config.py → data/ directory                                    │
│  ├── meta.parquet     (track metadata)                          │
│  ├── embeddings.parquet (audio embeddings)                      │
│  ├── index.npy        (FAISS vectors)                           │
│  └── ids.json         (track ID mapping)                        │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Program Entry Points

### Command Line Interface (dj_companion.py)

```python
# Entry point structure
if __name__ == "__main__":
    cli()  # Typer CLI dispatcher
```

**Available Commands:**
1. `python dj_companion.py index <xml_file> [--force] [--sample N]`
2. `python dj_companion.py ui`

---

## 📊 INDEXING FLOW (Detailed)

When you run: `python dj_companion.py index rekordbox_export.xml`

### Phase 1: CLI Command Parsing

```
dj_companion.py:index()
│
├─ Argument: xml (Rekordbox XML file path)
├─ Option: --force (boolean, default False)
├─ Option: --sample N (integer, optional debug sample size)
│
└─ Calls: pipeline.cmd_index(xml, force_full=force, sample_size=sample)
```

### Phase 2: Incremental Index Pipeline

```mermaid
graph TD
    A[cmd_index starts] --> B{force_full?}
    B -->|Yes| C[existing_meta = None<br/>existing_emb = None]
    B -->|No| D[load_existing_data]
    
    D --> E{Data files exist?}
    E -->|Yes| F[Load meta.parquet<br/>Load embeddings.parquet]
    E -->|No| G[existing_meta = None<br/>existing_emb = None]
    
    C --> H[read_rekordbox_xml]
    F --> H
    G --> H
    
    H --> I[find_new_tracks]
    I --> J{sample_size set?}
    J -->|Yes| K[Limit to first N tracks]
    J -->|No| L[Process all new tracks]
    K --> M{New tracks found?}
    L --> M
    M -->|No| N[Print: No new tracks<br/>EXIT]
    M -->|Yes| O[Initialize DiscogsEffnetEmbedder]
    
    O --> P[Process each new track]
    P --> Q[embed_file for each track]
    Q --> R[Collect vectors & track_ids]
    R --> S[Create embeddings DataFrame with pd.concat]
    S --> T[merge_embeddings]
    T --> U[Save combined data]
    U --> V[Print completion stats]
```

### Detailed Component Calls in Indexing:

#### 1. **pipeline.cmd_index(rb_xml, force_full=False, sample_size=None)**
```python
def cmd_index(rb_xml: str, force_full: bool = False, sample_size: int | None = None):
    # Step 1: Load existing data (unless force)
    if force_full:
        existing_meta, existing_emb = None, None
    else:
        existing_meta, existing_emb = load_existing_data()
    
    # Step 2: Parse current XML
    current_meta = read_rekordbox_xml(rb_xml)  # → rekordbox.py
    
    # Step 3: Find new tracks
    new_tracks = find_new_tracks(current_meta, existing_meta)
    
    # Step 4: Apply sample limit if debugging
    if sample_size is not None:
        new_tracks = new_tracks.head(sample_size)
    
    # Step 5: Process new tracks
    embedder = DiscogsEffnetEmbedder()  # → embeddings.py
    for track in new_tracks:
        vector = embedder.embed_file(track.path_local)
    
    # Step 6: Create DataFrame efficiently (no fragmentation warnings)
    v_cols = [f"v{i}" for i in range(new_vectors_array.shape[1])]
    new_emb_df = pd.concat([
        pd.DataFrame({"track_id": new_track_ids}),
        pd.DataFrame(new_vectors_array, columns=v_cols)
    ], axis=1)
    
    # Step 7: Merge and save
    combined_data = merge_embeddings(...)
    save_to_files(combined_data)
```

#### 2. **rekordbox.read_rekordbox_xml(xml_path)**
```python
def read_rekordbox_xml(xml_path: str) -> pd.DataFrame:
    # Parse XML using lxml
    tree = etree.parse(xml_path)
    root = tree.getroot()
    
    # Extract track data with robust URL decoding
    for track in root.xpath("//COLLECTION/TRACK"):
        location = track.get("Location")
        # Handle file://localhost URLs and percent-encoding
        if location.startswith("file://"):
            parsed_url = urlparse(location)
            path_local = unquote(parsed_url.path)
        
        extract_metadata(track)  # artist, title, bpm, key, etc.
    
    # Return DataFrame with verified local file paths
    return processed_dataframe
```

#### 3. **embeddings.DiscogsEffnetEmbedder.embed_file(path)**
```python
def embed_file(self, path_local: str) -> np.ndarray:
    # Multi-decoder fallback strategy
    audio = self._load_audio_robust(path_local)  # Essentia → soundfile → librosa → ffmpeg
    if audio is None:
        return None
    
    # Use Essentia's recommended approach
    # Call TensorflowPredictEffnetDiscogs once on whole audio
    embeddings = self.pred(audio)  # output="PartitionedCall:1"
    
    # Pool if model outputs multiple embeddings
    if embeddings.ndim > 1:
        pooled = np.concatenate([embeddings.mean(axis=0), embeddings.std(axis=0)])
    else:
        pooled = embeddings
    
    # L2 normalize
    return pooled / (np.linalg.norm(pooled) + 1e-9)
```

### Data Files Created/Updated:

```
data/
├── meta.parquet        ← Current XML metadata
├── embeddings.parquet  ← Track embeddings with IDs
├── index.npy          ← Normalized vectors for FAISS
└── ids.json           ← Track ID → vector index mapping
```

---

## 🎵 UI/APPLICATION FLOW (Detailed)

When you run: `python dj_companion.py ui`

### Phase 1: Application Startup

```
dj_companion.py:ui()
│
└─ Calls: ui.run_ui()
   │
   └─ Creates: App() instance
      │
      └─ App.__init__()
         ├─ Load all data: recommendations.load_all()
         ├─ Create UI widgets (including sorting buttons)
         └─ Start mainloop()
```

### Phase 2: Data Loading Process

```mermaid
graph TD
    A[App.__init__ starts] --> B[recommendations.load_all]
    B --> C[Load meta.parquet]
    B --> D[Load embeddings.parquet] 
    B --> E[Load index.npy vectors]
    B --> F[Load ids.json]
    
    C --> G[Create indexed DataFrames]
    D --> G
    E --> H[Build FaissCosIndex]
    F --> H
    
    G --> I[Return loaded structures]
    H --> I
    I --> J[UI ready for interaction]
    J --> K[Initialize empty recommendations list]
```

#### **recommendations.load_all() - Detailed Flow**
```python
def load_all():
    # Load saved data files
    meta = pd.read_parquet(META_PQ)           # Track metadata
    emb = pd.read_parquet(EMB_PQ)             # Embeddings with track_ids
    V = np.load(IDX_NPY)                      # Vector matrix
    ids = json.load(IDS_JSON)                 # Track ID list
    
    # Build FAISS index with defensive normalization
    idx = FaissCosIndex(V.shape[1])           # → indexing.py
    for track_id, vector in zip(ids, V):
        idx.add(track_id, vector)             # Vectors normalized in add()
    
    # Create indexed DataFrames for fast lookup
    meta_ix = meta.set_index("track_id")
    emb_ix = emb.set_index("track_id")
    
    return meta, meta_ix, emb_ix, idx, V, ids
```

### Phase 3: Enhanced User Interaction Flow

```mermaid
graph TD
    A[User clicks 'Set Current Track'] --> B[pick_current]
    B --> C[Show search dialog]
    C --> D[User enters search query]
    D --> E[Search metadata for matches]
    E --> F[Show SimplePicker dialog]
    F --> G[User selects track]
    G --> H[set_current with track_id]
    H --> I[refresh_suggestions]
    
    I --> J[recommendations.recommend_for]
    J --> K[Get track vector from embeddings]
    K --> L[FAISS similarity search]
    L --> M[Recompute cosine from stored vectors]
    M --> N[Score results: cosine + key + BPM]
    N --> O[Sort by final score]
    O --> P[Store in current_recommendations]
    P --> Q[update_listbox]
    
    Q --> R[Display with Cos XX.X% Score YY.Y%]
    
    S[User clicks sort button] --> T[sort_suggestions]
    T --> U{Sort by what?}
    U -->|Score| V[Sort by weighted score DESC]
    U -->|Cosine| W[Sort by cosine similarity DESC]
    U -->|Key| X[Sort by key alphabetically ASC]
    U -->|BPM| Y[Sort by BPM DESC]
    U -->|Artist| Z[Sort by artist alphabetically ASC]
    
    V --> AA[update_listbox]
    W --> AA
    X --> AA
    Y --> AA
    Z --> AA
    AA --> R
```

#### **Enhanced UI Components**

```python
# New UI layout with sorting
def __init__(self):
    # ... existing setup ...
    
    # Main buttons
    btns = tk.Frame(self)
    tk.Button(btns, text="Set Current Track", command=self.pick_current)
    tk.Button(btns, text="Copy Selected to Clipboard", command=self.copy_selected)
    
    # NEW: Sorting buttons
    sort_frame = tk.Frame(self)
    tk.Label(sort_frame, text="Sort by:")
    tk.Button(sort_frame, text="Score", command=lambda: self.sort_suggestions("score"))
    tk.Button(sort_frame, text="Cosine", command=lambda: self.sort_suggestions("cosine"))
    tk.Button(sort_frame, text="Key", command=lambda: self.sort_suggestions("key"))
    tk.Button(sort_frame, text="BPM", command=lambda: self.sort_suggestions("bpm"))
    tk.Button(sort_frame, text="Artist", command=lambda: self.sort_suggestions("artist"))
    
    # Store recommendations for sorting
    self.current_recommendations: List[Dict[str, Any]] = []
```

#### **New Sorting Functionality**

```python
def sort_suggestions(self, sort_by: str):
    """Sort current recommendations by the specified field."""
    if not self.current_recommendations:
        return
    
    # Define sort logic
    if sort_by == "score":
        key_func = lambda x: float(x.get('score', 0))
        reverse = True  # Highest first
    elif sort_by == "cosine":
        key_func = lambda x: float(x.get('cosine', 0))
        reverse = True  # Highest first
    elif sort_by == "key":
        key_func = lambda x: str(x.get('key', ''))
        reverse = False  # Alphabetical
    elif sort_by == "bpm":
        key_func = lambda x: float(x.get('bpm', 0) or 0)
        reverse = True  # Highest first
    elif sort_by == "artist":
        key_func = lambda x: str(x.get('artist', '')).lower()
        reverse = False  # Alphabetical
    
    # Apply sort and refresh display
    self.current_recommendations.sort(key=key_func, reverse=reverse)
    self.update_listbox()

def update_listbox(self):
    """Separate display logic for clean sorting."""
    self.listbox.delete(0, tk.END)
    
    for r in self.current_recommendations:
        cosine = float(r.get('cosine', 0))
        score = float(r.get('score', 0))
        cos_pct = cosine * 100.0
        score_pct = max(0.0, min(1.0, score)) * 100.0
        line = f"{r['artist']} – {r['title']}   [Key {r['key'] or '?'}  BPM {r['bpm'] or '?'}  Cos {cos_pct:.1f}%  Score {score_pct:.1f}%]"
        self.listbox.insert(tk.END, line)
    
    self.status.config(text=f"{self.listbox.size()} suggestions")
```

#### **Recommendation Generation - Step by Step**

```python
# 1. User sets current track
def set_current(self, track_id: str):
    self.current_id = track_id
    self.refresh_suggestions()

# 2. Generate and store recommendations
def refresh_suggestions(self):
    if not self.current_id:
        self.current_recommendations = []
        self.update_listbox()
        return
    
    # Get fresh recommendations with explicit cosine calculation
    self.current_recommendations = recommend_for(
        self.current_id,      # Source track
        self.meta_ix,         # Metadata lookup
        self.emb_ix,          # Embeddings lookup  
        self.idx,             # FAISS index
        final_top=20          # Number of results
    )
    self.update_listbox()
```

#### **recommendations.recommend_for() - Enhanced with Explicit Cosine**
```python
def recommend_for(track_id, meta_ix, emb_ix, idx, topk=200, final_top=15):
    # Step 1: Get source track vector (normalized)
    src_vector = vector_for(track_id, emb_ix)     # Defensive normalization
    src_meta = meta_ix.loc[track_id]              # Source metadata
    
    # Step 2: FAISS similarity search
    nbrs = idx.search(src_vector, k=topk+1)       # → indexing.py
    # Returns: [(track_id, faiss_inner_product), ...]
    
    # Step 3: Score each candidate with explicit cosine calculation
    recommendations = []
    for candidate_id, faiss_score in nbrs:
        if candidate_id == track_id: continue      # Skip self
        
        target_meta = meta_ix.loc[candidate_id]
        target_vector = vector_for(candidate_id, emb_ix)  # Re-fetch for accuracy
        
        # Explicit cosine calculation (dot product of normalized vectors)
        cosine_similarity = np.dot(src_vector, target_vector)
        
        # Calculate compatibility scores
        key_score = key_compat(src_meta.key, target_meta.key)        # → scoring.py
        bmp_score = bpm_compat(src_meta.bpm, target_meta.bpm)        # → scoring.py
        final_score = final_score(cosine_similarity, key_score, bmp_score) # → scoring.py
        
        recommendations.append({
            "track_id": candidate_id,
            "artist": target_meta.artist,
            "title": target_meta.title,
            "bpm": target_meta.bpm,
            "key": target_meta.key,
            "score": final_score,
            "cosine": cosine_similarity,  # Store explicit cosine
            "key_score": key_score,
            "bmp_score": bmp_score,
        })
    
    # Step 4: Sort by final score and return top results
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return recommendations[:final_top]
```

### Scoring Components Detail

#### **scoring.py Functions Called:**

1. **key_compat(src_key, dst_key)**
   ```python
   # Convert to Camelot wheel notation (expanded mapping)
   src_camelot = to_camelot(src_key)    # e.g., "Am" → "8A", "G#m" → "4A"
   dst_camelot = to_camelot(dst_key)
   
   # Calculate harmonic compatibility
   if same_key: return 1.0
   if adjacent_keys: return 0.8         # ±1 on Camelot wheel
   if relative_major_minor: return 0.6  # 8A ↔ 8B
   if two_steps_away: return 0.4        # ±2 on wheel
   else: return 0.0
   ```

2. **bpm_compat(src_bpm, dst_bpm)**
   ```python
   # Check direct BPM match (±6% tolerance)
   if within_tolerance(src_bpm, dst_bpm, 0.06): return 1.0
   
   # Check half/double tempo matches
   for multiplier in [0.5, 2.0]:
       if within_tolerance(src_bpm * multiplier, dst_bpm, 0.06): return 0.7
   
   return 0.0
   ```

3. **final_score(cosine, key, bmp, weights=(0.7, 0.2, 0.1))**
   ```python
   return 0.7*cosine + 0.2*key + 0.1*bmp
   ```

---

## 🔄 Complete System Data Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Rekordbox XML  │    │  Audio Files    │    │  User Input     │
│                 │    │  (.mp3, .wav)   │    │  (UI clicks)    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ rekordbox.py    │    │ embeddings.py   │    │ ui.py           │
│ XML parsing     │    │ Audio→Vectors   │    │ User interface  │
│ URL decoding    │    │ Multi-decoder   │    │ Sorting logic   │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────┐
                    │ pipeline.py     │
                    │ Orchestration   │
                    │ Incremental     │
                    └─────────┬───────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Data Files      │
                    │ (.parquet,      │
                    │  .npy, .json)   │
                    └─────────┬───────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │recommendations.py│
                    │ Load & Search   │
                    │ Explicit cosine │
                    └─────────┬───────┘
                              │
                              ▼
         ┌─────────────────┐  │  ┌─────────────────┐
         │ indexing.py     │  │  │ scoring.py      │
         │ FAISS Search    │◄─┴─►│ Key/BPM Compat │
         │ Defensive norm  │     │ Extended keys   │
         └─────────────────┘     └─────────────────┘
```

## 📋 Component Responsibility Matrix

| Component | Primary Role | Key Functions | Dependencies |
|-----------|--------------|---------------|--------------|
| **dj_companion.py** | CLI Entry Point | `index()`, `ui()` | pipeline, ui |
| **pipeline.py** | Indexing Orchestration | `cmd_index()`, `merge_embeddings()` | rekordbox, embeddings, config |
| **rekordbox.py** | XML Parsing | `read_rekordbox_xml()` | lxml, pandas, urllib |
| **embeddings.py** | Audio Processing | `DiscogsEffnetEmbedder.embed_file()` | essentia, soundfile, librosa |
| **indexing.py** | Similarity Search | `FaissCosIndex.search()` | faiss, numpy |
| **scoring.py** | Compatibility Scoring | `key_compat()`, `bpm_compat()` | None |
| **recommendations.py** | Data Loading & Recommendations | `load_all()`, `recommend_for()` | All above |
| **ui.py** | User Interface | `App.sort_suggestions()`, `refresh_suggestions()` | tkinter, recommendations |
| **config.py** | Configuration | File paths, constants | pathlib |

## ⚡ Performance Characteristics

### Indexing Performance:
- **First Run**: O(n) where n = number of tracks (must process all)
- **Incremental**: O(k) where k = number of new tracks (k << n)
- **Bottleneck**: Audio file I/O and embedding computation
- **Sample Mode**: O(sample_size) for debugging/testing

### Search Performance:
- **FAISS Search**: O(log n) approximate nearest neighbors
- **Scoring**: O(k) where k = number of candidates (typically 200)
- **UI Update**: O(k) for displaying results
- **Sorting**: O(k log k) for recommendation sorting

### Memory Usage:
- **Embeddings**: ~1KB per track (depends on model dimensionality)
- **FAISS Index**: ~4x embedding size (HNSW overhead)
- **Metadata**: ~100 bytes per track
- **UI State**: ~50KB for current recommendations list

### New UI Features:
- **Interactive Sorting**: Sort by Score, Cosine, Key, BPM, or Artist
- **Persistent State**: Recommendations cached until track change
- **Dual Score Display**: Both raw cosine (Cos XX.X%) and weighted score (Score YY.Y%)
- **Larger Window**: 800x600 to accommodate sorting controls

This flow ensures efficient, scalable operation while maintaining clear separation of concerns between components and providing enhanced user interaction capabilities.
