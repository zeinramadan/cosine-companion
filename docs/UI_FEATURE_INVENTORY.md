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

### How this document is checked

A false claim here is not a documentation nit. PR 3 is reviewed against this document, so a false
claim becomes a regression that passes review. Three kinds of check apply, and they catch different
things:

| Kind of claim | How it is settled | Where |
|---|---|---|
| **Existential** — "string X is rendered", "the widget is at `file.py:N`" | one grep; a single hit confirms it | round-1/2 characterisation tests |
| **Absence / universal / exclusivity / attribution** — "X never appears", "the only listbox with…", "every call site discards…" | a falsifier: a test that would find the counterexample if one existed. 98 of these were written in round 3 | the characterisation suite, plus `tests/test_ui_reports_success_for_every_terminal_outcome.py` |
| **Ordering / timing** — "the last line is X", "the flag is always seen", "the lines are dead code" | neither of the above can settle these. They are refuted by an INTERLEAVING, which no static search over the source surfaces. Each one needs the concurrency reasoned through by hand and then pinned with a deterministic test that stands in for the interleaving | §2.13, defects #16–#18 |

Some failure modes are entirely internal to the document and no source-facing test can see them —
a stated **count** disagreeing with its own enumeration, or one passage contradicting another.
`tests/test_inventory_self_consistency.py` is the check whose subject is this document. What it
settles and what it leaves open are both stated here, because a guard that is trusted for more than
it does is worse than no guard:

**It verifies.** Every `file.py:N` citation names a file that exists and a line number inside it.
Every §-reference, every `#n` defect reference and every `tests/…::test_name` citation resolves to
something real, and the defect table is numbered without gaps. The listbox and print-site counts
are re-derived from the source rather than trusted, and no stated count contradicts its own
enumeration. A short list of claims already found false in review cannot reappear verbatim. And
every block matching the hand-written absolute-claim vocabulary — `never`, `dead code`,
`none of …`, `no … are written` — carries a justification token in the same block: a test
citation, the word *pinned*, or a `file.py:N` derivation.

**It does not verify.** It does not check that a citation *supports* the sentence it hangs off:
the citation check reads the cited file's length, never the cited line, so any real line number
satisfies it. It has no general contradiction detector — the two contradiction checks it does have
are hand-written for specific known pairs (scrolling, and the refuted-claim list), so a new claim
that contradicts a distant section passes. The absolute-claim vocabulary is a finite hand-written
list of phrasings, not a general detector of absoluteness: a claim worded outside it — *zero data
files are written* — goes unseen, and an unseen block is not asked to justify itself. Widening the
list is a permanent game of catch-up, and finishing it is not attempted. And it cannot settle an
**ordering** claim at all, because those are refuted by an interleaving rather than by anything in
the text.

A worked example of the gap, recorded so it is not rediscovered as a surprise: rewriting the timing
B paragraph below to assert the *opposite* of what it asserts, with a real `pipeline.py` line
number appended, passes every one of these checks. A general semantic checker is not achievable
here and none is attempted. Ordering claims are settled instead by the deterministic timing tests
in `tests/services/test_indexing_service.py` and
`tests/test_ui_reports_success_for_every_terminal_outcome.py`, each of which has been verified to
FAIL when the behaviour it pins is changed — the mutations are listed in the PR description.

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
`ProgressEvent`'s `message` is queued as one log line. The 10-messages-per-tick cap applies only
**while the worker is alive**: `check_indexing_status` drains at most 10 and reschedules itself with
`after(200, …)`, but once `indexing_thread.is_alive()` is False it drains the queue in an
**unbounded** loop before showing the terminal state, so no line is ever lost to the cap
(`onboarding.py:398-441`). Onboarding passes no `cancel`, so it still offers no cancellation. On
finish the bar is `stop()`ped.

