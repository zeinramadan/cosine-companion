# Playlist Export Feature

## Overview

The Playlist Export feature allows you to generate recommendation playlists in the standard `.m3u` format that can be imported directly into Rekordbox. This is the easiest way to use Cosine Companion's recommendations in your DJ software.

## What are .m3u Playlists?

`.m3u` is a universal playlist format supported by most DJ software and music players. It's a simple text file that contains file paths to your music files.

Rekordbox fully supports importing `.m3u` playlists, which makes it the perfect format for exporting your recommendations.

## How It Works

1. **Select Tracks**: Choose which tracks you want to generate recommendations for:
   - All tracks in your collection
   - Selected tracks via the "+ Add Tracks" search dialog

2. **Configure**: Set how many recommendations you want per track (10-50)

3. **Generate**: The app creates `.m3u` playlist files containing recommendations

4. **Import**: Import the playlists into Rekordbox (File → Import → Playlist)

5. **Use**: Access your recommendations directly in Rekordbox playlists!

## Using the Playlist Export Tab

### Step 1: Select Tracks

Navigate to the **Playlist Export** tab in Cosine Companion.

Choose one of two options:

**Option A: All tracks in collection**
- Generates a playlist for every track in your library
- Best for comprehensive recommendation sets
- Takes longer for large collections

**Option B: Selected tracks**
- Click **+ Add Tracks** to open the search dialog
- Search by artist or title
- Select tracks using:
  - Click to select one track
  - Ctrl+Click (Cmd+Click on Mac) to select multiple tracks
  - Shift+Click to select a range of tracks
- Click **Add Selected Tracks**
- Only selected tracks will have playlists generated

### Step 2: Configure Playlists

**Recommendations per track:**
- Choose between 10-50 recommendations
- Default: 25 tracks
- More recommendations = longer playlists but more options
- Fewer recommendations = focused, curated playlists

**Export format:**
- **Separate playlist per track**: Creates one `.m3u` file per track
  - Example: `Daft Punk - One More Time.m3u` contains 25 recommendations for that track
  - Best when you want to browse recommendations by source track
  
- **Single combined playlist**: Creates one large `.m3u` file with all recommendations
  - Example: `Cosine_Recommendations.m3u` contains all unique recommendations
  - Best for creating one big playlist to browse through

### Step 3: Choose Output Location

- Default location: `~/Desktop/Cosine_Playlists/`
- Click **Browse...** to choose a different location
- The folder will be created if it doesn't exist

### Step 4: Generate Playlists

Click **🎵 Generate Playlists**

The app will:
1. Show a confirmation dialog with details
2. Generate recommendations for each selected track
3. Create `.m3u` files with proper file paths
4. Show progress as it processes tracks
5. Display a completion summary

## Importing into Rekordbox

### Method 1: Import Individual Playlists

1. Open Rekordbox
2. Click **File** → **Import** → **Playlist**
3. Navigate to your output folder
4. Select one or more `.m3u` files
5. Click **Open**
6. Playlists will appear in your Rekordbox sidebar

### Method 2: Import Entire Folder (Mac)

1. Open Rekordbox
2. Drag the entire output folder into Rekordbox's playlist sidebar
3. All playlists will be imported at once

### Method 3: Import via Finder/Explorer

1. Navigate to the output folder in Finder (Mac) or Explorer (Windows)
2. Drag `.m3u` files directly into Rekordbox

## Use Cases

### 1. Pre-Set Preparation

**Scenario**: You have a 2-hour set coming up and want recommendation playlists for your potential opening tracks.

**Workflow**:
1. Go to Playlist Export tab
2. Click **+ Add Tracks** and select 10-15 tracks you might open with
3. Set recommendations to 30
6. Choose "Separate playlist per track"
7. Generate and import into Rekordbox
8. Before your set, browse through playlists to find transitions

### 2. Genre Exploration

**Scenario**: You want to discover new tracks similar to your entire techno collection.

**Workflow**:
1. Go to Playlist Export tab
2. Select "All tracks in collection"
3. Set recommendations to 20
4. Choose "Single combined playlist"
5. Generate and import into Rekordbox
6. You now have a massive playlist of related tracks to explore

### 3. Quick Recommendations

**Scenario**: You're building a set and want recommendations for one specific track.

**Workflow**:
1. Go to Playlist Export tab
2. Click **+ Add Tracks** and select a single track
3. Set recommendations to 25
4. Generate
5. Import the single playlist into Rekordbox

### 4. USB Preparation for CDJ

**Scenario**: You want to export recommendations to your DJ USB stick.

**Workflow**:
1. Generate playlists using Playlist Export
2. Import playlists into Rekordbox
3. Review and curate the recommendations
4. Export playlists to USB via Rekordbox
5. Use on CDJs with full recommendation access

## Tips & Best Practices

### Recommendation Count Guidelines

| Collection Size | Recommended Per Track | Reasoning |
|----------------|----------------------|-----------|
| < 500 tracks   | 30-50               | Your collection is focused, more recs give variety |
| 500-1500 tracks | 20-30              | Good balance of variety and curation |
| 1500+ tracks   | 10-20               | Many options available, keep playlists focused |

### File Organization

**Separate Playlists**:
```
Cosine_Playlists/
├── Aphex Twin - Windowlicker.m3u
├── Daft Punk - One More Time.m3u
├── The Chemical Brothers - Block Rockin' Beats.m3u
└── ...
```

**Combined Playlist**:
```
Cosine_Playlists/
└── Cosine_Recommendations.m3u
```

### Naming Conventions

The app automatically creates safe filenames:
- Special characters are removed
- File names are limited to 200 characters
- Format: `Artist - Title.m3u`

### Rekordbox Integration

