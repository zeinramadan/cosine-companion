#!/usr/bin/env python3
"""GUI smoke harness for Cosine Companion.

Drives the REAL Tkinter App against a COPY of data/, so destructive workflows
(track deletion) can be exercised without touching the read-only library. Tk
wiring is what unit tests cannot cover, so this walks the workflow checklist in
docs/UI_FEATURE_INVENTORY.md section 5 and prints a pass/fail table.

Usage:  PYTHONPATH=src python smoke.py [--only 4,5,6]
"""
import os, shutil, sys, tempfile, traceback
from pathlib import Path

REPO = Path(os.environ.get("COCO_REPO", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO / "src"))

# ---- point the app at a throwaway copy of the library -----------------------
TMP = Path(tempfile.mkdtemp(prefix="coco-smoke-"))
for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json",
             "deleted_tracks.json", "settings.json"):
    src = REPO / "data" / name
    if src.exists():
        shutil.copy2(src, TMP / name)

import core.deleted_tracks as deleted_tracks_module
deleted_tracks_module.DELETED_TRACKS_JSON = TMP / "deleted_tracks.json"

# Redirect the whole data directory BEFORE any ui module does
# `from config import DATA`, otherwise SettingsWindow.change_xml_path and
# friends write settings.json into the real, read-only data/.
import config
config.DATA = TMP

# Fingerprint the real data directory so the run can prove it never wrote to it.
REAL_DATA = REPO / "data"
BEFORE = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
          for p in sorted(REAL_DATA.iterdir()) if p.is_file()}

from services.library_session import LibrarySession
_orig_load = LibrarySession.load.__func__
LibrarySession.load = classmethod(
    lambda cls, data_dir=None: _orig_load(cls, TMP if data_dir is None else data_dir)
)

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog

RESULTS = []
CHECKS = []


def check(cid, name):
    def deco(fn):
        CHECKS.append((cid, name, fn))
        return fn
    return deco


class Scripted:
    """Records dialog calls and replays scripted answers."""
    def __init__(self):
        self.calls = []
        self.answers = {}

    def install(self, *modules):
        for mod in modules:
            for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
                if hasattr(mod, fn):
                    setattr(mod, fn, self._make(fn))

    def _make(self, fn):
        def handler(title=None, message=None, **kw):
            self.calls.append((fn, title, message))
            return self.answers.get(fn, True)
        return handler

    def last(self):
        return self.calls[-1] if self.calls else (None, None, None)

    def reset(self):
        self.calls.clear()


SCRIPT = Scripted()
import ui.app, ui.library_tab, ui.set_creator_tab, ui.playlist_export_tab
import ui.recommendations_tab, ui.dialogs, ui.track_selector_dialog, ui.settings_window
SCRIPT.install(ui.app.messagebox, ui.library_tab.messagebox, ui.set_creator_tab.messagebox,
               ui.playlist_export_tab.messagebox, ui.recommendations_tab.messagebox,
               ui.dialogs.messagebox, ui.track_selector_dialog.messagebox,
               ui.settings_window.messagebox, messagebox)

from ui.app import App

app = None


def pump(n=3):
    for _ in range(n):
        app.update_idletasks()
        app.update()


def rows(listbox):
    return [listbox.get(i) for i in range(listbox.size())]


# ---------------------------------------------------------------- workflows
@check(1, "Launch: window, title, tabs, initial hint")
def _():
    assert app.title() == "Cosine Companion - Explore your taste", app.title()
    tabs = [app.notebook.tab(i, "text") for i in range(len(app.notebook.tabs()))]
    assert tabs == ["Explore", "Set Creator", "Playlist Export", "Library"], tabs
    assert app.lbl_current.cget("text") == "Current track: —"
    assert app.library.track_count == 1307, app.library.track_count
    assert not hasattr(app, "idx") and not hasattr(app, "meta_ix")