> Until the service layer existed this was a process-global `sys.stdout` swap onto a `QueueWriter`
> that split on `\n` and dropped blank lines. That is the **one** mechanism PR 2 was permitted to
> change (§4 defect #7); the lines rendered in the log pane are byte-identical, because events
> carry the same strings and are never blank
> (`tests/services/test_indexing_service.py::test_no_blank_messages_are_emitted`).

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

No scrollbar widgets and no double-click bindings on either listbox in this tab (rows 6 and 7
of the table in §2.7; wheel and keyboard scrolling still work).

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

Measured full-collection export: **≈ 6.8 minutes**. There is **no cancel control** once started:
nothing in the UI signals the worker to stop, and `ExportService` is given no `cancel` argument
(`playlist_export_tab.py:394-412`). Closing the main window does not ask it to stop either — it ends
`mainloop()`, and the worker, being a daemon thread, is killed when the interpreter exits, possibly
part-way through writing a playlist file.

The worker calls `self.after(0, …)` from the background thread to marshal progress and completion
back to Tk. Progress goes through `update_export_progress`, handed to the service as `progress=` at
`playlist_export_tab.py:401` and calling `self.after(0, update)` at `:438`; completion is marshalled
at `:420` and the error path at `:422`. Tk is not thread-safe and `after` is not one of the
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
vertical `tk.Scrollbar` wired both ways (`library_tab.py:44-49`). It is the only listbox **in a main
tab** with a scrollbar widget; two dialogs have one as well. Three of the app's **nine** listboxes
have a scrollbar widget and six do not — every row is enumerated, so the count and the table cannot
drift apart:

| # | Listbox | Constructed at | Scrollbar widget |
|---|---|---|---|
| 1 | `library_tab.library_listbox` | `library_tab.py:43` | **yes** — `library_tab.py:44-49` |
| 2 | `DeletedTracksDialog.listbox` | `dialogs.py:191` | **yes** — `dialogs.py:188-198` |
| 3 | `TrackSelectorDialog.results_listbox` | `track_selector_dialog.py:65` | **yes** — `track_selector_dialog.py:62-74` |
| 4 | `SimplePicker` picker list (§2.9) | `dialogs.py:21` | **no** |
| 5 | `AddAnchorDialog.results_listbox` | `dialogs.py:65` | **no** |
| 6 | `set_creator_tab.anchor_listbox` | `set_creator_tab.py:40` | **no** |
| 7 | `set_creator_tab.set_listbox` | `set_creator_tab.py:46` | **no** |
| 8 | `recommendations_tab.listbox` | `recommendations_tab.py:66` | **no** |
| 9 | `playlist_export_tab.export_selected_listbox` | `playlist_export_tab.py:86` | **no** |

**A missing scrollbar widget does not make content unreachable.** All nine scroll: Tk's default
`Listbox` class bindings include `<MouseWheel>` (`%W yview scroll …`), `<Shift-MouseWheel>`,
`<Key-Prior>`/`<Key-Next>` and the `<<PrevLine>>`/`<<NextLine>>` virtual events, and this app never
rebinds or unbinds them — there is no `bind_class`, `unbind` or `<MouseWheel>` binding anywhere in
`src/ui/`. What rows 4–9 lack is the **affordance**: no visible track, so no indication that more
rows exist, no thumb showing position within the list, and no drag- or click-to-page. Content past
the visible height is reachable by wheel, and by keyboard once the listbox has focus.

Enumeration and counts are re-derived from the source by
`tests/test_inventory_self_consistency.py`, which greps `Listbox(`/`Scrollbar(` in `src/ui/` and
fails if this table or the sentence above it disagrees with what is there.

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

- `tk.Listbox`, height 20, `padx=8, pady=8`, single selection, rows rendered `{artist} – {title}`,
  **no scrollbar widget** (row 4 of the table in §2.7; wheel and keyboard scrolling still work)
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
`ProgressEvent`, and a 200 ms tick draining at most 10 messages **while the worker is alive**,
followed by one unbounded drain once it is not (`reindex_window.py:195-252`). Unlike onboarding, a
cancellation token **is** supplied — `service.run(..., cancel=self.cancel_event)`, where
`cancel_requested` is a property over that `threading.Event` so every existing read and write of
the flag still works. (On `main` this was `cancel_check=lambda: self.cancel_requested` passed
straight to `index_library`, under a process-global `sys.stdout` swap; §4 defect #7.)

`Cancel` first asks
`messagebox.askyesno("Cancel Indexing", "Are you sure you want to cancel? Progress will be lost.")`.
On confirm it logs `\n⚠️ Cancellation requested...` and sets `cancel_event`
(`reindex_window.py:148-152`). If a per-track checkpoint still lies ahead, the pipeline raises
`KeyboardInterrupt` there and **every embedding computed so far is discarded** (§4). If none does,
the cancellation is never observed by the pipeline at all — see *Two cancellation timings* below.

Terminal states — the bar stops and the `Cancel` button is destroyed, then:

| State | Status label | Button |
|---|---|---|
| Cancelled | `⚠️ Indexing cancelled` (Helvetica 12 bold, **orange**) | `Close` (Helvetica 12) |
| Success | `✅ Library updated successfully!` (Helvetica 12 bold, **green**) | `Done` (Helvetica 12 bold) |
| Error | `❌ An error occurred` (Helvetica 12 bold, **red**) | `Close` (Helvetica 12) |

Log lines appended by the window, one per terminal branch of `run_indexing`
(`reindex_window.py:180-194`): `\n✅ Indexing completed successfully!`,
`\n⚠️ Indexing cancelled by user`, `\n⚠️ Indexing cancelled`, or
`\n❌ Error during indexing: {msg}` plus the traceback. Which of the two cancellation lines can
appear, and when, is set out under *Two cancellation timings* below.

#### Two cancellation timings

**Cancellation is observed in exactly one place**: `processing/pipeline.py:182`, at the **top** of
each per-track loop iteration. `cancel_check` is called nowhere else — not in the XML read, the
duplicate scan, the deleted-track filter, `embed_file`, the normalisation, the merge or the
four-file write. (`IndexingService` passes `cancel.is_set` straight through,
`services/indexing_service.py:174`; there is no second consumer anywhere in `src/`.)

Which log lines appear therefore depends on **when** `cancel_event` is first set relative to that
one checkpoint. Both timings are user-reachable and they produce different observable results.

---

**Timing A — early cancel: at least one checkpoint still runs after the flag is set.**

This is the common case: the user clicks `Cancel` while tracks are still being embedded and more
than one remain. Iteration *i+1* sees the flag, reports `⚠️ Cancellation detected, stopping...` and
raises `KeyboardInterrupt`. That derives from `BaseException`, so `run_indexing`'s `except
Exception` (`reindex_window.py:186`) does **not** catch it; it propagates out of `run_indexing`, the
worker thread dies with an unhandled traceback on **stderr**, and **no** further message is queued.

The log pane then shows **two** cancellation lines, from two different sources:

| # | Line | Emitted by | Thread |
|---|---|---|---|
| 1 | `\n⚠️ Cancellation requested...` | `cancel_indexing()`, on confirming the dialog (`reindex_window.py:152`) | main |
| 2 | `⚠️ Cancellation detected, stopping...` | the pipeline's per-track checkpoint (`processing/pipeline.py:183`), as a `cancelled` `ProgressEvent`, immediately before it raises `KeyboardInterrupt` | worker |

**Their order is not guaranteed (§4 #18).** `cancel_indexing` sets the `Event` at
`reindex_window.py:151` and only then queues line 1 at `:152`. Those are two separate statements on
the main thread, and the worker is free to run between them — it releases the GIL on every
`time.sleep(0.05)` and inside numpy — so a checkpoint reached in that window queues line 2 **first**.
In practice line 1 nearly always wins, because the window is short in **wall-clock** terms — a
few microseconds. It is not short in *instructions*, and it is not atomic: `:151` is a property
assignment whose setter (`reindex_window.py:60-65`) calls `Event.set()`, and `:152` then builds a
tuple and calls `queue.Queue.put`, which takes a mutex, appends to a deque and notifies a condition
variable. That is many bytecodes across several Python frames, and CPython may switch threads at
a bytecode boundary once the switch interval has elapsed (`sys.setswitchinterval()`, 5 ms by
default) — it does not switch on a fixed 5 ms period, and it may also switch while that mutex is
contended. Nothing enforces the order. Any check written as "line 1 **followed by** line 2", or
as "the **last** line is `⚠️ Cancellation detected, stopping...`", is asserting a race it cannot
rely on; check for the
**presence** of both lines instead.

Absent under this timing: `⚠️ Indexing cancelled by user`, `⚠️ Indexing cancelled` and
`✅ Indexing completed successfully!`. **No data files are written** — the interrupt is raised
before the merge and before `save_all`, so every embedding computed so far is discarded (§4 #4).
The window still reaches its orange cancelled state, because `cancel_indexing()` set the flag that
`check_indexing_status` reads. Pinned by
`tests/services/test_indexing_service.py::test_cancel_discards_every_embedding_computed_so_far`.

---

**Timing B — late cancel: no checkpoint runs after the flag is set (§4 #17).**

Reachable whenever the flag is first set after the **last** checkpoint has already been passed —
that is:

- during the final track's `embed_file` call, or during the 50 ms `time.sleep` after it
  (`pipeline.py:200-216`); or
- during any post-loop phase: normalisation, `merge_embeddings`, the metadata merge, index build or
  the four-file write; or
- at **any** moment of a run that never enters the loop at all: `len(new_tracks) == 0` returns
  `STATUS_UP_TO_DATE` at `pipeline.py:169-170` without ever reading `cancel_check`, so there is no
  moment at which a flag on such a run could be seen (pinned by
  `tests/services/test_indexing_service.py::test_a_cancel_during_an_up_to_date_run_is_never_observed`); or
- after the **last** track's checkpoint on a run where every track fails to embed. That run does
  enter the loop and does perform one checkpoint per track, but `pipeline.py:219-221` then returns
  `STATUS_NO_EMBEDDINGS` without another read — so a flag set from the final track onwards is never
  observed, while one set earlier still is (pinned by
  `…::test_a_late_cancel_on_the_no_embeddings_path_is_never_observed`).

The pipeline never re-reads `cancel_check`, so it **completes normally** and returns a summary
dict. `service.run(...)` returns, and `run_indexing`'s `if self.cancel_requested:`
(`reindex_window.py:180`) is now **True**. The window therefore queues:

| # | Queued | Source |
|---|---|---|
| 1 | `('cancelled', True)` | `reindex_window.py:181` |
| 2 | `('log', "\n⚠️ Indexing cancelled by user")` | `reindex_window.py:182` |

`⚠️ Indexing cancelled by user` **IS appended** under this timing, and it is the last line in the
pane. `✅ Indexing completed successfully!` is still absent (it is the `else` of the same branch).
`⚠️ Cancellation detected, stopping...` is absent too, because the pipeline never reached a
checkpoint with the flag set (`processing/pipeline.py:181-186` is the only emitter) — so timing B is
distinguishable from timing A in the log pane by that line alone. Pinned by
`tests/test_ui_reports_success_for_every_terminal_outcome.py::test_a_late_cancel_appends_the_cancelled_by_user_line`.

**Whether data is written depends on which sub-case of B occurred.** If the run reached
`STATUS_INDEXED`, all four data files are written and the on-disk index is fully updated while the
window reports a cancellation. If it returned `STATUS_UP_TO_DATE` or `STATUS_NO_EMBEDDINGS`,
nothing is written — those returns are at `processing/pipeline.py:169-170` and
`processing/pipeline.py:219-221`, both of which precede `save_index_data`. The `STATUS_INDEXED`
half is pinned by
`tests/services/test_indexing_service.py::test_a_cancel_first_observed_after_the_last_checkpoint_does_not_stop_the_run`
and the `STATUS_NO_EMBEDDINGS` half by
`…::test_a_late_cancel_on_the_no_embeddings_path_is_never_observed`, which sets a real cancel flag
after that run's last checkpoint. (`…::test_a_run_where_nothing_could_be_embedded_is_not_up_to_date`
pins the same empty outcome but passes no cancel token, so it says nothing about timing B.)

Either way the window shows the orange `⚠️ Indexing cancelled` state with a `Close` button, **not**
`Done` (`reindex_window.py:246-247` dispatches to `show_cancelled` at `reindex_window.py:270-285`,
which is the only branch that does not build a `Done` button), so the user is never offered the
`Restart Required` prompt (§4 #5) even though the on-disk index may have changed underneath the
running app.

---

**Timing C — cancel plus an unrelated error.** `\n⚠️ Indexing cancelled`
(`reindex_window.py:189`) needs an ordinary `Exception` to reach `except Exception` while
`cancel_requested` is already `True` — for example an `OSError` during the merge or the four-file
write after the user pressed `Cancel`. Rarer than A or B because it needs two events, but not a
dead branch either.

Pinned by:

| Claim | Test |
|---|---|
| A: cancellation raises `KeyboardInterrupt`, which is not an `Exception` | `tests/services/test_indexing_service.py::test_cancel_raises_keyboardinterrupt_which_is_not_an_exception` |
| A: nothing is persisted | `…::test_cancel_discards_every_embedding_computed_so_far` |
| B: a flag first set after the last checkpoint is never observed, and the run completes and persists | `…::test_a_cancel_first_observed_after_the_last_checkpoint_does_not_stop_the_run` |
| B: the window then appends `⚠️ Indexing cancelled by user` | `tests/test_ui_reports_success_for_every_terminal_outcome.py::test_a_late_cancel_appends_the_cancelled_by_user_line` |
| C: the `except Exception` cancellation branch is reachable | `…::test_a_cancel_plus_an_unrelated_error_appends_the_other_cancelled_line` |

The manual harness is `tests/manual/real_indexing.py:145-149`. It exercises **timing A only** — it
cancels after track 2 of at least 6, which guarantees a subsequent checkpoint — and its assertions
check presence and absence, never ordering. It cannot observe timing B, which is why B is pinned by
the deterministic unit tests above rather than by the harness.

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
frozen). **Two** keys are in real use. **`xml_path`** is read by every consumer below;
**`first_run_complete`** is written by `onboarding.save_settings` and *read* by
`onboarding.needs_onboarding` (`onboarding.py:613`), where `not settings.get("first_run_complete",
False)` decides whether the whole onboarding flow runs at startup — so it gates more of the app than
`xml_path` does. No third key is ever read or written. Read/written at **seven** sites in three
files (the `SettingsStore(...)` instances in `reindex_window.py:166` and `onboarding.py:384` are
**not** among them: they are handed to `IndexingService`, which takes its XML path as a `run()`
argument and never touches the file):

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
| 2 | Non-atomic four-file rewrite | `services/library_session.py::_persist` (was `library_tab.py:257-270` on `main`) | `meta.parquet`, `embeddings.parquet`, `index.npy`, `ids.json` are written in sequence with no temp-file-and-rename and no rollback. A crash or full disk between writes leaves the four files mutually inconsistent, and the next launch fails the `load_all` validation → the `Inconsistent Index Data` dialog |
| 3 | Deleting every track leaves `idx = None` | `services/library_session.py::delete_tracks` (was `library_tab.py:251-255` on `main`) | `V = np.array([])`, `ids = []`, `idx = None`, and `index.npy` is **not** rewritten, so it retains the pre-delete vectors and disagrees with the now-empty `ids.json` |
| 4 | Cancel discards all work | `pipeline.py:182-186` | `KeyboardInterrupt` is raised at the next per-track checkpoint **if one remains** (§2.13 timing A); every embedding computed so far is dropped. A cancelled 6.8-minute run leaves nothing behind. If no checkpoint remains the opposite happens and the work is kept — defect #17 |
| 5 | `sys.exit(0)` after indexing | `reindex_window.py:304-321` | Choosing "Restart now?" kills the process without relaunching. Declining leaves the app running on a stale index with no indication |
| 6 | Indeterminate progress bar | `reindex_window.py:92-97`, `onboarding.py:335-341` | The pipeline prints `[ i/N]` per track but the bar is `mode='indeterminate'`; the ratio is only readable in the log pane |
| 7 | Process-global `sys.stdout` swap | *(resolved in PR 2)* | A worker thread used to replace `sys.stdout` for the whole process for the duration of indexing, so any other thread's output was captured too. **This is the single mechanism Task 8 was permitted to replace**, and it has been: `IndexingService` emits a `ProgressEvent` per pipeline message and both windows queue `event.message`. The rendered log lines are unchanged, so the contract below is unaffected |
| 8 | ~350 lines of macOS Tk workarounds | across the UI | §3.5 |
| 9 | Blank query returns nothing | `search.py:21-22` | `AddAnchorDialog` and `TrackSelectorDialog` both open with an **empty** result list, contradicting their `# Initialize with all tracks` intent and the `limit = 100 if not query` branch |
| 10 | Combined export shows no success dialog | `playlist_export_tab.py:440-456` | `export_single_playlist` returns stats without a `playlists_created` key, so `export_complete` raises `KeyError` while building the message. The button is re-enabled and the progress block hidden first, so the user sees the export simply stop with **no confirmation** and a traceback on stderr. The playlist file is written correctly |
| 11 | Combined export reports no progress | `playlist_export_tab.py:403-412` | `export_single_playlist` **does** accept a `progress_callback` and emits one per seed (`playlist_exporter.py:183`, `:223-229`), and `ExportService.export_combined` forwards it. The preserved behaviour is in the **caller**: the tab deliberately omits the `progress=` argument for combined mode (`playlist_export_tab.py:403-412`), exactly as `main` did, so the determinate bar sits at 0 % for the whole run. Wiring it up is PR 3 work — a one-argument change, not a redesign |
| 12 | Duplicate ranking policy | *(resolved in PR 2)* | There were three copies of the same `recommend_for(topk=500, final_top=200)` + cosine re-sort, in `recommendations_tab.py` and twice in `playlist_exporter.py`. **Verified behaviourally identical** before consolidation (harness: `tests/manual/ranking_equivalence.py`); only the caller-supplied truncation differed. All three now call `recommendations/ranking.py::ranked_recommendations` |
| 13 | Selection is an unordered `set` | `playlist_export_tab.py:338-347` | Manual-mode export order is arbitrary and varies between runs; the progress readout therefore visits tracks in no particular order |
| 14 | Deletion leaves `meta` stale | `services/library_session.py::delete_tracks` (was `library_tab.py:213-273` on `main`) | Deletion rebuilds `meta_ix`, `emb_ix`, `V`, `ids` and the index, but **not** `meta`. Explore's `Set Current Track` picker still offers the deleted track (and raises `KeyError` from `meta_ix.loc` if it is chosen), and the Playlist Export all-tracks count and id list still include it, until the app is restarted. See the stale-consumer table in §2.7 |
| 15 | `after()` called from a worker thread | `playlist_export_tab.py:420,422,438` | The export worker marshals progress (`:438`, via `update_export_progress`), completion (`:420`) and errors (`:422`) back to Tk with `self.after(0, …)` from a background thread. Tk is not thread-safe and `after` is not an exception to that; it happens to work. **Pre-existing on `main` and deliberately untouched by PR 2** — fixing it would be a behaviour change in a PR whose contract forbids one |
| 16 | Cancellation is signalled by `KeyboardInterrupt`, so the log line the user sees is timing-dependent | `reindex_window.py:180-194` | `KeyboardInterrupt` derives from `BaseException`, so `except Exception` at `:186` never catches it. When the pipeline **does** raise (timing A) the worker thread dies unhandled and neither `\n⚠️ Indexing cancelled by user` nor `\n⚠️ Indexing cancelled` is appended; when it does **not** (timings B and C, defect #17) one of them is. Which line — or none — the user ends up with is decided by an interleaving, not by anything they did. Pre-existing on `main`; §2.13 |
| 17 | Late cancel is silently ignored by the pipeline, then reported as a cancellation | `pipeline.py:182` (the only `cancel_check` call) vs `reindex_window.py:180-182` | `cancel_check` is read **only** at the top of each per-track loop iteration. A flag first set after the last checkpoint — during the final `embed_file`, during the 50 ms sleep, during the merge/index/write phase, or at any time on a run that returns `STATUS_UP_TO_DATE`/`STATUS_NO_EMBEDDINGS` without re-entering the loop — is never observed. The pipeline completes, and on the `STATUS_INDEXED` path **writes all four data files**; `run_indexing` then sees `cancel_requested` and queues `('cancelled', True)` plus `\n⚠️ Indexing cancelled by user`. The user is told the run was cancelled while the index was in fact updated, and `show_cancelled` offers `Close` rather than `Done`, so the `Restart Required` prompt (#5) is never shown and the app keeps a stale in-memory index over changed files. Pre-existing on `main`; §2.13 timing B |
| 18 | The two cancellation log lines can arrive in either order | `reindex_window.py:151-152` vs `processing/pipeline.py:182-183` | `cancel_indexing` sets the `threading.Event` **before** it queues `\n⚠️ Cancellation requested...`. Between those two statements the worker may reach a checkpoint, see the flag and queue `⚠️ Cancellation detected, stopping...` first. Both lines always appear; which one is last is decided by a GIL switch. The window is narrow in wall-clock terms — microseconds — but it is not two instructions and it is not atomic: `:151` is a property assignment whose setter calls `Event.set()`, and `:152` builds a tuple and calls `queue.Queue.put`, which takes a mutex and notifies a condition variable, across several Python frames. Line 1 therefore nearly always wins, which is exactly why an ordering assertion here would pass in testing and fail in the field. Pre-existing on `main`; §2.13 timing A |

Backlog references: `backlog-n3-ids-lag-race` (#1, #3), spec §3.2 (#1–#8), spec §10.

**Deliberately fixed in PR 3, not here:** #14 (recompute or invalidate `meta` on delete), #15 (marshal
through a queue the main thread drains, as `ReindexWindow` already does), #16 (catch `BaseException`
or stop using `KeyboardInterrupt` as a control-flow signal), #17 (check cancellation at more than
one point, and have the pipeline report whether it actually stopped rather than letting the window
infer it from a flag), #18 (queue the log line before setting the flag, or emit both from one
thread), #1 (a real read/write discipline around the library), #10 and #11 (the
combined-export dialog and progress).

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
| 22d | …then Playlist Export ▸ All tracks ▸ export ▸ the deleted id is sent and silently skipped; no playlist is written for it (`recommendations/playlist_exporter.py:137-139` — a seed missing from `meta_ix` is `continue`d before the write) | §2.7, §4 #14 |
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
| 34a | Reindex ▸ Cancel **while more than one track is still to be embedded** (timing A — at least one per-track checkpoint runs after the flag is set) ▸ the log pane contains **both** `⚠️ Cancellation requested...` and `⚠️ Cancellation detected, stopping...` — in either order, see §4 #18 — while `⚠️ Indexing cancelled by user`, `⚠️ Indexing cancelled` and `✅ Indexing completed successfully!` must **NOT** appear | §2.13, §4 #16, #18 |
| 34b | …the same run (timing A) ▸ an unhandled `KeyboardInterrupt` traceback appears on stderr, and **no** data files are written (pinned by `…::test_cancel_discards_every_embedding_computed_so_far`) | §2.13, §4 #4 |
| 34d | Reindex ▸ Cancel **after the last per-track checkpoint has passed** — during the final track's embed, or during the merge/write phase (timing B) ▸ the pipeline does **not** raise, no `⚠️ Cancellation detected, stopping...` appears, and the log pane ends with `⚠️ Indexing cancelled by user`. `✅ Indexing completed successfully!` is still absent | §2.13, §4 #16, #17 |
| 34e | …the same run (timing B) reaching `STATUS_INDEXED` ▸ all four data files **are** written and the on-disk index is updated, while the window shows the orange cancelled state and a `Close` button — no `Restart Required` prompt is offered | §2.13, §4 #17, #5 |
| 34f | Reindex ▸ Cancel an already-up-to-date library, at any moment (timing B via `STATUS_UP_TO_DATE`) ▸ `⚠️ Indexing cancelled by user` is appended and no data files are written (`processing/pipeline.py:169-170` returns before `save_index_data`; pinned by `…::test_a_cancel_during_an_up_to_date_run_is_never_observed`) | §2.13, §4 #17 |
| 34g | Reindex ▸ Cancel **during the last track of a run whose files are all missing or undecodable** (timing B via `STATUS_NO_EMBEDDINGS`) ▸ the pipeline does **not** raise, `❌ No new embeddings generated. Check audio paths/codecs.` is still logged, `⚠️ Indexing cancelled by user` is appended over what was a failure, and no data files are written (`processing/pipeline.py:219-221` returns before `save_index_data`; pinned by `…::test_a_late_cancel_on_the_no_embeddings_path_is_never_observed`) | §2.13, §4 #17 |
| 34c | Reindex ▸ let it finish ▸ the log pane ends with `🚀 Ready to use! …` then `✅ Indexing completed successfully!` | §2.13 |
| 35 | Reindex ▸ Done ▸ Restart Required dialog ▸ declining leaves the app running | §2.13 |
| 36 | Menu ▸ Library ▸ Update Library (Incremental) ▸ same reindex window | §2.3 |
| 37 | Tab switching ▸ status hint changes per tab | §2.2 |
| 38 | Onboarding (fresh data directory) ▸ welcome ▸ file ▸ confirm ▸ index ▸ Start Using | §2.1 |
| 39 | Onboarding ▸ all seven fake buttons respond to click and to hover, and none can be reached by Tab | §2.1, §3.5 |
| 40 | Settings ▸ open with an unreadable `meta.parquet` ▸ `Total Tracks: Loading...` **and** `Deleted Tracks: Loading...` remain on screen, and `Error loading statistics: …` is printed to stdout | §2.8, §4 |
| 41 | Set Creator ▸ generate a set larger than the candidates available ▸ unfillable rows read exactly `[ n] 🤖 No suitable track found – (Unknown Title)` | §2.5 |
| 42 | Playlist Export ▸ combined mode ▸ the progress bar stays at 0 % for the whole run and no completion dialog appears | §2.6, §4 #10, #11 |

