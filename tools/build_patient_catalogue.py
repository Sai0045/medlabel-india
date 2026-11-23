"""Validate the patient CSV, JSONL and optional gzip mirror against the existing catalogue."""
import argparse
from collections import Counter
from contextlib import closing
import csv
import gzip
import hashlib
from itertools import groupby, zip_longest
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from label_patient import QUESTIONS, normal, official, ingredient_candidate
from label_rag import connection

COLUMNS = ["simple_indian_explanation", "when_to_take", "can_take_before_lunch", "missed_dose_advice",
           "pregnancy_breastfeeding_safety", "alcohol_interaction_warning", "common_side_effects", "severe_health_risks"]
IDENTITY = [("MedicineName","medicine_name","name"), ("Brand","brand","brand"),
            ("salt_composition","salt_composition","salt"), ("manufacturer","manufacturer","maker"), ("pack_size","pack_size","pack")]
# Simplify only a narrow affirmative phrase in a product-specific indication sentence.
# Each rule also requires the patient answer to contain the named symptom or use.
RULES = [
    (r"used to relieve pain and (?:to )?reduce fever", r"fever \(bukhar\)", "Helps relieve pain and reduce fever (bukhar)."),
    (r"used in the treatment of cough with mucus", r"mucus/phlegm", "Helps with a cough that brings up mucus (balgam)."),
    (r"used (?:in the treatment of|to treat) type 2 diabetes\b", r"lower high blood sugar", "Helps control blood sugar in people with type 2 diabetes."),
    (r"used (?:in the treatment of|to treat) hypertension \(high blood pressure\)", r"high blood pressure \(BP\)", "Helps lower high blood pressure (BP)."),
    (r"used (?:in the treatment of|to treat) fungal infections of the skin", r"fungal infections of the skin", "Treats certain fungal infections of the skin."),
    (r"used (?:in the treatment of|to treat) (?:gastroesophageal reflux disease \(acid reflux\)|acid reflux)", r"heartburn", "Helps with acid reflux, when stomach acid comes back up and causes heartburn."),
]
RULES = [(re.compile(old,re.I), re.compile(new,re.I), text) for old,new,text in RULES]
QA = re.compile(r"^• Q: (.+)\n  A: ([^\n]*)$", re.M)
SALT = re.compile(r"([^()]+?)\s*\(([^()]+)\)")

def digest(path, opener=open):
    with opener(path,"rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def validate(line, row, doc, product):
    md = doc["metadata"]
    if doc["id"] != md["id"] or doc["id"] != product["source_id"] or product["rowid"] != line:
        raise ValueError(f"Record ID mismatch at {line}")
    for col, key, prior in IDENTITY:
        if normal(row[col]) != normal(md[key]) or normal(row[col]) != normal(product[prior]):
            raise ValueError(f"Identity mismatch at {line} ({col})")
    pairs = QA.findall(doc["text"])
    if pairs != list(zip(QUESTIONS.values(),(row[k] for k in COLUMNS))):
        raise ValueError(f"Patient questions or answers disagree at {line}")
    value = row["quantity_of_content"]
    if value != md["quantity_of_content"]:
        raise ValueError(f"Ingredient breakdown mismatch at {line}")
    parts = [SALT.fullmatch(x.strip()) for x in row["salt_composition"].split("+")]
    if all(parts):
        expected = " | ".join(f"{m[1].strip()}: {m[2].strip()}" for m in parts)
        if normal(expected).casefold() == normal(value).casefold():
            return normal(value)

def eligible(row, passages):
    for old, new, text in RULES:
        patient = new.search(row["simple_indian_explanation"])
        if not patient:
            continue
        for sentence in passages:
            if (old.search(sentence) and not re.search(r"\b(?:not|only|except|after|before|severe|mild|moderate|adults?|children|other medicines|along with|who|when used)\b",sentence,re.I)):
                return text, patient.group(), sentence
    return None, None, None

def build(csv_path,jsonl_path,mirror,out):
    inputs = {p.name:digest(p) for p in (csv_path,jsonl_path)}
    if mirror:
        if digest(mirror,gzip.open) != inputs[jsonl_path.name]:
            raise ValueError("Gzip mirror differs from the JSONL.")
        inputs[mirror.name] = digest(mirror)
    out.mkdir(parents=True,exist_ok=True)
    counts = Counter()
    dictionary = {}
    with tempfile.TemporaryDirectory(dir=out) as temp:
        dest = Path(temp)/"patient.sqlite"
        with closing(connection()) as old, closing(sqlite3.connect(dest)) as db:
            db.executescript("""CREATE TABLE patient(id INTEGER PRIMARY KEY, composition INTEGER, plain_use TEXT,
                                patient_quote TEXT, evidence TEXT, effects TEXT, ingredient TEXT);
                                CREATE TABLE composition(id INTEGER PRIMARY KEY, value TEXT UNIQUE);""")
            groups = groupby(old.execute("SELECT * FROM passage ORDER BY product_id, rowid"),key=lambda p:p["product_id"])
            group_id, group = next(groups,(None,()))
            with csv_path.open(newline="",encoding="utf-8-sig") as fc, jsonl_path.open(encoding="utf-8-sig") as fj:
                for line, (row, raw, product) in enumerate(zip_longest(csv.DictReader(fc), fj, old.execute("SELECT * FROM product ORDER BY rowid")),1):
                    if row is None or raw is None or product is None:
                        raise ValueError(f"Different record counts at row {line}")
                    comp = validate(line,row,json.loads(raw),product)
                    chunks = []
                    if line == group_id:
                        chunks = list(group)
                        group_id, group = next(groups,(None,()))
                    use, quote, evidence = eligible(row, [p["excerpt"] for p in chunks if p["kind"]=="use"])
                    effects = next((p["excerpt"] for p in chunks if p["kind"]=="effects" and p["excerpt"]==row["common_side_effects"]
                                    and not re.search(r"depending on individual patient sensitivity|not (available|known)|no (common|known)|individual response",p["excerpt"],re.I)),None)
                    if effects:
                        effects = ", ".join(x.strip() for x in effects.split(",") if x.strip())
                    if comp and comp not in dictionary:
                        dictionary[comp] = len(dictionary)+1
                        db.execute("INSERT INTO composition VALUES (?,?)",(dictionary[comp],comp))
                    ingredient = ingredient_candidate(product, row["simple_indian_explanation"])
                    db.execute("INSERT INTO patient VALUES (?,?,?,?,?,?,?)",(line,dictionary.get(comp),use,quote,evidence,effects,ingredient))
                    counts.update(records=1, checked_questions=len(QUESTIONS), ingredient_breakdowns=int(bool(comp)),
                                  simplified_uses=int(bool(use)), official_product_uses=int(bool(official(product))), eligible_effect_lists=int(bool(effects)), printed_ingredient_candidates=int(bool(ingredient)))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Patient index failed SQLite integrity check.")
        manifest = {"inputs":inputs,"counts":counts,"questions":QUESTIONS,"database_sha256":digest(dest)}
        dest.replace(out/"patient.sqlite")
        (out/"patient_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(counts), flush=True)

if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv",type=Path); p.add_argument("jsonl",type=Path); p.add_argument("--gzip-mirror",type=Path)
    p.add_argument("--output",type=Path,default=ROOT/"catalogue")
    args=p.parse_args()
    build(args.csv,args.jsonl,args.gzip_mirror,args.output)
