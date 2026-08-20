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

Download the pre-built application from the [Releases](https://github.com/zeinramadan/cosine-companion/releases) page:

| Platform | Download | Status |
|----------|----------|--------|
| macOS (Apple Silicon) | `Cosine-Companion-macOS.dmg` | Working |
| macOS (Intel) | `Cosine-Companion-macOS-x86_64.dmg` | Builds, binary does not run |
| Windows | `Cosine-Companion-Windows.zip` | Blocked upstream — see below |

Install and run; no Python required. **Apple Silicon macOS is the only supported target.**

> **Windows is blocked on an upstream dependency, not on effort.** `essentia-tensorflow`
> has never published a Windows wheel — every release on PyPI is macOS or manylinux
> only, with no source distribution. `pip install -r requirements.txt` therefore cannot
> succeed on a Windows runner, so `build-windows.yml` fails before packaging begins.
> Porting to Windows means solving the Essentia dependency first.

> **Intel macOS** builds but the binary does not launch. The likeliest cause is that
> current Essentia wheels are tagged `macosx_15_0` while the bundle declares
> `LSMinimumSystemVersion 10.13` — a deployment-target mismatch rather than a
> code-signing problem. Worth checking before chasing signing.

### Option 2: Run from Source

#### Prerequisites
- Python 3.10 or higher
- Rekordbox (for exporting your library as XML)

#### Install Dependencies

**Using pip:**
```bash
git clone https://github.com/zeinramadan/cosine-companion.git
cd cosine-companion
pip install -r requirements.txt
```

**Using conda (recommended for Apple Silicon):**
```bash
git clone https://github.com/zeinramadan/cosine-companion.git
cd cosine-companion
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

Or try the **experimental** web UI, which runs the same services in a
pywebview window:

```bash
python src/cosine_companion.py ui-web
```

Tkinter remains the default and is what `ui` and the packaged `.app` launch.
`ui-web` currently implements Explore, Library browsing/deletion, and the small
Settings path editor; Set Creator and Export render a placeholder. See
[the web UI](#the-experimental-web-ui).

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

# Launch the graphical interface (Tkinter - the default)
python src/cosine_companion.py ui

# Launch the experimental web UI (pywebview; Explore + Library + Settings)
python src/cosine_companion.py ui-web

# ...with devtools, and against a specific index directory
python src/cosine_companion.py ui-web --debug --data-dir /path/to/data

# Check for duplicate tracks
python src/cosine_companion.py clean-duplicates /path/to/rekordbox.xml
```

## The experimental web UI

`ui-web` opens a [pywebview](https://pywebview.flowrl.com/) window (WKWebView on
macOS - the same engine as Safari) onto a small JSON API served over loopback.
It exists because the Tkinter UI is hard to make look like a 2026 application;
the engine underneath is identical.

**Status.** Experimental. Explore works end to end - pick a seed with ⌘K, see
ranked recommendations with Camelot keys and match scores, re-seed by clicking
one, go back through history. Library browses, filters, seeds and atomically
deletes tracks. Settings reads and writes the Rekordbox XML path; Set Creator
and Export render a "coming in the next PR" placeholder.
Tkinter is unchanged, is still the default, and is what the packaged `.app`
launches.

**How it is wired.**

- A `ThreadingHTTPServer` binds `127.0.0.1` on an ephemeral port in a daemon
  thread; pywebview owns the main thread, as macOS requires.
- Every `/api/` request needs a per-process token, `/api/health` included. The
  token reaches the page in its own URL and moves to a header from there.
- Authenticated API requests may use bounded JSON `POST` bodies. Static files
  remain `GET`/`HEAD` only.
- The frontend is hand-written HTML, CSS and ES modules. **There is no build
  step and no Node toolchain** - what is in `src/web/static/` is what the
  browser loads.
- No business logic lives in `src/web/`. It translates JSON to service calls
  and back.

**Extra dependency.** `pywebview` - the only one the web UI adds. It is in
`requirements.txt`. Nothing else needs it: `src/web/server.py` and
`src/web/api.py` deliberately do not import it, which is what lets the API be
tested on a headless CI runner. Only `src/web/host.py` does.

## How It Works

1. **Audio Analysis**: Each track is processed through a neural network (Discogs-EffNet) trained on millions of songs, producing a 2,560-dimensional "fingerprint" (1,280 mean + 1,280 standard-deviation features) of how the track sounds

2. **Similarity Search**: When you select a track, NumPy computes exact cosine similarity against every fingerprint in your library

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
cosine-companion/
├── src/                    # Source code
│   ├── config/             # Configuration and constants
│   ├── core/               # Data loading, persistence, exact cosine index
│   ├── processing/         # Audio analysis and XML parsing
│   ├── recommendations/    # Recommendation engine and scoring
│   ├── services/           # Headless session/service layer (no UI imports)
│   ├── ui/                 # Tkinter GUI (the default)
│   └── web/                # Experimental web UI: loopback API + no-build frontend
├── tests/                  # pytest suite (run in CI on every PR)
├── benchmarks/             # Recommendation benchmark harness and results
├── models/                 # ML models (download required)
├── data/                   # Your library index (gitignored — never committed)
├── docs/                   # Documentation
└── assets/                 # Application icons
```

> Note: `data/` is gitignored because it contains your personal library. Tests that
> depend on it are written to **skip** when it is absent, so they do not run in CI —
> any test that must gate a merge has to use a committed fixture under
> `tests/fixtures/` instead.

## Requirements

- Python 3.10+
- ~300 MB disk space for ML model
- ~50 MB per 1,000 indexed tracks

### Dependencies

- `essentia-tensorflow` - Audio analysis
- `numpy`, `pandas` - Exact similarity search and data processing
- `lxml` - XML parsing
- `typer` - CLI
- `tkinter` - GUI (included with Python)
- `pywebview` - experimental web UI only; `ui` does not need it

## Contributing

Contributions are welcome! Here's how to help:

1. **Report Bugs** - Open an issue describing the problem
2. **Suggest Features** - Open an issue with your idea
3. **Submit PRs** - Fork the repo, make changes, submit a pull request

### Development Setup

```bash
git clone https://github.com/zeinramadan/cosine-companion.git
cd cosine-companion
conda env create -f environment.yml
conda activate dj-companion
# Download the model (see Installation)
python src/cosine_companion.py ui
```

### Running the Tests

```bash
pip install -e ".[test]"     # or: pip install "pytest>=7.0"
python -m pytest -q
```

`pytest.ini` sets `pythonpath = src`, so no `PYTHONPATH` export or editable install
of the package itself is needed.

The suite deliberately runs without the heavy audio stack. **Nothing under `src/services/`
or the test suite may import `essentia` at module scope** — it is a ~480 MB TensorFlow
dependency that CI does not install, and a module-level import there breaks the entire
suite at collection time. Import it lazily, inside the function that needs it.

Before opening a PR, verify in an environment that matches CI, not just your dev env.
CI installs only `numpy pandas pyarrow lxml pytest`, on the interpreter named in
`.python-version` (the single source of truth for it, currently **3.11**):

```bash
# Must match .python-version. On macOS, bare `python3` is often 3.9 and will fail
# at collection with: TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
conda run -n dj-companion python -m venv /tmp/ci-check
/tmp/ci-check/bin/pip install numpy pandas pyarrow lxml "pytest>=7.0"
/tmp/ci-check/bin/python -m pytest -q
```

A suite that passes in a full conda environment can still fail in CI, and a test that
silently *skips* there looks identical to one that passes.

> **Python 3.10 is a hard floor**, not a recommendation. The codebase uses PEP 604
> union syntax (`X | None`), which is a syntax error on 3.9. Note that `setup.py`
> currently declares `python_requires=">=3.8"`, which is inaccurate.

### Code Style

- Follow existing code patterns
- Keep functions focused and documented
- Add or update tests with your change; test with your own library too

### GitHub Actions

Four workflows. One runs automatically; three are manual builds.

| Workflow | Trigger | Runner | Status |
|----------|---------|--------|--------|
| `test-macos.yml` | Automatic — every PR and push to `main` | `macos-latest` | **Required check** |
| `build-macos.yml` | Manual | `macos-latest` (Apple Silicon) | Working |
| `build-macos-intel.yml` | Manual | `macos-13` (Intel x86_64) | Builds, binary does not run |
| `build-windows.yml` | Manual | `windows-latest` | Cannot install deps (see Installation) |

To trigger a build, go to **Actions** > select workflow > **Run workflow**. Build
artifacts (DMG/ZIP) are retained for 90 days.

### Branch Protection

`main` is protected. A pull request needs:

- 1 approving review (stale reviews are dismissed on new pushes)
- the `pytest` check passing
- all review conversations resolved
- linear history — no merge commits, no force pushes

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Essentia](https://essentia.upf.edu/) for audio analysis and the Discogs-EffNet model
- [r/ProperTechno](https://www.reddit.com/r/ProperTechno/) for remaining true to Techno.

---

**Note**: This tool analyzes your local music files. No audio data is uploaded or shared.
