"""Read product-scoped patient evidence. All clinical text is local and rendered literally."""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
QUESTIONS = {
    "use": "What is this medicine commonly used for in India?",
    "time": "When should I take this medicine?",
    "food": "Can I take this medicine before lunch or on an empty stomach?",
    "missed": "What should I do if I miss a dose?",
    "pregnancy": "Can pregnant or breastfeeding women take this medicine?",
    "alcohol": "Can I drink alcohol while taking this medicine?",
    "effects": "What are the common side effects?",
    "risks": "What are the severe health risks, warnings, and interactions?",
}
GUIDANCE = {
    "time": "Check the directions on your prescription or ask your pharmacist when to take this exact medicine.",
    "food": "Meal instructions vary by medicine. Check your pack leaflet or ask your pharmacist about food.",
    "missed": "Missed-dose instructions vary. Check your pack leaflet or call your pharmacist for advice about your missed dose.",
    "pregnancy": "A doctor or pharmacist can check this medicine for your stage of pregnancy or breastfeeding.",
    "alcohol": "Ask a pharmacist to check this exact medicine before drinking alcohol.",
    "risks": "A pharmacist can check the warnings for this pack against your allergies and other medicines.",
}
NO_USE = "We could not confirm what this exact pack is used for. Check its leaflet or ask a pharmacist."
NO_EFFECTS = "We could not confirm a side-effect list for this exact pack."
CETIRIZINE = "Cetirizine helps relieve sneezing and a runny nose caused by allergies."
INDIA_CETIRIZINE = "https://india-pharma.gsk.com/media/kdbnpjsp/cetzine-tablet-and-cetzine-suspension.pdf#page=1"
# Each entry is an explicit product name and complete recorded composition. Never match a variant by prefix.
LEAFLETS = {
    ("Cetzine Tablet", "Cetirizine (10mg)"): (CETIRIZINE, "GSK India · Cetzine tablet, therapeutic indications", INDIA_CETIRIZINE),
    ("Augmentin 625 Duo Tablet", "Amoxycillin (500mg) + Clavulanic Acid (125mg)"): (
        "An antibiotic for certain infections caused by bacteria, including some ear and sinus infections.",
        "GSK India · Augmentin Duo, section 4.1", "https://india-pharma.gsk.com/media/3wpapw52/augmentin-duo-tablets.pdf#page=2"),
    ("Allegra 120mg Tablet", "Fexofenadine (120mg)"): (
        "Helps ease sneezing and a runny nose caused by allergies.", "Sanofi India · Allegra, indications",
        "https://www.sanofi.com/assets/countries/india/docs/consumer-healthcare/for-healthcare-professionals/products-information/allegra-api.pdf"),
    ("Allegra-M Tablet", "Montelukast (10mg) + Fexofenadine (120mg)"): (
        "Helps adults with a nose allergy that causes sneezing or a runny nose.", "Sanofi India · Allegra-M, indications",
        "https://www.sanofi.com/assets/countries/india/docs/consumer-healthcare/for-healthcare-professionals/products-information/allegra-m-api-6-2-25.pdf"),
}

BP_SOURCE = "https://cdn.who.int/media/docs/default-source/india-news/india-hypertension-control-initiative/cvh-hpertension-india.pdf"
INGREDIENT_GUIDES = {
    "Cetirizine": ({"10"}, "sneezing", CETIRIZINE, "GSK India · oral cetirizine, indications", INDIA_CETIRIZINE),
    "Paracetamol": ({"500","650"}, "fever", "Paracetamol helps relieve pain and reduce fever (bukhar).", "Crocin India · oral paracetamol, indications",
                    "https://www.crocin.com/content/dam/cf-consumer-healthcare/panadol/en_in/documents/Crocin%20650.pdf"),
    "Telmisartan": ({"40","80"}, "high blood pressure", "Telmisartan helps lower high blood pressure (BP).", "India Hypertension Control Initiative · treatment protocol", BP_SOURCE),
    "Amlodipine": ({"5","10"}, "high blood pressure", "Amlodipine helps lower high blood pressure (BP).", "India Hypertension Control Initiative · treatment protocol", BP_SOURCE),
}