---

## 6. Web UI coverage

PR 3a adds a second front end (`src/web/`, launched with
`python src/cosine_companion.py ui-web`) alongside the Tkinter app. Tkinter is
untouched, is still the default, and is what the packaged `.app` launches;
nothing in §1–§5 above describes behaviour that changed.

This section records **which catalogued controls the web UI reimplements**, so
the rewrite can be reviewed against the contract rather than against a demo.
It adds no claim about the Tkinter app. PR 3a implemented Explore; the small
write-surface follow-up adds only the Rekordbox XML path from Settings; the Set
Creator follow-up adds §2.5 and the §2.12 dialog it opens (§6.5, §6.6). Library
and Export still render a labelled placeholder, so §2.6 and §2.7 are entirely
outstanding.

The line numbers below are coordinates in this document.

### 6.1 Explore controls reimplemented

| Control | §2.4 line | How it appears in the web UI |
|---|---|---|
| `Set Current Track` | :326 | The ⌘K palette. Unlike `pick_current` it lists the first 50 tracks for a blank query rather than an empty list — see §6.3 |
| `← Back` | :325 | A button on the seed card, disabled until the history is non-empty, per §3.10 :1397 |
| History behaviour | :414-421 | Pushed only when a seed and a list both exist; capacity 20 (§3.9 :1387). Going back restores the stored list **in the order it was stored in**, with no recomputation, and re-renders honouring the **current** Top-N — the asymmetry :420-421 states. Pinned by `tests/web/test_frontend_behaviour.py::test_frontend_behaviour`, which runs `tests/web/js/explore_history.test.mjs` against the shipped module |
| `Set Selected as Current` | :328 | Clicking a recommendation row re-seeds |
| `<Double-Button-1>` re-seed | :347 | Folded into the single click above — the web list is a set of buttons, not a `tk.Listbox` |
| Sort buttons | :335, :377-387 | A segmented control with the same five keys and directions, including the ascending lexicographic Camelot sort at :381 |
| Sorts apply to all computed rows | :385-386 | Sorting runs over the full computed set before truncation |
| `Top:` combobox | :336-337 | A `<select>` offering the same six values, default 50 (§3.9 :1377) |
| Top-N does not recompute | :338 | Changing it re-renders only; verified in WKWebView to issue zero requests |
| Rendered row fields | :356-366 | Artist, title, Camelot key, BPM, cosine and score. The Camelot key is a coloured pill and the score is a bar plus its number |
| Score clamped, `Cos` not | :365-366 | Preserved exactly: `format.percentClamped` for score, `format.percent` for cosine |
| Computation parameters | :370, §3.9 :1378 | `topk=500, final_top=200`, passed explicitly rather than left to a default. Pinned by `tests/web/test_api_recommendations.py::test_the_explore_tab_configuration_is_used_by_default` |
| Full set retained, `topn` rendered | :372-373 | All 200 are fetched once and kept client-side |
| Current-track header | §3.2 :1211-1218 | The gradient seed card, carrying the same fields |
| `Copy Selected to Clipboard` | :327 | A `Copy` control on **each recommendation row**, which is the target :423-429 describes. The seed card also carries one; that is an addition rather than this control — see §6.3. The clipboard FORMAT still differs from Tkinter's on purpose, also §6.3 |
| Sort selection follows the list | :380 | A fresh computation arrives in cosine order — :380, "matches the post-refresh default order" — and the segmented control returns to `Cosine` to say so, matching `refresh_suggestions` replacing `current_recommendations` without reapplying the last sort |

