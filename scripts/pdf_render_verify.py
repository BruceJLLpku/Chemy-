"""Render without reusing MuPDF tiling-pattern tiles for visual verification.

MuPDF 1.27's tile cache can reuse a tile rasterized at another fractional
translation. Removing a hidden earlier Form can then change its later cached
appearance. This device forwards every drawing operation unchanged except the
tile cache ID: zero asks MuPDF to render the tile again. Image interpolation,
antialiasing, colour, clipping and the PDF contents are not changed.
"""
import math
import hashlib

import pymupdf as fitz
from PIL import Image


_METHODS = (
    'close_device', 'fill_path', 'stroke_path', 'clip_path', 'clip_stroke_path',
    'fill_text', 'stroke_text', 'clip_text', 'clip_stroke_text', 'ignore_text',
    'fill_shade', 'fill_image', 'fill_image_mask', 'clip_image_mask', 'pop_clip',
    'begin_mask', 'end_mask', 'begin_group', 'end_group', 'begin_tile', 'end_tile',
    'render_flags', 'set_default_colorspaces', 'begin_layer', 'end_layer',
    'begin_structure', 'end_structure', 'begin_metatext', 'end_metatext',
)


def _forward(name):
    target_name = {'end_mask': 'end_mask_tr', 'begin_tile': 'begin_tile_tid'}.get(name, name)
    # Director callbacks supply C pointers, including float* colour arrays.
    # Some public Python wrappers instead require Python colour tuples, so use
    # the unchanged SWIG low-level bindings from the pinned PyMuPDF version.
    target = getattr(fitz.mupdf._mupdf, 'll_fz_' + target_name)

    def call(self, _context, *args):
        if name == 'begin_tile':
            args = (*args[:-2], 0, args[-1])
        return target(self._draw_device.m_internal, *args)
    return call


class _NoTileCache(fitz.mupdf.FzDevice2):
    def __init__(self, draw_device):
        super().__init__()
        available = {name.removeprefix('use_virtual_') for name in dir(fitz.mupdf.FzDevice2)
                     if name.startswith('use_virtual_')}
        # drop_device is a lifetime callback: the owned draw_device is released
        # by its Python wrapper. Forwarding it would drop that device twice.
        if available != set(_METHODS) | {'drop_device'}:
            raise RuntimeError('MuPDF drawing API changed; review the verification forwarding device')
        self._draw_device = draw_device
        for name in _METHODS:
            getattr(self, 'use_virtual_' + name)()


for _method in _METHODS:
    setattr(_NoTileCache, _method, _forward(_method))


def render_no_tile_cache(page, scale=2, *, offset=(0, 0)):
    """Return an RGB/white-background Pixmap, retaining normal drawing settings.

Use this for both sides of a failed comparison involving a tiling pattern. It
is a renderer diagnostic, not a reason to accept a changed image or PDF.
"""
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Render scale must be positive and finite')
    if (not isinstance(offset, (tuple, list)) or len(offset) != 2 or
        any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in offset)):
        raise ValueError('Render offset must contain two finite numbers')
    mupdf = fitz.mupdf
    transform = fitz.JM_matrix_from_py(fitz.Matrix(scale, 0, 0, scale, *offset))
    rectangle = mupdf.fz_transform_rect(mupdf.fz_bound_page(page.this), transform)
    bbox = mupdf.fz_round_rect(rectangle)
    pixmap = mupdf.fz_new_pixmap_with_bbox(fitz.csRGB.this, bbox, mupdf.FzSeparations(), 0)
    mupdf.fz_clear_pixmap_with_value(pixmap, 255)
    device = _NoTileCache(mupdf.fz_new_draw_device(mupdf.FzMatrix(), pixmap))
    try:
        mupdf.fz_run_page(page.this, device, transform, mupdf.FzCookie())
    finally:
        mupdf.fz_close_device(device)
    return fitz.Pixmap('raw', pixmap)


