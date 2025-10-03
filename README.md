# Cosine Companion

A tool for finding similar tracks based on audio content, key compatibility, and BPM matching. Uses Essentia's Discogs-EffNet embeddings and FAISS for efficient similarity search.

## Quick Start

1. **Install dependencies** (see [Installation](#installation))
2. **Download the required model** (see [Model Setup](#model-setup))
3. **Export your library from Rekordbox** as XML
4. **Index your library:** `python src/dj_companion.py index /path/to/rekordbox_export.xml`
5. **Launch the UI:** `python src/dj_companion.py ui`

## Installation

### Option 1: Standalone Application (Recommended for End Users)

Download the pre-built application for your platform:
- **macOS**: `DJ-Companion-Installer.dmg`
- **Windows**: `DJ-Companion-Setup.exe`  
- **Linux**: `DJ-Companion.AppImage`

Simply install and run - no Python required!

### Option 2: From Source (For Developers)

#### Prerequisites
- Python 3.8+
- Conda (recommended) or pip

#### Install Dependencies

Using conda (recommended):
```bash
conda install -c conda-forge numpy pandas lxml soundfile typer
conda install -c mtg essentia-tensorflow
conda install -c conda-forge faiss-cpu
```

Using pip:
```bash
pip install -r requirements.txt
```

Or use the provided environment:
```bash
conda env create -f environment.yml
conda activate dj-companion
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
├── src/                       # Source code
│   ├── dj_companion.py        # Main CLI entry point
│   │
│   ├── config/                # Configuration management
│   │   ├── paths.py           # File paths
│   │   └── defaults.py        # Default parameters
│   │
│   ├── core/                  # Core data management
│   │   ├── loader.py          # Data loading
│   │   ├── persistence.py     # Data saving
│   │   ├── index_builder.py   # FAISS index management
│   │   └── duplicates.py      # Duplicate detection
│   │
│   ├── processing/            # Audio processing & pipeline
│   │   ├── embeddings.py      # Audio embedding generation
│   │   ├── xml_parser.py      # Rekordbox XML parsing
│   │   └── pipeline.py        # Indexing orchestration
│   │
│   ├── recommendations/       # Recommendation engine
│   │   ├── engine.py          # Main recommendation logic
│   │   ├── scoring.py         # Key/BPM compatibility
│   │   ├── set_generator.py   # DJ set generation
│   │   ├── models.py          # Data models
│   │   ├── transitions.py     # Transition scoring
│   │   └── search.py          # Track search
│   │
│   ├── ui/                    # User interface
│   │   ├── app.py             # Main application
│   │   ├── recommendations_tab.py  # Track exploration
│   │   ├── set_creator_tab.py      # DJ set creation
│   │   ├── library_tab.py          # Library management
│   │   └── dialogs.py         # UI dialogs
│   │
│   └── features/              # Feature specifications
│
├── models/                    # ML models (download required)
├── data/                      # Generated data files (gitignored)
├── README.md
└── PROGRAM_FLOW.md           # Detailed system documentation
```

### Architecture

The codebase follows a modular package structure with clear separation of concerns:

- **config/**: Configuration and constants (no dependencies)
- **core/**: Data management, loading, persistence, and indexing
- **processing/**: Audio processing and indexing pipeline
- **recommendations/**: Recommendation engine with scoring and set generation
- **ui/**: Tabbed user interface with mixin architecture

Each package contains focused modules (90-270 lines each) for better maintainability and testability. See [PROGRAM_FLOW.md](PROGRAM_FLOW.md) for detailed documentation.

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

### Check for Duplicates (Optional)
```bash
python src/dj_companion.py clean-duplicates /path/to/rekordbox_export.xml
```

This analyzes your collection for duplicate tracks without modifying any files. Duplicates are automatically removed during indexing.

### Launch the UI
```bash
python src/dj_companion.py ui
```

The UI features three tabs:
- **Explore**: Find similar tracks with interactive sorting
- **Set Creator**: Generate DJ sets with anchor tracks at specific positions
- **Library**: Browse, search, and manage your indexed tracks

## Features

- 🎵 **Audio Similarity Search**: Find tracks that sound similar using deep learning embeddings
- 🎹 **Key Compatibility**: Harmonic mixing support with Camelot wheel notation
- 🥁 **BPM Matching**: Automatic tempo compatibility detection (including half/double time)
- 🎛️ **Interactive Sorting**: Sort recommendations by score, cosine similarity, key, BPM, or artist
- 🎚️ **DJ Set Generation**: Create complete sets with anchor tracks at specific positions
- 📚 **Library Management**: Browse, search, and delete tracks with multi-select support
- ⚡ **Incremental Indexing**: Only process new tracks, saving time on library updates
- 🔍 **Duplicate Detection**: Automatic identification and removal of duplicate tracks

## Dependencies

- `numpy`, `pandas` - Data processing
- `lxml` - XML parsing  
- `soundfile` - Audio file reading
- `essentia-tensorflow` - Audio analysis and embeddings (Discogs-EffNet model)
- `faiss-cpu` - Fast similarity search with HNSW indexing
- `typer` - CLI interface
- `tkinter` - GUI (included with Python)

## Data Files

The indexing process creates these files in the `data/` directory:

- `meta.parquet` - Track metadata from Rekordbox XML
- `embeddings.parquet` - Audio embeddings with track IDs  
- `index.npy` - Normalized embedding vectors for FAISS
- `ids.json` - Track ID mapping for FAISS index
- `settings.json` - User preferences and configuration

## Building Standalone Application

To create a distributable app that end users can install:

```bash
# Install build dependencies
pip install pyinstaller

# Build the application
python build_app.py
```

The application will be created in the `dist/` directory. See [PACKAGING.md](PACKAGING.md) for detailed instructions on creating installers for each platform.

## First-Run Experience

When users launch the app for the first time:

1. **Welcome Screen**: Explains what Cosine Companion does
2. **XML File Selection**: User chooses their Rekordbox XML export
3. **Indexing Progress**: Shows real-time progress as library is indexed
4. **Completion**: Automatically launches the main application

Subsequent launches skip directly to the main interface.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