### 6.2 Deferred to PR 3b

Everything catalogued under §2.4 that PR 3a does **not** reimplement, so the
omission is on the record rather than left for a reviewer to notice.

| Control | §2.4 line | Note |
|---|---|---|
| Right-click context menu | :348-354 | Both of its items exist as controls on the row itself — `Set as Current Track` is the row click, `Copy to Clipboard` is the row's `Copy` control (both pinned by `tests/web/js/explore_copy.test.mjs`). The **menu** itself, and the `listbox.nearest` selection it performs before opening, are outstanding |
| Status-bar message strings | :389-403 | The web UI shows a row count and a history count, not the catalogued strings, colours or the 3-second revert |
| `SimplePicker` and search implementation B | :405-412, §3.4 | The palette calls the service `search_tracks` (implementation A) over the API. The regex `.head(50)` variant and the modal picker are outstanding |
| `No match` dialog | :409 | The palette shows an inline empty state instead of a modal |
| Selection-error dialogs | :431-437 | `No Selection`, `No Recommendations` and `Invalid selection.` have no web equivalent; a row can only be clicked when it is rendered |
| Suggestions list as a `tk.Listbox` | :340-341 | The web list is a scrollable container of buttons; the mouse-wheel-only scrolling noted in §2.4 does not carry over |

