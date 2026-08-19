# PR 4 — Rekordbox playlist lookup (track → playlists)

**Branch:** `feat/playlist-lookup` · **Base:** `main@37d5a4b`
**Spec:** `docs/superpowers/specs/2026-08-18-ui-rewrite-and-playlist-lookup-design.md` §6
**Contract:** `docs/UI_FEATURE_INVENTORY.md` (this PR ADDS a surface; it has no Tkinter counterpart)

---

## 0. Why this PR lands now, ahead of PR 3b

The original sequencing put the playlist lookup last because it "depends on the new UI".
Half of that dependency is already satisfied and the other half turns out not to exist:

- `src/web/static/js/components/drawer.js:5` already documents that `track.playlists`
  "comes back explicitly null" because "there is no playlist endpoint yet", and
  `:13` renders a `PLAYLIST_PLACEHOLDER`. **The drawer contract is already carved out.**
- This feature is **read-only at the HTTP layer**. `docs/UI_FEATURE_INVENTORY.md` §6.4
  states the server answers `GET` and `HEAD` only. Nothing in this plan changes that.

PR 3b (Library, Set Creator, Export, onboarding, reindex, settings) needs a *write*
surface — `POST`/`DELETE`, mutation safety, long-running jobs. That is a different and
larger problem. This PR deliberately does not touch it.

---

## 1. Scope

**In:** parsing `<PLAYLISTS>`, persisting two tables plus provenance, a `PlaylistService`,
one API field, the drawer section, a CLI import command, tests.

**Out, and each must be stated in the PR description rather than silently omitted:**

- Any HTTP method other than `GET`/`HEAD`. The "re-import now" **button** belongs to PR 3b;
  this PR surfaces the staleness *prompt* as a banner that tells the user which command to run.
- Browsing by playlist. §2 of the spec locks **track → playlists only**; there is no
  playlist list screen, no playlist detail screen, no fifth destination.
- Any change to `src/ui/` (Tkinter). It stays exactly as it is.
- Any change to embeddings, the index, or `meta.parquet`.

---

## 2. Hard constraints

1. **`src/ui/` diff must be empty.** Verify with `git diff --stat main -- src/ui/`.
2. **Existing tests must not be edited to accommodate this work.** `git diff main -- tests/`
   must show additions and new files only, no modified assertions in pre-existing files.
   If a pre-existing test genuinely must change, stop and report why instead.
3. **`meta.parquet`, `embeddings.parquet`, `index.npy`, `ids.json` must not be written**
   by any code path this PR adds. The spec (§6.2) is explicit that membership is two
   separate tables precisely because `meta.parquet` is rewritten wholesale elsewhere and
   would clobber it.
4. **Never write to `/Users/zein/dj-cosine/data`.** This worktree has its own copy at
   `<worktree>/data`. Every test and every manual run must use the worktree copy or a
   `tmp_path`. Before you finish, confirm the real directory's mtimes are untouched.
5. **No new runtime dependency.** `lxml` and `pandas`/`pyarrow` are already present.

---

## 3. Task 1 — Parse the `<PLAYLISTS>` half of the XML

`src/processing/xml_parser.py:26` already parses the whole tree and reads only
`//COLLECTION/TRACK`. Add playlist parsing **without changing the existing collection
parse in any observable way** — its output is load-bearing for the index.

**Deliverable:** a function that, given an XML path, returns the playlist tree and the
membership pairs. Put it where it reads naturally (a new `src/processing/playlist_parser.py`
is acceptable and probably cleaner than growing `xml_parser.py`); if you extend
`xml_parser.py` instead, the existing `parse_collection` output must remain byte-identical.

**Structure, measured on `data/library_export_190826.xml` (spec §6.3):**

| Property | Value |
|---|---|
| `<NODE Type="1">` playlists | 141 |
| `<NODE Type="0">` folders | 14, plus a single root node literally named `ROOT` |
| `KeyType` | `"0"` on all 141 — membership is by TrackID, never by path |
| Membership entries | 4,669 |
| Max display depth | 4 segments (5 including `ROOT`) |
| Duplicate leaf names | **36** |
| Empty playlists | 0 |
| `Entries` attribute vs actual `<TRACK>` children | 0 mismatches |

