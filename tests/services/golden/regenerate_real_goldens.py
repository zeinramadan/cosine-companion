"""Deliberately recapture the real-library goldens and their fingerprint."""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "services"))

from config import DATA
from real_library_guard import fingerprint_ids
from services.library_session import LibrarySession
from services.set_builder import SetBuilder
from recommendations.ranking import ranked_recommendations

OUT = REPO / "tests" / "services" / "golden"
lib = LibrarySession.load(DATA)

if lib.track_count != len(lib.ids):
    raise ValueError(
        "cannot capture a real-library fingerprint: metadata has "
        f"{lib.track_count} tracks but ids.json has {len(lib.ids)}"
    )

SEEDS = ["64638770", "24614611", "36999061"]
FIELDS = ["track_id", "artist", "title", "bpm", "key", "cosine", "score", "key_score", "bpm_score"]

real = {"track_count": lib.track_count, "seeds": {}}
for seed in SEEDS:
    recs = ranked_recommendations(seed, lib.meta_ix, lib.emb_ix, lib.index, topk=500, final_top=200)
    real["seeds"][seed] = {
        "order": [r["track_id"] for r in recs],
        # Full precision for the head of the list; the whole 200-long id order
        # above is what catches a ranking change.
        "head": [
            {f: (float(r[f]) if isinstance(r[f], (int, float)) and f != "track_id" else r[f]) for f in FIELDS}
            for r in recs[:10]
        ],
    }

real["truncations"] = {}
for n in (1, 15, 25, 50, 200):
    recs = ranked_recommendations(SEEDS[0], lib.meta_ix, lib.emb_ix, lib.index, topk=500, final_top=n)
    real["truncations"][str(n)] = [r["track_id"] for r in recs]

real["limits"] = {}
for n in (10, 25):
    recs = ranked_recommendations(SEEDS[0], lib.meta_ix, lib.emb_ix, lib.index,
                                  topk=500, final_top=200, limit=n)
    real["limits"][str(n)] = [r["track_id"] for r in recs]

(OUT / "explore_real.json").write_text(json.dumps(real, indent=2, sort_keys=True) + "\n")

builder = SetBuilder(lib)
CASES = [
    {"name": "single_anchor_mid", "anchors": {3: SEEDS[0]}, "total": 6},
    {"name": "two_anchors", "anchors": {1: SEEDS[0], 5: SEEDS[1]}, "total": 8},
]
sets = {}
for case in CASES:
    got = builder.build(case["anchors"], case["total"])
    sets[case["name"]] = {
        "anchors": {str(k): v for k, v in case["anchors"].items()},
        "total": case["total"],
        "tracks": [
            {"position": t.position, "track_id": t.track_id, "is_anchor": t.is_anchor,
             "score": float(t.score), "artist": t.artist, "title": t.title,
             "display_name": t.display_name, "icon": t.icon}
            for t in got
        ],
    }
(OUT / "set_builder_real.json").write_text(json.dumps(sets, indent=2, sort_keys=True) + "\n")
(OUT / "real_library_fingerprint.json").write_text(
    json.dumps(fingerprint_ids(lib.ids), indent=2, sort_keys=True) + "\n"
)
print("real goldens written")
for f in sorted(OUT.glob("*real*.json")):
    print(" ", f.name, f.stat().st_size, "bytes")
