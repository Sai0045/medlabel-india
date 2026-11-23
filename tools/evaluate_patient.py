"""Run an image through OCR and replay questions against the patient and uploaded-file sources."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from label_patient import QUESTIONS, NO_USE
from label_questions import answer_question, upload_passages, reference_answer, NOT_FOUND
from label_rag import candidates, retrieve
from scan import scan

def main():
    fixture = ROOT/"examples/cetzine-10.png"
    pages = scan(fixture.read_bytes(),fixture.name)
    record = candidates(pages[0]["text"])[0]
    if record["source_id"] != "med_33942":
        raise ValueError("The fixture did not retrieve the expected product.")
    rows=[]
    def check(scope,q,expected,citation,observed):
        answer,source = observed
        rows.append(dict(scope=scope,question=q,expected=expected,answer=answer,source=source,
                         passed=expected in answer and (citation in source if source and citation else source is citation)))
    for topic,expected,citation in [("use","caused by allergies","GSK India"),("effects","Sleepiness","med_33942")]:
        q=QUESTIONS[topic]
        check(record["source_id"],q,expected,citation,reference_answer(q,"product",record,pages[0]["text"]))
    q="Does it help with a running nose?"
    check(record["source_id"],q,"caused by allergies","GSK India",reference_answer(q,"product",record))
    for topic in ("time","food","missed","pregnancy","alcohol","risks"):
        q=QUESTIONS[topic]
        check("med_1",q,"pharmacist",None,reference_answer(q,"product",retrieve(1)[0]))
    check("med_30",QUESTIONS["use"],NO_USE,None,reference_answer(QUESTIONS["use"],"product",retrieve(30)[0]))
    check("uploaded image",QUESTIONS["use"],NOT_FOUND,None,answer_question(QUESTIONS["use"],upload_passages(pages)))
    check("uploaded image","What is the strength?","10 mg","page 1",answer_question("What is the strength?",upload_passages(pages)))
    dest=ROOT/"evaluation/patient_results.json"
    dest.write_text(json.dumps(dict(fixture=fixture.name,read=pages,confirmed=record["source_id"],cases=rows),indent=2)+"\n")
    print(f"{sum(i['passed'] for i in rows)}/{len(rows)} patient and file questions passed")
    if not all(i["passed"] for i in rows):
        raise SystemExit(1)

if __name__=="__main__":
    main()
