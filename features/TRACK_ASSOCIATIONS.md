# Track Associations Feature

## Overview

A manual track association system that allows DJs to create and manage custom relationships between tracks that work well together in mixes. This complements the automated cosine similarity recommendations with user-defined mixing knowledge.

## User Story

As a DJ, I want to manually associate tracks that I know work well together so that:
- I don't forget good track combinations I've discovered
- I can build a personal knowledge base of mixing relationships
- I have quick access to proven track pairings alongside AI suggestions
- My manual associations persist even if I lose playlists or change software

## UI Design

### Tab System
When a track is selected, the suggestions area will show two tabs:
1. **AI Suggestions** (existing functionality) - Shows cosine similarity recommendations
2. **My Associations** (new) - Shows user-defined track relationships

### My Associations Tab Layout
```
┌─────────────────────────────────────────────────────────┐
│ [AI Suggestions] [My Associations*]                     │
├─────────────────────────────────────────────────────────┤
│ Associated Tracks (12):                    [+ Add New]  │
├─────────────────────────────────────────────────────────┤
│ ☐ Artist Name - Track Title               [Remove]     │
│ ☐ Another Artist - Another Track          [Remove]     │
│ ☐ Third Artist - Third Track              [Remove]     │
│ ...                                                     │
├─────────────────────────────────────────────────────────┤
│ [Set as Current] [Copy Selected] [Play in App]         │
└─────────────────────────────────────────────────────────┘
```

### Add Association Dialog
```
┌─────────────────────────────────────────────────────────┐
│ Add Track Association                            [X]    │
├─────────────────────────────────────────────────────────┤
│ Current Track: Artist - Title                          │
│                                                         │
│ Search for track to associate:                         │
│ [___________________________] [Search]                │
│                                                         │
│ Search Results:                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ ○ Artist A - Track A                               │ │
│ │ ○ Artist B - Track B                               │ │
│ │ ○ Artist C - Track C                               │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Notes (optional):                                       │
│ [_________________________________________________]     │
│                                                         │
│           [Cancel]              [Add Association]       │
└─────────────────────────────────────────────────────────┘
```

## Data Structure

### Association Storage
Store associations in a JSON file: `data/track_associations.json`

```json
{
  "associations": {
    "track_id_1": [
      {
        "associated_track_id": "track_id_2",
        "notes": "Great energy transition",
        "created_date": "2025-09-29T10:30:00Z",
        "last_used": "2025-09-29T15:45:00Z",
        "use_count": 3
      },
      {
        "associated_track_id": "track_id_3",
        "notes": "Perfect key match",
        "created_date": "2025-09-28T14:20:00Z",
        "last_used": "2025-09-29T12:15:00Z",
        "use_count": 1
      }
    ]
  },
  "metadata": {
    "version": "1.0",
    "total_associations": 245,
    "last_updated": "2025-09-29T15:45:00Z"
  }
}
```

### Track ID System
Use a consistent track identifier across the system:
- Format: `{artist}___{title}` (sanitized, lowercase, spaces to underscores)
- Example: `"deadmau5___strobe_original_mix"` 
- Fallback to file path hash if metadata is missing

## Implementation Plan

### Phase 1: Data Layer
1. **Create `associations.py` module**
   - `AssociationManager` class
   - Methods: `load_associations()`, `save_associations()`, `add_association()`, `remove_association()`, `get_associations_for_track()`
   - Track ID generation and normalization

2. **Update `config.py`**
   - Add `ASSOCIATIONS_JSON = DATA / "track_associations.json"`

### Phase 2: Core Functionality
3. **Extend track search in `recommendations.py`**
   - Add `search_tracks(query)` function for association dialog
   - Fuzzy matching on artist/title

4. **Create association dialogs in `ui.py`**
   - `AddAssociationDialog` class
   - Track search functionality
   - Association creation interface

### Phase 3: UI Integration
5. **Update main UI (`ui.py`)**
   - Convert suggestions area to tabbed interface using `ttk.Notebook`
   - Create `MyAssociationsTab` class
   - Update track selection to show both tabs

6. **Association management features**
   - Add/remove associations
   - Edit association notes
   - Sort by date, usage, notes
   - Bulk operations (export, import)

### Phase 4: Advanced Features
7. **Usage analytics**
   - Track when associations are viewed/used
   - Show most/least used associations
   - Suggest reciprocal associations

8. **Import/Export**
   - Export associations to CSV/JSON
   - Import from other DJ software playlists
   - Backup/restore functionality

## File Structure Changes

```
dj-cosine/
├── associations.py          # New: Association management
├── ui.py                   # Modified: Add tabbed interface
├── config.py               # Modified: Add associations path
├── recommendations.py      # Modified: Add track search
└── data/
    └── track_associations.json  # New: Association storage
```

## Technical Considerations

### Performance
- Load associations once at startup, cache in memory
- Use sets for fast lookup of associated track IDs
- Lazy load association details only when needed

### Data Integrity
- Validate track IDs exist in current library
- Handle missing/moved tracks gracefully
- Provide cleanup tools for orphaned associations

### Bidirectional Associations
- When A→B association is created, optionally create B→A
- UI setting to control automatic bidirectional creation
- Visual indication of bidirectional vs unidirectional

### Backup & Sync
- Associations file should be easily backed up
- Consider cloud sync integration (Dropbox, Google Drive)
- Version control for association changes

## User Workflows

### Creating Associations
1. Select current track
2. Switch to "My Associations" tab
3. Click "Add New" button
4. Search for track to associate
5. Select track from results
6. Add optional notes
7. Save association

### Using Associations
1. Select track in library
2. View "My Associations" tab
3. See all manually associated tracks
4. Double-click to set as current track
5. Use same controls as AI suggestions

### Managing Associations
1. Right-click on association for context menu
2. Edit notes, remove association
3. View usage statistics
4. Export/import associations

## Testing Scenarios

### Core Functionality
- Create association between two tracks
- View associations for a track
- Remove associations
- Search for tracks in add dialog

### Edge Cases
- Associate track with itself (should prevent)
- Associate same tracks multiple times (should prevent duplicates)
- Handle tracks that no longer exist in library
- Large numbers of associations (performance)

### Data Persistence
- Associations survive app restart
- Associations survive library reindex
- Handle corrupted association file

## Future Enhancements

### Smart Suggestions
- Suggest associations based on usage patterns
- ML to predict good associations from user behavior
- Integration with streaming service playlists

### Social Features
- Share associations with other DJs
- Community association database
- Rating system for associations

### Advanced Analytics
- Mixing success rate tracking
- Association effectiveness metrics
- Recommendations based on association patterns

## Migration Strategy

### Existing Users
- Feature is opt-in, doesn't affect existing functionality
- Associations start empty, user builds over time
- Import wizard for existing playlists

### Data Migration
- If changing association format, provide migration scripts
- Backup old format before migration
- Rollback capability if migration fails

## Implementation Priority

1. **High Priority**: Core association CRUD operations
2. **Medium Priority**: Search and UI integration
3. **Low Priority**: Analytics and advanced features

This feature will significantly enhance the DJ workflow by combining AI-powered suggestions with personal mixing knowledge, creating a comprehensive track relationship system.