@check(4, "Explore: Set Current Track -> SimplePicker -> suggestions render")
def _():
    real_picker = ui.recommendations_tab.SimplePicker
    simpledialog.askstring = lambda *a, **k: "boris"
    ui.recommendations_tab.simpledialog.askstring = lambda *a, **k: "boris"
    captured = {}

    class Picker(real_picker):
        def __init__(self, master, df):
            super().__init__(master, df)
            captured["rows"] = rows(self.winfo_children()[0])
            # Drive it the way a user would: let wait_window run its event loop,
            # then select and press Select from inside that loop.
            self.after(10, lambda: self._done((0,)))

    ui.recommendations_tab.SimplePicker = Picker
    try:
        app.pick_current()
        pump()
    finally:
        ui.recommendations_tab.SimplePicker = real_picker
    assert captured["rows"], "picker was empty"
    assert " – " in captured["rows"][0], captured["rows"][0]
    assert app.current_id is not None
    assert len(app.current_recommendations) == 200, len(app.current_recommendations)
    assert app.listbox.size() == 50, app.listbox.size()
    line = app.listbox.get(0)
    assert " – " in line and "[Key " in line and "Cos " in line and "Score " in line, line
    assert app.lbl_current.cget("text").startswith("Current track: ")
    assert "BPM)" in app.lbl_current.cget("text")


@check(5, "Explore: search with no match -> 'No match' dialog")
def _():
    SCRIPT.reset()
    ui.recommendations_tab.simpledialog.askstring = lambda *a, **k: "zzzz-no-such-track-zzzz"
    app.pick_current(); pump()
    assert SCRIPT.last()[:2] == ("showinfo", "No match"), SCRIPT.calls


@check(6, "Explore: double-click a suggestion -> becomes current, Back enables")
def _():
    before = app.current_id
    assert app.back_btn.cget("state") == "disabled"
    app.listbox.selection_clear(0, tk.END)
    app.listbox.selection_set(3)
    app.on_suggestion_double_click(None); pump()
    assert app.current_id != before
    assert app.back_btn.cget("state") == "normal"
    assert app.status.cget("fg") == "green"
    assert app.status.cget("text").startswith("✅ Set '")


@check(7, "Explore: Back restores the previous track and list")
def _():
    prev = app.history[-1]["track_id"]
    app.go_back(); pump()
    assert app.current_id == prev
    assert app.back_btn.cget("state") == "disabled"
    assert app.status.cget("fg") == "blue"
    assert app.status.cget("text").startswith("↩️ Went back to '")


@check(8, "Explore: all five sort buttons reorder")
def _():
    seen = {}
    for field in ("score", "cosine", "key", "bpm", "artist"):
        app.sort_suggestions(field); pump()
        seen[field] = rows(app.listbox)[:5]
        assert app.listbox.size() == 50
    assert len({tuple(v) for v in seen.values()}) > 1, "no sort changed the order"
    keys = [float(r.cosine) for r in app.current_recommendations]
    app.sort_suggestions("cosine")
    assert [float(r.cosine) for r in app.current_recommendations] == sorted(keys, reverse=True)


@check(9, "Explore: Top-N changes row count without recomputing")
def _():
    computed = len(app.current_recommendations)
    for n in ("10", "200", "50"):
        app.topn_var.set(n); app.update_listbox(); pump()
        assert app.listbox.size() == int(n), (n, app.listbox.size())
        assert len(app.current_recommendations) == computed


@check(10, "Explore: right-click context menu items")
def _():
    labels = [app.context_menu.entrycget(i, "label")
              for i in range(app.context_menu.index("end") + 1)
              if app.context_menu.type(i) != "separator"]
    assert labels == ["Set as Current Track", "Copy to Clipboard"], labels


@check(11, "Explore: Copy Selected to Clipboard copies the title")
def _():
    app.listbox.selection_clear(0, tk.END); app.listbox.selection_set(0)
    app.copy_selected(); pump()
    got = app.selection_get(selection="CLIPBOARD")
    assert got and got in app.listbox.get(0), (got, app.listbox.get(0))
    assert got == app.listbox.get(0).split("   [")[0].split(" – ", 1)[1].strip(), got


