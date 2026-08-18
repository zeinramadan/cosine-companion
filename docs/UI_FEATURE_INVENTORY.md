# Cosine Companion — Tkinter UI Feature Inventory

**Status:** Acceptance contract for the UI rewrite (PR 3).
**Captured from:** `feat/services-layer` (fork of `main` @ `91afe15`), re-verified surface by
surface against `src/ui/*.py` after the service-layer extraction.
**Scope:** every tab, window, dialog, control, rendered string, per-track field and its
formatting, mouse/keyboard binding, default value, sort order, and conditional
enabled/disabled state across the 12 files of `src/ui/` (3,437 lines) plus `src/utils/icon.py`.

> **How to use this document.** Section 2 catalogues the surfaces in the order a user meets
> them. Section 3 collects the cross-cutting formatting and search rules that several surfaces
> share, so they are stated once and referenced. Section 4 lists behaviours that are defects but
> are nonetheless *current behaviour* and therefore part of the contract until explicitly
> retired. Section 5 is the numbered workflow list used for manual smoke testing.
>
> **The rewrite is complete when every behaviour catalogued here is reachable in the new UI.**
> Anything intentionally dropped must be listed in that PR's description.

---

## 1. Application shell

### 1.1 Launch paths

| Entry point | Behaviour |
|---|---|
| `python src/cosine_companion.py ui` | Calls `ui.run_ui()` |
| `python src/cosine_companion.py index <xml> [--force/-f] [--sample/-s N]` | Headless indexing, no UI |
| `python src/cosine_companion.py clean-duplicates <xml>` | Headless duplicate report, no UI |
| Frozen `.app` double-click | `cosine_companion.py` detects `sys.frozen` with no args (or a single `-psn_*` arg from LaunchServices), prints `Launching Cosine Companion UI...`, runs `run_ui()`, then `sys.exit(0)` |

`run_ui()` (`src/ui/__init__.py`):

1. Creates a hidden `tk.Tk(className='Cosine Companion')` root, sets the window icon, `withdraw()`s it.
2. If `needs_onboarding()` → shows `OnboardingWindow` over the hidden root and enters `root.mainloop()`.
   On completion the root is `quit()`+`destroy()`ed and a fresh `App()` is constructed and run.
3. Otherwise the hidden root is destroyed immediately and `App()` runs directly.

### 1.2 `needs_onboarding()` decision table

Evaluated in this order (`src/ui/onboarding.py:597-613`):

| Condition | Result |
|---|---|
| `meta.parquet`, `ids.json`, `index.npy`, `embeddings.parquet` **all** exist | `False` — onboarding skipped, even if `settings.json` is absent |
| Otherwise, `settings.json` exists | `not settings.get("first_run_complete", False)` |
| Otherwise | `True` |

Note: the `settings.json` read here is unguarded — a corrupt file raises `json.JSONDecodeError`
at startup before any window is shown.

### 1.3 Window icon

`utils.icon.set_window_icon(window)` is applied to the root, the main `App`, `SettingsWindow`,
`ReindexWindow`, `OnboardingWindow` and `DeletedTracksDialog`. It looks for
`assets/coco_logo_small.png` (dev) or `<_MEIPASS>/assets/coco_logo_small.png` (frozen). On
darwin/linux it uses `iconphoto(True, photo)`; on win32 it looks for `coco_logo_small.ico` via
`iconbitmap`. All failures are swallowed; a load failure prints
`Warning: Could not load app icon: {e}` to stdout. `SimplePicker`, `AddAnchorDialog` and
`TrackSelectorDialog` do **not** set an icon.

### 1.4 Startup data load

`App.__init__` calls `_load_app_data(self)` → `LibrarySession.load()` → `core.loader.load_all()`,
which returns `(meta, meta_ix, emb_ix, idx, V, ids)` into the session. Measured at **0.79 s** for
the 1,307-track library, with no splash screen — the window simply does not appear until the load
finishes.

If `load_all()` raises `ValueError` (the index-consistency validations in
`core/loader.py:38-82`), an error dialog is shown and the process exits:

- Title: `Inconsistent Index Data`
- Body: `Cosine Companion could not load its saved index because the data files are inconsistent. Re-run indexing with --force, for example:\n\npython src/cosine_companion.py index <rekordbox.xml> --force\n\nDetails: {error}`
- `parent=` the window being constructed; then `parent.destroy()` and `SystemExit(1)`.

Only `ValueError` is handled. A missing `meta.parquet` (`FileNotFoundError`) propagates as an
unhandled traceback.

---

## 2. Surfaces

### 2.1 Onboarding window — `OnboardingWindow` (`onboarding.py`)

Shown only on first run (§1.2). `tk.Toplevel`, title **"Welcome to Cosine Companion"**,
600×400, **not resizable**, `transient(parent)` + `grab_set()` (modal), centred on screen,
then `deiconify()` / `lift()` / `focus_force()` / `update()`.

It is a four-screen wizard implemented by destroying all child widgets and rebuilding.

#### Screen 1 — Welcome

- Header: `🎵 Welcome to Cosine Companion` (Helvetica 20 bold, pady 20)
- Body (Helvetica 11, left-justified, wraplength 500):
  ```
  Cosine Companion helps you discover tracks that mix well together.

  To get started, we need to index your music library.

  This requires:
  • Your Rekordbox XML export file
  • A few minutes to process your tracks
  • About 1KB per track of disk space

  You only need to do this once. After that, you can add new tracks incrementally.
  ```
- **Get Started** — a fake button (see §3.5), green `#4CAF50`, Helvetica 12 bold, white text.
  Click → 100 ms later opens the XML file dialog.
- **Exit** — fake button, grey `#757575`, Helvetica 12. Click → 100 ms later `quit_app()`.
- Footer (Helvetica 9, grey):
  `Need help? Export your library from Rekordbox:\nFile → Export Collection in xml format`

`quit_app()` shows `messagebox.askokcancel("Exit", "Are you sure you want to exit?")`; on OK it
calls `self.master.quit()` and `self.master.destroy()`.

#### Screen 2 — File chooser

`filedialog.askopenfilename(title="Select Rekordbox XML Export", filetypes=[("XML files", "*.xml"), ("All files", "*.*")])`.
Cancelling returns to the current screen unchanged (no state is cleared).

#### Screen 3 — Ready to Index

- Header: `Ready to Index` (Helvetica 18 bold)
- `Selected file:` (Helvetica 11 bold), then the full absolute path (Helvetica 10, grey, wraplength 500)
- `\nIndexing will:` (Helvetica 11 bold), then four bullets (Helvetica 10):
  - `• Read track metadata from the XML file`
  - `• Generate audio embeddings for each track`
  - `• Build a similarity search index`
  - `• This may take a few minutes depending on library size`
- **Start Indexing** — fake button, green. **Choose Different File** — fake button, grey, reopens the file dialog.

#### Screen 4 — Indexing progress

- Header: `Indexing Your Library` (Helvetica 18 bold)
- Status label: `Starting indexing process...` (Helvetica 11, wraplength 500)
- `ttk.Progressbar`, **`mode='indeterminate'`**, length 400, `start(10)` — it animates but conveys no ratio
- Log `tk.Text`, height 10, `wrap=WORD`, Courier 9, with a vertical scrollbar; auto-scrolls to the end
- **No Cancel button on this screen** (unlike `ReindexWindow`)

Indexing runs on a daemon thread. It calls
`IndexingService(...).run(self.xml_path, force_full=False, progress=on_progress)`, and each
`ProgressEvent`'s `message` is queued as one log line; the UI drains at most 10 messages every
200 ms (`check_indexing_status`). Onboarding passes no `cancel`, so it still offers no
cancellation. On finish the bar is `stop()`ped.