**Three requirements that come directly from those measurements:**

- **Strip the `ROOT` segment.** It is Rekordbox's container, not a folder the user made.
  It must never reach the UI.
- **`folder_path` is a LIST of segments, not a joined string.** One of your folders is
  literally named `Collections/Hauls`, so ` / ` is ambiguous as a separator. Persisting a
  pre-joined string loses information irrecoverably.
- **Recursion must be genuinely recursive.** Depth 4 exists today; do not hard-code a depth.

**Tests:** build fixture XMLs. At minimum — nesting to depth 4; a folder whose *name*
contains `/`; two playlists sharing a leaf name under different parents; an empty playlist
(none exist in the real export, so this state is only reachable via fixture); a playlist
with `KeyType="1"`; a `<TRACK Key>` referencing an ID absent from the collection.
Assert the parse against the real export too, but guard that assertion the same way
`tests/services/golden/` guards its real-library tests — the export is gitignored and must
skip, not fail, when absent.

---

## 4. Task 2 — Persist the tables plus provenance

**`playlists.parquet`** — `playlist_id`, `name`, `folder_path`, `parent_id`, `entries`
**`playlist_membership.parquet`** — `track_id`, `playlist_id`

`playlist_id` is ours to mint (Rekordbox does not give playlists IDs); make it stable and
deterministic for the same XML so re-importing an unchanged file is a no-op. State in a
docstring what you chose and why.

**Provenance is a first-class requirement, not a nicety.** Persist `source_xml` (absolute
path), `imported_at`, and enough to detect staleness — the XML's mtime and size, or a
digest. Prefer the cheapest check that cannot produce a false "fresh". State the choice.

`track_id` in the membership table must be the same string type as `meta.parquet`'s
`track_id` — the join is exact-string. Assert this rather than trusting it: the whole
feature is worthless if the dtypes drift.

---

## 5. Task 3 — CLI import

`src/cosine_companion.py` already exposes subcommands. Add one that imports playlists from
the configured (or explicitly passed) XML **without re-running the 12-minute embedding
pipeline**. The user has just spent 11m33s indexing; making them do it again to see
playlists would be an unforced insult.

Also call the same import from the existing indexing pipeline so a normal reindex keeps
playlists current — but the standalone command must exist and must be what the staleness
banner names.

**Import summary must report, not hide, the unresolvable entries.** Measured: **514 of
4,669 entries (11.01%)** reference Rekordbox tracks CoCo has not indexed, because the
export holds 1,610 tracks against CoCo's 1,532 indexed. Per spec §6.5 this is reported as
*"N entries reference tracks not in your library — reindex to include them"*, **not** as an
error. Silently dropping 11% would make playlist counts quietly wrong.

---

## 6. Task 4 — `PlaylistService`

`src/services/playlist_service.py`, following the six existing services exactly:

- **Zero UI imports.** `tests/services/test_no_ui_imports.py` (or its equivalent) already
  enforces this by AST walk for `src/services/`; make sure the new module is covered.
- **No module-level heavy imports.** PR #8 blocker 0 was every service transitively
  importing Essentia. `pandas`/`pyarrow` are fine; anything from `processing` that reaches
  `essentia` must be imported lazily inside the function that needs it. Prove it: importing
  this service in a venv with only `numpy pandas pyarrow lxml pytest` must succeed.
- Loads the two tables once, builds the **reverse index** `track_id → [playlist…]`, and
  answers a lookup for one track. Mean 3.18 playlists per track, **max 21**.
- Exposes provenance and a staleness verdict. The service reports *whether* the XML on disk
  differs from what was imported; it never imports on its own. Spec §6.4: **prompt, never
  auto-import.**
- Degrades rather than crashes when the tables are absent (nothing imported yet) or when
  `source_xml` no longer exists on disk (spec §6.5).

**Return a typed result, not a bare dict** — the other services use dataclasses; match them.
Each returned playlist carries at least its name, its `folder_path` segment list, and its
total entry count.

---

## 7. Task 5 — API

`src/web/api.py` currently exposes six `GET` routes and `_detail(track_id)` builds the
drawer payload. `drawer.js` already expects `track.playlists` and currently receives `null`.

