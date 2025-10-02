# Cosine Companion v1.0.0 🎵

**AI-Powered Music Companion for DJs**

Cosine Companion helps you discover tracks that mix well together using advanced machine learning. Find similar songs, create seamless DJ sets, and explore your music library in new ways.

---

## ✨ What's Included

### 🎯 Core Features

- **AI-Powered Recommendations** - Find similar tracks based on audio features, not just metadata
- **Smart Set Creator** - Automatically generate DJ sets with smooth transitions
- **Library Management** - Browse and search your entire Rekordbox collection
- **BPM & Key Matching** - Filter recommendations by BPM range and key compatibility
- **Energy Flow Control** - Create sets with natural energy progression
- **Deleted Track Management** - Keep track of tracks you've removed from rotation

### 🧠 How It Works

Cosine Companion uses **Essentia's Discogs-EffNet embeddings** - deep learning models trained on millions of tracks. Combined with **FAISS** for lightning-fast similarity search, it understands what makes tracks sound similar, not just their tags.

### 🎨 User Experience

- Beautiful, native macOS interface
- Fast search and filtering
- Real-time recommendations
- Configurable settings for personalized results
- One-click set generation

---

## 📥 Installation

### System Requirements

- **macOS**: 10.15 (Catalina) or later
- **Disk Space**: ~800 MB for the app + ~1 KB per track indexed
- **Rekordbox**: XML export file from your library

### Install Steps

1. **Download** `Cosine-Companion-Installer.dmg`
2. **Open** the DMG file
3. **Drag** Cosine Companion to your Applications folder
4. **Launch** from Applications
   - If you see a security warning, right-click → Open
5. **Follow** the onboarding wizard
   - Select your Rekordbox XML file
   - Wait for initial indexing (a few minutes for most libraries)
6. **Start discovering** new track combinations!

---

## 🚀 Getting Started

### First Launch

On first launch, you'll be guided through:

1. **Select Your Library** - Point to your Rekordbox XML export
   - In Rekordbox: File → Export Collection in xml format
2. **Indexing** - Let Cosine Companion analyze your tracks
   - This happens once, subsequent launches are instant
3. **Explore** - Start finding similar tracks!

### Quick Tips

- **Explore Tab**: Select a track, see similar recommendations instantly
- **Set Creator Tab**: Choose a starting track and desired length, get a complete set
- **Library Tab**: Browse all your tracks, delete unwanted ones
- **Settings**: Adjust BPM tolerance, energy thresholds, and update your library

---

## 🎛️ Key Features Explained

### Recommendations Engine

- **Cosine Similarity**: Finds tracks with similar audio characteristics
- **Configurable Filters**: Set BPM range (±% tolerance)
- **Energy Matching**: Control how similar the energy level should be
- **Key Compatibility**: Optional filtering for harmonic mixing

### Set Creator

- **Automatic Generation**: Creates complete DJ sets from a starting track
- **Smart Transitions**: Considers BPM, energy flow, and track variety
- **Configurable Length**: Choose how long your set should be
- **Export Options**: Copy tracklist or save to file

### Library Management

- **Full Search**: Find tracks by artist, title, or any metadata
- **Smart Filtering**: Filter by BPM, key, year, genre
- **Deleted Tracks**: Manage a list of tracks you don't want to see
- **Incremental Updates**: Re-index only new tracks when your library grows

---

## ⚙️ Settings

Customize Cosine Companion to match your style:

- **BPM Tolerance**: How much variation in tempo is acceptable (default: ±6%)
- **Energy Threshold**: How similar the energy should be (default: 0.2)
- **Set Length**: Preferred duration for generated sets
- **Library Path**: Update when you move your music
- **Deleted Tracks**: Review and restore accidentally deleted tracks

---

## 📊 Performance

- **Indexing Speed**: ~10-30 tracks per second (varies by system)
- **Search Speed**: Milliseconds for libraries of 10,000+ tracks
- **Memory Usage**: ~200-400 MB depending on library size
- **Disk Usage**: Minimal (embeddings are compact)

---

## 🔒 Privacy

- **100% Local**: All processing happens on your computer
- **No Internet Required**: Works completely offline after initial install
- **No Tracking**: We don't collect any data about you or your music
- **Your Music Stays Yours**: No uploads, no cloud storage

---

## 🐛 Known Issues & Limitations

- **Rekordbox Only**: Currently supports Rekordbox XML exports only
  - Serato, Traktor support planned for future versions
- **macOS Only**: Windows and Linux versions coming soon
- **First Launch**: Indexing large libraries (5,000+ tracks) can take 10-15 minutes
  - Subsequent launches are instant
- **Security Warning**: App is not yet notarized by Apple
  - Right-click → Open to bypass the warning
  - Code signing coming in future releases

---

## 💡 Tips & Tricks

1. **Re-index Regularly**: Update your library when you add new tracks (Settings → Update Library)
2. **Experiment with Settings**: Try different BPM tolerances for your style
3. **Use Energy Flow**: Enable energy matching for smoother set progressions
4. **Deleted Tracks**: Use this to hide bootlegs, low-quality tracks, or songs you're tired of
5. **Backup Your Data**: Your library data is in `~/Library/Application Support/Cosine Companion`

---

## 🤝 Feedback & Support

Found a bug? Have a feature request? Want to share your experience?

- **Issues**: [GitHub Issues](https://github.com/zeinramadan/cosine-companion/issues)
- **Discussions**: [GitHub Discussions](https://github.com/zeinramadan/cosine-companion/discussions)
- **Email**: [your-email@example.com] (if you want to include this)

---

## 🙏 Credits

Built with:
- **[Essentia](https://essentia.upf.edu/)** - Audio analysis and ML models
- **[FAISS](https://github.com/facebookresearch/faiss)** - Efficient similarity search
- **Python** - Core language
- **Tkinter** - Native UI

Special thanks to the open-source community for making this possible.

---

## 📜 License

Copyright © 2024. All rights reserved.

---

## 🚀 What's Next?

Planned for future releases:

- **v1.1**: Serato and Traktor support
- **v1.2**: Windows and Linux versions
- **v1.3**: Playlist export to Rekordbox
- **v2.0**: Live mode - real-time suggestions while DJing

---

**Enjoy discovering new connections in your music! 🎧**

*Star this project on GitHub if you find it useful!*