@check(12, "Set Creator: AddAnchorDialog search + position -> anchor listed")
def _():
    d = ui.dialogs.AddAnchorDialog(app, app.library.meta_ix, {})
    pump()
    assert rows(d.results_listbox) == [], "blank query should show nothing (defect #9)"
    d.search_var.set("boris"); d.on_search_change(); pump()
    assert rows(d.results_listbox), "search returned nothing"
    d.results_listbox.selection_set(0)
    d.position_var.set("3")
    d.add_selected()
    assert d.result and d.result[0] == 3, d.result
    app.anchor_tracks[d.result[0]] = d.result[1]
    app.update_anchor_listbox(); pump()
    assert rows(app.anchor_listbox)[0].startswith("3. "), rows(app.anchor_listbox)


@check(13, "Set Creator: Generate Set renders icons and match percentages")
def _():
    app.total_tracks_var.set("6")
    app.generate_set_ui(); pump()
    got = rows(app.set_listbox)
    assert len(got) == 6, got
    assert any("🔒" in r for r in got) and any("🤖" in r for r in got), got
    assert got[2].startswith("[ 3] 🔒"), got[2]
    assert any("match)" in r for r in got), got
    assert app.status.cget("text") == "✅ Generated 6-track set successfully!"


@check(14, "Set Creator: Remove deletes the selected anchor")
def _():
    app.anchor_listbox.selection_set(0)
    app.remove_anchor_track(); pump()
    assert app.anchor_tracks == {}, app.anchor_tracks
    assert rows(app.anchor_listbox) == []


@check(16, "Set Creator: Export to Clipboard reports the count")
def _():
    SCRIPT.reset()
    app.export_set(); pump()
    kind, title, msg = SCRIPT.last()
    assert (kind, title) == ("showinfo", "Exported"), SCRIPT.calls
    assert "tracks to clipboard" in msg, msg


@check(15, "Set Creator: Clear Set empties both lists")
def _():
    app.clear_set(); pump()
    assert rows(app.anchor_listbox) == [] and rows(app.set_listbox) == []
    assert app.status.cget("text") == "🧹 Set cleared."


@check(17, "Set Creator: Generate with no anchors -> warning")
def _():
    SCRIPT.reset()
    app.generate_set_ui(); pump()
    assert SCRIPT.last()[:2] == ("showwarning", "No Anchors"), SCRIPT.calls


@check(18, "Library: live filter + 'x of y' stats")
def _():
    app.notebook.select(3); pump()
    total = app.library_listbox.size()
    assert total == 1307, total
    assert app.library_stats_label.cget("text") == "1307 tracks"
    app.library_search_var.set("boris"); app.filter_library(); pump()
    n = app.library_listbox.size()
    assert 0 < n < total
    assert app.library_stats_label.cget("text") == f"{n} of {total} tracks"
    assert all("boris" in r.lower() for r in rows(app.library_listbox))


@check(19, "Library: Clear and Refresh restore the full list")
def _():
    app.clear_library_search(); pump()
    assert app.library_listbox.size() == 1307
    app.refresh_library(); pump()
    assert app.library_listbox.size() == 1307
    first = rows(app.library_listbox)[:3]
    assert first == sorted(first, key=lambda s: s.lower()), first


@check(20, "Library: double-click sets current and switches to Explore")
def _():
    app.library_listbox.selection_clear(0, tk.END)
    app.library_listbox.selection_set(5)
    app.on_library_double_click(None); pump()
    assert app.notebook.index(app.notebook.select()) == 0
    assert app.current_id is not None
    assert app.listbox.size() > 0


@check(21, "Library: Set as Current with no selection -> warning")
def _():
    SCRIPT.reset()
    app.notebook.select(3); pump()
    app.library_listbox.selection_clear(0, tk.END)
    app.set_library_selected_as_current(); pump()
    assert SCRIPT.last()[:2] == ("showwarning", "No Selection"), SCRIPT.calls


@check(22, "Library: Delete Selected removes the track and persists")
def _():
    import json
    SCRIPT.reset(); SCRIPT.answers["askyesno"] = True
    before = app.library.track_count
    app.library_listbox.selection_clear(0, tk.END)
    app.library_listbox.selection_set(0)
    victim = app.filtered_library_tracks[0]["track_id"]
    app.delete_selected_tracks(); pump()
    assert ("askyesno", "Confirm Deletion") == SCRIPT.calls[0][:2], SCRIPT.calls
    assert app.library.track_count == before - 1, (before, app.library.track_count)
    assert app.library_listbox.size() == before - 1
    assert app.status.cget("text") == "✅ Deleted 1 tracks from library"
    assert victim in json.loads((TMP / "deleted_tracks.json").read_text())
    assert len(LibrarySession.load().ids) == before - 1  # persisted to disk
    SCRIPT.answers.pop("askyesno", None)