After importing:
1. **Create Smart Playlists**: Filter by BPM, key, or genre
2. **Add Ratings**: Rate recommended tracks as you discover them
3. **Create Sub-Folders**: Organize by mood or energy level
4. **Update Regularly**: Re-export when you add new tracks

### Storage Considerations

- `.m3u` files are tiny (typically < 5KB each)
- They only contain file paths, not audio data
- 1000 playlists = ~5MB total
- No impact on disk space

## Performance

### Generation Time

| Track Count | Recommendations | Time (est.) |
|------------|----------------|-------------|
| 10 tracks  | 25 each        | ~5 seconds  |
| 50 tracks  | 25 each        | ~20 seconds |
| 100 tracks | 25 each        | ~40 seconds |
| 500 tracks | 25 each        | ~3 minutes  |
| 1000 tracks | 25 each       | ~6 minutes  |

*Times vary based on CPU speed. Uses existing embeddings, no audio processing needed.*

### Rekordbox Import Time

- Small (< 50 playlists): Instant
- Medium (50-200 playlists): 10-30 seconds
- Large (200-1000 playlists): 1-3 minutes
- Very Large (1000+ playlists): 3-10 minutes

## Troubleshooting

### "No Tracks Selected"

**Problem**: Error when clicking Generate Playlists

**Solution**:
- If "Selected tracks" is chosen, click **+ Add Tracks** and select at least one track
- Try switching to "All tracks in collection"

### "Playlists are empty after import"

**Problem**: Playlists import but contain no tracks

**Possible causes**:
1. File paths in Rekordbox don't match the paths in the XML export
2. Files have been moved since the XML export
3. Different disk/volume names

**Solution**:
1. Re-export your collection from Rekordbox (File → Export Collection in xml format)
2. Re-index in Cosine Companion (Library → Full Re-index)
3. Generate playlists again

### "Some recommendations are missing"

**Problem**: Fewer tracks than expected in playlists

**Possible causes**:
- Some recommended tracks don't exist at their stored file paths
- Files were deleted or moved

**Solution**:
- Re-export and re-index
- Check that tracks exist in Rekordbox

### "Import fails in Rekordbox"

**Problem**: Rekordbox won't import the .m3u files

**Solution**:
1. Verify the .m3u files aren't empty (open in text editor)
2. Check file paths exist and are accessible
3. Try importing a single small playlist first
4. Update Rekordbox to latest version

### "Generation is very slow"

**Problem**: Taking much longer than expected

**Possible causes**:
- Very large collection
- Old/slow computer

**Solution**:
- Start with fewer tracks to test
- Use "Selected tracks" instead of "All tracks"
- Reduce recommendations per track
- Be patient - it's computing thousands of comparisons

## Technical Details

### M3U Format

Extended M3U format with metadata:

```
#EXTM3U
#EXTINF:-1,Daft Punk - Around the World
/Users/yourname/Music/Daft Punk/Homework/01 Around the World.mp3
#EXTINF:-1,Stardust - Music Sounds Better With You
/Users/yourname/Music/Stardust/Music Sounds Better With You.mp3
```

### File Paths

- Uses absolute file paths from Rekordbox XML export
- Paths are extracted from `<TRACK Location="file://...">` in XML
- Must be accessible at import time

### Recommendation Algorithm

1. Uses the existing embeddings and exact NumPy cosine index to find similar tracks
2. Scores candidates by cosine, key compatibility, and BPM compatibility
3. For export, recommendations are sorted by **cosine similarity** (pure audio similarity) and the top N are written to the playlist

## Comparison with Other Features

### Playlist Export vs. CDJ USB Export

| Feature | Playlist Export | CDJ USB Export |
|---------|----------------|----------------|
| Format | .m3u playlists | XML + USB format |
| Import to Rekordbox | ✓ Yes (File → Import) | ✓ Yes (Import XML) |
| Use on CDJs | After Rekordbox export | After Rekordbox export |
| Speed | Very fast | Slower (XML generation) |
| Flexibility | High (edit in Rekordbox) | High (edit in Rekordbox) |
| Recommended | ✓ **Yes** | For advanced users |

**Verdict**: Use Playlist Export for most use cases - it's simpler and faster!

### Playlist Export vs. Explore Tab

| Feature | Playlist Export | Explore Tab |
|---------|----------------|-------------|
| Usage | Generate playlists for later | Real-time exploration |
| Recommendations | Batch for many tracks | One track at a time |
| Integration | Rekordbox playlists | In-app browsing |
| Workflow | Pre-set preparation | Live discovery |

**Verdict**: Use both! Explore tab for discovery, Playlist Export for preparation.

## Future Enhancements

Potential improvements:

1. **Playlist Filtering**: Export only recommendations matching BPM/key ranges
2. **Smart Deduplication**: Avoid duplicate recommendations across playlists
3. **Energy Curve Matching**: Sort recommendations by energy level
4. **Custom Weights**: Adjust cosine/key/BPM importance per export
5. **Direct USB Writing**: Skip Rekordbox import, write directly to USB
6. **Playlist Templates**: Save export configurations as presets

## Related Features

- [Explore Tab](../README.md#explore-tab): Real-time track recommendations
- [Set Generator](LIVE_COMPANION_FEATURE.md): Generate full DJ sets with anchor tracks
- [Library Management](../README.md#library-management): Browse and manage your collection

## Feedback & Support

If you encounter issues:
1. Check this guide's troubleshooting section
2. Re-export and re-index your collection
3. Try with a small subset of tracks first
4. Open an issue on GitHub with:
   - Collection size
   - Export configuration used
   - Error message or unexpected behavior
   - Rekordbox version

---

**Happy mixing! 🎵🎧**

**Pro tip**: Combine this feature with Rekordbox's smart playlists to create dynamic, automatically updating recommendation sets!