def render_pdfium(raw, expected_size, scale=2):
    """Render one unrotated page independently, returning RGB and exact scales.

    PDFium fits the page to integer bitmap dimensions. Its actual horizontal
    and vertical scales can differ slightly from the requested DPI; return
    both so pixel-cell ownership uses the real coordinate mapping. This helper
    supplies evidence only: callers still need structural and pixel checks.
    """
    import pypdfium2 as pdfium

    if (not isinstance(scale, (int,float)) or not math.isfinite(scale) or scale <= 0
            or len(expected_size) != 2
            or any(not math.isfinite(v) or v <= 0 for v in expected_size)):
        raise ValueError('PDFium verification requires finite positive dimensions and scale')
    with pdfium.PdfDocument(raw) as document:
        if len(document) != 1:
            raise ValueError('PDFium verification requires exactly one page')
        page=document[0]
        try:
            if page.get_rotation() != 0:
                raise ValueError('PDFium verification does not accept rotated pages')
            width,height=page.get_size()
            expected_box=(0.,0.,width,height)
            if (any(abs(a-b)>1e-4 for a,b in zip((width,height),expected_size))
                    or any(abs(a-b)>1e-4 for a,b in zip(page.get_mediabox(),expected_box))
                    or any(abs(a-b)>1e-4 for a,b in zip(page.get_cropbox(),expected_box))):
                raise ValueError('PDFium verification page geometry does not match the native page')
            bitmap=page.render(scale=scale,rotation=0,crop=(0,0,0,0),
                               fill_color=(255,255,255,255),may_draw_forms=False)
            try:
                expected_pixels=(math.ceil(width*scale),math.ceil(height*scale))
                if (bitmap.width,bitmap.height) != expected_pixels:
                    raise ValueError('PDFium verification bitmap dimensions changed')
                image=bitmap.to_pil().convert('RGB').copy()
                return image,(bitmap.width/width,bitmap.height/height)
            finally:
                bitmap.close()
        finally:
            page.close()


# Paint evidence uses the same complete forwarding contract as rendering.
KINDS={'fill_path':'fill-path','stroke_path':'stroke-path','fill_text':'fill-text',
 'stroke_text':'stroke-text','ignore_text':'ignore-text','fill_shade':'fill-shade',
 'fill_image':'fill-image','fill_image_mask':'fill-image'}
class PaintVisibility(_NoTileCache):
    def __init__(self,draw):
        super().__init__(draw);self.paints=[]

def wrapper(method,kind):
    forward=_forward(method)
    def call(self,ctx,*args):
        r=fitz.mupdf.fz_device_current_scissor(self._draw_device)
        self.paints.append((kind,(r.x0,r.y0,r.x1,r.y1)))
        return forward(self,ctx,*args)
    return call
for method,kind in KINDS.items():setattr(PaintVisibility,method,wrapper(method,kind))

def scissors(page):
    """Return each paint's conservative active clip bound in page coordinates."""
    fitz.TOOLS.store_shrink(100)
    m=fitz.mupdf
    pix=m.fz_new_pixmap_with_bbox(fitz.csRGB.this,m.fz_round_rect(m.fz_bound_page(page.this)),m.FzSeparations(),0)
    m.fz_clear_pixmap_with_value(pix,255)
    device=PaintVisibility(m.fz_new_draw_device(m.FzMatrix(),pix))
    try:m.fz_run_page(page.this,device,m.FzMatrix(),m.FzCookie())
    finally:m.fz_close_device(device)
    log=page.get_bboxlog()
    if [x[0]for x in device.paints]!=[x[0]for x in log]:
        raise ValueError(f'paint sequence mismatch: {len(device.paints)} vs {len(log)}')
    return {n:fitz.Rect(r)for n,(_kind,r)in enumerate(device.paints)}