@check(23, "Export: TrackSelectorDialog multi-select -> selection list + info label")
def _():
    app.notebook.select(2); pump()
    d = ui.track_selector_dialog.TrackSelectorDialog(app, app.library.meta_ix, set())
    pump()
    assert rows(d.results_listbox) == [], "blank query should show nothing (defect #9)"
    d.search_var.set("a"); d.on_search_change(); pump()
    assert len(rows(d.results_listbox)) == 50, len(rows(d.results_listbox))
    d.results_listbox.selection_set(0, 2)
    d.update_selection_count()
    assert d.selection_label.cget("text") == "3 tracks selected"
    d.add_selected()
    assert len(d.result) == 3, d.result
    app.export_selected_track_ids.update(d.result)
    app.update_selected_tracks_display(); pump()
    assert app.export_selected_listbox.size() == 3
    assert app.export_selection_info.cget("text").startswith("✓ 3 track(s) selected")
    assert app.export_selection_info.cget("fg") == "blue"


@check(24, "Export: Clear All -> orange warning label")
def _():
    app.clear_selected_tracks(); pump()
    assert app.export_selected_listbox.size() == 0
    assert app.export_selection_info.cget("text") == "⚠ No tracks selected. Click '+ Add Tracks' to select tracks"
    assert app.export_selection_info.cget("fg") == "orange"


@check(25, "Export: All-tracks radio shows the collection count")
def _():
    app.export_selection_var.set("all")
    app.on_export_selection_change(); pump()
    n = app.library.track_count
    assert app.export_selection_info.cget("text") == f"✓ Will generate playlists for all {n} tracks in your collection"
    app.export_selection_var.set("manual"); app.on_export_selection_change(); pump()


@check(29, "Export: Generate with nothing selected -> warning")
def _():
    SCRIPT.reset()
    app.export_selected_track_ids.clear()
    app.export_selection_var.set("manual")
    app.start_playlist_export(); pump()
    assert SCRIPT.last()[:2] == ("showwarning", "No Tracks Selected"), SCRIPT.calls


@check(26, "Export: Browse... sets the output directory")
def _():
    target = str(TMP / "playlists")
    ui.playlist_export_tab.filedialog.askdirectory = lambda **k: target
    app.browse_export_output(); pump()
    assert app.export_output_var.get() == target


def _run_export(start, deadline=300):
    """Run a threaded export under a REAL mainloop.

    The export worker calls self.after() from a background thread, and Tkinter
    only permits that while the main thread is actually inside mainloop() - not
    merely calling update(). That is how the app runs in production; it is only
    the harness that has to arrange it.
    """
    import time
    t0 = time.time()
    done = {"ok": False}

    def poll():
        if (str(app.export_btn.cget("state")) == "normal"
                and not app.export_progress_frame.winfo_ismapped()):
            done["ok"] = True
            app.quit()
            return
        if time.time() - t0 > deadline:
            app.quit()
            return
        app.after(50, poll)

    app.after(0, start)
    app.after(50, poll)
    app.mainloop()
    return done["ok"]


@check(27, "Export: separate mode writes files, shows progress and a completion dialog")
def _():
    out = TMP / "sep"
    SCRIPT.reset(); SCRIPT.answers["askyesno"] = True
    app.notebook.select(2); pump()
    app.export_selected_track_ids.clear()
    app.export_selected_track_ids.update(list(app.library.ids[:3]))
    app.export_selection_var.set("manual")
    app.update_selected_tracks_display(); pump()
    app.export_recs_var.set("10")
    app.export_format_var.set("separate")
    app.export_output_var.set(str(out))
    seen_progress = []
    real_progress = app.update_export_progress
    app.update_export_progress = lambda c, t, n: (seen_progress.append((c, t, n)), real_progress(c, t, n))[1]
    states = {}

    def start():
        app.start_playlist_export()
        states["after_start"] = str(app.export_btn.cget("state"))

    assert _run_export(start), "export did not finish"
    app.update_export_progress = real_progress
    assert states["after_start"] == "disabled", states

    kinds = [c[:2] for c in SCRIPT.calls]
    assert ("askyesno", "Confirm Export") in kinds, SCRIPT.calls
    assert ("showinfo", "Export Complete") in kinds, SCRIPT.calls
    body = [c[2] for c in SCRIPT.calls if c[1] == "Export Complete"][0]
    assert "Playlists created: 3" in body, body
    assert "File → Import → Playlist" in body
    files = sorted(out.glob("*.m3u"))
    assert len(files) == 3, files
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U\n#EXTINF:-1,")
    assert seen_progress and seen_progress[0][0] == 1 and seen_progress[-1][1] == 3
    SCRIPT.answers.pop("askyesno", None)


