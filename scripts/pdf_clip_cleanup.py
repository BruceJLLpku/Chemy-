"""Remove wholly hidden content from the library's rectangular clipping scopes.

This is a conservative cleaner for generated Chemy pages, not an arbitrary PDF
editor. Partially visible objects and non-rectangular clips keep their original
clipping paths. Each scope is filtered separately so replacement labels outside
the scope cannot be removed together with the source labels they replace.
"""
from copy import copy, deepcopy
from hashlib import sha256
from io import BytesIO
from math import isfinite
import math
import re

import pymupdf as fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from pdf_render_verify import scissors, text_ink_bounds, filled_text_is_distant, exact_paint_mask, image_paints
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, FloatObject, NameObject, NumberObject


class UnsupportedPDF(ValueError):
    pass


def _object(value):
    return value.get_object() if hasattr(value, 'get_object') else value


class Resources:
    def __init__(self):
        self.data = DictionaryObject()
        self.names = {}
        self.readers = []  # Keep indirect references alive until the final write.
        self.forms = {}

    def name(self, category, name, source, reader, initial_ctm=None):
        source = _object(source)
        table = _object(source.get(category, {}))
        value = table.get(name)
        if value is None:
            return name
        # Pattern matrices are relative to the enclosing Form's initial user
        # space, not the current cm at the point where the pattern is selected.
        # A Form reused under another transform therefore needs its own pattern.
        pattern_matrix = tuple(initial_ctm) if category == '/Pattern' and initial_ctm is not None else None
        key = (id(reader), category, getattr(value, 'idnum', id(value)), getattr(value, 'generation', 0), pattern_matrix)
        if key not in self.names:
            new = NameObject('/Clean' + str(len(self.names)))
            if pattern_matrix is not None:
                pattern = _object(value)
                value = copy(pattern)
                # A transformed copy is a new PDF object. Keeping the source
                # indirect identity would make PdfWriter deduplicate variants.
                if hasattr(value,'indirect_reference'):
                    del value.indirect_reference
                matrix = fitz.Matrix(*map(float,pattern.get('/Matrix',[1,0,0,1,0,0]))) * initial_ctm
                value[NameObject('/Matrix')] = ArrayObject([FloatObject(v) for v in matrix])
            self.data.setdefault(NameObject(category), DictionaryObject())[new] = value
            self.names[key] = new
        return self.names[key]

    def import_ops(self, stream, source, reader, depth=0, initial_ctm=None):
        if depth > 40:
            raise UnsupportedPDF('Recursive or deeply nested Form XObjects')
        source = _object(source)
        spaces = _object(source.get('/ColorSpace', {}))
        if any(name in spaces for name in ['/DefaultRGB', '/DefaultGray', '/DefaultCMYK']):
            raise UnsupportedPDF('Default colour-space substitution requires separate handling')
        out = []
        initial_ctm = fitz.Matrix(1,0,0,1,0,0) if initial_ctm is None else initial_ctm
        current_ctm = fitz.Matrix(initial_ctm)
        matrices = []
        categories = {
            b'Tf': ('/Font', 0), b'gs': ('/ExtGState', 0), b'Do': ('/XObject', 0),
            b'sh': ('/Shading', 0), b'CS': ('/ColorSpace', 0), b'cs': ('/ColorSpace', 0),
            b'SCN': ('/Pattern', -1), b'scn': ('/Pattern', -1),
            b'BDC': ('/Properties', -1), b'DP': ('/Properties', -1),
        }
        for operands, operator in ContentStream(stream, reader).operations:
            if operator == b'INLINE IMAGE':
                # pypdf represents inline images as a dict, not an operand list.
                operands = deepcopy(operands)
                settings = operands['settings']
                for key in ['/CS', '/ColorSpace']:
                    if isinstance(settings.get(key), NameObject):
                        settings[NameObject(key)] = self.name('/ColorSpace', settings[key], source, reader)
                out.append((operands, operator))
                continue
            args = list(operands)
            if operator == b'q':
                matrices.append(fitz.Matrix(current_ctm))
            elif operator == b'Q':
                if not matrices:
                    raise UnsupportedPDF('Unbalanced graphics-state restore')
                current_ctm = matrices.pop()
            elif operator == b'cm':
                current_ctm = fitz.Matrix(*map(float,args)) * current_ctm
            if operator == b'Do':
                obj = _object(_object(source['/XObject'])[args[0]])
                if obj.get('/Subtype') == '/Form':
                    if obj.get('/Group') or obj.get('/OC'):
                        raise UnsupportedPDF('Transparency-group or optional-content Form XObject')
                    box = list(map(float, obj['/BBox']))
                    out.extend([([], b'q'), (list(obj.get('/Matrix', [1, 0, 0, 1, 0, 0])), b'cm'),
                                ([box[0], box[1], box[2]-box[0], box[3]-box[1]], b're'), ([], b'W'), ([], b'n')])
                    form_ctm = fitz.Matrix(*map(float,obj.get('/Matrix',[1,0,0,1,0,0]))) * current_ctm
                    key = (id(reader), id(obj), id(source) if '/Resources' not in obj else None, tuple(form_ctm))
                    if key not in self.forms:
                        self.forms[key] = self.import_ops(obj, obj.get('/Resources', source), reader, depth+1, form_ctm)
                    out.extend(self.forms[key])
                    out.append(([], b'Q'))
                    continue
                image_space = obj.get('/ColorSpace')
                if isinstance(image_space, NameObject) and image_space in spaces:
                    raise UnsupportedPDF('Image refers to a context-dependent named colour space')
            if operator == b'gs':
                state = _object(_object(source.get('/ExtGState', {})).get(args[0], {}))
                if state.get('/SMask') not in (None, '/None'):
                    raise UnsupportedPDF('Soft-mask graphics state requires separate handling')
            if operator in (b'SCN', b'scn') and args and isinstance(args[-1], NameObject):
                pattern = _object(_object(source.get('/Pattern', {})).get(args[-1], {}))
                if pattern.get('/PatternType') == 1:
                    # The library uses self-contained image tiles for figure
                    # fills. Keep these vector/native image resources intact;
                    # general tiling programs need a separate cleaner.
                    if pattern.get('/PaintType') != 1 or '/Resources' not in pattern:
                        raise UnsupportedPDF('Context-dependent tiling pattern')
                    tile_resources = _object(pattern['/Resources'])
                    tile_images = _object(tile_resources.get('/XObject',{}))
                    tile_ops = ContentStream(pattern,reader).operations
                    tile_box = list(pattern.get('/BBox',[]))
                    tile_matrix = list(pattern.get('/Matrix',[1,0,0,1,0,0]))
                    steps = [float(pattern.get('/XStep',0)),float(pattern.get('/YStep',0))]
                    if (set(tile_resources) != {'/XObject'} or
                            [op for _,op in tile_ops] != [b'q',b'cm',b'Do',b'Q'] or
                            len(tile_box) != 4 or len(tile_matrix) != 6 or not all(steps) or
                            not all(isfinite(float(v)) for v in tile_box+tile_matrix+steps)):
                        raise UnsupportedPDF('Non-image or invalid tiling pattern requires separate handling')
                    for tile_args,tile_op in tile_ops:
                        if tile_op == b'Do':
                            tile = _object(tile_images.get(tile_args[0],{}))
                            if (tile.get('/Subtype') != '/Image' or tile.get('/OC') or tile.get('/SMask') or tile.get('/Mask') or
                                    tile.get('/ColorSpace') != '/DeviceRGB'):
                                raise UnsupportedPDF('Complex image tiling pattern requires separate handling')
                elif pattern.get('/PatternType') != 2:
                    raise UnsupportedPDF('Tiling pattern requires separate handling')
            if operator in categories and args:
                category, index = categories[operator]
                if isinstance(args[index], NameObject):
                    args[index] = self.name(category, args[index], source, reader, initial_ctm)
            out.append((args, operator))
        return out


def _stream(operations, reader=None):
    stream = ContentStream(None, reader)
    stream.operations = [
        (args if op == b'INLINE IMAGE' else [NumberObject(a) if isinstance(a,int) else FloatObject(a) if isinstance(a,float) else a for a in args], op)
        for args, op in operations
    ]
    return stream