class TextInkBounds(PaintVisibility):
    def __init__(self,draw):
        super().__init__(draw)
        self.text_ink={}

    def fill_text(self,ctx,*args):
        text,ctm=args[:2]
        m=fitz.mupdf
        ink=[]
        raw=text.head
        while raw:
            span=m.FzTextSpan(raw)
            for index in range(raw.len):
                item=span.items(index)
                # Negative gids hold extra unicode mappings, not painted ink.
                if item.gid<0:continue
                matrix=span.trm()
                matrix.e,matrix.f=item.x,item.y
                matrix=m.fz_concat(matrix,m.FzMatrix(ctm))
                rect=m.fz_bound_glyph(span.font(),item.gid,matrix)
                values=(rect.x0,rect.y0,rect.x1,rect.y1)
                if not all(math.isfinite(value)for value in values):
                    raise ValueError('Cannot prove nonfinite glyph ink bounds')
                ink.append({'gid':item.gid,'unicode':item.ucs,'bbox':values})
            raw=raw.next
        self.text_ink[len(self.paints)]=ink
        return PaintVisibility.fill_text(self,ctx,*args)


def text_ink_bounds(page):
    """Return fill-text seqno to individual ink boxes, validating every paint."""
    m=fitz.mupdf
    fitz.TOOLS.store_shrink(100)
    pix=m.fz_new_pixmap_with_bbox(fitz.csRGB.this,m.fz_round_rect(m.fz_bound_page(page.this)),m.FzSeparations(),0)
    m.fz_clear_pixmap_with_value(pix,255)
    device=TextInkBounds(m.fz_new_draw_device(m.FzMatrix(),pix))
    try:m.fz_run_page(page.this,device,m.FzMatrix(),m.FzCookie())
    finally:m.fz_close_device(device)
    if [x[0]for x in device.paints]!=[x[0]for x in page.get_bboxlog()]:
        raise ValueError('paint sequence mismatch for glyph ink bounds')
    return device.text_ink


def filled_text_is_distant(ink,support,*,margin=.5):
    """All individual glyph ink boxes plus a full AA pixel must be disjoint."""
    if ink is None:return False
    for item in ink:
        rect=fitz.Rect(item['bbox'])
        if rect.is_empty:continue
        rect=(rect+(-margin,-margin,margin,margin))*2
        box=(max(0,math.floor(rect.x0)),max(0,math.floor(rect.y0)),
             min(support.width,math.ceil(rect.x1)),min(support.height,math.ceil(rect.y1)))
        if box[0]<box[2]and box[1]<box[3]and support.crop(box).getbbox():return False
    return True




def snapshot(state,matrix):
    # Callback pointers are borrowed. Copy values now; do not retain the struct
    # or wrap it in an owning FzStrokeState after the callback returns.
    result={name:getattr(state,name)for name in ('start_cap','dash_cap','end_cap','linejoin','linewidth','miterlimit','dash_phase','dash_len')}
    result['dash_list']=[fitz.mupdf._mupdf.floats_getitem(state.dash_list,n)for n in range(state.dash_len)]
    result['ctm']=[getattr(matrix,name)for name in ('a','b','c','d','e','f')]
    a,b,c,d,_,_=result['ctm'];sx=math.hypot(a,b);sy=math.hypot(c,d)
    result['uniform_scale']=sx if abs(sx-sy)<1e-5 and abs(a*c+b*d)<1e-5 else None
    if result['uniform_scale'] is not None:
        result['page_linewidth']=result['linewidth']*sx
        result['page_dash_phase']=result['dash_phase']*sx
        result['page_dash_list']=[value*sx for value in result['dash_list']]
    return result


class StrokeSnapshots(PaintVisibility):
    def __init__(self,draw):super().__init__(draw);self.strokes={}
    def stroke_path(self,context,*args):
        self.strokes[len(self.paints)]=snapshot(args[1],args[2])
        return PaintVisibility.stroke_path(self,context,*args)
    def stroke_text(self,context,*args):
        self.strokes[len(self.paints)]=snapshot(args[1],args[2])
        return PaintVisibility.stroke_text(self,context,*args)


