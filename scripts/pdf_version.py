"""Publish a PDF-set content version without importing Windows layout fonts."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_pdf_version(root=ROOT):
    target = root / 'dist/numbering.json'
    original = target.read_text(encoding='utf8')
    numbering = json.loads(original)
    digest = hashlib.sha256(numbering['version'].encode() + b'continuous-native-v2')
    for book in sorted((root / 'dist/downloads').glob('*.pdf')):
        digest.update(book.name.encode() + hashlib.sha256(book.read_bytes()).digest())
    version = 'topic-pdf-' + digest.hexdigest()[:16]
    # The existing numbering file has a pdfVersion; retain its formatting.
    updated = re.sub(r'("pdfVersion"\s*:\s*")[^"]+(")', lambda m: m[1]+version+m[2], original)
    if numbering.get('pdfVersion') != version and updated == original:
        raise ValueError('numbering.json has no pdfVersion to update')
    target.write_text(updated, encoding='utf8', newline='')
    for path in (root / 'dist/export-index').glob('*.json'):
        data = json.loads(path.read_text(encoding='utf8'))
        data.update(version=2, bookVersion=version)
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    print('PDF VERSION', version, flush=True)
    return version


if __name__ == '__main__':
    sync_pdf_version()
