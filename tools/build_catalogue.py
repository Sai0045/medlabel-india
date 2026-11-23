"""Build a compressed, read-only search index from the paired Indian medicine files."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata


def normal(value):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC',value).casefold()))


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def evidence(name, uses, effects):
    # A different benefit paragraph is often copied between products in this source.
    if not name or not re.match(re.escape(name.strip()) + r'\s+(?:is|contains|belongs|helps|works|provides)\b', uses, re.I):
        return []
    # Only introductory, descriptive evidence. Keep a complete sentence and all negations.
    split = re.split(r'(?<=[.!?])\s+(?=[A-Z])|(?<=[a-z][.!?])(?=[A-Z])',uses)
    sentences=[]
    for i, sentence in enumerate(split[:3]):
        if i and not re.match(r'It (?:is|helps|works|can|does|also)\b', sentence):
            break
        checked = re.sub(r'\byour (body|stomach)\b', r'the \1', sentence, flags=re.I)
        if re.search(r'https?://|[<>\[\]]', sentence): break
        if len(sentence)>640 or re.search(r'\b(?:dos(?:es?|ages?|ing)|pregnan\w*|breastfeed\w*|you|your|should|take|taking|recommended|safe|daily|ignore|instructions|twice|once|swallow|inject)\b',checked,re.I):
            break
        if not sentence.endswith(('.', '!', '?')): break
        sentences.append(sentence)
    passages=[('use',s) for s in sentences]
    if sentences and 0<len(effects)<900 and not re.search(r'https?://|[<>\[\]]',effects) and not re.search(r'\b(?:not available|no common side effects|consult|unknown|no data|instructions|safe|not found)\b',effects,re.I):
        passages.append(('effects',effects))
    return passages


def build(csv_path,jsonl_path,out):
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        dbpath=Path(tmp)/'records.sqlite'
        con=sqlite3.connect(dbpath)
        con.executescript('''
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
            CREATE TABLE product(rowid INTEGER PRIMARY KEY, source_id TEXT UNIQUE, name TEXT, brand TEXT,
                salt TEXT, maker TEXT, pack TEXT, title_key TEXT, brand_key TEXT);
            CREATE TABLE passage(product_id INTEGER, kind TEXT, excerpt TEXT);
        ''')
        counts=Counter(); product_rows=[]; passage_rows=[]
        with csv_path.open(encoding='utf-8-sig',newline='') as fc, jsonl_path.open(encoding='utf-8-sig') as fj:
            for line,(row,line_json) in enumerate(zip_longest(csv.DictReader(fc),fj),1):
                if row is None or line_json is None: raise ValueError('Different record counts')
                doc=json.loads(line_json); md=doc['metadata']
                if any(row[a].strip()!=md[b].strip() for a,b in [('MedicineName','medicine_name'),('Brand','brand'),('all_ingredients_composition','salt_composition'),('manufacturer','manufacturer'),('pack_size','pack_size')]) or doc['id']!=md['id']:
                    raise ValueError(f'CSV and JSONL disagree at record {line}')
                name=row['MedicineName'].strip()
                uses=row['used_for'].strip(); effects=row['side_effects'].strip()
                if uses not in doc['text'] or effects not in doc['text']:
                    raise ValueError(f'Passages do not agree at record {line}')
                product_rows.append((line,doc['id'],name,row['Brand'],row['all_ingredients_composition'],row['manufacturer'],row['pack_size'],normal(name),normal(row['Brand'])))
                keep=evidence(name,uses,effects)
                counts['with_use' if keep else 'withheld_use']+=1
                passage_rows.extend((line,kind,t) for kind,t in keep)
                if len(product_rows)>=5000:
                    con.executemany('INSERT INTO product VALUES(?,?,?,?,?,?,?,?,?)',product_rows)
                    con.executemany('INSERT INTO passage VALUES(?,?,?)',passage_rows)
                    product_rows.clear();passage_rows.clear()
            con.executemany('INSERT INTO product VALUES(?,?,?,?,?,?,?,?,?)',product_rows)
            con.executemany('INSERT INTO passage VALUES(?,?,?)',passage_rows)
        con.executescript('''
            CREATE INDEX passage_by_product ON passage(product_id,kind);
            CREATE INDEX by_title ON product(title_key);
            CREATE INDEX by_brand ON product(brand_key);
            CREATE VIRTUAL TABLE search USING fts5(title_key,brand_key,content=product,content_rowid=rowid);
            INSERT INTO search(search) VALUES('rebuild');
        ''')
        counts['records']=con.execute('select count(*) from product').fetchone()[0]
        counts['identity_scoped_passages']=con.execute('select count(*) from passage').fetchone()[0]
        con.commit();con.close()
        parts=[]
        with dbpath.open('rb') as f:
            while block:=f.read(24*1024*1024):
                name=f'part-{len(parts):02}.gz'
                dest=out/name;dest.write_bytes(gzip.compress(block,compresslevel=6,mtime=0))
                parts.append({'file':name,'sha256':digest(dest)})
        manifest={'inputs':{p.name:digest(p) for p in (csv_path,jsonl_path)},'database_sha256':digest(dbpath),'counts':counts,'parts':parts}
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(counts),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('csv',type=Path);p.add_argument('jsonl',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();build(args.csv,args.jsonl,args.output)