def stroke_states(page):
    fitz.TOOLS.store_shrink(100);m=fitz.mupdf
    pix=m.fz_new_pixmap_with_bbox(fitz.csRGB.this,m.fz_round_rect(m.fz_bound_page(page.this)),m.FzSeparations(),0)
    m.fz_clear_pixmap_with_value(pix,255)
    device=StrokeSnapshots(m.fz_new_draw_device(m.FzMatrix(),pix))
    try:m.fz_run_page(page.this,device,m.FzMatrix(),m.FzCookie())
    finally:m.fz_close_device(device)
    log=page.get_bboxlog()
    if [entry[0]for entry in device.paints]!=[entry[0]for entry in log]:
        raise ValueError(f'paint sequence mismatch: {len(device.paints)} vs {len(log)}')
    for number,state in device.strokes.items():
        state.update(kind=log[number][0],bbox=list(log[number][1]),scissor=list(device.paints[number][1]))
    return device.strokes




class _SelectedVectorPaint(_NoTileCache):
    def __init__(self, draw, selected):
        super().__init__(draw)
        self.selected = set(selected)
        self.paints = []
        self.snapshots = {}
        self.unsupported = []
        self.groups = []

    def begin_mask(self, context, *args):
        self.unsupported.append('soft mask')
        return _forward('begin_mask')(self, context, *args)

    def begin_tile(self, context, *args):
        self.unsupported.append('tiling pattern')
        return _forward('begin_tile')(self, context, *args)

    def begin_group(self, context, *args):
        # area, colorspace, isolated, knockout, blendmode, alpha
        self.groups.append({'isolated': args[2], 'knockout': args[3],
                            'blendmode': args[4], 'alpha': args[5]})
        return _forward('begin_group')(self, context, *args)

    def end_group(self, context, *args):
        result = _forward('end_group')(self, context, *args)
        self.groups.pop()
        return result


def _paint_callback(method, kind):
    forward = _forward(method)

    def call(self, context, *args):
        seqno = len(self.paints)
        scissor = fitz.mupdf.fz_device_current_scissor(self._draw_device)
        self.paints.append((kind, tuple(getattr(scissor, key) for key in ('x0', 'y0', 'x1', 'y1'))))
        if seqno not in self.selected:
            return
        if method not in ('fill_path', 'stroke_path'):
            self.unsupported.append(f'selected non-vector paint {seqno}: {kind}')
            return
        if any(g['knockout'] or g['blendmode'] or g['alpha'] != 1 for g in self.groups):
            self.unsupported.append(f'selected vector {seqno} in nontrivial transparency group')
            return
        if method == 'stroke_path':
            self.snapshots[seqno] = snapshot(args[1], args[2])
        else:
            matrix = args[2]
            self.snapshots[seqno] = {
                'even_odd': bool(args[1]),
                'ctm': [getattr(matrix, key) for key in ('a', 'b', 'c', 'd', 'e', 'f')],
            }
        self.snapshots[seqno].update(kind=kind, alpha=float(args[5]),
                                      scissor=self.paints[-1][1], groups=list(self.groups))
        # Critical: original path, original full stroke state, original CTM.
        # Their lifetime is valid during this callback only.
        return forward(self, context, *args)

    return call


for _method, _kind in KINDS.items():
    setattr(_SelectedVectorPaint, _method, _paint_callback(_method, _kind))


