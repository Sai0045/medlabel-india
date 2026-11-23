"""Question-specific retrieval over one upload or one confirmed record. No private text is cached."""
from dataclasses import dataclass
import re
import unicodedata

from label_generator import normalized, predict_question
from label_rag import retrieve
from label_patient import QUESTIONS, faq_answer, patient_details, CETIRIZINE


@dataclass(frozen=True)
class Passage:
    text: str
    source: str
    field: str = ""


# Question expressions and corresponding evidence cues. A requested field must exist in the selected source.
FIELDS = {
    "strength": (r"strength|how strong|milligrams?|how (?:much|many) mg|ingredient|composition|contains?|made of|salt|active substance",
                 r"ingredients?|composition|contains?|\d\s*(?:mg|mcg|g|ml|%)\b"),
    "maker": (r"who (?:made|makes|produces|manufactures|manufactured)|manufacturer|company|made by|manufactured by|maker",
              r"manufactur|marketed by|made by|mfg[.]? by|company"),
    "use": (r"(?:does (?:it|this|this medicine) help(?: with)?)|(?:is (?:it|this) for)|uses?\b|used (?:for|to)|what (?:is|are) (?:it|this|this medicine|these tablets) for|treats?|purpose|indication|what.*(?:do|help)\b|benefits?", r"\buse[ds]?\b|relie(?:f|ve)|treat|indication|helps|purpose"),
    "effects": (r"side[ -]?effects?|adverse (?:effects?|reactions?)",r"side[ -]?effects?|adverse (?:effects?|reactions?)"),
    "storage": (r"stor(?:e|age|ing)|kept|temperature|refrigerat|how.*keep",r"stor(?:e|age|ing)|keep|temperatur|refrigerat|°[cf]"),
    "expiry": (r"expir\w*|exp[.]? date|shelf life|valid until|use.by",r"expir|\bexp\b|shelf life|use.by"),
    "batch": (r"batch|lot (?:no|number|code)",r"batch|\blot\b"),
    "pack": (r"pack size|packaging|how many.*(?:pack|strip|bottle|box)|how .* (?:packaged|packed)|quantity in",r"pack|strip|bottle|box of|blister"),
    "warning": (r"warnings?|cautions?|precautions?|contraindication",r"warnings?|cautions?|precautions?|contraindicat|allerg|do not"),
    "price": (r"price|cost|mrp",r"price|\bmrp\b|₹|rs\."),
    "form": (r"what form|dosage form|tablet or capsule",r"tablet|capsule|syrup|injection|drop|cream|solution|ointment"),
    "name": (r"what.*(?:name|called)|which medicine|name of",r"brand name|medicine name|product name"),
}
STOP = set("a an am the and of for if in on with from are is was be to as this that my its it they i how many much me which who what when where does do can have tell please file pdf page label read say says show written printed listed medicine drug medication product pack information about per this these any by or at there".split())
INSTRUCTION = re.compile(r"ignore.{0,60}(?:instructions|previous)|system prompt|developer message|jailbreak|<script|https?://|assistant:|execute code",re.I)
ADVICE = re.compile(r"\b(?:how (?:to|do i|should i) (?:use|administer|apply|drink|inject)|when (?:to|should i) (?:use|apply|take)|should (?:i|we) (?:take|stop|start|give|use|mix)|can (?:i|we) (?:take|give|use|stop|mix|combine)|safe (?:for|to|with)|dos(?:es?|ing|age)(?! form)|how (?:much|often|many).*\b(?:take|give|swallow|use)|(?:start|stop|switch|combine|mix|take|give|recommend|prescrib\w*|diagnos\w*|substitut\w*|interact\w*|pregnan\w*|breastfeed\w*)\b|for my (?:child|baby)|twice daily|once daily)",re.I)
NOT_FOUND = "I couldn’t find that answer in the selected source."
REFUSE = "For personal dosing, interactions or treatment decisions, ask a doctor or pharmacist."
EMERGENCY = re.compile(r"overdose|cannot breathe|can.t breathe|trouble breathing|unconscious|chest pain",re.I)