def _pdf(operations, resources, box):
    writer = PdfWriter()
    page = writer.add_blank_page(width=float(box[2])-float(box[0]), height=float(box[3])-float(box[1]))
    page.mediabox = copy(box)
    # Copy only referenced resources into temporary scopes. In particular, a
    # one-glyph scope must not repeatedly clone all fonts/images of the page.
    used = DictionaryObject()
    categories = {b'Tf':('/Font',0), b'gs':('/ExtGState',0), b'Do':('/XObject',0),
                  b'sh':('/Shading',0), b'CS':('/ColorSpace',0), b'cs':('/ColorSpace',0),
                  b'SCN':('/Pattern',-1), b'scn':('/Pattern',-1), b'BDC':('/Properties',-1), b'DP':('/Properties',-1)}
    def include(category, name):
        if isinstance(name,NameObject) and name in resources.get(category,{}):
            used.setdefault(NameObject(category),DictionaryObject())[name] = resources[category][name]
    for args,op in operations:
        if op in categories and args:
            category,index = categories[op]
            include(category,args[index])
        elif op == b'INLINE IMAGE':
            for key in ('/CS','/ColorSpace'):
                include('/ColorSpace',args['settings'].get(key))
    page[NameObject('/Resources')] = used.clone(writer)
    page[NameObject('/Contents')] = writer._add_object(_stream(operations))
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def _intersect(a, b):
    r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return r if r[2] > r[0] and r[3] > r[1] else None


def _rectangles(path, even_odd):
    """Partition rectangle unions / even-odd holes without changing winding."""
    xs = sorted({v for r, _ in path for v in (r[0], r[2])})
    ys = sorted({v for r, _ in path for v in (r[1], r[3])})
    if len(xs)*len(ys) > 100000:
        raise UnsupportedPDF('Rectangular clipping path is too complex')
    result = []
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            x, y = (x0+x1)/2, (y0+y1)/2
            covers = [sign for r, sign in path if r[0] < x < r[2] and r[1] < y < r[3]]
            inside = len(covers) % 2 if even_odd else sum(covers) != 0
            if inside:
                result.append((x0, y0, x1, y1))
    return result


class Scope:
    def __init__(self):
        self.items = []


def _scopes(operations):
    root = Scope()
    stack = [root]
    for args, op in operations:
        if op == b'q':
            child = Scope()
            stack[-1].items.append(child)
            stack.append(child)
        elif op == b'Q':
            if len(stack) == 1:
                raise UnsupportedPDF('Unbalanced graphics-state restore')
            stack.pop()
        else:
            stack[-1].items.append((args, op))
    if len(stack) != 1:
        raise UnsupportedPDF('Unbalanced graphics-state save')
    return root


GRAPHICS_STATE = {b'w', b'J', b'j', b'M', b'd', b'ri', b'i', b'gs', b'CS', b'cs',
                  b'SC', b'sc', b'SCN', b'scn', b'G', b'g', b'RG', b'rg', b'K', b'k',
                  b'Tc', b'Tw', b'Tz', b'TL', b'Tf', b'Tr', b'Ts'}
PATH_END = {b'n', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'}
PAINT = PATH_END - {b'n'} | {b'Tj', b'TJ', b"'", b'"', b'Do', b'INLINE IMAGE', b'sh'}


def _prefix_clip(scope, diagnostics):
    """Find clips preceding all painting in this q scope, in scope coordinates."""
    matrix = fitz.Matrix(1, 0, 0, 1, 0, 0)
    path, pending, allowed, label_holes = [], None, None, []
    polygon = []
    rectangular = True
    for position,item in enumerate(scope.items):
        if isinstance(item, Scope):
            if any(not isinstance(tail,Scope) and tail[1] in (b'W',b'W*') for tail in scope.items[position+1:]):
                raise UnsupportedPDF('Clipping path after a nested graphics scope')
            break
        args, op = item
        if op in PAINT:
            if any(not isinstance(tail,Scope) and tail[1] in (b'W',b'W*') for tail in scope.items[position+1:]):
                raise UnsupportedPDF('Clipping path after painted content')
            break
        if op == b'cm':
            matrix = fitz.Matrix(*map(float, args)) * matrix
        elif op == b're':
            x, y, w, h = map(float, args)
            if abs(matrix.b) > 1e-8 or abs(matrix.c) > 1e-8:
                rectangular = False
            rect = fitz.Rect(min(x,x+w), min(y,y+h), max(x,x+w), max(y,y+h)) * matrix
            path.append((tuple(rect), 1 if w*h*matrix.a*matrix.d >= 0 else -1))
        elif op == b'm':
            if polygon:
                rectangular = False
            polygon = [tuple(fitz.Point(*map(float, args)) * matrix)]
        elif op == b'l':
            polygon.append(tuple(fitz.Point(*map(float, args)) * matrix))
        elif op == b'h':
            if len(polygon) == 4 and len({p[0] for p in polygon}) == 2 and len({p[1] for p in polygon}) == 2 and all(a[0] == b[0] or a[1] == b[1] for a,b in zip(polygon,polygon[1:]+polygon[:1])):
                area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1]))
                path.append(((min(p[0] for p in polygon),min(p[1] for p in polygon),max(p[0] for p in polygon),max(p[1] for p in polygon)),1 if area >= 0 else -1))
            else:
                rectangular = False
            polygon = []
        elif op in (b'c', b'v', b'y'):
            rectangular = False
        elif op in (b'W', b'W*'):
            pending = op
        elif op in PATH_END:
            if pending:
                if rectangular and path:
                    region = _rectangles(path, pending == b'W*')
                    allowed = region if allowed is None else [r for a in allowed for b in region if (r := _intersect(a,b))]
                    if pending == b'W*' and len(path) > 1:
                        outer = path[0][0]
                        holes = [r for r,_ in path[1:]]
                        # The numbering generator cuts small, disjoint rectangular
                        # label holes. Other even-odd paths use conservative bounds.
                        if all(_intersect(outer,r) == r for r in holes) and not any(_intersect(a,b) for i,a in enumerate(holes) for b in holes[i+1:]):
                            label_holes.extend(r for r in holes if r[2]-r[0] <= 120 and r[3]-r[1] <= 24)
                else:
                    diagnostics['nonrectangular_clips'] += 1
                pending = None
            path, polygon, rectangular = [], [], True
    return None if allowed is None else (allowed, label_holes)


class _Culler(fitz.mupdf.PdfSanitizeFilterOptions2):
    def __init__(self, rectangles, diagnostics, label_holes=()):
        super().__init__()
        self.rectangles, self.diagnostics = rectangles, diagnostics
        self.label_holes = label_holes
        self.use_virtual_culler()

    def culler(self, ctx, bbox, kind):
        # A removed clip subpath can enlarge visibility, especially W* holes.
        if kind in (0, 4, 5, 6, 7):
            return 0
        rect = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        # Paths and images can contribute antialiased edge pixels even when their
        # geometric bounds fall just outside the clip. Keep a half-point margin
        # for these objects; glyphs retain the tighter label-specific handling.
        padding = .5 if kind in (1,2,3,9,10) else .001
        rect = (rect[0]-padding, rect[1]-padding, rect[2]+padding, rect[3]+padding)
        remove = not any(_intersect(rect, visible) for visible in self.rectangles)
        if kind == 8 and not remove:
            x, y = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
            remove = any(h[0] < x < h[2] and h[1] < y < h[3]
                         and rect[0] >= h[0]-.002 and rect[2] <= h[2]+.002
                         and rect[3]-rect[1] <= 1.5*(h[3]-h[1]) for h in self.label_holes)
        if remove:
            key = 'removed_glyphs' if kind == 8 else 'removed_objects'
            self.diagnostics[key] += 1
        return int(remove)


