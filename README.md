# DJ Companion

A tool for finding similar tracks based on audio content, key compatibility, and BPM matching. Uses Essentia's Discogs-EffNet embeddings and FAISS for efficient similarity search.

## Project Structure

The codebase has been organized into logical modules:

### Core Modules

- **`config.py`** - Configuration constants and data paths
- **`rekordbox.py`** - Rekordbox XML parsing functionality  
- **`embeddings.py`** - Audio embedding generation using Essentia Discogs-EffNet
- **`indexing.py`** - FAISS index management for similarity search
- **`scoring.py`** - Key and BPM compatibility scoring for DJ mixing
- **`recommendations.py`** - Track recommendation logic and data loading
- **`pipeline.py`** - Complete indexing pipeline (XML → embeddings → index)
- **`ui.py`** - Tkinter user interface

### Main Application

- **`dj_companion.py`** - Main entry point with CLI commands

## Usage

### 1. Index your library
```bash
python dj_companion.py index /path/to/rekordbox_export.xml
```

### 2. Launch the UI
```bash  
python dj_companion.py ui
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