def words(value):
    return set(re.findall(r"[^\W_]+",unicodedata.normalize("NFKC",value).casefold()))


def upload_passages(pages):
    passages = []
    for page in pages:
        lines = [v.strip() for v in page["text"].splitlines()]
        first = next((i for i,line in enumerate(lines) if line.strip()), -1)
        for i, line in enumerate(lines):
            if not line or INSTRUCTION.search(line):
                continue
            source = f"Uploaded file · page {page['page']} · line {i+1}"
            text = line
            heading = line.casefold().rstrip(":").strip()
            is_heading = heading in {"storage", "strength", "composition", "ingredients", "side effects", "batch number", "warnings", "manufacturer", "expiry date", "indications", "uses", "pack size", "shelf life"}
            # Printed labels often put a heading on one line and its value on the next.
            if i+1 < len(lines) and lines[i+1] and (line.endswith(":") or is_heading):
                text += " " + lines[i+1]
                source += f"–{i+2}"
            if len(text) <= 1000 and not INSTRUCTION.search(text):
                passages.append(Passage(text,source))
                # A short first-line product heading can give the name even without a "Name:" prefix.
                if (i == first and len(line) < 90 and not is_heading
                        and re.search(r"[A-Za-z]",line) and re.search(r"\d|\b(?:tablets?|capsules?|syrup|drops?)\b",line,re.I)
                        and not re.search(r"[:.]|\b(?:practice|sample|leaflet|page|ingredient|each|contains)\b",line,re.I)):
                    passages.append(Passage(line,source,"name"))
            elif len(text)>1000:
                for sentence in re.split(r"(?<=[.!?])\s+",line):
                    if len(sentence)<=1000 and not INSTRUCTION.search(sentence):
                        passages.append(Passage(sentence,source))
    return passages


def reference_passages(kind, record, printed=""):
    if kind == "product":
        product, chunks = retrieve(record["rowid"])
        source = f"Supplied catalogue · {product['source_id']} · JSONL line {product['rowid']}"
        fields = [("name","Name",product["name"]), ("strength","Composition",product["salt"]),
                  ("maker","Manufacturer",product["maker"]), ("pack","Pack",product["pack"])]
        passages = [Passage(f"{label}: {value}", source, key) for key,label,value in fields if value and value.strip()]
        details = patient_details(product, chunks, printed)
        if details["use"]:
            passages.append(Passage(details["use"],details["use_source"],"use"))
        if details["effects"]:
            passages.append(Passage(details["effects"],details["source"],"effects"))
        return passages
    if kind == "leaflet":
        source = record["source"]
        return [Passage(record["brand"],source,"name"), Passage(record["description"],source,"form"),
                Passage(", ".join(" ".join(i) for i in record["ingredients"]),source,"strength"),
                Passage(record["use"],source,"use"), Passage(record["caution"],source,"warning")]
    source = f"Gazette of India · entry {record['entry']} · page {record['page']}"
    if record["name"] == "Cetirizine":
        return [Passage(record["name"],source,"name"), Passage(record["forms"],source,"form"),
                Passage(record["forms"],source,"strength"), Passage("For oral cetirizine: " + CETIRIZINE,"GSK India · oral cetirizine, indications","use")]
    return [Passage(record["name"],source,"name"), Passage(record["forms"],source,"form"),
            Passage(record["forms"],source,"strength")] if record["forms"] else [Passage(record["name"],source,"name")]