def _filter(operations, resources, box, region, diagnostics):
    # Inline font dictionaries in temporary PDFs can otherwise collide with
    # another document's font cache entry when their indirect object IDs match.
    fitz.TOOLS.store_shrink(100)
    doc = fitz.open('pdf', _pdf(operations, resources, box))
    page = fitz._as_pdf_page(doc[0])
    culler = _Culler(region[0], diagnostics, region[1])
    options = fitz._make_PdfFilterOptions(sanitize=1, sopts=culler)
    fitz.mupdf.pdf_filter_page_contents(page.doc(), page, options)
    # The sanitizer may share an indirect-reference object between image
    # aliases. Renumbering xrefs in that live document can then rewrite the
    # same reference twice (an image becomes a font-width array). Temporary
    # pages only need unused objects removed; reparsing separates references
    # before the final document performs full compaction and deduplication.
    raw = doc.tobytes(garbage=1, deflate=True)
    doc.close()
    return PdfReader(BytesIO(raw))


def _same_glyph_paint(first, second):
    """Match visible text state before considering a raster sampling retry."""
    for key in ('font', 'type', 'wmode', 'flags', 'colorspace', 'layer'):
        if first.get(key) != second.get(key):
            return False
    for key, tolerance in [('size', .001), ('opacity', 1e-6), ('linewidth', .001)]:
        a, b = first.get(key), second.get(key)
        if a is None or b is None:
            if a != b:
                return False
        elif abs(a-b) > tolerance:
            return False
    return all(len(first.get(key, ())) == len(second.get(key, ())) and
               all(abs(a-b) <= 1e-6 for a,b in zip(first.get(key, ()),second.get(key, ())))
               for key in ('dir', 'color'))


def _matched_glyph_difference(original, cleaned, difference):
    """Require every >8 pixel to lie in an unchanged visible glyph's bounds.

    Sanitizing can round a text coordinate by a few float32 units. At a glyph
    cache subpixel boundary this changes antialiasing substantially, even though
    the glyph's identity, geometry and paint are unchanged. This gate excludes
    missing glyphs, moved text, recolouring and unrelated paths/images before
    the two additional full-page render comparisons are attempted.
    """
    channels = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
    changed = maximum.point(lambda value: 255 if value > 8 else 0)
    bounds = changed.getbbox()
    if bounds is None:
        return 0
    target = fitz.Rect(bounds) / 2
    fitz.TOOLS.store_shrink(100)
    source_spans = original.get_texttrace()
    fitz.TOOLS.store_shrink(100)
    result_spans = cleaned.get_texttrace()
    candidates = {}
    for span in source_spans:
        if span['type'] not in (0, 1) or not fitz.Rect(span['bbox']).intersects(target):
            continue
        for character in span['chars']:
            if fitz.Rect(character[3]).intersects(target):
                key = (span['font'],character[0],character[1])
                candidates.setdefault(key,[]).append((span,character))
    allowed = Image.new('L',difference.size,0)
    draw = ImageDraw.Draw(allowed)
    matched = 0
    for span in result_spans:
        if span['type'] not in (0, 1) or not fitz.Rect(span['bbox']).intersects(target):
            continue
        for character in span['chars']:
            if not fitz.Rect(character[3]).intersects(target):
                continue
            for old_span,old_character in candidates.get((span['font'],character[0],character[1]),[]):
                if (_same_glyph_paint(old_span,span) and
                    all(abs(a-b) <= .001 for a,b in zip(old_character[2],character[2])) and
                    all(abs(a-b) <= .001 for a,b in zip(old_character[3],character[3]))):
                    rect = (fitz.Rect(old_character[3]) | fitz.Rect(character[3])) * 2
                    draw.rectangle(tuple(rect),fill=255)
                    matched += 1
                    break
    return matched if ImageChops.subtract(changed,allowed).getbbox() is None else 0


def _path_maximum(image):
    channels = image.split()
    return ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])


def _path_touches(mask, rect, scale=2):
    rect = fitz.Rect(rect)*scale
    box = (max(0,math.floor(rect.x0)),max(0,math.floor(rect.y0)),
           min(mask.width,math.ceil(rect.x1)+1),min(mask.height,math.ceil(rect.y1)+1))
    return box[0] < box[2] and box[1] < box[3] and mask.crop(box).getbbox() is not None


def _path_supported(path):
    return (path['type'] == 's' and path['stroke_opacity'] == 1 and
            path.get('_context_safe',True) and 0 < path['width'] <= 2 and path['dashes'] == '[] 0' and
            not path.get('layer') and not path['closePath'] and
            len(set(path['lineCap'])) == 1 and
            all(item[0] in ('l','c') for item in path['items']) and
            _path_known_join(path))


def _path_known_join(path):
    # get_drawings does not expose the miter limit. Only smooth joins are
    # eligible for miter strokes; round/bevel joins do not use that limit.
    if path.get('lineJoin') != 0:
        return True
    # A zero-length segment has no join angle. Its cap is still reproduced by
    # the mask, and the full operator sequence remains part of identity checks.
    items = [item for item in path['items'] if any(point != item[1] for point in item[2:])]
    for first,second in zip(items,items[1:]):
        if first[-1] != second[1]:
            continue
        a,b = first[-1]-first[-2],second[2]-second[1]
        norm = math.hypot(*a)*math.hypot(*b)
        if norm == 0 or abs(a.x*b.y-a.y*b.x) > norm*1e-5 or a.x*b.x+a.y*b.y <= 0:
            return False
    return True


def _paths_with_context(page):
    active,paths = [],[]
    for entry in page.get_drawings(extended=True):
        active = [scope for scope in active if scope['level'] < entry['level']]
        if entry['type'] in ('clip','group'):
            active.append(entry)
            continue
        bounds = fitz.Rect(entry['rect']) + (-2,-2,2,2)
        safe = True
        hidden = False
        for scope in active:
            if scope['type'] == 'group':
                safe &= (scope['opacity'] == 1 and scope['blendmode'] == 'Normal'
                         and not scope['knockout'] and not scope.get('layer'))
                continue
            if fitz.Rect(scope['scissor']).is_empty:
                hidden = True
            rectangles = _path_clip_rectangles(scope['items'])
            if rectangles is None:
                safe = False
                continue
            outer = rectangles[0]
            safe &= outer.contains(bounds)
            if len(rectangles) > 1:
                holes = rectangles[1:]
                safe &= (scope['even_odd'] and all(outer.contains(hole) for hole in holes)
                         and not any(a.intersects(b) for i,a in enumerate(holes) for b in holes[i+1:])
                         and not any(bounds.intersects(hole) for hole in holes))
        entry['_context_safe'] = safe
        entry['_context_hidden'] = hidden
        entry['_validation_scopes'] = tuple(active)
        paths.append(entry)
    return paths


def _path_clip_rectangles(items):
    if items and all(item[0] == 're' for item in items):
        return [fitz.Rect(item[1]) for item in items]
    if len(items) == 4 and all(item[0] == 'l' for item in items):
        points = [item[1] for item in items]
        xs,ys = {p.x for p in points},{p.y for p in points}
        if (len(xs) == len(ys) == 2 and
            all(item[2] == following[1] for item,following in zip(items,items[1:]+items[:1])) and
            all(item[1].x == item[2].x or item[1].y == item[2].y for item in items)):
            return [fitz.Rect(min(xs),min(ys),max(xs),max(ys))]
    return None


def _same_path(first, second):
    if not _path_supported(first) or not _path_supported(second):
        return False
    for key in ('type','lineCap','lineJoin','closePath','dashes','stroke_opacity','color','layer'):
        if first.get(key) != second.get(key):
            return False
    if abs(first['width']-second['width']) > 1e-6 or len(first['items']) != len(second['items']):
        return False
    for a,b in zip(first['items'],second['items']):
        if a[0] != b[0] or len(a) != len(b):
            return False
        if any(abs(x-y) > .001 for p,q in zip(a[1:],b[1:]) for x,y in zip(p,q)):
            return False
    return True


def _stroke_mask(path, page_rect, size, scale=2, *, filled=False):
    """Rasterize actual curves; a bounding rectangle alone is not sufficient."""
    with fitz.open() as doc:
        page = doc.new_page(width=page_rect.width,height=page_rect.height)
        shape = page.new_shape()
        for item in path['items']:
            if item[0] == 'l':
                shape.draw_line(*item[1:])
            elif item[0] == 'c':
                shape.draw_bezier(*item[1:])
            else:
                raise ValueError('Unsupported path operator')
        if filled:
            shape.finish(color=None,fill=(0,0,0),even_odd=path['even_odd'],closePath=path['closePath'])
        else:
            shape.finish(color=(0,0,0),width=path['width'],lineCap=path['lineCap'][0],
                         lineJoin=path['lineJoin'],closePath=False)
        shape.commit()
        bounds = fitz.Rect(path['rect']) + (-2,-2,2,2)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False,clip=bounds)
        local = Image.frombytes('RGB',(pix.width,pix.height),pix.samples).convert('L')
        local = local.point(lambda value:255 if value < 255 else 0)
        mask = Image.new('L',size,0)
        mask.paste(local,(pix.x,pix.y))
        # One output pixel is the AA neighborhood, not a path-bounding-box fill.
        return mask.filter(ImageFilter.MaxFilter(3))


