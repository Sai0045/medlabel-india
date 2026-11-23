"""Retrieve printed product names with FTS5, then read only the confirmed product's passages."""
import atexit
from contextlib import closing
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unicodedata

ROOT = Path(__file__).resolve().parent
STOP = set("tablet tablets tab tabs capsule capsules cap caps strip box medicine medicines syrup injection solution oral contains each ip bp usp coated mg mcg ml gm g manufacturer batch expiry date manufactured by for store of in and with the a sodium hydrochloride film pack".split())
VARIANTS = set("sr er xr cr mr dt ds forte plus duo cv iv d a o me od xt mf cold m advance kid kids junior lc ls af dx dm fx dmr".split())
FORMS = {"tablet", "capsule", "injection", "syrup", "cream", "ointment", "gel", "drops", "suspension"}
AMOUNT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mcg|mg|gm|ml|g|%)(?![a-z])",re.I)
_cache_lock = threading.Lock()


def words(text):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


def tokens(text):
    return words(re.sub(r"(\d)(?=mcg\b|mg\b|ml\b|gm\b)", r"\1 ", text, flags=re.I))


@lru_cache(maxsize=1)
def index_file():
    folder = ROOT / "catalogue"
    manifest = json.loads((folder / "manifest.json").read_text())
    tmp = tempfile.TemporaryDirectory(prefix="medlabel-reference-")
    atexit.register(tmp.cleanup)
    destination = Path(tmp.name) / "catalogue.sqlite"
    with destination.open("xb") as out:
        for item in manifest["parts"]:
            compressed = (folder / item["file"]).read_bytes()
            if hashlib.sha256(compressed).hexdigest() != item["sha256"]:
                raise RuntimeError("Medicine catalogue integrity check failed.")
            out.write(gzip.decompress(compressed))
    with destination.open("rb") as src:
        if hashlib.file_digest(src, "sha256").hexdigest() != manifest["database_sha256"]:
            raise RuntimeError("Medicine index integrity check failed.")
    return destination


def connection():
    with _cache_lock:
        path = index_file()
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    return db


def amount_set(text):
    return {(float(number),unit.lower()) for number,unit in AMOUNT.findall(text)}


def ingredient_lines_agree(lines, title, salt):
    salt_words = set(tokens(salt))
    fillers = STOP | {"composition", "ingredient", "ingredients", "active", "equivalent", "to", "provides", "strength", "w", "v"}
    for line in lines:
        parts = tokens(line)
        if not parts or not amount_set(line):
            continue
        # Check words immediately before each printed amount on a separate composition line.
        for field in re.split(r"[+,;]", line):
            match = AMOUNT.search(field)
            if not match:
                continue
            names = {w for w in tokens(field[:match.start()]) if w.isalpha()} - fillers
            if title[0] in parts:
                names -= set(title) | {"rx", "brand", "name", "tm"}
            if names and not names <= salt_words:
                return False
    return True


def candidates(text):
    raw_lines = [line.strip() for line in text[:8000].splitlines() if line.strip()][:80]
    lines = []
    for line in raw_lines:
        parts = tokens(line)
        while parts and parts[0] in {"rx", "brand", "name", "tm"}:
            parts = parts[1:]
        lines.append(parts)
    keywords = list(dict.fromkeys(w for line in lines for w in line if w not in STOP and not w.isdecimal() and len(w)>1))[:35]
    if not lines:
        return []
    query = " OR ".join(f'"{word}"' for word in keywords)
    starts = {line[0] for line in lines if line}
    with closing(connection()) as db:
        hits = list(db.execute("""SELECT p.*, bm25(search,4,1) AS rank FROM search JOIN product p ON p.rowid=search.rowid
                                  WHERE search MATCH ? ORDER BY rank LIMIT 180""", (query,))) if query else []
        for line in raw_lines[:30]:
            hits.extend(db.execute("SELECT *, 0 AS rank FROM product WHERE title_key=? LIMIT 40", (" ".join(words(line)),)))
        heading_brand = None
        for line in lines:
            if not line or line[0] in STOP:
                continue
            if db.execute("SELECT 1 FROM product WHERE brand_key=? LIMIT 1", (line[0],)).fetchone():
                heading_brand = line[0]
            break
    label_words = set(word for line in lines for word in line)
    printed_forms = {w.rstrip("s") if w != "drops" else w for w in label_words} & FORMS
    printed_amounts = amount_set("\n".join(raw_lines))
    ranked = {}
    for row in hits:
        title = tokens(row["name"])
        if not title or title[0] not in starts or row["rowid"] in ranked:
            continue
        if heading_brand and title[0] != heading_brand:
            continue
        brand_lines = [line for line in lines if line and line[0] == title[0]]
        brand_words = set(word for line in brand_lines for word in line)
        name_words = set(title)
        product_forms = {w.rstrip("s") if w != "drops" else w for w in name_words} & FORMS
        if printed_forms and product_forms and printed_forms.isdisjoint(product_forms):
            continue
        distinctive = {w for w in name_words - STOP if w.isalpha() and w not in FORMS}
        if distinctive - label_words:
            continue
        if (brand_words & VARIANTS) - name_words:
            continue
        numbers = {w for w in brand_words if w.isdecimal()}
        ref_numbers = set(re.findall(r"\d+", row["name"] + " " + row["salt"]))
        if numbers - ref_numbers:
            continue
        ref_amounts = amount_set(row["name"] + " " + row["salt"])
        if printed_amounts and ref_amounts and not printed_amounts <= ref_amounts:
            continue
        if not ingredient_lines_agree(raw_lines, title, row["salt"]):
            continue
        # A short heading can omit the form. A different modifier after the brand denotes another pack.
        meaningful = name_words - STOP
        exact = any(line == title for line in lines)
        overlap = len(meaningful & label_words) / max(1, len(meaningful))
        score = (exact, overlap, len(meaningful & label_words), -row["rank"])
        ranked[row["rowid"]] = (score, dict(row))
    eligible = sorted(ranked.values(), key=lambda v: v[0], reverse=True)
    if eligible and eligible[0][0][0]:
        eligible = [hit for hit in eligible if hit[0][0]]
    return [row for _, row in eligible[:12]]


def retrieve(product_id):
    with closing(connection()) as db:
        product = db.execute("SELECT * FROM product WHERE rowid=?", (product_id,)).fetchone()
        if product is None:
            raise ValueError("The selected medicine is missing.")
        passages = db.execute("SELECT kind,excerpt FROM passage WHERE product_id=? ORDER BY rowid", (product_id,)).fetchall()
    return dict(product), [dict(p) for p in passages]


def explanation(product_id, printed=""):
    from label_generator import choose
    from label_patient import patient_details
    record, chunks = retrieve(product_id)
    patient = patient_details(record, chunks, printed)
    # For a cross-checked simplification, retrieve the original product sentence for the model.
    # Display its reviewed plain-language equivalent after the source check.
    context = patient["evidence"] if patient["quote"] and not patient["url"] else patient["use"]
    uses = [context] if context else []
    selected, mode = choose(record["name"], uses) if uses else (None, "No eligible use passage")
    use = patient["use"] if selected else None
    if selected and selected != use:
        mode += " · displayed in plain language"
    passages = list(chunks)
    if uses and not any(p["excerpt"] == use for p in passages):
        passages.append({"kind":"use", "excerpt":use, "source":patient["use_source"]})
    return {"product":record, "use":use, "effects":patient["effects"], "passages":passages,
            "mode":mode, "model_context":uses, "patient":patient}
