# Cosine Companion

A DJ music recommendation tool that helps you find similar tracks and create seamless DJ sets. Uses deep learning audio analysis to find tracks that sound alike, combined with harmonic (key) and tempo (BPM) compatibility scoring.

## What It Does

Cosine Companion analyzes your music library and helps you:

- **Find Similar Tracks** - Select any track and instantly get recommendations based on how it actually sounds, not just metadata
- **Mix Harmonically** - Recommendations are scored for key compatibility using the Camelot wheel system
- **Match Tempos** - BPM matching with support for half-time and double-time detection
- **Build DJ Sets** - Create complete sets with anchor tracks at specific positions, auto-filled with compatible tracks
- **Export Playlists** - Generate M3U playlists that import directly into Rekordbox

## Installation

### Option 1: Standalone Application (Recommended)

Download the pre-built application for your platform from the [Releases](https://github.com/yourusername/dj-cosine/releases) page:

| Platform | Download |
|----------|----------|
| macOS (Apple Silicon) | `Cosine-Companion-macOS-arm64.dmg` |

Simply install and run - no Python required. Please note only the Apple Silicon build is tested and working. Intel Mac and Windows need to be sorted, I just don't have the time so contributions are more than welcome!

### Option 2: Run from Source

#### Prerequisites
- Python 3.10 or higher
- Rekordbox (for exporting your library as XML)

#### Install Dependencies

**Using pip:**
```bash
git clone https://github.com/yourusername/dj-cosine.git
cd dj-cosine
pip install -r requirements.txt
```

**Using conda (recommended for Apple Silicon):**
```bash
git clone https://github.com/yourusername/dj-cosine.git
cd dj-cosine
conda env create -f environment.yml
conda activate dj-companion
```

#### Download the ML Model

The application requires the Discogs-EffNet model (~300 MB):

```bash
cd models/
curl -O https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
cd ..
```

## Quick Start

Please note the rekordbox collection MUST be local, **NOT** on a USB device.

### 1. Export Your Library from Rekordbox

In Rekordbox: `File` → `Export Collection in xml format`

### 2. Index Your Library

```bash
python src/cosine_companion.py index /path/to/rekordbox.xml
```

This analyzes your audio files and builds a searchable index. Re-run when you add more tracks to your rekordbox collection and want to index them.

### 3. Launch the Application

```bash
python src/cosine_companion.py ui
```

### 4. Start Exploring

1. Click **"Set Current Track"** and search for a track
2. View recommendations sorted by similarity score
3. Double-click any recommendation to explore from that track
4. Use the **Set Creator** tab to build complete DJ sets

## Features

| Feature | Description |
|---------|-------------|
| **Audio Similarity** | Deep learning embeddings capture how tracks actually sound |
| **Key Compatibility** | Camelot wheel scoring for harmonic mixing |
| **BPM Matching** | Tempo compatibility with half/double time detection |
| **DJ Set Generator** | Place anchor tracks, auto-fill the rest |
| **Playlist Export** | M3U export for Rekordbox and other DJ software |
| **Library Management** | Browse, search, and manage indexed tracks |
| **Incremental Updates** | Only process new tracks when re-indexing |

## CLI Commands

```bash
# Index your library (first time or to add new tracks)
python src/cosine_companion.py index /path/to/rekordbox.xml

# Force full re-index (rebuilds everything)
python src/cosine_companion.py index /path/to/rekordbox.xml --force

# Launch the graphical interface
python src/cosine_companion.py ui

# Check for duplicate tracks
python src/cosine_companion.py clean-duplicates /path/to/rekordbox.xml
```

## How It Works

1. **Audio Analysis**: Each track is processed through a neural network (Discogs-EffNet) trained on millions of songs, producing a 256-dimensional "fingerprint" of how the track sounds

2. **Similarity Search**: When you select a track, FAISS (Facebook AI Similarity Search) quickly finds the most similar fingerprints in your library

3. **Compatibility Scoring**: Results are ranked using a weighted formula:
   - 70% audio similarity (cosine distance)
   - 20% key compatibility (Camelot wheel)
   - 10% BPM compatibility

You may choose to ignore the weighted score and just rely on the cosine similarity to sort the tracks. This is done via the UI by clicking on the sort buttons.

## Documentation

Detailed technical documentation is available in the [`docs/`](docs/) folder:

| Document | Description |
|----------|-------------|
| [System Architecture](docs/SYSTEM_ARCHITECTURE.md) | Complete system design and component overview |
| [Embeddings Guide](docs/EMBEDDINGS_GUIDE.md) | How audio analysis and similarity search works |
| [Program Flow](docs/PROGRAM_FLOW.md) | Detailed execution flow and data pipelines |
| [Build Instructions](docs/BUILD_INSTRUCTIONS.md) | Building standalone applications |

## Project Structure

```
dj-cosine/
├── src/                    # Source code
│   ├── config/             # Configuration and constants
│   ├── core/               # Data loading, persistence, indexing
│   ├── processing/         # Audio analysis and XML parsing
│   ├── recommendations/    # Recommendation engine and scoring
│   └── ui/                 # Tkinter GUI
├── models/                 # ML models (download required)
├── data/                   # Generated index files (gitignored)
├── docs/                   # Documentation
└── assets/                 # Application icons
```

## Requirements

- Python 3.10+
- ~300 MB disk space for ML model
- ~50 MB per 1,000 indexed tracks

### Dependencies

- `essentia-tensorflow` - Audio analysis
- `faiss-cpu` - Similarity search
- `numpy`, `pandas` - Data processing
- `lxml` - XML parsing
- `typer` - CLI
- `tkinter` - GUI (included with Python)

## Contributing

Contributions are welcome! Here's how to help:

1. **Report Bugs** - Open an issue describing the problem
2. **Suggest Features** - Open an issue with your idea
3. **Submit PRs** - Fork the repo, make changes, submit a pull request

### Development Setup

```bash
git clone https://github.com/yourusername/dj-cosine.git
cd dj-cosine
conda env create -f environment.yml
conda activate dj-companion
# Download the model (see Installation)
python src/cosine_companion.py ui
```

### Code Style

- Follow existing code patterns
- Keep functions focused and documented
- Test changes with your own library before submitting

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Essentia](https://essentia.upf.edu/) for audio analysis and the Discogs-EffNet model
- [FAISS](https://github.com/facebookresearch/faiss) for efficient similarity search
- [r/ProperTechno](https://www.reddit.com/r/ProperTechno/) for remaining true to Techno.

---

**Note**: This tool analyzes your local music files. No audio data is uploaded or shared.