def answer_question(question, passages):
    question = unicodedata.normalize("NFKC",question).strip()
    if EMERGENCY.search(question):
        return "For a possible emergency, seek local emergency medical assistance now.", None
    if ADVICE.search(question) or re.search(r"\b(?:alcohol|empty stomach|missed dose|before lunch|after meals)\b",question,re.I):
        return REFUSE, None
    if not question or len(question)>400 or INSTRUCTION.search(question):
        return "Ask a short question about something written in the file.", None
    page_request = re.search(r"\b(?:on |from )?page\s+(\d+)\b", question, re.I)
    if page_request:
        marker = f"Uploaded file · page {int(page_request.group(1))} ·"
        passages = [p for p in passages if p.source.startswith(marker)]
        question = (question[:page_request.start()] + " " + question[page_request.end():]).strip()
    fields = [key for key,(ask,_) in FIELDS.items() if re.search(ask,question,re.I)]
    if not fields and re.search(r"how much .+ (?:in|per) (?:each |one |a )?(tablet|capsule)",question,re.I):
        fields = ["strength"]
    if len(fields)>1:
        # "What ingredients does it contain?" and similar aliases are one field.
        return "Please ask about one detail at a time.", None
    question = re.sub(r"\brunning nose\b", "runny nose", question, flags=re.I)
    terms = words(question) - STOP
    field = fields[0] if fields else None
    # Keep specific terms in questions such as "does this contain aspirin?" or
    # "does it treat malaria?" so a merely topical passage cannot answer them.
    qualifiers = set()
    if field:
        cue = re.compile(FIELDS[field][0], re.I)
        expanded = re.sub(r"\w+", lambda m: "" if cue.search(m.group()) else m.group(), cue.sub(" ",question))
        qualifiers = words(expanded) - STOP - set("main common possible different printed bottle strip tablets capsule capsules how strong size amount comes usually used tablet most has been their known any proper date expiry makes made same exactly stated each purpose commonly india meant include includes there describe explain contains ingredients use help us find given mention referred number no please some brand generic treatment best normally did kept store storing should".split())
    named = next((p for p in passages if p.field == "name" and not p.source.startswith("Uploaded file")), None)
    if named:
        qualifiers -= words(named.text)
    ranked = []
    for p in passages:
        if not p.text or INSTRUCTION.search(p.text) or ADVICE.search(p.text):
            continue
        passage_words = words(p.text)
        if qualifiers and not qualifiers <= passage_words:
            continue
        overlap = len(terms & passage_words)
        if field:
            if p.field and p.field != field:
                continue
            if not p.field and not re.search(FIELDS[field][1],p.text,re.I):
                continue
        elif p.field == "name" and not (terms & passage_words):
            continue
        elif not terms or overlap < max(1, (len(terms)*2+2)//3):
            continue
        ranked.append((overlap,p))
    ranked.sort(key=lambda item:item[0], reverse=True)
    if ranked and field in {"strength","maker","expiry","batch","name","pack"}:
        distinct = {normalized(p.text) for score,p in ranked if score == ranked[0][0] and p.source.startswith("Uploaded file")}
        complete = [line for line in distinct if not any(line != other and line in other for other in distinct)]
        if len(complete) > 1:
            return "I found several matching lines. Include the ingredient, product name or page number in your question.", None
    hits = [p for _,p in ranked[:4]]
    if not hits:
        return NOT_FOUND, None
    # Names, dosages and negations are never reconstructed from model tokens.
    try:
        guess = normalized(predict_question(question, [p.text for p in hits]))
    except (ImportError, OSError, RuntimeError, ValueError):
        guess = ""
    exact = next((p for p in hits if normalized(p.text)==guess),None)
    inside = [p for p in hits if guess and guess in normalized(p.text)]
    if exact:
        chosen = exact
    elif len(inside)==1 and len(words(guess))>=2:
        chosen = inside[0]
    elif field:
        chosen = hits[0]
    else:
        return NOT_FOUND, None
    return chosen.text, chosen.source

def reference_answer(question, kind, record, printed=""):
    """Use the eight validated FAQ topics only for a confirmed product and an exact question."""
    folded = normal_question(question)
    if kind == "product":
        topic = next((k for k,q in QUESTIONS.items() if normal_question(q) == folded), None)
        if topic:
            from label_generator import choose
            product, chunks = retrieve(record["rowid"])
            details = patient_details(product, chunks, printed)
            answer, source = faq_answer(topic, details)
            if source and topic == "use":
                answer, _ = choose(product["name"], [answer])
            return answer, source
    return answer_question(question, reference_passages(kind, record, printed))

def normal_question(question):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC",question).casefold()))