@check(28, "Export: combined mode writes one file and shows NO dialog (defect #10)")
def _():
    out = TMP / "comb"
    out.mkdir(exist_ok=True)
    SCRIPT.reset(); SCRIPT.answers["askyesno"] = True
    errors = []
    app.report_callback_exception = lambda exc, val, tb: errors.append((exc, val))
    app.export_format_var.set("combined")
    app.export_output_var.set(str(out))

    assert _run_export(app.start_playlist_export), "export did not finish"

    target = out / "Cosine_Recommendations.m3u"
    assert target.exists(), "combined playlist was not written"
    assert target.read_text(encoding="utf-8").startswith("#EXTM3U\n")
    assert ("showinfo", "Export Complete") not in [c[:2] for c in SCRIPT.calls], SCRIPT.calls
    assert errors and errors[0][0] is KeyError, errors
    assert "playlists_created" in str(errors[0][1]), errors
    assert str(app.export_btn.cget("state")) == "normal"
    app.export_format_var.set("separate")
    SCRIPT.answers.pop("askyesno", None)


@check(37, "Tab switching updates the status hint")
def _():
    expected = {0: "Choose a track to start", 1: "Click '+ Add Anchor'",
                2: "Click '+ Add Tracks'", 3: "Ctrl+Click to multi-select"}
    for i, frag in expected.items():
        app.notebook.select(i)
        app.set_default_status_hint(); pump()
        assert frag in app.status.cget("text"), (i, app.status.cget("text"))
        assert app.status.cget("fg") == "gray"


@check(3, "Menu: Help -> About dialog")
def _():
    SCRIPT.reset()
    app.show_about(); pump()
    kind, title, msg = SCRIPT.last()
    assert (kind, title) == ("showinfo", "About Cosine Companion"), SCRIPT.calls
    assert "Cosine Companion v1.0" in msg


@check(2, "Menu: File -> Settings window with real path and statistics")
def _():
    from config import DATA
    import services.settings_store as ss
    w = ui.settings_window.SettingsWindow(app)
    pump()
    assert w.title() == "Settings - Cosine Companion"
    assert w.tracks_label.cget("text").startswith("Total Tracks: "), w.tracks_label.cget("text")
    assert "," in w.tracks_label.cget("text") or w.tracks_label.cget("text").endswith("0")
    assert w.last_indexed_label.cget("text").startswith("Last Indexed: ")
    assert w.size_label.cget("text").endswith(" MB")
    assert w.deleted_tracks_label.cget("text").startswith("Deleted Tracks: ")
    xml = w.xml_path_label.cget("text")
    assert xml != "Not set" and xml.endswith(".xml"), xml
    w.destroy(); pump()


@check(31, "Settings: Manage Deleted Tracks lists the deleted track")
def _():
    d = ui.dialogs.DeletedTracksDialog(app)
    pump()
    assert d.listbox.size() >= 1, d.listbox.size()
    assert " – " in d.listbox.get(0), d.listbox.get(0)
    d.destroy(); pump()