def exact_paint_mask(page, seqnos, *, scale=2, offset=(0, 0)):
    """Return (PIL L alpha coverage, per-seq proof); fail closed on unsupported context."""
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('scale must be positive and finite')
    if (not isinstance(offset, (tuple, list)) or len(offset) != 2 or
        any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in offset)):
        raise ValueError('offset must contain two finite values')
    selected = set(seqnos)
    if any(not isinstance(n, int) or n < 0 for n in selected):
        raise ValueError('seqnos must be nonnegative integers')
    fitz.TOOLS.store_shrink(100)
    m = fitz.mupdf
    transform = fitz.JM_matrix_from_py(fitz.Matrix(scale, 0, 0, scale, *offset))
    rectangle = m.fz_transform_rect(m.fz_bound_page(page.this), transform)
    pix = m.fz_new_pixmap_with_bbox(fitz.csRGB.this, m.fz_round_rect(rectangle), m.FzSeparations(), 1)
    m.fz_clear_pixmap(pix)
    device = _SelectedVectorPaint(m.fz_new_draw_device(m.FzMatrix(), pix), selected)
    try:
        m.fz_run_page(page.this, device, transform, m.FzCookie())
    finally:
        m.fz_close_device(device)
    log = page.get_bboxlog()
    if [kind for kind, _ in device.paints] != [entry[0] for entry in log]:
        raise ValueError(f'paint sequence mismatch: {len(device.paints)} vs {len(log)}')
    if device.unsupported:
        raise ValueError('; '.join(dict.fromkeys(device.unsupported)))
    if set(device.snapshots) != selected:
        raise ValueError(f'missing selected paints: {sorted(selected - set(device.snapshots))}')
    result = fitz.Pixmap('raw', pix)
    alpha = Image.frombytes('RGBA', (result.width, result.height), result.samples).getchannel('A')
    for seqno, proof in device.snapshots.items():
        proof['source_bbox'] = list(log[seqno][1])
    return alpha, device.snapshots


def _native_image(image,*,mask=False):
    """Copy real callback pixels and parameters, independent of xref guesses."""
    low=fitz.mupdf._mupdf
    if (image.bpc!=8 or image.n not in (1,3) or image.use_colorkey or image.scalable or
            image.orientation or (mask and (image.mask is not None or image.n!=1))):return None
    cs=image.colorspace
    if cs is None:
        if not mask:return None
        colour=None
    elif not low.ll_fz_colorspace_is_device(cs):return None
    else:
        channels=low.ll_fz_colorspace_n(cs)
        if channels not in (1,3) or channels!=image.n:return None
        colour=(str(low.ll_fz_colorspace_name(cs)),channels)
    native=fitz.mupdf.FzPixmap(low.ll_fz_get_unscaled_pixmap_from_image(image))
    pix=fitz.Pixmap('raw',native)
    decode=tuple(float(low.floats_getitem(image.decode,i)) for i in range(2*image.n)) if image.use_decode else ()
    if not all(math.isfinite(v) for v in decode):return None
    return (int(image.w),int(image.h),int(image.bpc),int(image.n),int(image.interpolate),
            int(image.imagemask),int(image.use_decode),decode,
            int(image.intent) if image.has_intent else None,colour,
            pix.width,pix.height,pix.n,pix.alpha,hashlib.sha256(pix.samples).hexdigest())


class _Rectangles(fitz.mupdf.FzPathWalker2):
    def __init__(self, matrix):
        super().__init__()
        self.matrix=fitz.Matrix(*[getattr(matrix,k) for k in 'abcdef'])
        self.paths=[];self.current=[];self.known=True
        supported={'moveto','lineto','curveto','closepath','quadto','curvetov','curvetoy','rectto'}
        available={k.removeprefix('use_virtual_') for k in dir(type(self)) if k.startswith('use_virtual_')}
        if available!=supported:raise ValueError('MuPDF path walker API changed')
        for method in supported:getattr(self,'use_virtual_'+method)()
    def flush(self):
        if self.current:self.paths.append(self.current);self.current=[]
    def moveto(self,opaque,x,y):self.flush();self.current=[(x,y)]
    def lineto(self,opaque,x,y):self.current.append((x,y))
    def closepath(self,opaque):self.flush()
    def rectto(self,opaque,x0,y0,x1,y1):
        self.flush();self.paths.append([(x0,y0),(x1,y0),(x1,y1),(x0,y1)])
    def curveto(self,*args):self.known=False
    def quadto(self,*args):self.known=False
    def curvetov(self,*args):self.known=False
    def curvetoy(self,*args):self.known=False
    def rectangles(self):
        self.flush()
        if not self.known:return None
        result=[]
        for raw in self.paths:
            points=[fitz.Point(*p)*self.matrix for p in raw]
            if points and points[-1]==points[0]:points.pop()
            if len(points)!=4:return None
            if not all(math.isfinite(v) for p in points for v in p):return None
            edges=list(zip(points,points[1:]+points[:1]))
            if any((a.x==b.x)==(a.y==b.y) for a,b in edges):return None
            xs={p.x for p in points};ys={p.y for p in points}
            if len(xs)!=2 or len(ys)!=2 or len({tuple(p) for p in points})!=4:return None
            signed=sum(a.x*b.y-b.x*a.y for a,b in edges)
            if not signed:return None
            result.append((tuple(fitz.Rect(min(xs),min(ys),max(xs),max(ys))),1 if signed>0 else -1))
        return result


