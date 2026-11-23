"""Look up printed names in Indian documents. No web or model calls."""
import json
from pathlib import Path
import re
import unicodedata

DATA = Path(__file__).resolve().parent / 'data'
SCHEDULE = json.loads((DATA / 'indian_schedule.json').read_text())
BRANDS = json.loads((DATA / 'indian_brands.json').read_text())


def words(text):
    return ' '.join(re.findall(r'[\w]+|[.+%/]', unicodedata.normalize('NFKC', text).casefold()))


def contains(text, term):
    return f' {term} ' in f' {text} '


def brand_evidence(text, brand):
    """Require a distinct printed brand line and each ingredient with its own printed strength."""
    lines = [words(line) for line in text.splitlines() if line.strip()]
    title = words(brand['brand'])
    form = brand['form']
    headings = {title, f'{title} {form}', f'{title} {form}s'}
    if not headings.intersection(lines):
        return False
    content = words(text)
    if not any(contains(content, f) for f in (form, form + 's')):
        return False
    # Require a name and quantity together. Do not derive strength from a brand's number.
    quantities = set(re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*mg\b',text.casefold()))
    required = {dose.split()[0] for _,dose in brand['ingredients']}
    if quantities != required:
        return False
    for ingredient, strength in brand['ingredients']:
        n = strength.split()[0]
        pattern = rf'\b{re.escape(ingredient)}\b(?:\s+(?:i\.?\s*p\.?|sodium|equivalent to|maleate))*\s*[:.\- ]*{n}\s*mg\b'
        if not re.search(pattern, text, re.I):
            return False
    return True


def lookup(text):
    content = words(text)
    brands = [b for b in BRANDS if brand_evidence(text, b)]
    entries = [r for r in SCHEDULE['entries'] if contains(content, words(r['name']))]
    return brands, entries