@check(30, "Settings: Change XML path truncates the label and writes settings.json")
def _():
    import json
    from config import DATA
    long_path = "/Users/zein/very/deeply/nested/rekordbox/export/directory/collection-export-2026.xml"
    ui.settings_window.filedialog.askopenfilename = lambda **k: long_path
    SCRIPT.reset()
    w = ui.settings_window.SettingsWindow(app); pump()
    w.change_xml_path(); pump()
    shown = w.xml_path_label.cget("text")
    assert shown == "..." + long_path[-47:], shown
    assert len(shown) == 50, len(shown)
    assert str(w.xml_path_label.cget("fg")) == "black"
    assert SCRIPT.last()[:2] == ("showinfo", "XML Path Updated"), SCRIPT.calls
    written = json.loads((DATA / "settings.json").read_text())
    assert written["xml_path"] == long_path, written
    w.destroy(); pump()


@check(32, "Settings: Clear All deleted tracks confirms and reports")
def _():
    import json
    SCRIPT.reset(); SCRIPT.answers["askyesno"] = True
    w = ui.settings_window.SettingsWindow(app); pump()
    before = w.deleted_tracks_label.cget("text")
    assert before.startswith("Deleted Tracks: "), before
    w.clear_all_deleted_tracks(); pump()
    kinds = [c[:2] for c in SCRIPT.calls]
    assert ("askyesno", "Clear All Deleted Tracks") in kinds, SCRIPT.calls
    assert ("showinfo", "Deleted Tracks Cleared") in kinds, SCRIPT.calls
    assert json.loads((TMP / "deleted_tracks.json").read_text()) == {}
    assert w.deleted_tracks_label.cget("text") == "Deleted Tracks: 0"
    SCRIPT.answers.pop("askyesno", None)
    w.destroy(); pump()

    SCRIPT.reset()
    w2 = ui.settings_window.SettingsWindow(app); pump()
    w2.clear_all_deleted_tracks(); pump()
    assert SCRIPT.last()[:2] == ("showinfo", "No Deleted Tracks"), SCRIPT.calls
    w2.destroy(); pump()


@check(36, "Menu: Library -> Update Library opens ReindexWindow with the right mode")
def _():
    import ui.reindex_window as rwin
    real_start = rwin.ReindexWindow.start_indexing
    rwin.ReindexWindow.start_indexing = lambda self: None  # a real pass is covered by real_indexing.py
    opened = {}
    real_init = rwin.ReindexWindow.__init__

    def spy(self, parent, xml_path, force_full=False):
        real_init(self, parent, xml_path, force_full)
        opened["win"] = self
    rwin.ReindexWindow.__init__ = spy
    try:
        app.update_library(); pump()
        w = opened.get("win")
        assert w is not None, "ReindexWindow was not opened"
        assert w.title() == "Update Library - Cosine Companion", w.title()
        assert w.force_full is False
        assert str(w.xml_path).endswith(".xml"), w.xml_path
        header = [c.cget("text") for c in w.winfo_children() if isinstance(c, tk.Label)]
        assert "Checking for New Tracks" in header, header
        assert str(w.progress_bar.cget("mode")) == "indeterminate"
        assert [b.cget("text") for b in w.button_frame.winfo_children()] == ["Cancel"]
        w.destroy(); pump()
    finally:
        rwin.ReindexWindow.__init__ = real_init
        rwin.ReindexWindow.start_indexing = real_start


@check(33, "Settings: Update Library (Incremental) launches the reindex flow")
def _():
    import ui.reindex_window as rwin
    real_start = rwin.ReindexWindow.start_indexing
    rwin.ReindexWindow.start_indexing = lambda self: None
    opened = {}
    real_init = rwin.ReindexWindow.__init__

    def spy(self, parent, xml_path, force_full=False):
        real_init(self, parent, xml_path, force_full)
        opened["win"] = self
    rwin.ReindexWindow.__init__ = spy
    SCRIPT.reset()
    try:
        w = ui.settings_window.SettingsWindow(app); pump()
        w.update_library(); pump()
        # The configured path was rewritten by check 30 to a file that does not
        # exist, so this is the guarded "XML File Not Found" branch.
        if opened.get("win") is None:
            assert SCRIPT.last()[:2] == ("showerror", "XML File Not Found"), SCRIPT.calls
        else:
            assert opened["win"].force_full is False
            opened["win"].destroy(); pump()
    finally:
        rwin.ReindexWindow.__init__ = real_init
        rwin.ReindexWindow.start_indexing = real_start


