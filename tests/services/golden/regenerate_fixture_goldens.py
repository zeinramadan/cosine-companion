"""Generate the committed golden files. Run once; the output is reviewed and committed."""
import json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "services"))

from fixture_library import FIXTURE_TRACKS, GOLDEN_SEEDS, write_fixture_library
from services.library_session import LibrarySession
from services.set_builder import SetBuilder
from recommendations.ranking import ranked_recommendations

OUT = REPO / "tests" / "services" / "golden"
OUT.mkdir(exist_ok=True)

tmp = Path(tempfile.mkdtemp(prefix="golden-"))
data = write_fixture_library(tmp / "data", audio_dir=tmp / "audio")
lib = LibrarySession.load(data)

FIELDS = ["track_id", "artist", "title", "bpm", "key", "cosine", "score", "key_score", "bpm_score"]

def rows(recs):
    return [{f: (r[f] if not isinstance(r[f], float) else float(r[f])) for f in FIELDS} for r in recs]

# --- explore ---------------------------------------------------------------
explore = {"seeds": {}, "truncations": {}}
for seed in GOLDEN_SEEDS:
    recs = ranked_recommendations(seed, lib.meta_ix, lib.emb_ix, lib.index, topk=500, final_top=200)
    explore["seeds"][seed] = rows(recs)

# truncation: final_top applied BEFORE the cosine re-sort, so a smaller
# final_top is NOT a prefix of the larger one. Capture that exactly.
for n in (1, 3, 5, 11):
    recs = ranked_recommendations(GOLDEN_SEEDS[0], lib.meta_ix, lib.emb_ix, lib.index, topk=500, final_top=n)
    explore["truncations"][str(n)] = [r["track_id"] for r in recs]

# the exporter's extra limit= truncation, applied AFTER the re-sort
explore["limits"] = {}
for n in (1, 3, 5):
    recs = ranked_recommendations(GOLDEN_SEEDS[0], lib.meta_ix, lib.emb_ix, lib.index,
                                  topk=500, final_top=200, limit=n)
    explore["limits"][str(n)] = [r["track_id"] for r in recs]

(OUT / "explore_fixture.json").write_text(json.dumps(explore, indent=2, sort_keys=True) + "\n")

# --- set builder -----------------------------------------------------------
builder = SetBuilder(lib)
SET_CASES = [
    {"name": "single_anchor_mid", "anchors": {3: "f01"}, "total": 6, "exclude": None},
    {"name": "two_anchors", "anchors": {1: "f01", 5: "f06"}, "total": 8, "exclude": None},
    {"name": "anchor_first", "anchors": {1: "f10"}, "total": 4, "exclude": None},
    {"name": "unfillable", "anchors": {1: "f01"}, "total": 4,
     "exclude": [t[0] for t in FIXTURE_TRACKS if t[0] != "f01"]},
]
sets = {}
for case in SET_CASES:
    got = builder.build(case["anchors"], case["total"], exclude_tracks=case["exclude"])
    sets[case["name"]] = {
        "anchors": {str(k): v for k, v in case["anchors"].items()},
        "total": case["total"],
        "exclude": case["exclude"],
        "tracks": [
            {"position": t.position, "track_id": t.track_id, "is_anchor": t.is_anchor,
             "score": float(t.score), "artist": t.artist, "title": t.title,
             "display_name": t.display_name, "icon": t.icon}
            for t in got
        ],
    }
(OUT / "set_builder_fixture.json").write_text(json.dumps(sets, indent=2, sort_keys=True) + "\n")

# --- export ----------------------------------------------------------------
from recommendations.playlist_exporter import playlist_filename
export = {"per_seed": {}, "combined": {}}
for per_track in (2, 5):
    per_seed = {}
    for seed in GOLDEN_SEEDS:
        track = lib.meta_ix.loc[seed]
        recs = ranked_recommendations(seed, lib.meta_ix, lib.emb_ix, lib.index,
                                      topk=500, final_top=200, limit=per_track)
        per_seed[playlist_filename(track["artist"], track["title"])] = [r["track_id"] for r in recs]
    export["per_seed"][str(per_track)] = per_seed

    seen, combined = set(), []
    for seed in GOLDEN_SEEDS:
        recs = ranked_recommendations(seed, lib.meta_ix, lib.emb_ix, lib.index,
                                      topk=500, final_top=200, limit=per_track)
        for r in recs:
            if r["track_id"] not in seen:
                seen.add(r["track_id"]); combined.append(r["track_id"])
    export["combined"][str(per_track)] = combined
(OUT / "export_fixture.json").write_text(json.dumps(export, indent=2, sort_keys=True) + "\n")

print("fixture goldens written")
for f in sorted(OUT.glob("*.json")):
    print(" ", f.name, f.stat().st_size, "bytes")
