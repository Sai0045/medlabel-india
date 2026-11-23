"""Run questions against the included text PDF and its confirmed Indian leaflet."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from label_questions import answer_question, upload_passages, reference_passages, NOT_FOUND, REFUSE
from reference import lookup
from scan import scan


def main():
    sample = ROOT / "examples/pan40.pdf"
    pages = scan(sample.read_bytes(), sample.name)
    uploaded = upload_passages(pages)
    matching, _ = lookup(pages[0]["text"])
    leaflet = reference_passages("leaflet", matching[0])
    rows = []
    cases = [("uploaded PDF","What is the strength?",uploaded,"40 mg"),
             ("uploaded PDF","What is it used for?",uploaded,NOT_FOUND),
             ("confirmed leaflet","What is it used for?",leaflet,"acid reflux"),
             ("uploaded PDF","Does this contain aspirin?",uploaded,NOT_FOUND),
             ("uploaded PDF","How many tablets should I take?",uploaded,REFUSE)]
    for source,question,passages,expected in cases:
        answer,citation = answer_question(question,passages)
        passed = expected in answer and bool(citation) == (expected not in (NOT_FOUND,REFUSE))
        rows.append({"source":source,"question":question,"answer":answer,"citation":citation,"passed":passed})
    (ROOT/"evaluation/question_results.json").write_text(json.dumps(rows,indent=2)+"\n")
    print(f"{sum(r['passed'] for r in rows)}/{len(rows)} grounded-question checks passed")
    if not all(r["passed"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