def ingredient_candidate(record, patient_answer):
    # Limit the scope to named single-ingredient standard tablets. Suffixes such as -D and multiple strengths are ineligible.
    if not re.fullmatch(r"[A-Za-z]+(?: \d+(?:mg)?)? Tablets?",record["name"],re.I):
        return None
    for name, (strengths, cue, *_) in INGREDIENT_GUIDES.items():
        salt = re.fullmatch(re.escape(name) + r"\s*\((\d+)\s*mg\)",record["salt"],re.I)
        if salt and salt[1] in strengths and cue in patient_answer.casefold():
            return name
    return None

def printed_ingredient(record, name, printed):
    if not name:
        return False
    strength = re.search(r"\d+",record["salt"])[0]
    # Require the active ingredient and its own strength together, as well as tablet form.
    return (re.search(r"\btablets?\b", printed, re.I)
            and re.search(r"\b"+re.escape(name)+r"(?: hydrochloride)?(?: i\.?p\.?)?\s*[:(-]?\s*"+strength+r"\s*mg\b",printed,re.I))

def normal(value):
    return " ".join(value.split())

def official(record):
    return LEAFLETS.get((record["name"], normal(record["salt"])))

def informative(text):
    if not text or re.search(r"pharmaceutical formulation|clinical indications matching|depending on individual patient sensitivity|^.+ belongs to a (group|class)|^it works by|^it does (not|this)", text, re.I):
        return False
    return bool(re.search(r"\b(?:used (?:for|to|in)|treat(?:s|ment)?|relie(?:f|ves?)|helps (?:to |your body |the body )?(?:fight|control|prevent|reduce|lower)|prevents?)\b",text,re.I))

@lru_cache(maxsize=1)
def patient_index():
    path = ROOT / "catalogue/patient.sqlite"
    meta = json.loads((ROOT / "catalogue/patient_manifest.json").read_text())
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != meta["database_sha256"]:
            raise RuntimeError("The patient reference failed its integrity check.")
    return path.as_uri() + "?mode=ro&immutable=1"

def patient_details(record, chunks, printed=''):
    with closing(sqlite3.connect(patient_index(), uri=True)) as db:
        row = db.execute("""SELECT c.value, p.plain_use, p.patient_quote, p.evidence, p.effects, p.ingredient
                             FROM patient p LEFT JOIN composition c ON c.id=p.composition
                             WHERE p.id=?""", (record["rowid"],)).fetchone()
    if row is None:
        raise ValueError("The patient reference is missing the confirmed product.")
    composition, use, quote, evidence, effects, ingredient = row
    source = f"Patient Q&A · {record['source_id']} · JSONL line {record['rowid']} · CSV data row {record['rowid']}"
    label = official(record)
    if label:
        use, authority, url = label
    else:
        authority, url = None, None
    ingredient_only = False
    if not label and not use and printed_ingredient(record, ingredient, printed):
        _, _, use, authority, url = INGREDIENT_GUIDES[ingredient]
        ingredient_only = True
    if not use:
        evidence = next((p["excerpt"] for p in chunks if p["kind"]=="use" and informative(p["excerpt"])), None)
        use = evidence
    use_source = authority or (source + " + same-product catalogue description" if quote else f"Indian medicine catalogue · {record['source_id']}")
    return dict(use=use, source=source, use_source=use_source, url=url, quote=quote, evidence=evidence,
                effects=effects, composition=composition, ingredient_only=ingredient_only)

def faq_answer(topic, details):
    if topic == "use":
        return (details["use"], details["use_source"]) if details["use"] else (NO_USE, None)
    if topic == "effects":
        return (details["effects"], details["source"]) if details["effects"] else (NO_EFFECTS, None)
    return GUIDANCE[topic], None
