"""Store repeated PDF bytes once in the published static site."""
from collections import Counter
import gzip
import hashlib
import json
import struct


def stream_spans(raw):
    """Use stream delimiters as byte boundaries. No PDF object is re-encoded."""
    start = 0
    while True:
        marker = raw.find(b'\nstream\n', start)
        if marker < 0:
            return
        first = marker + len(b'\nstream\n')
        end = raw.find(b'\nendstream', first)
        if end < 0:
            return
        if end - first >= 256:
            yield first, end
        start = end + len(b'\nendstream')


def pack_fragments(dist, files, destination=None):
    """Return original files replaced and the inventory of packed files.

    Only the validated manifest's question fragments are packed. The original
    path, byte count and digest continue to identify the reconstructed PDF.
    With no destination the same encoding calculates the exact release size.
    """
    manifests = {}
    records = {}
    for name in sorted(files):
        if not (name.startswith('export-parts/') and name.endswith(('-answers.json', '-questions.json'))):
            continue
        manifest = json.loads((dist / name).read_text(encoding='utf8'))
        manifests[name] = manifest
        for record in manifest['questions'].values():
            path = 'export-parts/' + record['path']
            if path not in files or path in records:
                raise ValueError(f'Invalid question fragment in {name}: {path}')
            records[path] = record

    def verified_pdf(path, record):
        raw = (dist / path).read_bytes()
        if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError(f'Question PDF changed before packing: {path}')
        return raw

    counts = Counter()
    for path, record in records.items():
        raw = verified_pdf(path, record)
        counts.update(hashlib.sha256(raw[a:b]).digest() for a, b in stream_spans(raw))

    written = {}

    def emit(name, data):
        digest = hashlib.sha256(data).hexdigest()
        if destination is not None:
            output = destination / name
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                stream.write(data)
            if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                raise OSError(f'Staged fragment bytes differ: {name}')
        written[name] = {'path': name, 'bytes': len(data), 'sha256': digest}

    for path, record in records.items():
        raw = verified_pdf(path, record)
        if not 0 < len(raw) <= 100 * 1024 * 1024:
            raise ValueError(f'Unsupported packed question size: {path}')
        recipe = bytearray(b'CHEMYPK1')
        last = 0
        segments = 0
        for first, end in stream_spans(raw):
            block = raw[first:end]
            key = hashlib.sha256(block).digest()
            if counts[key] < 2:
                continue
            name = 'export-parts/shared/' + key.hex() + '.bin'
            if name not in written:
                emit(name, block)
            if first > last:
                recipe.extend(struct.pack('<I', first - last))
                recipe.extend(raw[last:first])
                segments += 1
            recipe.extend(struct.pack('<I', 0x80000000 | len(block)))
            recipe.extend(key)
            segments += 1
            last = end
        if last < len(raw):
            recipe.extend(struct.pack('<I', len(raw) - last))
            recipe.extend(raw[last:])
            segments += 1
        if segments > 65536 or len(recipe) > 128 * 1024 * 1024:
            raise ValueError(f'Packed question exceeds the browser decoding limit: {path}')
        emit(path + '.pack', gzip.compress(recipe, compresslevel=6, mtime=0))
        record['packed'] = True
    for name, manifest in manifests.items():
        emit(name, json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode('utf8'))
    return set(records) | set(manifests), list(written.values())