Outside §2.4, the whole of §2.1, §2.3, §2.6, §2.7, §2.9, §2.10, §2.11 and
§2.13 are outstanding, and the two remaining placeholder destinations say so on
screen. §2.5 and §2.12 are covered by §6.5 and §6.6 below. Within §2.8, library
statistics, deleted-track management and both reindex actions remain
outstanding; this follow-up implements only reading and changing `xml_path`.

### 6.3 Deliberate divergences

Four places where PR 3a's Explore and Settings work does something different on
purpose. Each is a change of behaviour, not an omission, and is called out for
that reason. The Set Creator destination's divergences are listed with that
destination, in §6.6.

**Blank palette query.** `pick_current` (:407-408) and the two selector dialogs
open with an empty list for a blank query — §4 defect #9. The palette lists the
first 50 tracks instead, from a browse endpoint that does not go through
`search_tracks`. The service is unchanged and the characterisation of defect #9
still holds; this is a second surface answering the same question, pinned by
`tests/web/test_api_library.py::test_search_with_no_query_is_a_bad_request` and
its browse counterparts.

**Copy.** Two things differ, and an earlier version of this section recorded
only one of them.

*What it copies.* The Tkinter implementation (:423-429) splits the rendered row
at the first of six candidate separators and copies what follows, which yields
the title alone and truncates differently when a hyphen sits inside an artist
name. The web `Copy` puts `{artist} – {title}` on the clipboard, and omits the
separator entirely when either field is empty — this library really does hold
tracks with a blank artist. Workflow row 11 (:1464) describes the Tkinter
behaviour and still does.

*What it copies FROM.* :423-429 operates on the selected recommendation, and
the web control that answers it is the `Copy` on each recommendation row. The
seed card carries a second `Copy` that puts the **current track** on the
clipboard. That one is an ADDITION with no counterpart in §2.4, not a
reimplementation of :327, and it is recorded here rather than counted in §6.1
for that reason. Re-seeding to a row in order to copy it would not be
equivalent to either: it pushes to history and recomputes the list.

**Camelot keys are coloured.** §3.1 :1209 records that the key is displayed as
stored, with no conversion. That still holds — the pill's text is the stored
Camelot string. The web UI adds a hue derived from the wheel position on top of
it. Colour is never the only signal, because the pill always draws its own
text; all 24 pill variants are re-derived and checked against a 4.5:1 contrast
floor by
`tests/web/test_frontend_conventions.py::test_every_camelot_pill_is_readable`.

**Settings uses a path field, not a file picker.** The Tkinter window opens a
native picker and receives the selected file's absolute path. A browser file
input deliberately does not reveal that path, so using one would persist a
synthetic filename that the indexer cannot open. The web destination exposes an
explicit text field instead. Like §2.8, it does not require the file to exist,
and its API uses `SettingsStore.set` so `first_run_complete` is preserved. The
rest of §2.8 is deferred in §6.2.

### 6.4 What pins the web layer

**The HTTP surface, stated exactly.** Static assets still answer only `GET` and
`HEAD`; their `405` names `GET, HEAD`. Authenticated API requests additionally
answer `POST`, and an unsupported API method gets a JSON `405` naming `GET,
HEAD, POST`. There is no `PUT`, `PATCH`, `DELETE` or `OPTIONS` implementation.
Every method still enters through `_Handler.__getattr__` and `_dispatch`; POST
does not add a per-verb handler or a second authentication door.

`HEAD` remains implemented rather than tolerated: `_dispatch` routes it as the
`GET` it stands in for and only the content is dropped at the end of `_send`, so
a `HEAD` response carries the status, `Content-Type` and `Content-Length` its
`GET` would have carried — RFC 9110 sections 9.3.2 and 8.6. That is worth
writing down because the first round-2 implementation did only the second half:
the body was elided correctly while routing sent `HEAD` down the
unsupported-method branch. Pinned by
`tests/web/test_server_auth.py::test_head_returns_what_get_returns_minus_the_content`,
which asserts that parity across an API path and a static path in both a
success and a failure state.

**Why there is no Origin/CSRF gate.** The per-process token is an explicit
bearer credential held by the page's JavaScript and sent in `X-Coco-Token`; it
is not a cookie, client certificate or other credential a browser attaches
ambiently. A hostile page can submit a form to loopback, but it cannot supply
the unknown token. Supplying the custom header or an `application/json` body
cross-origin requires a CORS preflight, and this server grants no CORS access.
An Origin allow-list would therefore reject no request that has authority the
token did not already grant, while making non-browser clients invent a browser
header. The existing Host check remains useful DNS-rebinding defence in depth.

**POST bodies are bounded before parsing.** Authentication runs first. A
successful POST then requires exactly one `Content-Type` whose media type is
`application/json`, exactly one non-negative `Content-Length`, and at most
16 KiB. Wrong media types are 415, missing lengths 411, oversized bodies 413,
and malformed UTF-8/JSON or invalid lengths 400. Every failure uses the shared
JSON error shape, declares its byte length, and closes the connection when a
body may remain unread so it cannot desynchronise the next request.

**Transport errors are framed as well as JSON.** The request lines
`parse_request` rejects before any routing happens — a one-word line, an
invalid version, `HTTP/2.0` — were answered with a JSON body and no status
line in front of it. `BaseHTTPRequestHandler` suppresses the status line, the
headers and the blank line ending them while `request_version` holds the
`HTTP/0.9` sentinel, and `parse_request` installs that sentinel before it
reads anything, so every line it rejects on the way to a verdict is answered
while the suppression is still on. A real client does not read the result as a
response at all: `http.client` raises `BadStatusLine` and never sees the status
or the body. This is inherited stdlib behaviour rather than something this
branch introduced — `main@c5bf32e`, which has no `send_error` override,
returns an unframed **HTML** page for the same three request lines — but the
override's docstring claimed these were now JSON, which was half true and read
as wholly true. `_ensure_framable` (`src/web/server.py:321`) makes it wholly
true, on the one path every response takes. Pinned over **raw sockets** rather
than `http.client`, which is forgiving enough to hand back a body that never
had a status line, by
`tests/web/test_server_auth.py::test_a_rejected_request_line_still_gets_a_framed_json_response`.
No token is required to receive any of these, and that is correct: they happen
before a single header has been parsed, so there is no API request to protect.

The web UI still has no automated test of the **rendered** DOM: nothing here
lays out CSS, resolves a cascade or measures a pixel, so whether the result
looks right is settled by hand in WKWebView and the pass is recorded in the PR
description. What *is* automated, since the round-2 fixes, is frontend
**behaviour**: `tests/web/js/` imports the shipped modules and runs them under
`node --test` against the documented shim in `tests/web/js/dom_shim.mjs`,
driven from pytest by
`tests/web/test_frontend_behaviour.py::test_frontend_behaviour`. That
distinction is the whole of what those tests are worth — they can say what a
module did, not what a user saw — and it is stated at the top of the shim as
well as here.

The one environmental dependency in the web suite is `node`, for the JavaScript
suites. When it is absent they skip with a reason naming the file that did not
run. With node present the web suite gives **434 passed**; without it, **424
passed and 10 skipped** — one named skip per JavaScript file, and those ten
files are what `tests/web/test_frontend_behaviour.py` discovers. One of them,
`globals.test.mjs`, has the
shim itself as its subject rather than any shipped module — CI runs node 24,
where `globalThis.navigator` is a getter-only accessor the runtime owns, and
the shim's original plain assignment to it threw at import. Beyond that, no
web test reads `data/`: the
library each one sees is built under `tmp_path` by
`tests/web/webtest_support.py`, and it is what
`tests/web/test_api_library.py::test_library_reports_the_real_track_count`
counts.

A fresh-clone gate for the write-surface follow-up is recorded in its PR. It
installs only numpy, pandas, pyarrow, lxml and pytest: the API and server must
work without Essentia, TensorFlow, FAISS or a GUI toolkit. In that profile the
host module skips explicitly because pywebview is absent; no API or server test
may skip with it.

