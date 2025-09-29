# DJ Cosine Companion

A tool for finding similar tracks based on audio content, key compatibility, and BPM matching. Uses Essentia's Discogs-EffNet embeddings and FAISS for efficient similarity search.

## Quick Start

1. **Install dependencies** (see [Installation](#installation))
2. **Download the required model** (see [Model Setup](#model-setup))
3. **Export your library from Rekordbox** as XML
4. **Index your library:** `python src/dj_companion.py index /path/to/rekordbox_export.xml`
5. **Launch the UI:** `python src/dj_companion.py ui`

## Installation

### Prerequisites
- Python 3.8+
- Conda (recommended) or pip

### Install Dependencies

Using conda (recommended):
```bash
conda install -c conda-forge numpy pandas lxml soundfile typer
conda install -c mtg essentia-tensorflow
conda install -c conda-forge faiss-cpu
```

Using pip:
```bash
pip install numpy pandas lxml soundfile typer essentia-tensorflow faiss-cpu
```

## Model Setup

**Required:** Download the Discogs-EffNet model for audio embeddings.

```bash
# Navigate to the models directory
cd models/

# Download the model (choose one method):
wget https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb

# OR using curl:
curl -O https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
```

See [models/README.md](models/README.md) for detailed instructions and troubleshooting.

## Project Structure

```
dj-cosine/
├── src/                    # Source code
│   ├── dj_companion.py     # Main entry point
│   ├── config.py           # Configuration constants
│   ├── rekordbox.py        # Rekordbox XML parsing
│   ├── embeddings.py       # Audio embedding generation
│   ├── indexing.py         # FAISS similarity search
│   ├── scoring.py          # Key/BPM compatibility
│   ├── recommendations.py  # Track recommendation logic
│   ├── pipeline.py         # Indexing pipeline
│   ├── ui.py              # Tkinter user interface
│   └── features/          # Feature specifications
├── models/                # ML models (download required)
├── data/                  # Generated data files (gitignored)
└── README.md
```

## Usage

### Indexing Your Library

**First time (full index):**
```bash
python src/dj_companion.py index /path/to/rekordbox_export.xml
```

**Update with new tracks (incremental):**
```bash
python src/dj_companion.py index /path/to/rekordbox_export.xml
```

**Force full reindex:**
```bash
python src/dj_companion.py index /path/to/rekordbox_export.xml --force
```

**Debug with sample size:**
```bash
python src/dj_companion.py index /path/to/rekordbox_export.xml --sample 50
```

### Launch the UI
```bash
python src/dj_companion.py ui
```

## Dependencies

- `numpy`, `pandas` - Data processing
- `lxml` - XML parsing  
- `soundfile` - Audio file reading
- `essentia` - Audio analysis and embeddings
- `faiss` - Similarity search
- `typer` - CLI interface
- `tkinter` - GUI (included with Python)

## Data Files

The indexing process creates these files in the `data/` directory:

- `meta.parquet` - Track metadata from Rekordbox XML
- `embeddings.parquet` - Audio embeddings with track IDs  
- `index.npy` - Normalized embedding vectors for FAISS
- `ids.json` - Track ID mapping for FAISS index