def _path_residual(first, second):
    upper = first.filter(ImageFilter.MaxFilter(3))
    lower = first.filter(ImageFilter.MinFilter(3))
    return ImageChops.lighter(ImageChops.subtract(second,upper),ImageChops.subtract(lower,second))


def _verify_path_sampling(original, cleaned, before, after):
    """Verify unchanged opaque strokes within their actual AA neighborhood."""
    snapshots = []
    text_inks = []
    for page,image in ((original,before),(cleaned,after)):
        fitz.TOOLS.store_shrink(100)
        snapshots.append((image,page.rect,_paths_with_context(page),page.get_bboxlog()))
        text_inks.append(text_ink_bounds(page))
    if before.size != after.size:
        return {'accepted':False,'reason':'dimensions'}
    diff = ImageChops.difference(before,after)
    maximum = _path_maximum(diff)
    changed = maximum.point(lambda value:255 if value > 8 else 0)
    evidence = {'initial_max_delta':maximum.getextrema()[1],
                'changed_pixels':changed.histogram()[255],
                'bbox':changed.getbbox()}
    if not changed.getbbox():
        return {**evidence,'accepted':True,'reason':'ordinary strict comparison'}
    support_for_selection = changed.filter(ImageFilter.MaxFilter(3))
    selected = []
    for _image,page_rect,paths,_log in snapshots:
        near = []
        for path in paths:
            if path.get('_context_hidden'):
                continue
            if not _path_touches(changed,fitz.Rect(path['rect'])+(-2,-2,2,2)):
                continue
            if _rect_fill_is_distant(path,support_for_selection):
                continue
            if not _path_supported(path):
                return {**evidence,'accepted':False,'reason':'unsupported nearby path'}
            mask = _stroke_mask(path,page_rect,before.size)
            if ImageChops.multiply(changed,mask).getbbox():
                near.append((path,mask))
        selected.append(near)
    evidence['selected_paths'] = [len(paths) for paths in selected]
    if not selected[0] or len(selected[0]) != len(selected[1]):
        return {**evidence,'accepted':False,'reason':'unmatched path count'}
    allowed = Image.new('L',before.size,0)
    # Retain paint order and multiplicity: deleting one of two overlapping
    # strokes must not borrow the surviving stroke as its structural match.
    for (old,old_mask),(new,new_mask) in zip(*selected):
        if not _same_path(old,new):
            return {**evidence,'accepted':False,'reason':'path geometry or paint differs'}
        allowed = ImageChops.lighter(allowed,ImageChops.lighter(old_mask,new_mask))
    if ImageChops.subtract(changed,allowed).getbbox():
        return {**evidence,'accepted':False,'reason':'difference outside actual stroke neighborhood'}
    # Only colors within one pixel of a differing pixel enter the neighborhood
    # calculation. An unrelated overlap elsewhere along a long path cannot
    # influence this comparison; an overlap inside this support must reject it.
    comparison_support = changed.filter(ImageFilter.MaxFilter(3))
    for (_image,_rect,_paths,log),ink in zip(snapshots,text_inks):
        hidden = {path['seqno'] for path in _paths if path.get('_context_hidden')}
        by_sequence = {path['seqno']:path for path in _paths}
        for seqno,(kind,bounds,*_rest) in enumerate(log):
            if seqno in hidden:
                continue
            if _rect_fill_is_distant(by_sequence.get(seqno,{}),comparison_support):
                continue
            if kind == 'fill-text' and filled_text_is_distant(ink.get(seqno),comparison_support):
                continue
            if kind != 'stroke-path' and _pixel_cells_touch(comparison_support,bounds):
                return {**evidence,'accepted':False,'reason':'overlapping '+kind}
    residual = ImageChops.lighter(_path_residual(before,after),_path_residual(after,before))
    evidence['neighborhood_max_delta'] = max(channel[1] for channel in residual.getextrema())
    return {**evidence,'accepted':evidence['neighborhood_max_delta'] <= 8,
            'reason':'matched opaque strokes, bidirectional one-pixel residual'}




def _fill_supported(path):
    return (path['type'] == 'f' and path['fill_opacity'] == 1 and
            path.get('_context_safe',True) and not path.get('layer') and
            path.get('fill') is not None and path['items'] and
            all(item[0] in ('l','c') for item in path['items']))


def _same_fill(first, second):
    if not _fill_supported(first) or not _fill_supported(second):
        return False
    if any(first.get(key) != second.get(key) for key in
           ('type','closePath','even_odd','fill_opacity','fill','layer')):
        return False
    if len(first['items']) != len(second['items']):
        return False
    for a,b in zip(first['items'],second['items']):
        if a[0] != b[0] or len(a) != len(b):
            return False
        if any(abs(x-y) > .001 for p,q in zip(a[1:],b[1:]) for x,y in zip(p,q)):
            return False
    return True


def _matched_fill_difference(original, cleaned, difference):
    """Gate two strict full-page phases; fills never use neighborhood tolerance."""
    changed = _path_maximum(difference).point(lambda value:255 if value > 8 else 0)
    if changed.getbbox() is None:
        return 0
    support_for_selection = changed.filter(ImageFilter.MaxFilter(3))
    selected,contexts = [],[]
    for page in (original,cleaned):
        fitz.TOOLS.store_shrink(100)
        paths = _paths_with_context(page)
        near = []
        for path in paths:
            if path.get('_context_hidden') or not _path_touches(changed,fitz.Rect(path['rect'])+(-2,-2,2,2)):
                continue
            if _rect_fill_is_distant(path,support_for_selection):
                continue
            if not _fill_supported(path):
                if _path_supported(path):
                    mask = _stroke_mask(path,page.rect,difference.size)
                    if ImageChops.multiply(changed,mask).getbbox() is None:
                        continue
                return 0
            mask = _stroke_mask(path,page.rect,difference.size,filled=True)
            if ImageChops.multiply(changed,mask).getbbox():
                near.append((path,mask))
        selected.append(near)
        contexts.append((paths,page.get_bboxlog(),text_ink_bounds(page)))
    if not selected[0] or len(selected[0]) != len(selected[1]):
        return 0
    allowed = Image.new('L',difference.size,0)
    for (old,old_mask),(new,new_mask) in zip(*selected):
        if not _same_fill(old,new):
            return 0
        allowed = ImageChops.lighter(allowed,ImageChops.lighter(old_mask,new_mask))
    if ImageChops.subtract(changed,allowed).getbbox():
        return 0
    support = changed.filter(ImageFilter.MaxFilter(3))
    for near,(paths,log,ink) in zip(selected,contexts):
        eligible = {path['seqno'] for path,_mask in near}
        hidden = {path['seqno'] for path in paths if path.get('_context_hidden')}
        by_sequence = {path['seqno']:path for path in paths}
        for seqno,(_kind,bounds,*_rest) in enumerate(log):
            if seqno not in eligible and seqno not in hidden and _pixel_cells_touch(support,bounds):
                if _kind == 'fill-text' and filled_text_is_distant(ink.get(seqno),support):
                    continue
                path = by_sequence.get(seqno)
                if _rect_fill_is_distant(path or {},support):
                    continue
                if path is not None and _path_supported(path):
                    mask = _stroke_mask(path,original.rect,difference.size)
                    if ImageChops.multiply(support,mask).getbbox() is None:
                        continue
                return 0
    return len(selected[0])



def _matching_label_spans(a,b):
    return (_same_glyph_paint(a,b) and len(a['chars'])==len(b['chars']) and
            all(x[:2]==y[:2] and all(abs(i-j)<=.001 for i,j in zip(x[2],y[2])) and
                all(abs(i-j)<=.001 for i,j in zip(x[3],y[3])) for x,y in zip(a['chars'],b['chars'])))