@check(35, "Reindex: Done -> Restart Required dialog; declining just closes")
def _():
    import ui.reindex_window as rwin
    real_start = rwin.ReindexWindow.start_indexing
    rwin.ReindexWindow.start_indexing = lambda self: None
    SCRIPT.reset(); SCRIPT.answers["askyesno"] = False  # do NOT let it sys.exit(0)
    try:
        w = rwin.ReindexWindow(app, str(TMP / "nothing.xml"), force_full=False)
        pump()
        w.cancel_btn.destroy()
        w.show_completion(); pump()
        assert w.status_label.cget("text") == "✅ Library updated successfully!"
        assert str(w.status_label.cget("fg")) == "green"
        assert [b.cget("text") for b in w.button_frame.winfo_children()] == ["Done"]
        w.finish(); pump()
        kind, title, msg = SCRIPT.last()
        assert (kind, title) == ("askyesno", "Restart Required"), SCRIPT.calls
        assert "you should restart Cosine Companion" in msg, msg
        assert not w.winfo_exists()
    finally:
        SCRIPT.answers.pop("askyesno", None)
        rwin.ReindexWindow.start_indexing = real_start


@check(38, "Onboarding: welcome -> file -> confirm -> settings written")
def _():
    import json, tempfile
    import ui.onboarding as ob
    fresh = Path(tempfile.mkdtemp(prefix="coco-onboard-"))
    real_meta = ob.META_PQ
    ob.META_PQ = fresh / "meta.parquet"
    import config
    real_data = config.DATA
    config.DATA = fresh
    ob.filedialog.askopenfilename = lambda **k: str(TMP / "chosen.xml")
    (TMP / "chosen.xml").write_text("<x/>")
    real_start = ob.OnboardingWindow.start_indexing
    ob.OnboardingWindow.start_indexing = lambda self: None
    try:
        assert ob.needs_onboarding() is True, "fresh directory should need onboarding"
        w = ob.OnboardingWindow(app, lambda: None)
        pump()
        assert w.title() == "Welcome to Cosine Companion"
        labels = [c.cget("text") for c in w.winfo_children() if isinstance(c, tk.Label)]
        assert "🎵 Welcome to Cosine Companion" in labels, labels
        assert any("File → Export Collection in xml format" in l for l in labels), labels
        w.select_xml_file(); pump()          # screen 2 -> 3
        labels = [c.cget("text") for c in w.winfo_children() if isinstance(c, tk.Label)]
        assert "Ready to Index" in labels, labels
        assert w.xml_path == str(TMP / "chosen.xml")
        w.save_settings()
        written = json.loads((fresh / "settings.json").read_text())
        assert written == {"xml_path": str(TMP / "chosen.xml"), "first_run_complete": True}
        assert ob.needs_onboarding() is False, "first_run_complete should end onboarding"
        w.destroy(); pump()
    finally:
        ob.META_PQ = real_meta
        config.DATA = real_data
        ob.OnboardingWindow.start_indexing = real_start


def main():
    global app
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    import time
    t0 = time.time()
    app = App()
    startup = time.time() - t0
    pump(5)
    for cid, name, fn in CHECKS:
        if only and cid not in only:
            continue
        try:
            fn()
            RESULTS.append((cid, name, "PASS", ""))
        except Exception as e:
            RESULTS.append((cid, name, "FAIL", f"{type(e).__name__}: {e}"))
            traceback.print_exc()
    app.destroy()

    print("\n| # | Workflow | Result |")
    print("|---|---|---|")
    for cid, name, status, detail in sorted(RESULTS):
        mark = "PASS" if status == "PASS" else f"**FAIL** {detail}"
        print(f"| {cid} | {name} | {mark} |")
    failed = [r for r in RESULTS if r[2] != "PASS"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed. App() construction: {startup:.2f}s")

    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
             for p in sorted(REAL_DATA.iterdir()) if p.is_file()}
    touched = [n for n in set(BEFORE) | set(after) if BEFORE.get(n) != after.get(n)]
    if touched:
        print(f"!! REAL data/ WAS MODIFIED: {touched}")
        failed = failed or [("data", "read-only violation", "FAIL", "")]
    else:
        print(f"real data/ untouched ({len(BEFORE)} files verified by size+mtime)")
    print(f"scratch library: {TMP}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