> Until the service layer existed this was a process-global `sys.stdout` swap onto a `QueueWriter`
> that split on `\n` and dropped blank lines. That is the **one** mechanism PR 2 was permitted to
> change (§4 defect #7); the lines rendered in the log pane are byte-identical, because events
> carry the same strings and are never blank.

Terminal log lines appended by the window itself:
- success: `\n✅ Indexing completed successfully!`
- failure: `\n❌ Error during indexing: {error}` followed by the full `traceback.format_exc()`

#### Screen 5a — Success

- Status label becomes `🎉 Your library has been indexed!` (Helvetica 14 bold, green)
- **Start Using Cosine Companion** — fake button, green. Click → `complete_onboarding()`:
  writes `settings.json` as `{"xml_path": <path>, "first_run_complete": true}` with `indent=2`
  (**overwriting any other keys**), destroys the window, invokes the completion callback which
  tears down the temporary root and constructs the real `App`.

#### Screen 5b — Failure

- Status label becomes `⚠️ Indexing encountered an error` (Helvetica 14 bold, red)
- **Try Again** — fake button, orange `#FF9800` (hover `#F57C00`) → returns to Screen 1
- **Exit** — fake button, grey → `quit_app()`

---

### 2.2 Main window — `App` (`app.py`)

`tk.Tk` subclass mixing in `RecommendationsTabMixin`, `SetCreatorTabMixin`, `LibraryTabMixin`,
`PlaylistExportTabMixin`.

| Property | Value |
|---|---|
| Title | `Cosine Companion - Explore your taste` |
| Geometry | `900x720` |
| Minimum size | `820x640` |
| Padding | `padx=12, pady=12` |
| `className` | `Cosine Companion` |

Layout, top to bottom:

1. **Menu bar** (§2.3)
2. **Current-track label** `self.lbl_current` — Helvetica 14 bold, left-anchored, fills width.
   Initial text: `Current track: —`. Format when set: see §3.2.
3. **`ttk.Notebook`** filling the remaining space (`pady=8`), with four tabs in this fixed order:
   1. `Explore` (§2.4)
   2. `Set Creator` (§2.5)
   3. `Playlist Export` (§2.6)
   4. `Library` (§2.7)
4. **Status bar** `self.status` — Helvetica 9, grey, left-anchored, packed `side="bottom"` so it
   stays visible at any window height.

Initial status text (set at construction, before the per-tab hint is applied):
`💡 Choose a track to start using 'Set Current Track' button, double-click any suggestion to set it as current track`

**Startup state:** `current_id = None`, `current_recommendations = []`, `history = []`,
`max_history = 20`.

**macOS re-styling workarounds.** `initialize_ui_state()` re-applies `state="normal"`,
`bg="lightgreen"`, `font=("Helvetica", 10, "bold")` to the Set Creator **+ Add Anchor** button.
It is invoked at construction, `after_idle`, `after(300)`, `after(1000)`, and on every `<Map>`
event. `on_tab_changed` re-applies it again whenever the Set Creator tab becomes visible.
After construction the window is forced visible with `deiconify()` / `lift()` / `focus_force()` /
`update()`.

**Tab-change behaviour** (`<<NotebookTabChanged>>` → `on_tab_changed`), wrapped in a bare
`except Exception: pass`:
- Set Creator → re-style **+ Add Anchor**, then `update_idletasks()`
- Playlist Export → `update_export_selection_info()`
- always → `set_default_status_hint()`

**Default status hint per tab** (`get_hint_for_tab`):

| Tab | Hint |
|---|---|
| Explore | `💡 Choose a track to start using 'Set Current Track' button, double-click any suggestion to set it as current track` |
| Set Creator | `💡 1) Click '+ Add Anchor' and choose a track + it's position in the set. 2) Set 'Total Tracks'. 3) Click 'Generate Set'. 4) Adjust anchors and regenerate as needed.` |
| Playlist Export | `💡 Click '+ Add Tracks' to select tracks → Configure settings → Generate .m3u playlists that import into Rekordbox` |
| Library | `💡 Ctrl+Click to multi-select • Shift+Click to select range • Double-click to set as current track in explore tab` |

If reading the active tab raises, the fallback is
`💡 Tip: Double-click any suggestion to set it as current track`. The hint colour is always grey.

---

### 2.3 Menu bar (`app.py:146-169`)

| Menu | Item | Action |
|---|---|---|
| **File** | `Settings...` | Opens `SettingsWindow` (§2.8) |
| | *(separator)* | |
| | `Exit` | `self.quit()` — leaves the mainloop; no confirmation |
| **Library** | `Update Library (Incremental)` | `App.update_library()` — see below |
| | `Full Re-index...` | Opens `SettingsWindow` (the actual re-index button lives there) |
| | *(separator)* | |
| | `Library Statistics` | Opens `SettingsWindow` — same command as `Settings...` |
| **Help** | `About` | About dialog |

All menus are created with `tearoff=0`. There are **no accelerator keys** on any item.

**`App.update_library()`**: if `data/settings.json` does not exist, or exists but has no
`xml_path`, shows `messagebox.showinfo("Setup Required", "Please configure your library settings first.")`
and then opens `SettingsWindow`. Otherwise opens `ReindexWindow(self, xml_path, force_full=False)`.
Unlike `SettingsWindow.update_library`, it does **not** check that the XML file still exists.

**About dialog** — `messagebox.showinfo`, title `About Cosine Companion`, body:
```
Cosine Companion v1.0

AI-powered music companion for finding similar tracks
and creating seamless DJ sets.

Uses Essentia's Discogs-EffNet embeddings and exact cosine search
for efficient similarity search.

© 2024
```

---

### 2.4 Explore tab (`recommendations_tab.py`)

Notebook tab text: **`Explore`** (index 0, the tab shown at launch).

#### Controls, top to bottom

**Button row**

| Control | Position | Initial state | Action |
|---|---|---|---|
| `← Back` | far left | **`disabled`** | `go_back()` |
| `Set Current Track` | centred | normal | `pick_current()` |
| `Copy Selected to Clipboard` | centred | normal | `copy_selected()` |
| `Set Selected as Current` | centred | normal | `set_selected_as_current()` |

The centre group is centred with two expanding spacer frames; a 90 px empty frame is packed on
the right to balance the `← Back` button.

**Sort row**

- Label `Sort by:` (Helvetica 10 bold), then five buttons: `Score`, `Cosine`, `Key`, `BPM`, `Artist`.
- Right-aligned: label `Top:` (Helvetica 10 bold) and a `ttk.Combobox`, width 5,
  **`state="readonly"`**, values `["10", "20", "30", "50", "100", "200"]`, **default `"50"`**.
  Selecting a value re-renders the list only — it does **not** recompute recommendations.

**Suggestions list** — `tk.Listbox`, height 20, fills and expands, default (single-item)
selection mode, no scrollbar widget (mouse-wheel scrolling only).

#### Bindings

| Binding | Target | Action |
|---|---|---|
| `<Double-Button-1>` | suggestions list | `set_selected_as_current()` (only if something is selected) |
| `<Button-2>` (macOS right-click) | suggestions list | context menu |
| `<Button-3>` (Win/Linux right-click) | suggestions list | context menu |
| `<<ComboboxSelected>>` | Top-N combobox | `update_listbox()` |

**Context menu** (`tearoff=0`): `Set as Current Track` · *(separator)* · `Copy to Clipboard`.
Right-click first selects the row nearest the pointer (`listbox.nearest(event.y)`), replacing any
existing selection, then pops the menu at the pointer.

#### Rendered row format

```
{artist} – {title}   [Key {key or '?'}  BPM {bpm or '?'}  Cos {cos_pct:.1f}%  Score {score_pct:.1f}%]
```

- Separator between artist and title is an **en dash** `–` (U+2013) surrounded by single spaces.
- **Three** spaces before `[`; **two** spaces between each bracketed field.
- `key`/`bpm` fall back to the literal `?` when falsy. `bpm` is a float, so it renders as e.g. `144.0`.
- `Cos` = `cosine * 100`, one decimal. **Not clamped** — a cosine above 1.0 or below 0 renders as-is.
- `Score` = `max(0.0, min(1.0, score)) * 100`, one decimal — **clamped to 0–100 %**.

#### Recommendation computation

`refresh_suggestions()` calls `self.explore.recommend(current_id, topk=500, final_top=200)`,
which applies the shared ranking policy — `recommend_for(...)` then a sort **by `cosine`
descending** (§3.3). The full 200 are retained in `current_recommendations` as `Recommendation`
objects; only the first `topn` are rendered.

#### Sorting

| Button | Key | Direction | Notes |
|---|---|---|---|
| `Score` | `float(score)` | descending | |
| `Cosine` | `float(cosine)` | descending | matches the post-refresh default order |
| `Key` | `str(key)` | **ascending** | lexicographic on the Camelot string, so `10A` < `1A` < `2A` |
| `BPM` | `float(bpm or 0)` | descending | missing BPM sorts last |
| `Artist` | `str(artist).lower()` | **ascending** | |

Sorting is a no-op when there are no recommendations. Sorts apply to all 200 computed
recommendations, then the list is re-rendered truncated to `topn`. All sorts are stable
(`list.sort`), so ties retain the previous order.

#### Status-bar messages

| Situation | Text | Colour |
|---|---|---|
| Rows rendered, all computed shown | `{n} suggestions - 💡 Tip: Double-click any suggestion to set it as current track` | grey |
| Rows rendered, truncated | `Showing {shown} of {total} recommendations - 💡 Tip: ...` | grey |
| …with history | ` ({k} in history)` is inserted after the count clause | grey |
| Empty list | `No suggestions available` | grey |
| After `Set Selected as Current` | `✅ Set '{artist} – {title}' as current track` | **green**, reverts after 3 s |
| After `← Back` | `↩️ Went back to '{artist} – {title}'` | **blue**, reverts after 3 s |

The 3-second revert text is the literal
`💡 Tip: Double-click any suggestion to set it as current track` — note this is **not** the
Explore tab's default hint from §2.2, and it is applied even if the user has switched tabs in
the meantime.

#### `Set Current Track` → `pick_current()`

1. `simpledialog.askstring("Pick Current", "Search artist/title:")`. Empty or cancelled → return.
2. Filters using **search implementation B** (§3.4) — regex-based, `.head(50)`.
3. No rows → `messagebox.showinfo("No match", "Couldn't find any tracks.")`.
4. Otherwise opens `SimplePicker` (§2.9) modally.
5. If a track was chosen, the current state is pushed to history (only when a current track
   already exists) and the new track becomes current.

#### History / `← Back`

- A history entry `{track_id, recommendations (copy), timestamp}` is pushed **only when both**
  `current_id` and `current_recommendations` are truthy.
- Capacity 20; the oldest entry is dropped on overflow.
- Pushing enables `← Back`; popping the last entry disables it again.
- Going back restores the stored recommendation list verbatim (including its sort order) without
  recomputing, updates the header label, and re-renders honouring the **current** Top-N value.

#### `Copy Selected to Clipboard` / context-menu `Copy to Clipboard`

No selection → silent no-op (no dialog). Otherwise it takes the rendered row, splits off the
metrics at the literal `"   ["`, then finds the **first** separator present from the ordered list
`[" – ", " | ", " - ", "|", "–", "-"]` and copies everything **after** it, stripped. For normal
rows this yields the title only. A hyphen inside an artist name that precedes the en dash will
truncate differently.

#### `Set Selected as Current`

| Condition | Response |
|---|---|
| No row selected | `messagebox.showinfo("No Selection", "Please select a track from the suggestions list.")` |
| No recommendations loaded | `messagebox.showinfo("No Recommendations", "No recommendations available.")` |
| Selected index ≥ list length | `messagebox.showerror("Error", "Invalid selection.")` |

---

### 2.5 Set Creator tab (`set_creator_tab.py`)

Notebook tab text: **`Set Creator`** (index 1).

#### Controls

**Configuration row**
- Label `Total Tracks:` (Helvetica 10 bold)
- `tk.Entry`, width 5, bound to `total_tracks_var`, **default `"10"`**
- `Generate Set` button, `bg="lightgreen"`
- `Clear Set` button

**Anchor row**
- Label `Anchor Tracks:` (Helvetica 10 bold)
- `+ Add Anchor` button — `bg="lightgreen"`, Helvetica 10 bold, `state="normal"`; re-styled
  repeatedly (§2.2)
- Anchor `tk.Listbox`, height 4, packed with `padx=(0, 80)`
- `Remove` button, packed to the right

**Generated set**
- Label `Generated Set:` (Helvetica 10 bold), left-anchored
- `tk.Listbox`, height 15, fills and expands
- `Export to Clipboard` button below

No scrollbars and no double-click bindings on either listbox in this tab.

#### Anchor list row format

```
{position}. {artist} – {title}
```
Rendered in ascending position order. A row is skipped entirely if its `track_id` is no longer in
`meta_ix`.

#### Generated-set row format

```
[{position:2d}] {icon} {display_name}{score_text}
```

- `position` is right-aligned in a 2-character field, so positions 1–9 render as `[ 1]`.
- `icon` — `🔒` for anchors, `🤖` for generated picks (`SetTrack.icon`).
- `display_name` (`SetTrack.display_name`) resolves in order:
  `{artist} – {title}` · `{artist} – (Unknown Title)` · `(Unknown Artist) – {title}` ·
  `Track #{track_id}` when the id is all digits · else the raw `track_id`.
- `score_text` is ` ({score:.0%} match)` — shown **only** for non-anchors with `score > 0`.
  Anchors carry `score=1.0` but never show it. Note `:.0%` rounds to whole percent, and
  transition scores are cosines, so a value above 1.0 would render above 100 %.
- Unfillable slots render as `[ n] 🤖 No suitable track found – (Unknown Title)`. The slot is
  built with artist `"No suitable track found"`, an **empty** title and `track_id = empty_{n}`,
  and `SetTrack.display_name` (`recommendations/models.py:23`) then takes its
  *artist-but-no-title* branch, which appends `– (Unknown Title)`. There is **no** bare trailing
  en dash. No score suffix is shown, because the placeholder's score is `0.0`.
  Pinned by `tests/services/test_set_builder.py::test_unfillable_slots_render_the_unknown_title_suffix`.

#### `Generate Set` validation, in order

| Condition | Response |
|---|---|
| `Total Tracks` not an integer | `messagebox.showerror("Invalid Input", "Please enter a valid number for total tracks.")` |
| No anchors | `messagebox.showwarning("No Anchors", "Please add at least one anchor track before generating a set.")` |
| `total_tracks < len(anchors)` | `messagebox.showerror("Invalid Configuration", "Total tracks must be greater than the number of anchor tracks.")` |

Note the message says *greater than* but the check is `<`, so `total == len(anchors)` is allowed.
An anchor position greater than `total_tracks` is **not** caught here; `generate_set` raises
`ValueError("Anchor track position exceeds total tracks")`, which surfaces as
`messagebox.showerror("Generation Error", "Failed to generate set: {error}")`.

During generation the status bar shows `🎵 Generating set... This may take a moment.` and the UI
is force-updated (`self.update()`) — the window is unresponsive for the duration (**2.76 s for a
30-track set** on the 1,307-track library). On success:
`✅ Generated {n}-track set successfully!`. On failure: the error dialog above plus
`❌ Set generation failed.`

#### `Clear Set`

Clears anchors and the generated set, re-renders both listboxes, status `🧹 Set cleared.`
No confirmation.

#### `Remove` (anchor)

No selection → `messagebox.showwarning("No Selection", "Please select an anchor track to remove.")`.
Otherwise the position is parsed from the row text by splitting on the first `.` and coercing to
`int`; a parse failure is silently ignored.

#### `Export to Clipboard`

No generated set → `messagebox.showwarning("No Set", "Please generate a set first.")`.
Otherwise it copies one `display_name` per line — **excluding** any row whose display name
contains `No suitable track found` — and reports
`messagebox.showinfo("Exported", "Copied {n} tracks to clipboard!")`. The clipboard text carries
no positions, icons or scores.

---

### 2.6 Playlist Export tab (`playlist_export_tab.py`)

Notebook tab text: **`Playlist Export`** (index 2). Contents sit in a frame with `padx=20, pady=15`.

- Title: `Export Recommendation Playlists` (Helvetica 14 bold)
- Description (Helvetica 9, grey, wraplength 850, left-justified):
  `Generate .m3u playlists with track recommendations that can be imported into Rekordbox.`

#### Section 1 — `1. Select Tracks` (`tk.LabelFrame`, Helvetica 10 bold)

| Control | Detail |
|---|---|
| Radio `Selected tracks:` | value `manual` — **the default** |
| Button `+ Add Tracks` | `bg="lightgreen"`, Helvetica 9 bold → opens `TrackSelectorDialog` (§2.11) |
| Button `Clear All` | empties the selection set |
| Selected-tracks `tk.Listbox` | height 6, `selectmode=EXTENDED`, `exportselection=False`, fills width. **Read-only in effect** — nothing is bound to its selection, so selecting rows here has no consequence and there is no per-row remove |
| Radio `All tracks in collection` | value `all` |
| Selection-info label | Helvetica 9, colour varies (below) |

Selection-info label text:

| Mode | Text | Colour |
|---|---|---|
| `all` | `✓ Will generate playlists for all {len(meta)} tracks in your collection` | blue |
| `manual`, ≥1 selected | `✓ {n} track(s) selected • Click '+ Add Tracks' to add more` | blue |
| `manual`, none selected | `⚠ No tracks selected. Click '+ Add Tracks' to select tracks` | **orange** |

The label is refreshed when a radio is clicked, when the selection changes, and whenever this tab
becomes visible.

Selected-track rows are sorted by `(artist.lower(), title.lower())` and rendered as
`{artist} – {title} [{key}] ({bpm} BPM)`, with each bracketed part omitted when the field is
falsy and the whole string `.strip()`ped (§3.1). Track IDs absent from `meta_ix` are skipped.

#### Section 2 — `2. Configure Playlists`

| Control | Detail |
|---|---|
| `Recommendations per track:` | `ttk.Combobox`, width 6, `state="readonly"`, values `["10","15","20","25","30","40","50"]`, **default `"25"`** |
| `Export format:` | Radio `Separate playlist per track` (value `separate`, **default**) · Radio `Single combined playlist` (value `combined`) |

#### Section 3 — `3. Output Location`

- `tk.Entry`, width 60, Helvetica 10, **default `~/Desktop/Cosine_Playlists`** (absolute,
  expanded from `Path.home()`). Freely editable.
- `Browse...` → `filedialog.askdirectory(title="Select Output Directory", initialdir=<current value or home>)`.
  Cancelling leaves the value unchanged.

#### Action area

- `🎵 Generate Playlists` — Helvetica 12 bold, `bg="lightgreen"`, `padx=20, pady=10`, centred.
- Progress block, **hidden until an export starts** (`pack`ed with `pady=(20, 0)`, `pack_forget()`
  on completion or error):
  - progress label (Helvetica 10)
  - `ttk.Progressbar`, **`mode='determinate'`**, length 400
  - status label (Helvetica 9, grey)

#### Export flow

1. Track ids: mode `all` → `list(meta['track_id'].values)` in parquet order; mode `manual` →
   `list(export_selected_track_ids)` — **a `set`, so the order is arbitrary**.
   Both the count label and this list read `meta`, **not** `meta_ix`, and deletion leaves `meta`
   stale (§4 defect #14) — so after deleting a track the label and the export agree with each
   other and both still describe the pre-deletion collection until the app is restarted.
2. Empty → `messagebox.showwarning("No Tracks Selected", "Please select tracks to export playlists for.")`
3. Empty output path → `messagebox.showwarning("No Output Directory", "Please select an output directory.")`
4. Confirmation `messagebox.askyesno("Confirm Export", …)`:
   ```
   This will generate {separate playlists|a single combined playlist} for {n} track(s),
   with {k} recommendations per track.

   Output directory: {dir}

   Continue?
   ```
5. The `🎵 Generate Playlists` button is **disabled**, the progress block appears, the bar resets
   to 0, the label shows `Generating playlists...`, and a **daemon thread** runs the export.
6. Progress (separate mode only) — marshalled to the main thread with `after(0, …)`:
   - bar value = `current / total * 100`
   - label `Generating playlists... ({current}/{total})`
   - status `Current: {artist} - {title}` — note a plain **hyphen** here, unlike the en dash used
     everywhere else
7. On success `export_complete` re-enables the button, hides the progress block and shows
   `messagebox.showinfo("Export Complete", …)`:
   ```
   ✓ Export Complete!

   Playlists created: {playlists_created}
   Successful: {successful}
   Total recommendations: {total_recommendations}
   Failed: {failed}

   Location: {output_dir}

   You can now import these .m3u files into Rekordbox:
   File → Import → Playlist → Select .m3u file(s)
   ```
8. On exception `export_error` re-enables the button, hides the progress block and shows
   `messagebox.showerror("Export Error", "An error occurred during export:\n\n{msg}")`.

Measured full-collection export: **≈ 6.8 minutes**. There is **no cancel control** once started,
and closing the main window does not stop the daemon thread.

The worker calls `self.after(0, …)` from the background thread to marshal progress and completion
back to Tk (`playlist_export_tab.py:397,434`). Tk is not thread-safe and `after` is not one of the
documented exceptions, so this is a latent crash rather than correct marshalling — it happens to
work in practice. **Pre-existing on `main`; deliberately not fixed here** (§4 defect #15).

See §4 for the combined-mode `playlists_created` defect and the export/delete race.

#### Output files

Separate mode writes into `{output_dir}` (created with `parents=True, exist_ok=True`), one file
per seed named `{safe_artist} - {safe_title}.m3u` (§3.6). Combined mode writes the single file
`{output_dir}/Cosine_Recommendations.m3u` — and does **not** create the directory first, so a
missing directory raises `FileNotFoundError` into the error dialog. The internal playlist name
`"Cosine Recommendations"` is passed but never used.

M3U content (§3.6) — UTF-8, `#EXTM3U` header, then per track
`#EXTINF:-1,{artist} - {title}` and the bare absolute `path_local`.

---

### 2.7 Library tab (`library_tab.py`)

Notebook tab text: **`Library`** (index 3).

#### Controls

**Search row** — label `Search:` (Helvetica 10 bold), `tk.Entry` width 30 (filters live on every
`<KeyRelease>`), `Clear` button, `Refresh` button.

**Controls row** — `Delete Selected` (`bg="lightcoral"`), `Set as Current`, and a right-aligned
stats label (Helvetica 9, grey).

**Track list** — `tk.Listbox`, height 20, `selectmode=EXTENDED`, `exportselection=False`, with a
vertical `tk.Scrollbar`. This is the only listbox in the app with a working scrollbar widget.
`<Double-Button-1>` → `Set as Current`.

#### Row format and order

```
{artist} – {title} [{key}] ({bpm} BPM)
```
Bracketed parts are omitted when falsy; the result is `.strip()`ped (§3.1). Rows are sorted by
`(artist.lower(), title.lower())` — this ordering is the identity used by every index-based
operation in the tab.

Stats label: `{n} tracks` when unfiltered, `{shown} of {total} tracks` when filtered.

#### Filtering — search implementation C (§3.4)

Case-insensitive plain-substring match against **artist, title, album or key**. The query is
lowercased but **not** stripped, so a lone space matches only rows containing a space. An empty
query restores the full list. There is no result limit.

`Clear` empties the box and re-filters. `Refresh` rebuilds the whole list from `meta_ix` and
re-applies the current filter; a failure sets the status to `❌ Error loading library: {error}`.

#### `Set as Current`

No selection → `messagebox.showwarning("No Selection", "Please select a track from the library.")`.
Otherwise it sets the track as current, refreshes the Explore recommendations and **switches to
tab index 0 (Explore)**. It sets `current_id` directly, so **nothing is pushed to the Explore
history** and `← Back` state is unaffected.

#### `Delete Selected`

No selection → `messagebox.showwarning("No Selection", "Please select tracks to delete.")`.

Confirmation `messagebox.askyesno("Confirm Deletion", …)`:

- one track:
  `Delete this track from your library?\n\n{artist} – {title}\n\nThis will remove it from recommendations but won't delete the audio file.`
- several:
  `Delete {n} selected tracks from your library?\n\nThis will remove them from recommendations but won't delete the audio files.`

On confirm, `LibrarySession.delete_tracks` (moved verbatim from
`library_tab.py:213-273` on `main`):

1. Appends the tracks to `deleted_tracks.json` with `{artist, title}` so they are excluded from
   future indexing runs.
2. Filters `meta_ix` and `emb_ix` in memory.
3. Rebuilds `V`, `ids` and a fresh `NumpyCosIndex`. **If nothing remains**, sets `V = np.array([])`,
   `ids = []` and **`idx = None`**.
4. Writes `meta.parquet`, `embeddings.parquet`, `index.npy` (skipped when `V` is empty) and
   `ids.json` — **four separate writes, no atomicity, no rollback** (§4).
5. Returns the count of removed metadata rows.

It does **not** rebuild `meta`. Everything that reads `meta_ix` refreshes immediately; everything
that reads `meta` keeps showing the deleted track until the app is restarted (§4 defect #14).

Afterwards the tab restores the scroll position (`first_visible` minus the number of deleted rows
above it), refreshes the list, and reports `✅ Deleted {n} tracks from library` or
`❌ No tracks were deleted`. If the current Explore track was deleted, it is cleared: the header
returns to `Current track: —` and the suggestions list is emptied. Any exception surfaces as
`messagebox.showerror("Deletion Error", "Failed to delete tracks: {error}")` plus status
`❌ Error deleting tracks`.

Deletion does **not** clear Explore history, Set Creator anchors, or the Playlist Export
selection, all of which may still reference the removed ids.

**Stale consumers after a deletion** — what refreshes and what does not:

| Surface | Reads | After a delete |
|---|---|---|
| Library tab list and stats | `meta_ix` | **updated** immediately |
| Explore recommendations | `meta_ix` / `emb_ix` / `idx` | **updated** immediately |
| Set Creator anchor list | `meta_ix` | **updated** (rows for missing ids are skipped) |
| Explore `Set Current Track` picker | **`meta`** | **stale** — still offers the deleted track, and choosing it raises `KeyError` from `meta_ix.loc` |
| Playlist Export all-tracks count | **`meta`** | **stale** — still counts the deleted track |
| Playlist Export all-tracks id list | **`meta`** | **stale** — still exports the id, which `create_m3u_playlist` then silently skips |
| A running export | its start-of-run snapshot | **stale by design** — see §4 defect #1 |

---

### 2.8 Settings window — `SettingsWindow` (`settings_window.py`)

`tk.Toplevel`, title **`Settings - Cosine Companion`**, 600×600, **not resizable**, modal
(`transient` + `grab_set`), centred by absolute offset (`screenwidth//2 - 300`,
`screenheight//2 - 300`), then `deiconify()` / `lift()` / `focus_force()` / `update()`.

Header `⚙️ Settings` (Helvetica 18 bold, pady 15). Content frame `padx=30, pady=10`. Four
sections separated by full-width `ttk.Separator`s (`pady=20`). A `Close` button
(Helvetica 11, `padx=40, pady=8`) sits at the bottom.

#### `Library Configuration` (Helvetica 13 bold)

Row: label `Rekordbox XML:` (Helvetica 10 bold, width 15, left-anchored), a path label, and a
`Change` button (right-aligned, Helvetica 9).

The path label starts as `Not set` in grey. When `settings.json` exists it shows
`settings.get("xml_path", "Not set")` in **black**, truncated to `"..." + path[-47:]` when longer
than 50 characters. If `settings.json` exists but has no `xml_path`, the label reads `Not set`
in black.

`Change` → `filedialog.askopenfilename(title="Select Rekordbox XML Export", filetypes=[("XML files", "*.xml"), ("All files", "*.*")])`.
On selection it merges `xml_path` into the existing settings dict (preserving other keys), writes
with `indent=2`, updates the label with the same truncation, and shows
`messagebox.showinfo("XML Path Updated", "XML file path has been updated. Click 'Update Library' to process any new tracks.")`.
The chosen file's existence is not verified here.

#### `Library Statistics` (Helvetica 13 bold)

Three labels (Helvetica 10). Their pre-load placeholders — `Total Tracks: Loading...`,
`Last Indexed: Unknown`, `Index Size: Calculating...` — are replaced synchronously during
construction, so they are not normally visible.

| Label | Loaded value |
|---|---|
| Total tracks | `Total Tracks: {count:,}` (thousands separator) from `len(meta.parquet)`, or `Total Tracks: 0` if the file is missing |
| Last indexed | `Last Indexed: {YYYY-MM-DD HH:MM}` from `meta.parquet`'s mtime, or `Last Indexed: Never` |
| Index size | `Index Size: {mb:.1f} MB` — the summed size of every `*.parquet`, `*.npy` and `*.json` in the data directory (so it includes `settings.json` and `deleted_tracks.json`) |

Any exception while loading statistics is swallowed after printing
`Error loading statistics: {e}` to stdout, leaving the placeholder text in place — for these three
labels **and** for `Deleted Tracks: Loading...` below, which is set last and so is the most likely
to survive.

#### `Deleted Tracks` (Helvetica 13 bold)

- Pre-load placeholder `Deleted Tracks: Loading...` (`settings_window.py:186`), replaced with
  `Deleted Tracks: {count:,}` (Helvetica 10) at the **end** of `load_statistics()`. It is the last
  thing that method sets, so **any** exception raised earlier in it — a missing or unreadable
  `meta.parquet`, an unstattable data file — leaves `Deleted Tracks: Loading...` on screen
  permanently, alongside whichever of the three statistics placeholders had not yet been replaced.
  Only `Error loading statistics: {e}` on stdout says otherwise.
- `Deleted tracks won't be re-added during re-indexing` (Helvetica 9, grey)
- `Manage Deleted Tracks...` → `DeletedTracksDialog` (§2.10); statistics are reloaded on close
- `Clear All` → when the list is empty, `messagebox.showinfo("No Deleted Tracks", "There are no deleted tracks to clear.")`.
  Otherwise `messagebox.askyesno("Clear All Deleted Tracks", "This will clear ALL {n} deleted track(s) from the list.\n\nAfter clearing, running 'Update Library' will re-add these tracks if they're in your Rekordbox XML.\n\nContinue?")`,
  then writes an empty dict and shows
  `messagebox.showinfo("Deleted Tracks Cleared", "Cleared {n} deleted track(s).\n\nRun 'Update Library' to restore these tracks.")`

#### `Library Actions` (Helvetica 13 bold)

| Button | Adjacent grey caption |
|---|---|
| `🔄 Update Library (Incremental)` (Helvetica 11 bold, padx 15, pady 8) | `  Process only new tracks` |
| `🔄 Full Re-index` (Helvetica 10, padx 15, pady 8) | `  Reprocess entire library (slow)` |

Both resolve the XML path from `settings.json` and guard it:

| Condition | Response |
|---|---|
| `settings.json` missing | `messagebox.showerror("No XML Path", "Please set your Rekordbox XML file path first.")` |
| `xml_path` empty or the file no longer exists | `messagebox.showerror("XML File Not Found", "The XML file could not be found:\n{path}\n\nPlease update the path in settings.")` |

`Full Re-index` asks first:
`messagebox.askyesno("Confirm Full Re-index", "This will reprocess your entire library, which may take a while.\n\nOnly do this if you're experiencing issues.\n\nContinue?")`.

On success both `destroy()` the settings window and open
`ReindexWindow(self.master, xml_path, force_full=…)` — parented to the **main app**, not to the
window being destroyed.

---

### 2.9 `SimplePicker` (`dialogs.py:11-31`)

`tk.Toplevel`, title **`Choose Track`**, 560×420, resizable, **non-modal** (no `transient`, no
`grab_set`) — the caller blocks on `wait_window` instead. No window icon.

- `tk.Listbox`, height 20, `padx=8, pady=8`, single selection, rows rendered `{artist} – {title}`
- `Select` button (`pady=6`)

`Select` with no row selected still closes the dialog and leaves `chosen = None` (a silent
cancel). There is no explicit Cancel button; the window-manager close button has the same effect.
Rows appear in the order given by the caller — for `pick_current` that is parquet order, capped
at 50.

---

### 2.10 `DeletedTracksDialog` (`dialogs.py:125-291`)

`tk.Toplevel`, title **`Manage Deleted Tracks`**, 700×500, resizable, modal, centred by absolute
offset, icon set, forced visible with `deiconify()` / `lift()` / `focus_force()`.

- Header `Deleted Tracks ({n})` (Helvetica 14 bold, pady 10)
- `Select tracks to restore (they'll be re-added during next library update)` (Helvetica 10, grey)
- `tk.Listbox`, `selectmode=EXTENDED`, Helvetica 10, with a vertical scrollbar, `padx=20, pady=10`.
  Rows are `{artist} – {title}` from `deleted_tracks.json`, ordered by **`sorted(track_id)`** —
  a lexicographic sort of the numeric-string ids, so ordering appears arbitrary to the user.
- `Select tracks using Ctrl+Click or Shift+Click` (Helvetica 9, grey) — a static caption, never updated
- `Remove Selected from Deleted List` (Helvetica 11 bold, padx 20, pady 8)
- `Close` (Helvetica 11, padx 20, pady 8)

`Remove Selected` with no selection →
`messagebox.showwarning("No Selection", "Please select one or more tracks to remove from the deleted list.")`.
Otherwise `messagebox.askyesno("Remove from Deleted List", "Remove {n} track(s) from the deleted list?\n\nThese tracks will be re-added during the next library update.")`,
then the ids are removed from `deleted_tracks.json` and
`messagebox.showinfo("Tracks Removed", "Removed {n} track(s) from deleted list.\n\nRun 'Update Library' to restore these tracks.")` is shown before the list reloads.

The header count is refreshed by scanning the window's children for the first `tk.Label` whose
text contains `Deleted Tracks`.

Old-format `deleted_tracks.json` (a bare JSON list of ids) is upgraded on read to
`{id: {"artist": "Unknown", "title": id}}`, so such rows render as `Unknown – {track_id}`.
An unreadable file prints `Warning: Could not load deleted tracks list ({e})` and is treated as empty.

---

### 2.11 `TrackSelectorDialog` (`track_selector_dialog.py`)

`tk.Toplevel`, title **`Select Tracks for Playlist Export`**, 600×550, resizable, modal
(`transient` + `grab_set`). No window icon.

- `Search for tracks:` (Helvetica 11 bold) and a `tk.Entry` (Helvetica 10) that **takes focus on
  open** and filters on `<KeyRelease>`
- `💡 Ctrl+Click to select multiple • Shift+Click to select range` (Helvetica 9, grey)
- `Search Results:` (Helvetica 10 bold)
- `tk.Listbox`, height 20, `selectmode=EXTENDED`, `exportselection=False`, Helvetica 10, with a
  vertical scrollbar
- Selection-count label (Helvetica 9): `0 tracks selected` in **grey**, `1 track selected` in
  blue, `{n} tracks selected` in blue. Initial text is `0 tracks selected` in **blue** — the grey
  is only applied once a selection event has fired.
- `Select All` / `Clear Selection` (Helvetica 9)
- `Add Selected Tracks` (`bg="lightgreen"`, Helvetica 10 bold, padx 20, pady 5) and
  `Cancel` (Helvetica 10, padx 20, pady 5), both right-packed — `Cancel` sits rightmost.

Results use **search implementation A** (§3.4) with `limit=100` for an empty query and `limit=50`
otherwise. Because implementation A returns `[]` for a blank query, **the dialog opens with an
empty list** despite the `# Initialize with all tracks` intent, and clearing the box empties it
again (§4).

Rows already in the export selection are prefixed `✓ ` (tick + space).

`Add Selected Tracks` with nothing selected →
`messagebox.showwarning("No Selection", "Please select at least one track.")`. Otherwise the
selected ids are **unioned into** the caller's set (never replacing it) and the dialog closes.
`Cancel` and the window-manager close button both discard the selection.

---

### 2.12 `AddAnchorDialog` (`dialogs.py:34-122`)

`tk.Toplevel`, title **`Add Anchor Track`**, 500×500, resizable, modal. No window icon.

- `Position in Set:` (Helvetica 10 bold) and a `tk.Entry` width 5 — **blank by default**
- `Search for Track:` (Helvetica 10 bold) and a full-width `tk.Entry` filtering on `<KeyRelease>`
- `Search Results:` (Helvetica 10 bold) and a `tk.Listbox`, height 15, single selection,
  `<Double-Button-1>` = `Add to Set`
- `Add to Set` (`bg="lightgreen"`) and `Cancel`, both right-packed — `Cancel` sits rightmost

Results use **search implementation A** with `limit=50`; rows render as `{artist} – {title}`.
As with §2.11, the dialog opens showing **nothing** because a blank query returns no results.

`Add to Set` validates in this order:

| Condition | Response |
|---|---|
| No row selected | `messagebox.showwarning("No Selection", "Please select a track.")` |
| Position not an integer (including blank) | `messagebox.showerror("Invalid Position", "Please enter a valid position number.")` |
| Position < 1 | `messagebox.showerror("Invalid Position", "Position must be 1 or greater.")` |
| Position already used | `messagebox.askyesno("Position Taken", "Position {n} already has an anchor track. Replace it?")` — declining returns to the dialog |

There is no upper bound on the position, and no check against the tab's `Total Tracks`.
The same track may be anchored at several positions.

---

### 2.13 `ReindexWindow` (`reindex_window.py`)

`tk.Toplevel`, title **`Full Re-index - Cosine Companion`** or **`Update Library - Cosine Companion`**,
600×400, **not resizable**, modal, centred by absolute offset, icon set, forced visible.
Indexing starts automatically 100 ms after the window opens.

- Header: `Reprocessing Entire Library` (full) or `Checking for New Tracks` (incremental) — Helvetica 16 bold, pady 15
- Status label: `Starting...` (Helvetica 11, wraplength 500)
- `ttk.Progressbar`, **`mode='indeterminate'`**, length 400, `start(10)`
- Log `tk.Text`, height 12, `wrap=WORD`, Courier 9, with a vertical scrollbar; auto-scrolls
- `Cancel` button (Helvetica 11 bold, padx 30, pady 8)

Progress plumbing is identical to onboarding: a daemon thread, one queued log line per
`ProgressEvent`, and a 200 ms drain of at most 10 messages per tick. Unlike onboarding, a
cancellation token **is** supplied — `service.run(..., cancel=self.cancel_event)`, where
`cancel_requested` is a property over that `threading.Event` so every existing read and write of
the flag still works. (On `main` this was `cancel_check=lambda: self.cancel_requested` passed
straight to `index_library`, under a process-global `sys.stdout` swap; §4 defect #7.)

`Cancel` first asks
`messagebox.askyesno("Cancel Indexing", "Are you sure you want to cancel? Progress will be lost.")`.
On confirm it logs `\n⚠️ Cancellation requested...` and sets the flag; the pipeline raises
`KeyboardInterrupt` at its next per-track checkpoint and **every embedding computed so far is
discarded** (§4).

Terminal states — the bar stops and the `Cancel` button is destroyed, then:

| State | Status label | Button |
|---|---|---|
| Cancelled | `⚠️ Indexing cancelled` (Helvetica 12 bold, **orange**) | `Close` (Helvetica 12) |
| Success | `✅ Library updated successfully!` (Helvetica 12 bold, **green**) | `Done` (Helvetica 12 bold) |
| Error | `❌ An error occurred` (Helvetica 12 bold, **red**) | `Close` (Helvetica 12) |

Log lines appended by the window: `\n✅ Indexing completed successfully!`, or
`\n❌ Error during indexing: {msg}` plus the traceback.

**The two cancellation lines are dead code and are never appended.** `run_indexing` writes
`\n⚠️ Indexing cancelled by user` after a successful `service.run(...)` and
`\n⚠️ Indexing cancelled` in its `except Exception` handler — but a cancelled run raises
`KeyboardInterrupt`, which derives from `BaseException`, so it satisfies neither branch. It
propagates out of `run_indexing` (`reindex_window.py:186`), the worker thread dies with an
unhandled exception printed to stderr, and **no** further message is queued. The only cancellation
text the user ever sees in the log pane is `\n⚠️ Cancellation requested...`, queued by the Cancel
button itself. The window still reaches its orange cancelled state, because `cancel_indexing()`
set the flag that `check_indexing_status` reads.

Pinned by `tests/services/test_indexing_service.py::test_cancel_raises_keyboardinterrupt_which_is_not_an_exception`;
the manual harness `tests/manual/smoke.py` asserts the two lines' **absence**.

**`Done` → `finish()`** shows
`messagebox.askyesno("Restart Required", "Library has been updated!\n\nTo see new tracks in the UI, you should restart Cosine Companion.\n\nRestart now?")`.

- **Yes** → destroys this window, destroys the main app and calls **`sys.exit(0)`**. The app does
  not relaunch itself; the user must start it again manually (§4).
- **No** → closes this window only. The main app keeps its **stale** in-memory index; newly
  indexed tracks are invisible until a manual restart.

Pipeline log lines rendered verbatim in the log pane, in order (`processing/pipeline.py`):

```
🎵 Cosine Companion - {Full Reindex|Incremental Indexing}
==================================================
🔄 Force full reindex requested - ignoring existing data      (full only)
Found existing data: {n} tracks already indexed               (incremental, when data exists)
📖 Reading Rekordbox XML...
   Found {n} tracks in XML
🔍 Checking for duplicate tracks...
   Removed {n} duplicate tracks / Kept {n} unique tracks / Duplicates found: … (up to 5, then "… and {n} more")
   No duplicates found
🔍 Checking for previously deleted tracks...
   Filtered out {n} previously deleted tracks
Found {n} new tracks to process
🔬 Debug sample enabled: limiting to first {n} new tracks      (CLI --sample only)
✅ No new tracks to process! Your index is up to date.
🎯 Processing {n} new tracks...
   [  1/{N}] {artist} - {title}                                (per track; index right-aligned in 3 chars)
      ⚠️  File not found: {path}
      ⚠️  Failed to process audio file (unsupported codec or decode error): {path}
⚠️ Cancellation detected, stopping...
❌ No new embeddings generated. Check audio paths/codecs.
✨ Generated {n} new embeddings
🔄 Merging with existing data...
🔄 Merging metadata...
==================================================
✅ Indexing complete!
   • Total tracks indexed: {n}
   • New tracks added: {n}
   • Data saved to: {DATA}/
🚀 Ready to use! Run 'python cosine_companion.py ui' to start the application.
```

Note the per-track line uses a plain **hyphen** between artist and title. The pipeline sleeps
50 ms after each successful embedding to keep the UI responsive. Blank lines are dropped by the
queue writer, so the pipeline's bare `print()` never reaches the log pane.

---

## 3. Cross-cutting rules

### 3.1 Track-row rendering

| Surface | Format |
|---|---|
| Explore suggestions | `{artist} – {title}   [Key {key\|?}  BPM {bpm\|?}  Cos {c:.1f}%  Score {s:.1f}%]` |
| Library list | `{artist} – {title} [{key}] ({bpm} BPM)`, empty parts omitted, `.strip()`ped |
| Export selected list | identical to the Library list |
| Set Creator anchors | `{position}. {artist} – {title}` |
| Set Creator generated set | `[{position:2d}] {🔒\|🤖} {display_name}{ (score:.0%) match}` |
| `SimplePicker` | `{artist} – {title}` |
| `AddAnchorDialog` / `TrackSelectorDialog` | `{artist} – {title}`, optionally prefixed `✓ ` |
| `DeletedTracksDialog` | `{artist} – {title}` |
| Export progress status | `Current: {artist} - {title}` (**hyphen**) |
| M3U `#EXTINF` | `{artist} - {title}` (**hyphen**) |
| Indexing log | `   [{i:3d}/{N}] {artist} - {title}` (**hyphen**) |

Everything user-facing in a list uses the **en dash** `–` (U+2013); the three exceptions above use
a hyphen. `bpm` is a `float64` column, so it always renders with a decimal point (`144.0`).
`key` is stored already in Camelot form (e.g. `10A`, `11B`); no conversion happens at display time.

### 3.2 Current-track header

```
Current track: {artist} – {title} {key_text} {bpm_text}
```
where `key_text` is `[{key}]` or the literal `[?]` when the key is falsy, and `bpm_text` is
`({bpm} BPM)` or the literal `(?)` when the BPM is falsy. With no current track the label is
exactly `Current track: —` (em dash).

### 3.3 Ranking policy

Both the Explore tab and the playlist exporter use the same two-step policy, which since the
service-layer extraction has exactly one implementation —
`recommendations/ranking.py::ranked_recommendations`, called by `ExploreSession.recommend`, by
`export_recommendations_as_playlists` and by `export_single_playlist`:

1. `recommend_for(seed, meta_ix, emb_ix, idx, topk=500, final_top=200)`
   — exact cosine search for `topk + 1 = 501` neighbours, the seed itself skipped, each candidate
   scored `0.7·cosine + 0.2·key_compat + 0.1·bpm_compat`, sorted by that **score** descending,
   truncated to **200**.
2. The caller then re-sorts those 200 **by `cosine` descending** and truncates.

The two steps compose to something that is neither pure-score nor pure-cosine ranking: the
*membership* of the 200 is decided by score, the *order* by cosine. Truncation counts differ only
because they are caller parameters — Explore shows `topn` (default 50, max 200), the exporter
takes `recommendations_per_track` (default 25, max 50). Both sorts are stable.

`recommend_for` returns dictionaries with exactly:
`track_id`, `artist`, `title`, `bpm`, `key`, `score`, `cosine`, `key_score`, `bpm_score`.
**`path_local` is not among them** — the exporter re-reads it from `meta_ix`.

Set generation uses a different per-hop configuration: `topk=100, final_top=50`, the top 20
candidates re-scored by `0.8·cos(prev→cand) + 0.2·cos(cand→next)` (or plain `cosine` when there is
no previous track).

### 3.4 The three divergent track searches

The plan named two; there are in fact **three**. None is used by more than one kind of caller and
**they must not be unified in this PR**.

| | **A — `recommendations/search.py`** | **B — `pick_current` (Explore)** | **C — `filter_library` (Library)** |
|---|---|---|---|
| Callers | `AddAnchorDialog` (50), `TrackSelectorDialog` (100 / 50) | `Set Current Track` | Library search box |
| Source | `meta_ix`, row order = parquet order | `meta` DataFrame | pre-sorted `library_tracks` |
| Blank query | **returns `[]`** | returns early, no dialog | shows everything |
| Whitespace query | `.strip()`ed → `[]` | not stripped | not stripped |
| Match type | plain lowercase substring | **`str.contains` — a regex** | plain lowercase substring |
| Fields | artist, title, and the joined `"{artist} {title}"` | artist, title (independently) | artist, title, **album**, **key** |
| Limit | caller's `limit`, early-break | `.head(50)` | none |
| Result shape | list of `{track_id, artist, title, display_name}` | DataFrame slice `[artist, title, track_id]` | list of the tab's track dicts |
| Result order | parquet order | parquet order | artist/title order |

Practical consequences: B treats `.` `*` `(` `[` as regex metacharacters (an unbalanced `(`
raises `re.error` out of the Tk callback); A's blank-query behaviour empties both selector
dialogs on open; only C searches album and key.

`LibrarySession.search_tracks()` exposes **A**, because that is what the two dialogs call.

### 3.5 macOS Tk workarounds (~350 lines)

These are compatibility scaffolding, not behaviour the rewrite must reproduce — but they are
listed so their disappearance is not mistaken for a lost feature.

- **Fake `Label` buttons.** All **seven** onboarding buttons are `tk.Label`s inside a coloured
  `tk.Frame` with `relief="raised", bd=2`, wired to `<Button-1>`, `<Enter>` and `<Leave>`, because
  `tk.Button` ignores `bg` under the macOS theme. Each has a hover shade and a 100 ms delay
  before acting. They have **no keyboard focus and no keyboard activation**. The seven, by screen:

  | Screen | Buttons |
  |---|---|
  | 1 Welcome | `Get Started` (green `#4CAF50`), `Exit` (grey `#757575`) |
  | 3 Ready to Index | `Start Indexing` (green), `Choose Different File` (grey) |
  | 5a Success | `Start Using Cosine Companion` (green) |
  | 5b Failure | `Try Again` (orange `#FF9800`), `Exit` (grey) |

  Screens 2 and 4 have none: screen 2 is a native file dialog and screen 4 is the progress view,
  which deliberately offers no Cancel.
- **Repeated re-styling** of the Set Creator `+ Add Anchor` button at five different moments (§2.2).
- **`deiconify()` / `lift()` / `focus_force()` / `update()`** after constructing `App`,
  `SettingsWindow`, `ReindexWindow`, `OnboardingWindow` and `DeletedTracksDialog`.
- **Absolute-offset centring** (`screenwidth//2 - w//2`) rather than measured geometry.
- **`<Button-2>` bound alongside `<Button-3>`** so right-click works on both platforms.
- **Status bar packed `side="bottom"`** so a short window cannot hide it.

### 3.6 M3U output format

`create_m3u_playlist` writes UTF-8 text:

```
#EXTM3U
#EXTINF:-1,{artist} - {title}
{path_local}
```

- The `#EXTM3U` header is written when `include_extended` is true — and every caller uses the
  default `True`.
- The duration is hard-coded `-1`; CoCo never captures track duration.
- `artist`/`title` fall back to `Unknown Artist` / `Unknown Title` only when the key is **absent**
  from the row; an empty string is written as empty.
- The path is the bare absolute `path_local`, unquoted, with no `file://` scheme.
- Tracks absent from `meta_ix`, with an empty `path_local`, or whose `path_local` does not exist
  on disk are **silently skipped** — they do not appear in the file and are not counted anywhere.
- Line separator is `\n` (the file is opened in text mode without `newline=`, so on macOS `\n`).

Per-seed filenames (`recommendations/playlist_exporter.py::playlist_filename`): `artist` and
`title` are filtered to characters where `c.isalnum() or c in (' ', '-', '_')`, `.strip()`ped,
joined as `{safe_artist} - {safe_title}.m3u`, and if the result exceeds 200 characters it is
truncated to `filename[:200] + ".m3u"`, yielding a **204-character** name cut mid-title. The
boundary is strictly greater than 200, so a name of exactly 200 characters is left alone.

A **doubled `.m3u` is impossible**, contrary to what this document previously claimed: the
sanitiser drops `.`, so the only dot in the name is the extension the function appends, and when
the name exceeds 200 characters that extension sits beyond the cut. Two different seeds that
sanitise to the same name overwrite each other silently.

### 3.7 Settings file

`data/settings.json` (or `~/Library/Application Support/Cosine Companion/settings.json` when
frozen). The only key in real use is **`xml_path`**; onboarding also writes
**`first_run_complete: true`**. Read/written at **seven** sites in three files:

| Site | Operation | Missing file | Corrupt file |
|---|---|---|---|
| `onboarding.save_settings` | write `{xml_path, first_run_complete}`, `indent=2` — **replaces the whole document** | creates it | n/a |
| `onboarding.needs_onboarding` | read | treated as "needs onboarding" | **raises `JSONDecodeError` at startup** |
| `app.update_library` | read | `Setup Required` dialog | **raises into the Tk callback** |
| `settings_window.load_settings` | read | label stays `Not set` | **raises during window construction** |
| `settings_window.change_xml_path` | read-modify-write, `indent=2` — **preserves other keys** | creates it | **raises into the Tk callback** |
| `settings_window.update_library` | read | `No XML Path` dialog | **raises into the Tk callback** |
| `settings_window.full_reindex` | read | `No XML Path` dialog | **raises into the Tk callback** |

No site wraps `json.load` in a `try`. Missing file is always handled by an `exists()` check;
a corrupt file always propagates. `SettingsStore` reproduces exactly this: `{}` for a missing
file, `JSONDecodeError` for a corrupt one.

### 3.8 Keyboard and mouse bindings

**There are no custom keyboard shortcuts and no menu accelerators anywhere in the app.** The only
keyboard involvement is text entry, `<KeyRelease>`-driven live filtering, and the platform's own
Tk defaults (Tab traversal, `⌘Q`, `⌘W`, standard text-field editing). Fake `Label` buttons (§3.5)
cannot be reached or activated from the keyboard at all.

| Event | Where | Effect |
|---|---|---|
| `<KeyRelease>` | Library search, `AddAnchorDialog` search, `TrackSelectorDialog` search | live re-filter |
| `<Double-Button-1>` | Explore list | Set Selected as Current |
| `<Double-Button-1>` | Library list | Set as Current (+ switch to Explore) |
| `<Double-Button-1>` | `AddAnchorDialog` results | Add to Set |
| `<Button-2>` / `<Button-3>` | Explore list | context menu |
| `<<ListboxSelect>>` | `TrackSelectorDialog` results | update the count label |
| `<<ComboboxSelected>>` | Explore Top-N | re-render the list |
| `<<NotebookTabChanged>>` | notebook | re-style, refresh export info, reset hint |
| `<Map>` | main window | re-style `+ Add Anchor` |
| `<Button-1>` / `<Enter>` / `<Leave>` | every onboarding fake button | activate / hover shade |
| Ctrl+Click, Shift+Click | Library list, `TrackSelectorDialog`, `DeletedTracksDialog`, export selected list | Tk-native extended selection |

### 3.9 Defaults

| Setting | Default |
|---|---|
| Explore Top-N | `50` (of `10/20/30/50/100/200`) |
| Explore computation | `topk=500`, `final_top=200` |
| Explore initial sort | cosine descending |
| Set Creator Total Tracks | `10` |
| Anchor position field | blank |
| Export selection mode | `Selected tracks:` (manual) |
| Export recommendations per track | `25` (of `10/15/20/25/30/40/50`) |
| Export format | `Separate playlist per track` |
| Export output directory | `~/Desktop/Cosine_Playlists` |
| Combined playlist filename | `Cosine_Recommendations.m3u` |
| Explore history capacity | `20` |
| Scoring weights | cosine `0.7`, key `0.2`, bpm `0.1` |
| BPM tolerance | ±6 %, half/double time scored `0.7` |
| Set generation per hop | `topk=100`, `final_top=50`, top 20 re-scored |
| Transition weighting | `0.8·cos(prev→cand) + 0.2·cos(cand→next)` |

### 3.10 Conditional control states

| Control | Condition |
|---|---|
| `← Back` (Explore) | `disabled` at launch; `normal` once history is non-empty; back to `disabled` when the last entry is popped |
| `🎵 Generate Playlists` | `disabled` for the duration of an export, re-enabled on completion **and** on error |
| Export progress block | hidden until an export starts, hidden again when it ends |
| `Cancel` (ReindexWindow) | present while indexing; **destroyed** at the terminal state and replaced by `Done` or `Close` |
| `+ Add Anchor` | permanently forced to `normal` by the re-styling passes (§2.2) |
| Top-N and recommendations-per-track comboboxes | `state="readonly"` — a value may be chosen but not typed |
| Export selected-tracks listbox | selectable but inert — no command consumes its selection |

Every other button in the app is unconditionally enabled and validates on click instead.

---

## 4. Known defects that are current behaviour

These are catalogued in spec §3.2 and characterised by the test suite **as-is**. They are part of
the contract only in the sense that PR 2 must not change them; the rewrite is expected to fix
them and say so.

| # | Defect | Location | Current observable behaviour |
|---|---|---|---|
| 1 | Export/delete data race | export worker thread vs `library_tab` delete | The export thread holds references to `meta_ix`/`emb_ix`/`idx` captured at start while deletion rebinds them on the main thread. A delete mid-export can yield `KeyError`, an `IndexError` from the index, or playlists built from a stale index. Nothing warns the user |
| 2 | Non-atomic four-file rewrite | `services/library_session.py::_persist` (was `library_tab.py:257-270`) | `meta.parquet`, `embeddings.parquet`, `index.npy`, `ids.json` are written in sequence with no temp-file-and-rename and no rollback. A crash or full disk between writes leaves the four files mutually inconsistent, and the next launch fails the `load_all` validation → the `Inconsistent Index Data` dialog |
| 3 | Deleting every track leaves `idx = None` | `services/library_session.py::delete_tracks` (was `library_tab.py:251-255`) | `V = np.array([])`, `ids = []`, `idx = None`, and `index.npy` is **not** rewritten, so it retains the pre-delete vectors and disagrees with the now-empty `ids.json` |
| 4 | Cancel discards all work | `pipeline.py:143-147` | `KeyboardInterrupt` is raised at the next per-track checkpoint; every embedding computed so far is dropped. A cancelled 6.8-minute run leaves nothing behind |
| 5 | `sys.exit(0)` after indexing | `reindex_window.py:304-321` | Choosing "Restart now?" kills the process without relaunching. Declining leaves the app running on a stale index with no indication |
| 6 | Indeterminate progress bar | `reindex_window.py:92-97`, `onboarding.py:335-341` | The pipeline prints `[ i/N]` per track but the bar is `mode='indeterminate'`; the ratio is only readable in the log pane |
| 7 | Process-global `sys.stdout` swap | *(resolved in PR 2)* | A worker thread used to replace `sys.stdout` for the whole process for the duration of indexing, so any other thread's output was captured too. **This is the single mechanism Task 8 was permitted to replace**, and it has been: `IndexingService` emits a `ProgressEvent` per pipeline message and both windows queue `event.message`. The rendered log lines are unchanged, so the contract below is unaffected |
| 8 | ~350 lines of macOS Tk workarounds | across the UI | §3.5 |
| 9 | Blank query returns nothing | `search.py:21-22` | `AddAnchorDialog` and `TrackSelectorDialog` both open with an **empty** result list, contradicting their `# Initialize with all tracks` intent and the `limit = 100 if not query` branch |
| 10 | Combined export shows no success dialog | `playlist_export_tab.py:440-456` | `export_single_playlist` returns stats without a `playlists_created` key, so `export_complete` raises `KeyError` while building the message. The button is re-enabled and the progress block hidden first, so the user sees the export simply stop with **no confirmation** and a traceback on stderr. The playlist file is written correctly |
| 11 | Combined export reports no progress | `playlist_export_tab.py:403-412` | `export_single_playlist` takes no `progress_callback`, so the determinate bar sits at 0 % for the whole run |
| 12 | Duplicate ranking policy | *(resolved in PR 2)* | There were three copies of the same `recommend_for(topk=500, final_top=200)` + cosine re-sort, in `recommendations_tab.py` and twice in `playlist_exporter.py`. **Verified behaviourally identical** before consolidation (harness: `tests/manual/ranking_equivalence.py`); only the caller-supplied truncation differed. All three now call `recommendations/ranking.py::ranked_recommendations` |
| 13 | Selection is an unordered `set` | `playlist_export_tab.py:338-347` | Manual-mode export order is arbitrary and varies between runs; the progress readout therefore visits tracks in no particular order |
| 14 | Deletion leaves `meta` stale | `services/library_session.py::delete_tracks` (was `library_tab.py:213-273`) | Deletion rebuilds `meta_ix`, `emb_ix`, `V`, `ids` and the index, but **not** `meta`. Explore's `Set Current Track` picker still offers the deleted track (and raises `KeyError` from `meta_ix.loc` if it is chosen), and the Playlist Export all-tracks count and id list still include it, until the app is restarted. See the stale-consumer table in §2.7 |
| 15 | `after()` called from a worker thread | `playlist_export_tab.py:397,434` | The export worker marshals progress and completion back to Tk with `self.after(0, …)` from a background thread. Tk is not thread-safe and `after` is not an exception to that; it happens to work. **Pre-existing on `main` and deliberately untouched by PR 2** — fixing it would be a behaviour change in a PR whose contract forbids one |
| 16 | Cancellation log lines are unreachable | `reindex_window.py:180-189` | `\n⚠️ Indexing cancelled by user` and `\n⚠️ Indexing cancelled` are written in branches a `KeyboardInterrupt` never reaches, so neither is ever appended (§2.13). Pre-existing on `main` |

Backlog references: `backlog-n3-ids-lag-race` (#1, #3), spec §3.2 (#1–#8), spec §10.

**Deliberately fixed in PR 3, not here:** #14 (recompute or invalidate `meta` on delete), #15 (marshal
through a queue the main thread drains, as `ReindexWindow` already does), #16 (catch `BaseException`
or stop using `KeyboardInterrupt` as a control-flow signal), #1 (a real read/write discipline around
the library), #10 and #11 (the combined-export dialog and progress).

---

## 5. Workflow checklist (manual smoke test)

Every row is a user-reachable workflow catalogued above. Task 9 records pass/fail for each.

| # | Workflow | Surface |
|---|---|---|
| 1 | Launch with an existing index — window appears, Explore tab active, hint shown | §2.2 |
| 2 | Menu ▸ File ▸ Settings… opens the settings window with the real XML path and statistics | §2.8 |
| 3 | Menu ▸ Help ▸ About shows the about dialog | §2.3 |
| 4 | Explore ▸ Set Current Track ▸ search ▸ pick from `SimplePicker` ▸ suggestions render | §2.4, §2.9 |
| 5 | Explore ▸ search with no match ▸ `No match` dialog | §2.4 |
| 6 | Explore ▸ double-click a suggestion ▸ it becomes current, green status, `← Back` enables | §2.4 |
| 7 | Explore ▸ `← Back` ▸ previous track and list restored, blue status | §2.4 |
| 8 | Explore ▸ each of the five sort buttons reorders the list | §2.4 |
| 9 | Explore ▸ Top-N 10/200 ▸ row count changes without recomputation | §2.4 |
| 10 | Explore ▸ right-click ▸ context menu ▸ both items work | §2.4 |
| 11 | Explore ▸ Copy Selected to Clipboard ▸ title on the clipboard | §2.4 |
| 12 | Set Creator ▸ + Add Anchor ▸ search, position, Add to Set ▸ anchor listed | §2.5, §2.12 |
| 13 | Set Creator ▸ Generate Set ▸ set renders with icons and match percentages | §2.5 |
| 14 | Set Creator ▸ Remove ▸ anchor disappears | §2.5 |
| 15 | Set Creator ▸ Clear Set ▸ both lists empty, status updated | §2.5 |
| 16 | Set Creator ▸ Export to Clipboard ▸ confirmation dialog with the right count | §2.5 |
| 17 | Set Creator ▸ Generate with no anchors ▸ warning dialog | §2.5 |
| 18 | Library ▸ type in the search box ▸ list filters live, stats show `x of y` | §2.7 |
| 19 | Library ▸ Clear / Refresh ▸ full list restored | §2.7 |
| 20 | Library ▸ double-click ▸ becomes current and the app switches to Explore | §2.7 |
| 21 | Library ▸ Set as Current with no selection ▸ warning dialog | §2.7 |
| 22 | Library ▸ Delete Selected ▸ confirmation ▸ track gone, status updated | §2.7 |
| 22a | …then Library ▸ Refresh ▸ the deleted track is **gone** from the list and the stats count drops | §2.7 |
| 22b | …then Explore ▸ Set Current Track ▸ search for the deleted track ▸ it is **still offered** (stale `meta`), and choosing it raises `KeyError` | §2.7, §4 #14 |
| 22c | …then Playlist Export ▸ All tracks radio ▸ the count is **unchanged** (still counts the deleted track) | §2.7, §4 #14 |
| 22d | …then Playlist Export ▸ All tracks ▸ export ▸ the deleted id is sent and silently skipped; no playlist is written for it | §2.7, §4 #14 |
| 22e | …then Set Creator ▸ an anchor on the deleted track disappears from the anchor list on next render | §2.5, §2.7 |
| 22f | Restart the app ▸ every stale surface above is now correct | §2.7, §4 #14 |
| 22g | Start a full export, delete a track while it runs ▸ the export finishes against its start-of-run snapshot; the deleted track still appears in playlists written after the delete | §2.6, §4 #1 |
| 23 | Playlist Export ▸ + Add Tracks ▸ search, multi-select, Add ▸ selection list and info label update | §2.6, §2.11 |
| 24 | Playlist Export ▸ Clear All ▸ orange warning label | §2.6 |
| 25 | Playlist Export ▸ All tracks radio ▸ label shows the full collection count | §2.6 |
| 26 | Playlist Export ▸ Browse… ▸ directory chosen | §2.6 |
| 27 | Playlist Export ▸ separate mode ▸ confirm ▸ progress advances ▸ completion dialog ▸ files on disk | §2.6 |
| 28 | Playlist Export ▸ combined mode ▸ single file written (no dialog — defect #10) | §2.6, §4 |
| 29 | Playlist Export ▸ Generate with nothing selected ▸ warning dialog | §2.6 |
| 30 | Settings ▸ Change ▸ pick an XML ▸ label truncates, confirmation dialog, `settings.json` updated | §2.8 |
| 31 | Settings ▸ Manage Deleted Tracks… ▸ list, restore, counts update | §2.8, §2.10 |
| 32 | Settings ▸ Clear All deleted tracks ▸ confirmation and result dialogs | §2.8 |
| 33 | Settings ▸ Update Library (Incremental) ▸ `ReindexWindow` runs and reports | §2.8, §2.13 |
| 34 | Reindex ▸ Cancel ▸ confirmation ▸ orange cancelled state and `Close` | §2.13 |
| 34a | Reindex ▸ Cancel ▸ the log pane's **last** line is `⚠️ Cancellation requested...` — `⚠️ Indexing cancelled by user` and `⚠️ Indexing cancelled` must **NOT** appear, and neither must `✅ Indexing completed successfully!` | §2.13, §4 #16 |
| 34b | Reindex ▸ Cancel ▸ an unhandled `KeyboardInterrupt` traceback appears on stderr, and no data files are written | §2.13, §4 #4 |
| 34c | Reindex ▸ let it finish ▸ the log pane ends with `🚀 Ready to use! …` then `✅ Indexing completed successfully!` | §2.13 |
| 35 | Reindex ▸ Done ▸ Restart Required dialog ▸ declining leaves the app running | §2.13 |
| 36 | Menu ▸ Library ▸ Update Library (Incremental) ▸ same reindex window | §2.3 |
| 37 | Tab switching ▸ status hint changes per tab | §2.2 |
| 38 | Onboarding (fresh data directory) ▸ welcome ▸ file ▸ confirm ▸ index ▸ Start Using | §2.1 |
| 39 | Onboarding ▸ all seven fake buttons respond to click and to hover, and none can be reached by Tab | §2.1, §3.5 |
| 40 | Settings ▸ open with an unreadable `meta.parquet` ▸ `Total Tracks: Loading...` **and** `Deleted Tracks: Loading...` remain on screen, and `Error loading statistics: …` is printed to stdout | §2.8, §4 |
| 41 | Set Creator ▸ generate a set larger than the candidates available ▸ unfillable rows read exactly `[ n] 🤖 No suitable track found – (Unknown Title)` | §2.5 |
| 42 | Playlist Export ▸ combined mode ▸ the progress bar stays at 0 % for the whole run and no completion dialog appears | §2.6, §4 #10, #11 |