| Area | Pinned by |
|---|---|
| Token auth on every `/api/` path | `tests/web/test_server_auth.py::test_an_api_request_with_no_token_is_rejected` |
| Loopback binding and port release | `…::test_the_server_binds_loopback_and_nothing_else` |
| Static path traversal | `tests/web/test_static_assets.py::test_a_traversal_cannot_read_the_application_source` |
| NaN and numpy scalars leaving as JSON | `tests/web/test_json_sanitisation.py::test_every_flavour_of_missing_becomes_null` |
| The API layer staying free of a GUI toolkit | `tests/web/test_no_heavy_imports.py::test_only_host_may_import_webview` |
| The host not reaching Tkinter | `tests/web/test_host_importable.py::test_importing_the_host_does_not_load_tkinter` |
| Design tokens, focus rings, reduced motion, contrast | `tests/web/test_frontend_conventions.py::test_body_text_clears_the_contrast_floor` |
| Every HTTP method, defined or not, meeting the token check | `tests/web/test_server_auth.py::test_no_method_whatsoever_reaches_the_api_without_a_token` |
| POST auth running before body parsing | `…::test_an_unauthenticated_post_is_rejected_before_its_body_or_api` |
| POST body size and media-type limits | `…::test_an_oversized_body_is_rejected_before_it_is_read_or_dispatched`, `…::test_a_wrong_content_type_is_rejected_before_dispatch` |
| Malformed JSON returning a framed API error | `…::test_malformed_json_is_a_framed_400` |
| `HEAD` returning its `GET`'s status and `Content-Length` | `…::test_head_returns_what_get_returns_minus_the_content` |
| A `HEAD` response not desynchronising the next one on the same connection | `…::test_a_head_response_leaves_the_connection_synchronised` |
| Request lines the stdlib rejects still getting a status line | `…::test_a_rejected_request_line_still_gets_a_framed_json_response` |
| There being one auth entry point rather than one per verb | `…::test_no_verb_gets_its_own_handler_method` |
| The token check reaching `compare_digest` for wrong-length candidates | `…::test_every_wrong_token_is_decided_by_compare_digest` |
| Requests addressed to another host name | `…::test_a_request_addressed_to_another_name_is_refused` |
| The printed URL not carrying the token | `tests/web/test_host_importable.py::test_the_url_the_host_prints_does_not_carry_the_token` |
| `← Back` restoring the stored order under the current Top-N | `tests/web/test_frontend_behaviour.py::test_frontend_behaviour` (`explore_history.test.mjs`) |
| Copy acting on a recommendation without re-seeding | `…::test_frontend_behaviour` (`explore_copy.test.mjs`) |
| The palette never rendering a superseded query | `…::test_frontend_behaviour` (`palette_sequencing.test.mjs`) |
| `aria-modal` being backed by an inert shell and a Tab trap | `…::test_frontend_behaviour` (`palette_modality.test.mjs`) |
| Settings loading and submitting the edited XML path | `…::test_frontend_behaviour` (`settings.test.mjs`) |
| Settings preserving the onboarding flag | `tests/web/test_api_settings.py::test_post_settings_persists_immediately_and_preserves_onboarding` |
| Browse, search and recommendation caps actually binding | `tests/web/test_api_library.py::test_tracks_clamps_an_absurd_limit_rather_than_serialising_the_library` |

### 6.5 Set Creator controls reimplemented

§2.5 and the §2.12 dialog it opens. Line numbers are §2.5, §2.12 and §2.2
coordinates in this document.

| Control | line | How it appears in the web UI |
|---|---|---|
| `Total Tracks:` label and entry | :448-449 | A text field, default `"10"` held as a STRING so :501's "not an integer" check is still reachable. Pinned by `tests/web/js/set_creator.test.mjs` |
| `Generate Set` | :450 | The primary button. Disabled while a request is in flight |
| `Clear Set` | :451 | The button beside it. No confirmation, per :519 |
| `Anchor Tracks:` label | :454 | The anchor section heading |
| `+ Add Anchor` | :455 | Opens the §2.12 dialog. The macOS re-styling workaround at :456 has no web counterpart and is not one — §3.5, §4 #8 |
| Anchor listbox | :457 | A single-selection list, ascending by position |
| `Remove` | :458 | Removes the selected anchor, or warns (:523). The anchor list is a keyboard-operable listbox, or this control could be pressed and never satisfied without a mouse |
| `Generated Set:` label | :461 | The set section heading |
| Generated-set listbox | :462 | The generated rows |
| `Export to Clipboard` | :463 | The button below them |
| Anchor row format | :471 | `{position}. {artist} – {title}`, built unconditionally as `update_anchor_listbox` builds it (`src/ui/set_creator_tab.py:90`), so a blank artist keeps the leading separator |
| Ascending position order | :473 | Sorted numerically, not by the string the position renders as |
| Generated row fields | :479-489 | Position, icon, `display_name` and the match percentage, laid out as a row rather than padded into one string — see §6.6. `display_name` and `icon` are computed by `SetTrack` and sent over the wire, so the four-branch resolution order at :484-486 has exactly one implementation |
| Score suffix rule | :487-489 | ` ({score:.0%} match)` for non-anchors scoring above zero, and for nothing else. Anchors carry `score=1.0` and show none; the unfillable placeholder carries `0.0` and shows none. One condition, not two special cases |
| `:.0%` rounding | :488 | Reproduced exactly, including the tie rule: Python rounds a tie to EVEN and both JavaScript roundings do not, which differs on 96 of 21,215 sampled values. `format.wholePercent`, pinned by `tests/web/js/set_creator.test.mjs` |
| Unfillable slot row | :490-495 | Rendered from the placeholder's own fields, so it reads `No suitable track found – (Unknown Title)` with no score suffix. Pinned by `tests/web/test_api_set.py::test_an_unfillable_slot_arrives_with_the_fields_the_row_is_built_from` |
| The three pre-generation checks | :501-503 | Made in the catalogued order with the catalogued titles and bodies, as modal dialogs. The ORDER is pinned by cases that make two conditions wrong at once |
| `total == len(anchors)` is allowed | :505 | The check is `<`, and the web check is `<` |
| `Generation Error` | :506-508 | `Failed to generate set: {error}`, carrying the service's own `ValueError` text over the wire as `set_generation_failed`. Pinned by `tests/web/test_api_set.py::test_an_anchor_past_the_end_is_the_generation_error_inventory_names` |
| The four status strings | :510-514 | `🎵 Generating set... This may take a moment.`, `✅ Generated {n}-track set successfully!`, `❌ Set generation failed.` and `🧹 Set cleared.`, in a status line inside the destination |
| Set Creator status hint | :271 | The resting text of that status line, verbatim |
| The status bar staying visible | :244, :1293 | `packed side="bottom"` "so a short window cannot hide it" is a property of the control, so the web status line is sticky to the bottom of the scrolling viewport. Left in the flow it sat under the generated rows and was off screen at the moment it announced the set. Pinned by `tests/web/test_frontend_conventions.py::test_the_set_creator_status_line_cannot_be_scrolled_out_of_reach` |
| `Remove` with no selection | :523 | `No Selection` / `Please select an anchor track to remove.` |
| `Export to Clipboard` with no set | :529 | `No Set` / `Please generate a set first.` |
| Clipboard contents | :530-533 | One `display_name` per line, no positions, icons or scores, and every row whose display name contains `No suitable track found` left out. Then `Exported` / `Copied {n} tracks to clipboard!` |
| `AddAnchorDialog`, modal | :946 | A modal dialog whose `aria-modal` is backed by an inert shell and a Tab trap, as the palette's is |
| `Position in Set:` entry, blank | :948 | Blank by default. It is not pre-filled with the next free slot, because :966 says the dialog does not know the set's length |
| `Search for Track:` entry | :949 | Filters as you type, debounced 120 ms and sequenced by keystroke, as the palette is |
| Results list, single selection | :950 | Nothing is selected until a row is chosen, which is what keeps :961 reachable. Both web lists are operable from the keyboard - roving tabindex, arrows to move, Enter or Space to choose - because `role="option"` on an unfocusable row is a promise the row cannot keep |
| `<Double-Button-1>` = `Add to Set` | :951 | Double-clicking a row adds it |
| `Add to Set` / `Cancel`, Cancel rightmost | :952 | Both, in that visual order |
| Search implementation A, `limit=50` | :954 | `GET /api/tracks/search?limit=50`, which is `LibrarySession.search_tracks` — implementation A unchanged. What the ROWS render is **not** parity and is declared as a divergence in §6.6: a blank field is dropped, and the separator with it |
| The four dialog checks | :961-964 | In the catalogued order with the catalogued strings. `Position Taken` is a Yes/No question whose No returns to the dialog with the selection and the typed position intact |
| No upper bound on the position | :966 | The dialog accepts 9999 against a 10-track set; the builder is what refuses it, as :506-508 says |
| The same track at several positions | :967 | The dialog permits it. What GENERATION then does with it is not catalogued anywhere in §2.5 or §2.12 — see §6.6 |

**What pins it.**