def _number_labels(page):
    fitz.TOOLS.store_shrink(100)
    return [s for s in page.get_texttrace() if s['type'] in (0,1) and s['opacity']>0 and
            re.fullmatch(r'\d+(?:-\d+)*',''.join(chr(c[0]) for c in s['chars']).strip())]

def _verify_label_edges(original, cleaned, holes, before, after):
    """Compatibility wrapper: require all differences to have label evidence."""
    proof = _label_coverage(original, cleaned, holes, before, after)
    return {**proof, 'accepted': proof['unprovenMax'] <= 8,
            'count': proof.get('rejectedCount', proof['count']),
            'maxDelta': _path_maximum(ImageChops.difference(before,after)).getextrema()[1]}




def _pixel_cells_touch(mask,bounds):
    """Half-open pixel cells with positive-area overlap against actual bounds."""
    rect=fitz.Rect(bounds)*2
    box=(max(0,math.floor(rect.x0)),max(0,math.floor(rect.y0)),
         min(mask.width,math.ceil(rect.x1)),min(mask.height,math.ceil(rect.y1)))
    return box[0]<box[2]and box[1]<box[3]and mask.crop(box).getbbox()is not None


def _rect_fill_is_distant(path,support):
    """Only exclude a fill when every actual rectangle is outside support.

    Clipping, alpha and blend modes can reduce or recolour coverage, but cannot
    paint outside a rectangle filled without stroke. The half-point margin is
    one 144-dpi antialias pixel, in addition to the caller's one-pixel support.
    This does not make rectangular fills eligible as structural matches.
    """
    if path.get('type')!='f' or not path.get('items'):return False
    for item in path['items']:
        if len(item)!=3 or item[0]!='re':return False
        rect=fitz.Rect(item[1])
        if not all(math.isfinite(v)for v in rect)or rect.is_empty:return False
        if _path_touches(support,rect+(-.5,-.5,.5,.5)):return False
    return True


def _label_ink_matches_pixel(pixel,span):
    """Require an opaque DeviceGray/RGB numeral painted over white.

    Coverage is unknown because this is an antialiased edge. All channels must
    agree with one coverage value; arbitrary colored pixels cannot borrow a
    nearby black numeral's bounding box as proof.
    """
    if span.get('opacity')!=1:return False
    color=span.get('color',())
    if span.get('colorspace')==1 and len(color)==1:color=color*3
    elif span.get('colorspace')!=3 or len(color)!=3:return False
    if not all(0<=c<=1 for c in color):return False
    ink=[255*(1-c)for c in color]
    channel=max(range(3),key=lambda i:ink[i])
    if ink[channel]<=0:return False
    coverage=(255-pixel[channel])/ink[channel]
    return (0<coverage<=1 and
            all(abs(pixel[i]-(255-coverage*ink[i]))<=1 for i in range(3)))


def _same_opaque_ink(first,second):
    return (first.get('type')==second.get('type')==0 and
            first.get('opacity')==second.get('opacity')==1 and
            first.get('colorspace')==second.get('colorspace') and
            first.get('color')==second.get('color'))


def _unmatched_nonlabel_glyphs(original,cleaned):
    """Match visible body glyphs once, retaining paint count and paint order."""
    visible=[]
    for page in (original,cleaned):
        fitz.TOOLS.store_shrink(100)
        traces=[s for s in page.get_texttrace() if s['type'] in (0,1) and s['opacity']>0 and
                not re.fullmatch(r'\d+(?:-\d+)*',''.join(chr(c[0])for c in s['chars']).strip())]
        visibility=scissors(page) if isinstance(page,fitz.Page) else None
        glyphs=[]
        for span in traces:
            for char in span['chars']:
                bounds=fitz.Rect(char[3])
                if visibility is not None:
                    clip=visibility[span['seqno']]
                    if clip.is_empty:continue
                    # Exclude only definitely hidden glyphs before matching.
                    # A hidden duplicate must not consume a visible match.
                    bounds &= clip+(-.5,-.5,.5,.5)
                    if bounds.is_empty:continue
                glyphs.append((span,char,bounds))
        visible.append(glyphs)
    candidates={}
    for index,(span,char,_bounds) in enumerate(visible[1]):
        candidates.setdefault((span['font'],char[0],char[1]),[]).append(index)
    consumed=set();unmatched=[];last=-1
    for span,char,bounds in visible[0]:
        match=None
        for index in candidates.get((span['font'],char[0],char[1]),[]):
            if index<=last:continue
            other,counterpart,_=visible[1][index]
            if (_same_glyph_paint(span,other) and
                    all(abs(a-b)<=.001 for a,b in zip(char[2],counterpart[2])) and
                    all(abs(a-b)<=.001 for a,b in zip(char[3],counterpart[3]))):
                match=index
                break
        if match is not None:
            consumed.add(match)
            last=match
        else:
            unmatched.append(bounds)
    unmatched.extend(bounds for index,(_span,_char,bounds) in enumerate(visible[1]) if index not in consumed)
    return unmatched


def _nontext_paint_bounds(original,cleaned):
    """Foreign graphics cannot borrow an old number's metric rectangle."""
    result=[]
    for page in (original,cleaned):
        if not isinstance(page,fitz.Page):continue
        fitz.TOOLS.store_shrink(100)
        log=page.get_bboxlog()
        if not any(kind not in ('fill-text','stroke-text','ignore-text')for kind,_box in log):continue
        visibility=scissors(page)
        paths={path['seqno']:path for path in page.get_drawings()}
        for seq,(kind,box)in enumerate(log):
            if kind in ('fill-text','stroke-text','ignore-text'):continue
            clip=visibility[seq]
            if clip.is_empty:continue
            path=paths.get(seq)
            if kind=='fill-path' and path and path['type']=='f' and path['items'] and all(item[0]=='re'for item in path['items']):
                # Independent filled rectangles do not paint their union's
                # empty gaps. Stroke, curves and unknown records stay bounded
                # by MuPDF's conservative whole paint bbox instead.
                bounds=[fitz.Rect(item[1])for item in path['items']]
            else:bounds=[fitz.Rect(box)]
            for rect in bounds:
                rect=(rect+(-.5,-.5,.5,.5))&(clip+(-.5,-.5,.5,.5))
                if not rect.is_empty:result.append(rect)
    return result