def _clip_rectangles(path,matrix):
    walker=_Rectangles(matrix)
    fitz.mupdf._mupdf.ll_fz_walk_path(path,walker.m_internal,walker.m_internal)
    return walker.rectangles()


def _clip_contains(clip,bounds,margin=.5):
    if clip is None:return False
    even_odd,rectangles=clip
    extended=fitz.Rect(bounds)+(-margin,-margin,margin,margin)
    winding=0
    for values,orientation in rectangles:
        rect=fitz.Rect(values)
        if rect.contains(extended):winding+=orientation
        elif not rect.intersects(extended):continue
        else:return False
    return bool(winding%2) if even_odd else bool(winding)


class ImagePaintEvidence(PaintVisibility):
    def __init__(self,draw):
        super().__init__(draw)
        self.images={};self.clips=[];self.groups=[];self.unsupported=[]
    def clip_path(self,ctx,*args):
        self.clips.append((bool(args[1]),_clip_rectangles(args[0],args[2])))
        if self.clips[-1][1] is None:self.clips[-1]=None
        return _forward('clip_path')(self,ctx,*args)
    def pop_clip(self,ctx,*args):
        if not self.clips:self.unsupported.append('clip stack mismatch')
        else:self.clips.pop()
        return _forward('pop_clip')(self,ctx,*args)
    def begin_group(self,ctx,*args):
        area=tuple(float(getattr(args[0],k)) for k in ('x0','y0','x1','y1'))
        cs=args[1];low=fitz.mupdf._mupdf
        colour=None if cs is None else (str(low.ll_fz_colorspace_name(cs)),low.ll_fz_colorspace_n(cs))
        if cs is not None and not low.ll_fz_colorspace_is_device(cs):self.unsupported.append('non-device group colours')
        self.groups.append({'isolated':int(args[2]),'knockout':int(args[3]),
                            'blendmode':int(args[4]),'alpha':float(args[5]),'area':area,'colour':colour})
        return _forward('begin_group')(self,ctx,*args)
    def set_default_colorspaces(self,ctx,*args):
        defaults=args[0]
        if (defaults.oi is not None or
                any(not fitz.mupdf._mupdf.ll_fz_colorspace_is_device(getattr(defaults,key))
                    or fitz.mupdf._mupdf.ll_fz_colorspace_n(getattr(defaults,key))!=channels
                    for key,channels in (('gray',1),('rgb',3),('cmyk',4)))):
            self.unsupported.append('non-device default colours')
        return _forward('set_default_colorspaces')(self,ctx,*args)
    def end_group(self,ctx,*args):
        if not self.groups:self.unsupported.append('group stack mismatch')
        else:self.groups.pop()
        return _forward('end_group')(self,ctx,*args)
    def fill_image(self,ctx,*args):
        matrix=args[1];values=tuple(float(getattr(matrix,k)) for k in 'abcdef')
        bounds=fitz.Rect(0,0,1,1)*fitz.Matrix(*values)
        params=args[3]
        colour={k:int(getattr(params,k)) for k in ('ri','bp','op','opm')}
        native_image=_native_image(args[0])
        contexts=[];known=True
        for clip in self.clips:
            if clip is None:known=False;continue
            if clip[0]=='image-mask':
                _,signature,address=clip
                # MuPDF expands an image's own SMask into a mask-clip callback.
                # Do not borrow an unrelated mask clip as image evidence.
                mask=args[0].mask
                if mask is None or int(mask.this)!=address:known=False
                contexts.append(('image-mask',signature))
            elif not _clip_contains(clip,bounds):
                # A boundary touching the image is safe to compare only by
                # exact complete rectangle geometry, not its outer scissor.
                even_odd,rectangles=clip
                contexts.append(('rectangles',even_odd,tuple(rectangles)))
        safe=(native_image is not None and known and not self.unsupported and not bounds.is_empty and
              all(math.isfinite(v) for v in (*values,float(args[2]))) and
              all(not g['knockout'] and not g['blendmode'] and g['alpha']==1 for g in self.groups))
        self.images[len(self.paints)]={'alpha':float(args[2]),'ctm':values,'context_safe':safe,
                                       'colour':colour,'groups':tuple(tuple(g.items()) for g in self.groups),
                                       'clip_context':tuple(contexts),'native_image':native_image}
        return PaintVisibility.fill_image(self,ctx,*args)
    def clip_image_mask(self,ctx,*args):
        image,matrix=args[:2]
        # Copy the borrowed callback's pixels and scalar values immediately.
        # Only ordinary 8-bit single-channel masks with no recursive mask or
        # colorkey are supported here; all other states remain unproved.
        signature=_native_image(image,mask=True)
        if signature is None:
            self.clips.append(None)
        else:
            values=tuple(float(getattr(matrix,k)) for k in 'abcdef')
            if not all(math.isfinite(v) for v in values):self.clips.append(None)
            else:self.clips.append(('image-mask',(signature,values),int(image.this)))
        return _forward('clip_image_mask')(self,ctx,*args)
    def fill_image_mask(self,ctx,*args):
        self.images[len(self.paints)]={'alpha':None,'ctm':None,'context_safe':False}
        return PaintVisibility.fill_image_mask(self,ctx,*args)