| Area | Pinned by |
|---|---|
| The generated set matching committed golden sequences over the API | `tests/web/test_api_set.py::test_the_endpoint_returns_the_golden_sequence` |
| `display_name` and `icon` surviving serialisation | `…::test_the_two_computed_strings_survive_serialisation` |
| The set length cap being refused rather than clamped | `…::test_a_set_longer_than_the_cap_is_refused_rather_than_quietly_shortened` |
| A position below 1 being refused before it lands on the last slot | `…::test_position_zero_would_otherwise_land_on_the_last_slot` |
| `POST /api/set` needing the token like every other API path | `…::test_the_set_endpoint_needs_the_token_like_every_other_api_path` |
| The three pre-generation checks running in the catalogued order | `tests/web/test_frontend_behaviour.py::test_frontend_behaviour` (`set_creator.test.mjs`) |
| The four dialog checks running in the catalogued order | `…::test_frontend_behaviour` (`anchor_dialog.test.mjs`) |
| `Export to Clipboard` leaving the unfillable rows out | `…::test_frontend_behaviour` (`set_creator.test.mjs`) |
| A message box over the dialog making the DIALOG inert as well as the shell | `…::test_frontend_behaviour` (`anchor_dialog.test.mjs`) |
| The Set Creator destination no longer rendering a placeholder | `tests/web/test_frontend_conventions.py::test_the_set_creator_destination_is_no_longer_a_placeholder` |

### 6.6 Set Creator: deferred, divergent, and found along the way

**Deferred.** Everything catalogued under §2.5 or §2.12 that this follow-up does
not reimplement, so the omission is on the record.