def _label_coverage(original,cleaned,holes,before,after,offset=(0,0),scale=2):
    """Return individually proven label-edge pixels, leaving others unapproved.

    The fixed one-pixel hole perimeter, 128-pixel/page bound and whole unchanged
    replacement spans remain mandatory. The pixel's actual square must overlap
    both the removed glyph's metric box and (for nonwhite output) the retained
    replacement glyph's box. A nonwhite result must be the same opaque ink over
    white, with coverage reduced; arbitrary recolouring is not explained.
    """
    sx,sy=(scale,scale) if isinstance(scale,(int,float)) else scale
    if any(not math.isfinite(v) or v <= 0 for v in (sx,sy)):
        raise ValueError('Label evidence requires finite positive pixel scales')
    maximum=_path_maximum(ImageChops.difference(before,after))
    bbox=maximum.point(lambda value:255 if value>8 else 0).getbbox()
    if not bbox:return {'covered':[],'proof':[],'count':0,'unprovenMax':maximum.getextrema()[1]}
    changed=[(x,y)for y in range(bbox[1],bbox[3])for x in range(bbox[0],bbox[2])
             if maximum.getpixel((x,y))>8]
    old,new=_number_labels(original),_number_labels(cleaned)
    kept=[s for s in new if any(c[0]==45 for c in s['chars']) and
          any(_matching_label_spans(s,t)for t in old)]
    removed=[s for s in old if not any(_matching_label_spans(s,t)for t in new)]
    unrelated=_unmatched_nonlabel_glyphs(original,cleaned)+_nontext_paint_bounds(original,cleaned)
    proof=[]
    def covers(span,p):
        x,y=p;dx,dy=offset
        cell=fitz.Rect((x-dx)/sx,(y-dy)/sy,(x+1-dx)/sx,(y+1-dy)/sy)
        return any(fitz.Rect(c[3]).intersects(cell)for c in span['chars'])
    for hole in holes:
        rect=fitz.Rect(hole)*original.transformation_matrix
        screen=rect*fitz.Matrix(sx,sy)+(*offset,*offset)
        replacements=[s for s in kept if fitz.Rect(s['bbox']).intersects(rect) and
                      all(rect.y0-1<=c[2][1]<=rect.y1+1 for c in s['chars'])]
        if not replacements:continue
        discarded=[s for s in removed if fitz.Rect(s['bbox']).intersects(rect)]
        proven=[]
        for p in changed:
            x,y=p;xx,yy=x+.5,y+.5
            outer=screen.x0-1<=xx<=screen.x1+1 and screen.y0-1<=yy<=screen.y1+1
            inner=screen.x0+1<xx<screen.x1-1 and screen.y0+1<yy<screen.y1-1
            if not outer or inner:continue
            dx,dy=offset
            cell=fitz.Rect((x-dx)/sx,(y-dy)/sy,(x+1-dx)/sx,(y+1-dy)/sy)
            if any(rect.intersects(cell)for rect in unrelated):continue
            a,b=before.getpixel(p),after.getpixel(p)
            # Removing old ink must lighten every channel, never darken it.
            if any(i>j for i,j in zip(a,b)):continue
            for source in discarded:
                if not covers(source,p)or not _label_ink_matches_pixel(a,source):continue
                if b==(255,255,255)or any(_same_opaque_ink(source,target)and covers(target,p)and
                    _label_ink_matches_pixel(b,target)for target in replacements):
                    proven.append(p);break
        if proven:proof.append({'hole':list(rect),'pixels':proven,
                                'keptLabels':[''.join(chr(c[0])for c in s['chars'])for s in replacements],
                                'removedLabels':[''.join(chr(c[0])for c in s['chars'])for s in discarded]})
    covered=set(p for item in proof for p in item['pixels'])
    if len(covered)>128:return {'covered':[],'proof':[],'count':0,'rejectedCount':len(covered),
                              'unprovenMax':maximum.getextrema()[1]}
    remaining=maximum.copy()
    for p in covered:remaining.putpixel(p,0)
    return {'covered':sorted(covered),'proof':proof,'count':len(covered),
            'unprovenMax':remaining.getextrema()[1]}


def _exact_stroke_supported(path):
    return (path['type']=='s'and path['stroke_opacity']==1 and path.get('_context_safe',True)and
            not path.get('layer')and 0<path['width']<=2 and path['dashes']=='[] 0'and
            not path['closePath']and len(set(path['lineCap']))==1 and
            all(i[0]in ('l','c')for i in path['items']))


def _local_vector_context(path, support):
    """Prove the sampled neighborhood is wholly inside every known clip.

    An otherwise identical curve may be clipped far away from the pixels
    compared here. The exact paint mask retains those clips; this proof only
    admits local samples with an additional half-point clearance from all
    rectangle edges and holes. Unknown clip geometry remains unsupported.
    """
    box = support.getbbox()
    if box is None:
        return False
    bounds = fitz.Rect(*(value / 2 for value in box)) + (-.5,-.5,.5,.5)
    for scope in path.get('_validation_scopes', ()):
        if scope['type'] == 'group':
            if (scope['opacity'] != 1 or scope['blendmode'] != 'Normal'
                    or scope['knockout'] or scope.get('layer')):
                return False
            continue
        rectangles = _path_clip_rectangles(scope['items'])
        if not rectangles or any(not all(math.isfinite(v) for v in r) for r in rectangles):
            return False
        outer, *holes = rectangles
        if not outer.contains(bounds):
            return False
        if holes and (not scope['even_odd'] or
                not all(outer.contains(hole) for hole in holes) or
                any(a.intersects(b) for i,a in enumerate(holes) for b in holes[i+1:]) or
                any(bounds.intersects(hole) for hole in holes)):
            return False
    return True


def _same_exact_stroke(first, second):
    if not _exact_stroke_supported(first) or not _exact_stroke_supported(second):
        return False
    for key in ('type','lineCap','lineJoin','closePath','dashes','stroke_opacity','color','layer'):
        if first.get(key) != second.get(key):
            return False
    if abs(first['width']-second['width']) > 1e-6 or len(first['items']) != len(second['items']):
        return False
    for a,b in zip(first['items'],second['items']):
        if a[0] != b[0] or len(a) != len(b):
            return False
        if any(abs(x-y) > .001 for p,q in zip(a[1:],b[1:]) for x,y in zip(p,q)):
            return False
    return True


def _same_exact_vector_state(a,b):
    for key in ('kind','alpha','start_cap','dash_cap','end_cap','linejoin','linewidth',
                'miterlimit','dash_phase','dash_len','dash_list','even_odd'):
        if a.get(key)!=b.get(key):return False
    if a.get('alpha')!=1:return False
    # Geometry is compared after the full transform. Require identical linear
    # CTMs too, so scalar linewidth never hides anisotropic stroke changes.
    if a['ctm'][:4]!=b['ctm'][:4]:return False
    return all(math.isfinite(v)for v in a['ctm']+b['ctm'])and all(abs(x-y)<=.002 for x,y in zip(a['ctm'][4:],b['ctm'][4:]))


def _verify_opaque_vectors(source,target,before,after):
    difference=ImageChops.difference(before,after)
    maximum=_path_maximum(difference);changed=maximum.point(lambda x:255 if x>8 else 0)
    evidence={'initialMax':maximum.getextrema()[1],'changedPixels':changed.histogram()[255]}
    if not changed.getbbox():return {**evidence,'accepted':True,'reason':'strict ordinary'}
    support=changed.filter(ImageFilter.MaxFilter(3));contexts=[];selected=[]
    for page in (source,target):
        fitz.TOOLS.store_shrink(100);paths=_paths_with_context(page);log=page.get_bboxlog()
        visibility=scissors(page);ink=text_ink_bounds(page);cache={};near=[]
        for path in paths:
            seq=path['seqno']
            if path['_context_hidden']or visibility[seq].is_empty or not _pixel_cells_touch(support,log[seq][1]):continue
            alpha,proof=exact_paint_mask(page,[seq]);actual=alpha.point(lambda x:255 if x else 0)
            cache[seq]=actual
            if not ImageChops.multiply(support,actual).getbbox():continue
            if not path['_context_safe'] and _local_vector_context(path,support):
                path = {**path, '_context_safe':True}
            if not(_fill_supported(path)or _exact_stroke_supported(path)):
                return {**evidence,'accepted':False,'reason':'unsupported actual overlapping vector','seq':seq}
            near.append((path,actual,proof[seq]))
        selected.append(near);contexts.append((page,log,visibility,ink,cache))
    if not selected[0]or len(selected[0])!=len(selected[1]):
        return {**evidence,'accepted':False,'reason':'paint count differs','counts':[len(p)for p in selected]}
    allowed=Image.new('L',difference.size,0);colors=set()
    for (old,oldmask,oldstate),(new,newmask,newstate)in zip(*selected):
        if old['type']!=new['type']or not(_same_fill(old,new)if old['type']=='f'else _same_exact_stroke(old,new))or not _same_exact_vector_state(oldstate,newstate):
            return {**evidence,'accepted':False,'reason':'geometry or exact paint state differs'}
        colors.add(tuple(old['fill']if old['type']=='f'else old['color']))
        allowed=ImageChops.lighter(allowed,ImageChops.lighter(oldmask,newmask))
    if len(colors)!=1:return {**evidence,'accepted':False,'reason':'multiple ink colours'}
    if ImageChops.subtract(changed,allowed.filter(ImageFilter.MaxFilter(3))).getbbox():
        return {**evidence,'accepted':False,'reason':'difference outside actual ink neighborhood'}
    for near,(page,log,visibility,ink,cache)in zip(selected,contexts):
        eligible={path['seqno']for path,_,_ in near}
        for seq,(kind,bounds,*_)in enumerate(log):
            if seq in eligible or visibility[seq].is_empty or not _pixel_cells_touch(support,fitz.Rect(bounds)&visibility[seq]):continue
            if kind=='fill-text'and filled_text_is_distant(ink.get(seq),support):continue
            if seq in cache and not ImageChops.multiply(support,cache[seq]).getbbox():continue
            return {**evidence,'accepted':False,'reason':'overlapping '+kind,'seq':seq}
    residual=ImageChops.lighter(_path_residual(before,after),_path_residual(after,before))
    delta=max(x[1]for x in residual.getextrema())
    return {**evidence,'accepted':delta<=8,'residual':delta,'matched':len(selected[0]),
            'types':[p['type']for p,_,_ in selected[0]],
            'miterLimits':[s.get('miterlimit')for _,_,s in selected[0]]}