def _unknown_clip(method):
    def call(self,ctx,*args):
        self.clips.append(None)
        return _forward(method)(self,ctx,*args)
    return call
for _name in ('clip_stroke_path','clip_text','clip_stroke_text'):
    setattr(ImagePaintEvidence,_name,_unknown_clip(_name))


def _unsupported(method):
    def call(self,ctx,*args):
        self.unsupported.append(method)
        return _forward(method)(self,ctx,*args)
    return call
for _name in ('begin_mask','begin_tile','begin_layer','render_flags'):
    setattr(ImagePaintEvidence,_name,_unsupported(_name))


def image_paints(page):
    fitz.TOOLS.store_shrink(100);m=fitz.mupdf
    pix=m.fz_new_pixmap_with_bbox(fitz.csRGB.this,m.fz_round_rect(m.fz_bound_page(page.this)),m.FzSeparations(),0)
    m.fz_clear_pixmap_with_value(pix,255)
    device=ImagePaintEvidence(m.fz_new_draw_device(m.FzMatrix(),pix))
    try:m.fz_run_page(page.this,device,m.FzMatrix(),m.FzCookie())
    finally:m.fz_close_device(device)
    log=page.get_bboxlog()
    if [v[0] for v in device.paints]!=[v[0] for v in log]:
        raise ValueError('Image paint sequence mismatch')
    if device.groups or device.clips:raise ValueError('Unbalanced image paint context stack')
    # A later unsupported callback can affect the page context too; do not
    # accept earlier image calls from a page containing masks or tiles.
    if device.unsupported:
        for state in device.images.values():state['context_safe']=False
    return {'images':device.images,'scissors':{n:fitz.Rect(r) for n,(_,r) in enumerate(device.paints)}}