| Control | line | Note |
|---|---|---|
| Widget geometry, fonts and colours | :448-463, :946-952 | `Helvetica 10 bold`, `bg="lightgreen"`, `height=4`, `height=15`, `width=5`, `padx=(0, 80)`, `500x500`. The web UI is built from the design tokens in `tokens.css`; the layout intent — a narrow numeric field, a short anchor list, a long set list, an affirmative primary button — is carried, the measurements are not |
| `+ Add Anchor` re-styling | :455-456, §2.2 | One of the ~350 lines of macOS Tk workarounds (§3.5, §4 #8). There is nothing to work around here |
| No scrollbar widgets on either listbox | :465-466 | Both web lists scroll normally, with a scrollbar. §2.7's table row is a Tk fact |
| An anchor row skipped when its `track_id` has left `meta_ix` | :473 | The web anchor carries the artist and title read from the library at the moment it was chosen, so there is no second lookup to fail. Not reachable in the web UI in this PR: nothing in it deletes a track. Workflow 22e (:1483) remains a Tkinter row |
| Parsing the position back out of the anchor row text | :524-525 | The web row keeps its position as data, so the split-on-first-`.` and its silently-ignored failure have nothing to do. Same observable behaviour |
| Window title `Add Anchor Track`, 500×500, resizable | :946 | The dialog is a panel in the page, not a window. The title is rendered as its heading |

**Divergences.** Each is a change of behaviour on purpose, not an omission.

*The blank query opens on a browse, not on nothing.* :955 records that the
dialog opens EMPTY, because search implementation A returns `[]` for a blank
query — §4 defect #9. The web dialog lists the first 50 tracks instead, from the
same browse endpoint the ⌘K palette uses and for the same reason (§6.3). The
service is untouched and the characterisation of defect #9 still holds.

*The generated row is a row, not a padded string.* :479 specifies
`[{position:2d}] {icon} {display_name}{score_text}`. The web row renders the
same four fields in columns: the position right-aligned in its own column, which
is what the two-character field buys on screen and which still reads at three
digits, then the icon, the name and the suffix. This is the same decision §6.1
records for the Explore row at :356-366. The clipboard, which is where the
string actually matters, is byte-for-byte :530-533.

*A set length has an upper bound.* :501-503 lists three checks and a maximum is
not among them, so the Tkinter tab will accept `100000` and freeze for as long
as it takes. `POST /api/set` refuses anything over `MAX_SET_TRACKS` (500, about
1.2 s of work at the measured ~2.3 ms per slot) with a 400 naming the cap. It is
refused rather than clamped, because a silently shortened set is not the set
that was asked for.

*A position below 1 is refused at the API as well as in the dialog.* :963 is a
dialog rule, and `generate_set` has no equivalent: it assigns
`set_slots[position - 1]`, so position `0` is Python's index `-1` and the anchor
silently becomes the LAST track of the set. The endpoint applies :963's rule at
the layer that can be reached without the dialog. Derivation pinned by
`tests/web/test_api_set.py::test_position_zero_would_otherwise_land_on_the_last_slot`.

*Enter submits the anchor dialog.* §2.12 catalogues no keyboard binding, so this
is an addition rather than a reimplementation of one.

*A blank field is dropped from the Add Anchor dialog's rows, and the separator
with it.* :954 says the rows render `{artist} – {title}`, and Tk builds that
string unconditionally: `search_tracks` composes it as `f"{artist} – {title}"`
(`recommendations/search.py:38`) and the dialog inserts the result as it stands
(`ui/dialogs.py:90`). A track whose artist is blank therefore opens its row with
a separator and nothing to the left of it. This dialog composes the row from the
fields the track actually has — `format.displayName`, the same helper the ⌘K
palette and the Explore rows already use — so that track reads as its title
alone.

This is not a corner case in this library. **69 of its 1,532 tracks carry an
artist of `''`** — 4.5 %, measured on the `data/meta.parquet` this branch was
developed against. `Skee Mask - Reviver` is one of them: the artist field is
empty and the artist's name is inside the title, which is why the missing left
half is not obvious on screen but the dangling separator is.

Two consequences worth stating rather than leaving to be discovered. The first
is that the SET CREATOR'S ANCHOR ROW does not follow: :471 catalogues
`{position}. {artist} – {title}` and `update_anchor_listbox` builds it
unconditionally (`ui/set_creator_tab.py:90`), that row is delivered as
catalogued, and so the same blank-artist track reads `Skee Mask - Reviver` in
the dialog and `1.  – Skee Mask - Reviver` once it is an anchor. Two renderings
of one track, a few centimetres apart. The second is that this is the same
decision §6.3 records for `Copy`, taken for the same reason and against the same
69 tracks; it is declared separately because it is a different control on a
different surface.

The rows the two implementations produce, which
`tests/web/js/anchor_dialog.test.mjs` reads out of this table rather than
restating in its assertions, and whose Tk column
`tests/web/test_anchor_row_contract.py` re-derives from
`recommendations/search.py` rather than trusting:

| artist | title | Tk's row (`recommendations/search.py:38`) | this dialog's row |
|---|---|---|---|
| `Blawan` | `Why They Hide` | `Blawan – Why They Hide` | `Blawan – Why They Hide` |
| | `Skee Mask - Reviver` | ` – Skee Mask - Reviver` | `Skee Mask - Reviver` |
| `Skee Mask` | | `Skee Mask – ` | `Skee Mask` |

*A generation in flight is abandoned when the configuration it was built from
stops being the one on screen.* The Tkinter tab cannot reach this: generation
runs on the Tk main thread behind `self.update()` (`ui/set_creator_tab.py:111`),
so the window takes no input for the duration and there is nothing to change
mid-build. The web destination stays live, which means `Clear Set`, `+ Add
Anchor`, `Remove` and `Total Tracks` are all operable while a set is being
built. A set is written only if `configurationKey()` — the anchors in position
order plus the length as it PARSES — still reads the same when the response
lands;
otherwise the response is dropped without a message, because the action that
changed the configuration has already had its say. `Generate Set` is disabled
for the duration of a build either way, so at most one is ever outstanding.
Pinned by the five cases in `tests/web/js/set_creator.test.mjs` that change
something WHILE the generation is in flight and answer it afterwards — two of
them positive controls that change the configuration and change it back — one by removing and re-adding the anchor, one by retyping the
same length as `030` and then in Arabic-Indic digits — where the response is
still valid and IS written.

*A failed regeneration keeps the set that is already on screen.* This is
Tkinter's behaviour and an earlier version of this destination diverged from it
silently. `generate_set_ui` assigns the RESULT of `build()` to
`self.generated_set` (`ui/set_creator_tab.py:113`), so a raise never reaches the
assignment and never reaches `update_set_listbox` either: the last good set
stays in the listbox behind the `Generation Error` dialog. The web destination
now leaves `generatedSet` alone on the failure path for the same reason — a
regenerate that fails should not cost the user the set they already had.

*An anchored track that is deleted from the library keeps its row here, and Tk
drops it.* :473 says an anchor is "skipped entirely if its `track_id` is no
longer in `meta_ix`", and that is what `update_anchor_listbox` does: it holds a
bare `Dict[int, str]` and looks the artist and title up at render time
(`ui/set_creator_tab.py:88-90`), so a row it cannot look up is not drawn. This
destination captures the artist and title from the search result the anchor was
chosen from, so nothing a delete does can reach the row. It therefore survives —
but it does not survive UNCHANGED: the next accepted build marks it, for the
reasons set out further down this section.

This PR shipped saying the case was unreachable, which is not true any more. The
sibling Library destination adds a reachable DELETE, and `delete_tracks`
(`services/library_session.py:183`) takes the row out of `meta_ix` for good; a
delete and a set build are two requests served off the Tk main thread rather
than two turns of one event loop, so a track can be anchored on this tab and
deleted on that one.

What GENERATION does is the same either way, and it is the part that matters:
the anchor is dropped. `generate_set` places one only `if track_id in
meta_ix.index` (`recommendations/set_generator.py:55`), so the slot is filled by
an ordinary generated pick and the set comes back one anchor short, with no
error and no message. The only thing the two implementations disagree about is
whether the anchor LIST still shows the row, and showing it is the more useful
of the two answers: a row on screen is a row that can be selected and `Remove`d,
where Tk's vanishes without a word and leaves the dead id in `self.anchors` to
be dropped again on every subsequent build.

**The row is MARKED, and the previous entry here was wrong about why it could
not be.** Round 2 declined to touch the stale row, on the stated grounds that
the drop could not be inferred from what comes back — that :967's duplicate
anchor "produces the identical shape — a requested position with no anchor on
it, for a track the library still has — so a frontend rule keyed on that shape
would remove the wrong row", and that telling them apart would need new response
surface.

That is false, and this document already contained the two facts that make it
false, four paragraphs apart. Probed against the real endpoint on the
twelve-track fixture, five tracks:

| request | response | the requested position |
| --- | --- | --- |
| duplicate `{1: f01, 4: f01}` | 4 tracks, positions `[1, 2, 3, 5]` | **absent** — de-duplication filters the assembled list, so the slot goes with the row (`set_generator.py:176-187`) |
| deleted `{1: f06, 4: f01}` | 5 tracks, positions `[1, 2, 3, 4, 5]` | **present**, `f02`, `is_anchor: false` — the anchor is dropped before placement (`set_generator.py:55`) and an ordinary pick fills the slot |

Two independent signals, both already in the response: the requested position is
absent for a duplicate and reassigned for a deletion, and the duplicated id is
still anchored at its surviving position where a deleted id is anchored nowhere.
`set-creator.js` keys on both, in that order. No new API field.

*The treatment: marked, not removed.* The row keeps its position and its name
and gains `⚠️ no longer in the library — this anchor was not used`, with
`data-dropped="true"` for the stylesheet. Removing it would take away the only
record of what the user had chosen and the `Remove` that clears it; leaving it
alone means a row asserting "this track is anchored at position 4" directly
above a set with an ordinary generated track at position 4, which is worse than
either. The note is in the row text, so it reaches a screen reader through the
option's accessible name rather than through colour alone. The mark is a
statement about the LAST accepted build: a build that honours the anchor again
clears it, and neither a failed build nor one the screen has moved on from sets
it, because neither carries information about what the library has.

Tk still differs, and the divergence is now smaller rather than larger: Tk drops
the row (:473) and this keeps it, marked.

*What pins it.* `tests/web/test_api_set.py::test_a_dropped_anchor_and_a_duplicate_anchor_are_different_response_shapes`
pins the premise against the real service — a change that renumbered the
duplicate's rows to close :967's gap turns it red — and five cases in
`tests/web/js/set_creator.test.mjs` pin the treatment, including the duplicate
answered in a shape the service does not currently produce, which is the only
case that reaches the second signal.

**Found along the way.** Two things the code does that §2.5 and §2.12 do not
say, reported rather than changed.

*The same track anchored twice loses the second anchor AND its slot.* :967 says
"The same track may be anchored at several positions", which is true of the
dialog — §2.12 has no such check — and says nothing about generation.
`generate_set` places both anchors, then its final de-duplication pass
(`src/recommendations/set_generator.py:176-187`) keeps only the first occurrence
of a repeated id. The dropped one takes its whole slot with it, because the pass
filters the assembled list rather than refilling the position. A five-track
request with the same track anchored at 1 and 4 therefore returns FOUR tracks
whose positions read 1, 2, 3, 5 — a visible gap in the rendered rows — plus
`⚠️  Warning: Duplicate tracks detected in generated set` on stdout, which no UI
shows. Pinned as current behaviour by
`tests/web/test_api_set.py::test_the_same_track_anchored_twice_loses_the_second_anchor_and_its_slot`.

**Known defect, declared here rather than fixed: the library can change under
an in-flight operation, and nothing notices.** One defect, two places it shows.
Neither is fixed in this PR, and both fixes belong to the same follow-up.

*Half 1 — `SetBuilder.build` does not capture the library atomically.*
`build` takes one `LibrarySession.snapshot()`, and `snapshot()`
(`services/library_session.py:149-166`) is itself six unlocked sequential
attribute reads; its own docstring says a delete landing between two of them can
be observed half-applied. `delete_tracks` rebinds `_meta_ix`, then `_emb_ix`,
then `_index` (`:202-224`), so the two run into each other from both directions.
Reproduced on the twelve-track fixture library, `{1: f01}` over five tracks:

| interleaving | result |
| --- | --- |
| delete lands between two of `snapshot()`'s reads — pre-delete `meta_ix`, post-delete `index` | the set changes silently, `['f01','f02','f03','f05','f04']` → `['f01','f02','f03','f12','f10']` |
| the reader lands inside `delete_tracks`, after the `meta_ix` rebind (`:202`) and before the index rebuild (`:220`) — post-delete `meta_ix`, pre-delete `index` | `KeyError: 'f05'` out of `SetBuilder.build` |

The second is the one that raises, and it is NOT the one a probe on
`snapshot()`'s own reads produces — it needs the reader interleaved into the
delete rather than the delete into the reader. Both are reachable for the same
reason: a delete and a build are two requests served off the Tk main thread
rather than two turns of one event loop.

Round 2 shipped a test named
`test_a_delete_between_the_property_reads_cannot_be_observed_half_applied`
asserting this was closed. It was not. The test patched the PUBLIC `meta_ix`
property and `snapshot()` reads the private attribute, so the delete never fired
and `fired == []` recorded only that the capture went through `snapshot()`. The
test is kept — the capture route is worth pinning — under a name that says so,
and `SetBuilder.build`'s docstring no longer claims the capture narrowed the
window from three reads to one. It never did: the previous code read the three
properties as three arguments of one call, which is already one window per
build. The per-seed-to-per-run reduction is `ExportService`'s alone.

*Half 2 — the Set Creator's `configurationKey()` does not capture the library.*
`configurationKey()` (`set-creator.js:154-186`) is a derived key over the
anchors and the parsed length. That covers every input of the REQUEST — `POST
/api/set` takes exactly those two fields (`web/api.py:325-339`) — and none of
the server state the answer also depends on. Refresh the Library destination
while a generation is outstanding and the anchors and the length are unchanged,
so the key compares EQUAL and a set built against a library that has since moved
on is accepted and rendered. A sequence counter would not have caught this
either: it is a missing INPUT, not a misplaced bump site.

It cannot be closed from the frontend as the API stands. `POST /api/set` returns
`{tracks: [...]}` with no library identity, and `GET /api/library` exposes
`track_count` but no revision — and a count is not a revision, since a delete
followed by a reindex restores it.

*The fix, for both halves: atomic publish in `LibrarySession`.* One immutable
snapshot object rebound as a unit, so a reader's single attribute read is atomic
by construction and the object it gets can carry the revision the response needs
to echo. This codebase has used that shape three times already — PR #15 (the
transitions vector cache, built privately and published by rebinding an
immutable tuple), PR #17 (`_Generation` + `MappingProxyType`) and PR #19
(generation files behind a manifest pointer). It is deliberately not in this PR:
it rewrites `delete_tracks`, which the sibling Library PR also rewrites, and a
core-services concurrency change deserves its own review rather than riding
inside a UI destination.

*The 2.76 s at :511-512 is no longer the number.* That figure was captured
before the transition-vector work. Measured on this branch against the same
`SetBuilder` the Tkinter tab calls, on the 1,532-track library: a 30-track set
takes **0.064 s**, a 100-track set 0.222 s and a 500-track set 1.154 s. The
sentence it sits in — that the window is unresponsive for the duration, because
generation runs on the Tk main thread behind `self.update()` — is unchanged and
still true; only the duration is different. This is why the web destination has
no progress stream and no cancellation: there is nothing to report.