def _image_fingerprint(document,xref,seen=()):
    if not isinstance(xref,int) or xref<=0 or xref in seen:return None
    allowed={'Type','Subtype','Width','Height','BitsPerComponent','ColorSpace','Decode','Interpolate',
             'Intent','Filter','DecodeParms','SMask','Mask','Matte','ImageMask','Length'}
    keys=set(document.xref_get_keys(xref))
    if not keys<=allowed:return None
    if document.xref_get_key(xref,'Subtype')!=('name','/Image'):return None
    cs=document.xref_get_key(xref,'ColorSpace')
    if cs not in [('name','/DeviceGray'),('name','/DeviceRGB')]:return None
    result=[]
    for key in sorted(keys-{'Length'}):
        kind,value=document.xref_get_key(xref,key)
        if kind=='xref':
            if key not in ('SMask','Mask'):return None
            child=_image_fingerprint(document,int(value.split()[0]),(*seen,xref))
            if child is None:return None
            result.append((key,child))
        else:
            if re.search(r'\b\d+\s+\d+\s+R\b',value):return None
            result.append((key,kind,' '.join(value.split())))
    raw=document.xref_stream_raw(xref)
    if raw is None:return None
    return (sha256(raw).hexdigest(),tuple(result))

def _matched_image_difference(source,target,difference):
    maximum=_path_maximum(difference)
    changed=maximum.point(lambda value:255 if value>8 else 0)
    if not changed.getbbox():return {'matched':0,'reason':'strict ordinary'}
    support=changed.filter(ImageFilter.MaxFilter(3));selected=[];contexts=[]
    for page in (source,target):
        fitz.TOOLS.store_shrink(100)
        state=image_paints(page)
        visibility=state['scissors'];log=page.get_bboxlog()
        image_calls=state['images']
        info=page.get_image_info(hashes=True,xrefs=True)
        if len(info)!=len(image_calls):return {'matched':0,'reason':'image occurrence sequence differs'}
        near=[];resource_images=None;verified_fingerprints={}
        for (seq,paint),image in zip(image_calls.items(),info):
            if image['bbox']!=log[seq][1]:return {'matched':0,'reason':'image occurrence bounds differ'}
            bounds=fitz.Rect(image['bbox'])&visibility[seq]
            if bounds.is_empty or not _pixel_cells_touch(support,bounds):continue
            if not paint['context_safe'] or paint['alpha']!=1:
                return {'matched':0,'reason':'unknown image paint context','seq':seq}
            digest=image['digest']
            if digest not in verified_fingerprints:
                # get_image_info resolves xrefs by RGB digest, omitting masks.
                # A hash shared by different soft masks is therefore ambiguous.
                # Only use that mapping when every matching resource has the
                # same complete image-and-mask identity.
                if resource_images is None:
                    resource_images={}
                    for resource in page.get_images():
                        pix=fitz.Pixmap(page.parent,resource[0])
                        resource_images.setdefault(pix.digest,set()).add(resource[0])
                fingerprints={_image_fingerprint(page.parent,xref)for xref in resource_images.get(digest,())}
                verified_fingerprints[digest]=next(iter(fingerprints)) if len(fingerprints)==1 and None not in fingerprints else None
            fingerprint=verified_fingerprints[digest]
            if fingerprint is None:return {'matched':0,'reason':'unsupported image resource'}
            near.append((seq,paint,image,bounds,fingerprint))
        selected.append(near);contexts.append((log,visibility))
    if not selected[0]or len(selected[0])!=len(selected[1]):
        return {'matched':0,'reason':'image paint count differs','counts':[len(v)for v in selected]}
    allowed=Image.new('L',difference.size,0);draw=ImageDraw.Draw(allowed)
    for old,new in zip(*selected):
        _seq,paint,image,bounds,fingerprint=old
        _other,other,target_image,target_bounds,target_fingerprint=new
        if (fingerprint!=target_fingerprint or paint!=other or
                any(image[k]!=target_image[k]for k in ('transform','width','height','colorspace','bpc','has-mask')) or
                bounds!=target_bounds):
            return {'matched':0,'reason':'image bytes, paint, transform or clipping differs'}
        r=bounds*2
        box=(max(0,math.floor(r.x0)),max(0,math.floor(r.y0)),
             min(allowed.width,math.ceil(r.x1)),min(allowed.height,math.ceil(r.y1)))
        draw.rectangle((box[0],box[1],box[2]-1,box[3]-1),fill=255)
    if ImageChops.subtract(changed,allowed).getbbox():return {'matched':0,'reason':'difference outside image cells'}
    for near,(log,visibility)in zip(selected,contexts):
        chosen={item[0]for item in near}
        for seq,(kind,bounds)in enumerate(log):
            if seq in chosen:continue
            active=fitz.Rect(bounds)&visibility[seq]
            if not active.is_empty and _pixel_cells_touch(support,active):
                return {'matched':0,'reason':'overlapping '+kind,'seq':seq}
    return {'matched':len(selected[0]),'reason':'identical image calls and independent local support'}


