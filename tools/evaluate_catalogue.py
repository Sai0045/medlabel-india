"""Replay deterministic exact titles, shortened labels and negative controls. No patient files."""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from label_rag import candidates, connection, explanation


def main():
    with closing(connection()) as db:
        rows = list(db.execute("SELECT rowid,source_id,name,salt FROM product WHERE rowid%3503=1 ORDER BY rowid"))
    cases = []
    totals = Counter()
    for row in rows:
        name = row["name"]
        for kind, label in (("full_heading", name), ("short_heading", " ".join(name.split()[:-1]) or name)):
            found = candidates(label)
            result_ids = [p["source_id"] for p in found]
            rank = result_ids.index(row["source_id"])+1 if row["source_id"] in result_ids else None
            totals[kind+"_n"] += 1
            totals[kind+"_top1"] += rank == 1
            totals[kind+"_top5"] += rank is not None and rank <= 5
            cases.append({"kind":kind, "query":label, "expected":row["source_id"], "rank":rank, "top5":result_ids[:5]})
    controls = {}
    for query, blocked in [("Dolo 650\nParacetamol 500 mg","med_58235"), ("Dolo 650\nParacetamol 650 mcg","med_58235"),
                           ("Dolo 650\nIbuprofen 650 mg","med_58235"), ("Azithral 500 Injection","med_2"), ("Unlistedxyz 91 Tablet",None)]:
        hits = [p["source_id"] for p in candidates(query)]
        controls[query] = {"returned":hits,"passed":blocked not in hits if blocked else not hits}
    withheld = explanation(601)
    controls["Arpimune record without an identity-matched use"] = {"passed":withheld["use"] is None and withheld["effects"] is None}
    output = {"scope":"Every 3503rd supplied row starting at 1. Full or shortened typed titles. Source row ID is the expected result. Duplicate names can have different IDs. These are catalogue checks, not OCR or clinical accuracy.",
              "totals":totals,"controls":controls,"cases":cases}
    dest = ROOT/"evaluation"/"catalogue_results.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(output, indent=2)+"\n")
    print(dict(totals))
    print("Negative controls passed:", sum(case["passed"] for case in controls.values()), "of",len(controls))
    if not all(case["passed"] for case in controls.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
