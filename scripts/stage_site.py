"""Copy a self-contained Pages tree without unused source assets.

Inputs are never removed or rewritten. A successful build replaces output/site
by renaming its predecessor to a unique sibling backup. Failed temporary trees
are retained for inspection. No recursive deletion is performed.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit
import uuid

from paper1_manifest import SLUGS
from check_release import check as check_release

MAX_SITE_BYTES = 1_000_000_000
ASSET_PATTERN = re.compile(r'assets/[^\s\"\'`<>()[\]{}]+')
URL_PATTERN = re.compile(r'url\(\s*[\"\']?([^\"\')]+)', re.I)
HREF_PATTERN = re.compile(r'(?:href|src)\s*=\s*[\"\']([^\"\']+)', re.I)
TEXT_TYPES = {'.html', '.css', '.js', '.svg'}
SKIP_SUFFIXES = {'.tmp', '.pyc'}


def safe_file(dist, relative):
    """Resolve a referenced local file, rejecting traversal and symbolic links."""
    value = html.unescape(relative)
    url = urlsplit(value)
    name = unquote(url.path)
    if url.scheme or url.netloc or not name or '\\' in name or ':' in name:
        raise ValueError(f'Nonlocal or invalid input path: {relative!r}')
    path = dist / name
    resolved = path.resolve()
    if Path(name).is_absolute() or '..' in Path(name).parts or not resolved.is_relative_to(dist):
        raise ValueError(f'Input path escapes dist: {relative!r}')
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != dist.parent):
        raise ValueError(f'Symbolic-link input is not supported: {relative!r}')
    if not resolved.is_file():
        raise ValueError(f'Missing referenced input: {relative}')
    return resolved


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for entry in value.values():
            yield from strings(entry)
    elif isinstance(value, list):
        for entry in value:
            yield from strings(entry)


def clean_export_files(root, dist):
    """Stage only the inventory that passed the same checks as a full release."""
    report = check_release(root, pdfs=True, parts=True)
    if not report['passed']:
        raise ValueError('Clean export inventory is not publishable:\n' + '\n'.join(report['errors']))
    files = {'export-parts/manifest.json'}
    for slug in SLUGS.values():
        for kind in ('questions', 'answers'):
            name = f'export-parts/{slug}-{kind}.json'
            metadata = json.loads(safe_file(dist, name).read_text(encoding='utf-8'))
            files.add(name)
            for entry in [metadata['frame'], metadata['cleanBook'], *metadata['questions'].values()]:
                relative = 'export-parts/' + entry['path']
                safe_file(dist, relative)
                files.add(relative)
    safe_file(dist, 'export-parts/manifest.json')
    return files


def plan_site(root, clean_books=False):
    root = Path(root).resolve()
    dist = (root / 'dist').resolve()
    if not dist.is_dir() or not dist.is_relative_to(root):
        raise ValueError('dist must be a directory inside the project')
    files = clean_export_files(root, dist) if clean_books else set()
    assets = {'assets/chemy-watermark.jpg'}  # Worker-added decoration.
    for name in ['questions.json', 'presentation.json']:
        data = json.loads(safe_file(dist, name).read_text(encoding='utf-8'))
        for value in strings(data):
            assets.update(ASSET_PATTERN.findall(html.unescape(value)))
    for path in dist.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(dist).as_posix()
        if relative.startswith('assets/') or path.suffix in SKIP_SUFFIXES:
            continue
        if clean_books and relative.startswith(('downloads/', 'export-parts/')):
            continue
        safe_file(dist, relative)
        files.add(relative)
        if path.suffix in TEXT_TYPES:
            text = path.read_text(encoding='utf-8')
            assets.update(ASSET_PATTERN.findall(html.unescape(text)))
            if clean_books and 'downloads/' in text:
                raise ValueError(f'{relative} still refers to source downloads; update links before --clean-books')
    # SVG/CSS assets may themselves refer to a sibling image or font.
    visited = set()
    while assets - visited:
        name = sorted(assets - visited)[0]
        path = safe_file(dist, name)
        relative = path.relative_to(dist).as_posix()
        visited.add(name)
        files.add(relative)
        if path.suffix in {'.svg', '.css'}:
            text = path.read_text(encoding='utf-8')
            assets.update(ASSET_PATTERN.findall(html.unescape(text)))
            for reference in URL_PATTERN.findall(text) + HREF_PATTERN.findall(text):
                reference = html.unescape(reference.strip())
                if reference.startswith('#') or urlsplit(reference).scheme or urlsplit(reference).netloc:
                    continue
                sibling = (path.parent / unquote(urlsplit(reference).path)).resolve()
                if not sibling.is_relative_to(dist):
                    raise ValueError(f'Asset reference escapes dist: {name}: {reference}')
                assets.add(sibling.relative_to(dist).as_posix())
    if 'index.html' not in files:
        raise ValueError('Missing website entry index.html')
    return dist, sorted(files), len(visited)


def stage_site(root, output=None, clean_books=False, max_bytes=MAX_SITE_BYTES):
    root = Path(root).resolve()
    output_root = (root / 'output').resolve()
    if (root / 'output').is_symlink() or not output_root.is_relative_to(root):
        raise ValueError('project/output must stay inside the project')
    target = Path(output).absolute() if output is not None else output_root / 'site'
    if target.is_symlink() or target.resolve() == output_root or not target.resolve().is_relative_to(output_root):
        raise ValueError('Staging output must be a directory below project/output')
    target = target.resolve()
    if target.exists() and not target.is_dir():
        raise ValueError('Staging target exists and is not a directory')
    if not 0 < max_bytes <= MAX_SITE_BYTES:
        raise ValueError('Site budget must be between 1 and 1,000,000,000 bytes')
    dist, files, asset_count = plan_site(root, clean_books)
    sizes = {name: safe_file(dist, name).stat().st_size for name in files}
    planned_bytes = sum(sizes.values())
    if planned_bytes > max_bytes:
        raise ValueError(f'Site would contain {planned_bytes:,} bytes; budget is {max_bytes:,}')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=target.name + '-building-', dir=target.parent)).resolve()
    if not temporary.is_relative_to(output_root):
        raise ValueError('Unexpected temporary directory outside output')
    inventory = []
    for name in files:
        source = safe_file(dist, name)
        destination = temporary / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if destination.stat().st_size != sizes[name]:
            raise ValueError(f'Input changed while staging: {name}; temporary tree retained at {temporary}')
        with source.open('rb') as stream:
            expected = hashlib.file_digest(stream, 'sha256').hexdigest()
        with destination.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError(f'Copy checksum differs: {name}; temporary tree retained at {temporary}')
        inventory.append({'path': name, 'bytes': sizes[name], 'sha256': actual})
    actual_bytes = sum(path.stat().st_size for path in temporary.rglob('*') if path.is_file())
    if actual_bytes != planned_bytes or actual_bytes > max_bytes:
        raise ValueError(f'Staged bytes changed or exceeded budget: {actual_bytes:,}')
    backup = None
    if target.exists():
        backup = target.with_name(target.name + '-backup-' + uuid.uuid4().hex)
        if not backup.resolve().is_relative_to(output_root):
            raise ValueError('Backup path escapes output')
        target.rename(backup)
    try:
        temporary.rename(target)
    except OSError:
        if backup is not None and not target.exists():
            backup.rename(target)
        raise
    report = {'path': str(target), 'bytes': actual_bytes, 'budget': max_bytes,
              'files': len(files), 'referencedAssets': asset_count, 'cleanBooks': clean_books,
              'previousSiteBackup': str(backup) if backup else None, 'inventory': inventory}
    target.with_name(target.name + '-stage-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--clean-books', action='store_true',
                        help='validate the full release, stage only referenced export files, and omit source downloads/')
    parser.add_argument('--max-bytes', type=int, default=MAX_SITE_BYTES)
    parser.add_argument('--plan', action='store_true', help='show the copy plan without creating staging files')
    args = parser.parse_args()
    if args.plan:
        dist, files, assets = plan_site(args.root, args.clean_books)
        total = sum((dist / name).stat().st_size for name in files)
        print(json.dumps({'files': len(files), 'referencedAssets': assets, 'bytes': total,
                          'budget': args.max_bytes, 'withinBudget': total <= args.max_bytes}, indent=2))
        return 0 if total <= args.max_bytes <= MAX_SITE_BYTES else 1
    report = stage_site(args.root, args.output, args.clean_books, args.max_bytes)
    print(json.dumps({key: value for key, value in report.items() if key != 'inventory'}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