def clean_source_page(page, reader, *, diagnostics=None):
    """Return a one-page PDF with flattened Forms and cleaned rect-clip scopes.

    The original page and reader are not mutated. A diagnostics dict may be
    supplied to record removed content and retained non-rectangular clipping.
    Font subsetting is deliberately left to the final assembled document.
    Every result is compared with the original page at 144 dpi. Outside known
    old-number holes every channel must stay within 8/255. Removing overlapping
    old labels may remove at most 128 paint-matched edge pixels on those holes'
    one-pixel perimeter, with unchanged replacement labels proved explicitly.
    A float-rounded glyph must retain its identity, placement and paint and pass
    two further 144 dpi sampling phases with the same 8/255 threshold. Unchanged
    opaque strokes may instead pass a two-way one-pixel neighborhood check at
    the same threshold, only within their verified stroke geometry and paint.
    If that complete vector proof still has renderer-dependent sampling noise,
    independent PDFium renders at both 144 and 288 dpi must each pass the same
    strict threshold, with old-label ownership proved separately at each scale.
    """
    stats = diagnostics if diagnostics is not None else {}
    for key in ('cleaned_scopes', 'removed_glyphs', 'removed_objects', 'nonrectangular_clips'):
        stats.setdefault(key, 0)
    if page.get('/Group') or page.get('/Rotate', 0) or page.get('/UserUnit', 1) != 1:
        raise UnsupportedPDF('Page transparency, rotation or non-default UserUnit')
    if page.cropbox != page.mediabox:
        raise UnsupportedPDF('Non-default page CropBox requires explicit clipping')
    resources = Resources()
    resources.readers.append(reader)
    operations = resources.import_ops(page['/Contents'], page['/Resources'], reader)
    root = _scopes(operations)
    label_holes = []

    def process(scope, inherited, in_text=False, initial_ctm=None):
        initial_ctm = fitz.Matrix(1,0,0,1,0,0) if initial_ctm is None else initial_ctm
        current_ctm = fitz.Matrix(initial_ctm)
        current = list(inherited)
        body = []
        for item in scope.items:
            if isinstance(item, Scope):
                child = process(item, current, in_text, current_ctm)
                body.extend([([], b'q'), *child, ([], b'Q')])
            else:
                args, op = item
                body.append(item)
                if op == b'cm':
                    current_ctm = fitz.Matrix(*map(float,args)) * current_ctm
                elif op == b'BT':
                    in_text = True
                elif op == b'ET':
                    in_text = False
                elif op in GRAPHICS_STATE:
                    current.append(item)
        region = _prefix_clip(scope, stats)
        if region is None:
            return body
        if in_text:
            raise UnsupportedPDF('Clipping scope crosses a text object boundary')
        label_holes.extend(fitz.Rect(hole)*initial_ctm for hole in region[1])
        cleaned = _filter([([], b'q'), *inherited, *body, ([], b'Q')], resources.data, page.mediabox, region, stats)
        resources.readers.append(cleaned)
        stats['cleaned_scopes'] += 1
        p = cleaned.pages[0]
        return resources.import_ops(p['/Contents'], p['/Resources'], cleaned)

    result = process(root, [])
    fitz.TOOLS.store_shrink(100)
    cleaned = fitz.open('pdf', _pdf(result, resources.data, page.mediabox))
    cleaned[0].clean_contents()
    raw = cleaned.tobytes(garbage=1, deflate=True)
    # Garbage collection can renumber resources while a live MuPDF document
    # still has loaded font objects. Verify the bytes we actually return in a
    # fresh document, rather than rendering through those stale live caches.
    cleaned.close()
    cleaned = fitz.open('pdf', raw)
    source_writer = PdfWriter()
    source_writer.add_page(page)
    source_buffer = BytesIO()
    source_writer.write(source_buffer)
    original = fitz.open('pdf', source_buffer.getvalue())
    fitz.TOOLS.store_shrink(100)
    source_pix = original[0].get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
    fitz.TOOLS.store_shrink(100)
    result_pix = cleaned[0].get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
    if (source_pix.width, source_pix.height) != (result_pix.width, result_pix.height):
        raise UnsupportedPDF('Cleanup changed page dimensions')
    before = Image.frombytes('RGB', (source_pix.width, source_pix.height), source_pix.samples)
    after = Image.frombytes('RGB', (result_pix.width, result_pix.height), result_pix.samples)
    difference = ImageChops.difference(before,after)
    delta = max(pair[1] for pair in difference.getextrema())
    if delta > 8 and any(_object(pattern).get('/PatternType') == 1
                         for pattern in resources.data.get('/Pattern',{}).values()):
        # A clipped-away invocation can populate MuPDF's tile cache with a
        # different subpixel phase. Compare both untouched source and result
        # with tile caching disabled; all drawing operators still run normally.
        from pdf_render_verify import render_no_tile_cache
        stats['render_cached_max_delta'] = delta
        fitz.TOOLS.store_shrink(100)
        source_pix = render_no_tile_cache(original[0])
        fitz.TOOLS.store_shrink(100)
        result_pix = render_no_tile_cache(cleaned[0])
        before = Image.frombytes('RGB',(source_pix.width,source_pix.height),source_pix.samples)
        after = Image.frombytes('RGB',(result_pix.width,result_pix.height),result_pix.samples)
        difference = ImageChops.difference(before,after)
        delta = max(pair[1] for pair in difference.getextrema())
        stats['tile_cache_disabled'] = True
    initial_delta = delta
    stats['render_max_delta'] = delta
    evidence_before = before
    if delta > 8 and label_holes:
        label_proof = _label_coverage(original[0],cleaned[0],label_holes,before,after)
        if label_proof['count']:
            evidence_before = before.copy()
            for pixel in label_proof['covered']:
                evidence_before.putpixel(pixel,after.getpixel(pixel))
            stats['label_edge_pixels'] = label_proof['count']
            stats['label_edge_max_delta'] = initial_delta
            stats['label_edge_proof'] = label_proof['proof']
            delta = label_proof['unprovenMax']
            stats['render_initial_max_delta'] = initial_delta
            stats['render_max_delta'] = delta
    difference = ImageChops.difference(evidence_before,after)
    phase_evidence = None

    def sampling_phases():
        nonlocal phase_evidence
        if phase_evidence is None:
            phase_evidence = []
            for offset in ((.37,.23),(.73,.61)):
                images = []
                for document in (original,cleaned):
                    fitz.TOOLS.store_shrink(100)
                    if stats.get('tile_cache_disabled'):
                        pix = render_no_tile_cache(document[0],offset=offset)
                    else:
                        pix = document[0].get_pixmap(matrix=fitz.Matrix(2,0,0,2,*offset),alpha=False)
                    images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
                if images[0].size != images[1].size:
                    raise UnsupportedPDF('Sampling phase changed page dimensions')
                if label_holes:
                    label = _label_coverage(original[0],cleaned[0],label_holes,*images,offset=offset)
                    phase_evidence.append({'delta':label['unprovenMax'],'label_pixels':label['count']})
                else:
                    phase_evidence.append({'delta':_path_maximum(ImageChops.difference(*images)).getextrema()[1],
                                           'label_pixels':0})
        return [phase['delta'] for phase in phase_evidence]

    for kind,matcher in [('glyph',_matched_glyph_difference),('fill',_matched_fill_difference)]:
        if delta <= 8:
            break
        matched = matcher(original[0],cleaned[0],difference)
        if matched:
            phase_deltas = sampling_phases()
            if max(phase_deltas) <= 8:
                stats['render_initial_max_delta'] = initial_delta
                stats[kind+'_sampling_phase_deltas'] = phase_deltas
                stats[kind+'_sampling_matched'] = matched
                stats['sampling_phase_label_pixels'] = [p['label_pixels'] for p in phase_evidence]
                delta = max(phase_deltas)
                stats['render_max_delta'] = delta
    if delta > 8:
        proof = _matched_image_difference(original[0],cleaned[0],difference)
        if proof['matched']:
            phase_deltas = sampling_phases()
            if max(phase_deltas) <= 8:
                stats['render_initial_max_delta'] = initial_delta
                stats['image_sampling_proof'] = proof
                stats['image_sampling_phase_deltas'] = phase_deltas
                stats['sampling_phase_label_pixels'] = [p['label_pixels'] for p in phase_evidence]
                delta = max(phase_deltas)
                stats['render_max_delta'] = delta
    if delta > 8:
        proof = _verify_path_sampling(original[0],cleaned[0],evidence_before,after)
        if proof['accepted']:
            stats['render_initial_max_delta'] = initial_delta
            stats['path_sampling_proof'] = proof
            delta = proof['neighborhood_max_delta']
            stats['render_max_delta'] = delta
    if delta > 8:
        proof = _verify_opaque_vectors(original[0],cleaned[0],evidence_before,after)
        if proof['accepted']:
            stats['render_initial_max_delta'] = initial_delta
            stats['opaque_vector_proof'] = proof
            delta = proof['residual']
            stats['render_max_delta'] = delta
        elif proof.get('matched'):
            # A complete structural/paint proof can also use the two full-page
            # strict samplings. Each phase independently proves old-number ink.
            phase_deltas = sampling_phases()
            if max(phase_deltas) <= 8:
                stats['render_initial_max_delta'] = initial_delta
                stats['opaque_vector_proof'] = proof
                stats['vector_sampling_phase_deltas'] = phase_deltas
                stats['sampling_phase_label_pixels'] = [p['label_pixels'] for p in phase_evidence]
                delta = max(phase_deltas)
                stats['render_max_delta'] = delta
            else:
                from pdf_render_verify import render_pdfium
                checks=[]
                size=(original[0].rect.width,original[0].rect.height)
                for scale in (2,4):
                    left,left_scale=render_pdfium(source_buffer.getvalue(),size,scale)
                    right,right_scale=render_pdfium(raw,size,scale)
                    if left.size!=right.size or left_scale!=right_scale:
                        raise UnsupportedPDF('Independent renderer pixel coordinates differ')
                    label=_label_coverage(original[0],cleaned[0],label_holes,
                                          left,right,scale=left_scale)
                    checks.append({'dpi':scale*72,'pixel_scales':list(left_scale),
                                   'initial_max_delta':_path_maximum(ImageChops.difference(left,right)).getextrema()[1],
                                   'label_pixels':label['count'],'max_delta':label['unprovenMax']})
                stats['independent_renderer']='PDFium'
                stats['independent_render_checks']=checks
                if max(item['max_delta'] for item in checks)<=8:
                    stats['render_initial_max_delta']=initial_delta
                    stats['opaque_vector_proof']=proof
                    delta=max(item['max_delta'] for item in checks)
                    stats['render_max_delta']=delta
    original.close()
    cleaned.close()
    if delta > 8:
        raise UnsupportedPDF(f'Cleanup changed rendered content (maximum channel delta {delta}/255)')
    return raw