**Populate `track.playlists`.** Prefer filling the existing field on the existing detail
response over adding a route, since the drawer already fetches it — but if a separate
`GET /api/tracks/{track_id}/playlists` reads better, that is acceptable. Whichever you pick,
say why in the PR description.

**Constraints:**

- `null` must keep meaning "no playlist data imported", distinct from `[]` meaning "imported,
  and this track is in zero playlists". The drawer renders these differently. Note that on
  the current export **every indexed track is in at least one playlist**, so the `[]` state
  is unreachable with real data and must be covered by a fixture.
- Provenance and the staleness verdict must reach the client. Do **not** leak the absolute
  XML path if a basename plus the import date is enough for the UI; the spec's example is
  "from `242.xml`, imported 12 Aug". Decide and state it.
- The API must still boot and answer when no playlist tables exist at all. `GET /api/health`
  must not depend on playlist data.
- Do not reorder or restructure `ROUTES`, `handle`, or `src/web/server.py`'s dispatch. A
  parallel PR (`feat/web-write-surface`) is adding the write surface to those exact
  functions. Additive changes only; keep your diff there as small as it can be.

---

## 8. Task 6 — The drawer

Replace `PLAYLIST_PLACEHOLDER` in `src/web/static/js/components/drawer.js`.

**Render the full path, not the leaf name.** 36 leaf names are duplicated; showing bare
names would present the user two identical rows with no way to tell them apart. Show
`Mischief / Collections-Hauls / biscuit (funk) / hard 1hr`. Join the segment list in the UI
— which is exactly why §4 persists a list.

**Handle 21 items gracefully.** That is the real maximum (`Fireground — Never Sleep`). The
drawer must not assume a handful. Whether that means scrolling, truncation with a count, or
a denser row is a design call — make it, and match the design system already in
`tokens.css`/`app.css` rather than introducing new colours or spacing values.

**States to cover, all of which are reachable:**

| State | Behaviour |
|---|---|
| Not imported | Import call-to-action naming the CLI command |
| Imported, in N playlists | The list, longest paths intact, plus the count |
| Imported, in 0 playlists | "In 0 playlists" — fixture-only, unreachable with real data |
| XML changed since import | Provenance line **plus** a re-import prompt naming the command |
| Recorded `source_xml` missing from disk | Provenance plus a note; must not crash |

**No `innerHTML`.** PR 3a's review confirmed everything goes through `textContent`; playlist
names are user data from an external file and are exactly the kind of string that would
carry an injection. Keep that property and let the existing convention test prove it.

---

## 9. Verification — all of it, before you open the PR

1. `python -m pytest -q` in the dev env. Report collected/passed. The baseline on
   `main@37d5a4b` is **647 passed, 25 skipped**.
2. **Fresh clone gate.** Clone the repo to a temp dir, check out this branch, create a venv
   with only `numpy pandas pyarrow lxml "pytest>=7.0"`, run the suite. This is the gate that
   caught two false greens on this project — a test that silently skips reads as a test that
   passes. Report passed/skipped and confirm the skip count is what you expect.
3. Confirm `essentia`, `tensorflow` and `faiss` are **not installed** in that venv and the
   API still imports and answers.
4. `git diff --stat main -- src/ui/` — must be empty.
5. Launch the web UI against the worktree's data, open a track's drawer, and confirm the
   playlists actually render. Report what you saw, including a track with many playlists.
6. Push and confirm **real GitHub Actions** is green — not just your local run.
7. Confirm `/Users/zein/dj-cosine/data` mtimes are unchanged.

**Then open the PR** with `gh` (auth is configured). The description must list, explicitly:
what §6 of the spec you did not implement, the API shape you chose and why, the
`playlist_id` minting scheme, the staleness check you chose, and the unresolvable-entry
count you measured.

---

## 10. Notes on judgement

- If this plan contradicts the code, **the code wins** — report the contradiction rather
  than following the plan into a bug. Previous PRs on this project found three plan errors
  each and were right to deviate.
- Do not "fix" unrelated defects you notice. `docs/UI_FEATURE_INVENTORY.md` §4 catalogues
  known current behaviour deliberately. Report them; do not fold them in.
- If any claim in this plan turns out false when you measure it, say so with the measurement.
  Several numbers here were re-measured once already when the export changed.
