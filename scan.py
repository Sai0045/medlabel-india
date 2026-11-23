"""Extract local page text in a time-limited child process. Never use a supplied path."""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

from PIL import Image, ImageOps

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 6
MAX_PIXELS = 16_000_000
MAX_TEXT = 80_000
ROOT = Path(__file__).resolve().parent


def find_tesseract():
    engine = shutil.which('tesseract')
    if engine:
        return engine
    if sys.platform == 'win32':
        candidates = [
            Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'),
            Path(r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'),
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Tesseract-OCR' / 'tesseract.exe',
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def read_words(image):
    buffer = BytesIO()
    ImageOps.exif_transpose(image).convert('RGB').save(buffer, format='PNG')
    engine = find_tesseract()
    helper = ROOT / 'tools/vision_ocr'
    if engine:
        command = [engine, 'stdin', 'stdout', '-l', 'eng', '--psm', '6']
        name = 'Tesseract OCR'
    elif sys.platform == 'darwin' and helper.is_file():
        command = [str(helper)]
        name = 'Apple Vision OCR'
    else:
        raise ValueError('Install English Tesseract, or build the Mac OCR helper using the README.')
    result = subprocess.run(command, input=buffer.getvalue(), capture_output=True, timeout=25, check=True)
    if engine:
        return result.stdout.decode('utf-8').strip(), name
    return '\n'.join(row['text'] for row in json.loads(result.stdout)), name


def pdf_pages(data):
    import pypdfium2 as pdfium
    output = []
    with pdfium.PdfDocument(data) as doc:
        if not 1 <= len(doc) <= MAX_PAGES:
            raise ValueError('Upload a PDF with 1 to 6 pages.')
        for n in range(len(doc)):
            page = doc[n]
            try:
                w, h = page.get_size()
                if not (0 < w <= 3000 and 0 < h <= 3000):
                    raise ValueError('This page is too large. Upload a cropped page image.')
                text_page = page.get_textpage()
                try:
                    if text_page.count_chars() > MAX_TEXT:
                        raise ValueError('This page contains too much text.')
                    text = text_page.get_text_bounded().strip()
                finally:
                    text_page.close()
                method = 'PDF text'
                # Short headers can sit above a scanned label. Read the visible page too.
                def covers_label_area(obj):
                    left, bottom, right, top = obj.get_bounds()
                    return abs((right-left) * (top-bottom)) >= w*h/4
                has_large_image = any(covers_label_area(obj) for obj in
                                      page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]))
                if len(text) < 32 or has_large_image:
                    scale = min(2.5, 2300 / max(w, h))
                    bitmap = page.render(scale=scale)
                    try:
                        visible, method = read_words(bitmap.to_pil())
                    finally:
                        bitmap.close()
                    if visible and text and text not in visible:
                        text = text + '\n' + visible
                    elif visible:
                        text = visible
                output.append({'page':n + 1, 'text':text, 'method':method})
            finally:
                page.close()
    return output


def extract(data, suffix):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Choose a nonempty file smaller than 10 MB.')
    if suffix == '.pdf' and data.startswith(b'%PDF-'):
        pages = pdf_pages(data)
    elif suffix in {'.jpg', '.jpeg', '.png'}:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                expected = 'PNG' if suffix == '.png' else 'JPEG'
                if image.format != expected or getattr(image, 'n_frames', 1) != 1 or image.width * image.height > MAX_PIXELS:
                    raise ValueError('Choose a single JPEG or PNG image under 16 megapixels.')
                text, method = read_words(image)
        pages = [{'page':1, 'text':text, 'method':method}]
    else:
        raise ValueError('Choose a JPEG, PNG or PDF with a matching file extension.')
    if sum(len(page['text']) for page in pages) > MAX_TEXT:
        raise ValueError('There is too much text. Upload one medicine label at a time.')
    if not any(page['text'].strip() for page in pages):
        raise ValueError('No readable words found. Try a clearer picture of the printed name.')
    return pages


def scan(data, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in {'.jpg','.jpeg','.png','.pdf'} or len(data) > MAX_BYTES:
        raise ValueError('Choose a JPG, PNG or PDF of up to 10 MB.')
    try:
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), suffix],
                             input=data, capture_output=True, timeout=90, check=True)
        result = json.loads(run.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise ValueError('The file could not be read in time. Try one smaller page.') from None
    if 'error' in result:
        raise ValueError(result['error'])
    return result['pages']


if __name__ == '__main__':
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    try:
        response = {'pages':extract(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[1])}
    except ValueError as exc:
        response = {'error':str(exc)}
    except Exception:
        response = {'error':'This file is damaged, locked, or could not be read. Try a clear image or an unlocked PDF.'}
    print(json.dumps(response))
