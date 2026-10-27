"""Uniform XZ cells, clipping, BSP and bounded local collision queries.

Authoritative sources: tracks.c:31,1741–1764,1986–2159,2510–2585;
hasm/collision.s:generate_collision_candidates/compute_grid_overlap_mask.
The NON_MATCHING C grid helper has an incorrect Z loop; the assembly advances
both cell endpoints on both axes. No game code or runtime limits are patched.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
import math
import struct

import numpy as np

from src.core.geometry import TRACK_HEAP, collision_base_planes, verify_geometry_stream
from src.core.level_model import BATCH_STRUCT, LevelModel, TextureInfo
from src.core.materials import SURFACES, TextureReference
from src.core.minimap import MINIMAP_FIELDS, SpriteReference, validate_minimap_edit
from src.core.track_rebuild import RuntimeTrack
from src.core.render_batches import MAX_BATCH_VERTICES, MAX_BATCH_FACES, ENCODED_BATCH_VERTICES
from src.core.track_import import (CompiledTrack, ImportError, ImportOptions, ObjCorner,
    ObjFace, ObjMesh, _bounds, collision_facets, compile_obj, validate_compiled_track,
    validate_import_runtime)

MAX_INPUT_FACES = 6000
MAX_OUTPUT_FACES = 6000
MAX_SEGMENTS = 127  # objectsVisible[128] also writes index numberOfSegments.
MAX_CELL_FACES = 120
CELL_SIZES = (4096,3072,2048,1536,1280,1024,768,512)
# For a raw query span <= cell_size-56: +20 each side, +5 boxes, +1 box
# margin => < one cell width. At most2 columns ×2 rows, <=4*(120+1)=484
# candidates, below500. A point's +4 floor margin hits at most4 cells (<8).
QUERY_MARGIN = 56


@dataclass(frozen=True)
class SegmentedTrack(CompiledTrack):
    segment_count: int
    input_faces: int
    cell_size: int
    seam_edges: int
    rendered_faces: int

    def to_text(self) -> str:
        return (f'{self.input_faces:,} input → {self.rendered_faces:,} rendered + {self.faces-self.rendered_faces:,} collision-helper triangles · '
                f'{self.vertices:,} stored vertices · {self.batches} batches\n'
                f'{self.segment_count} spatial segments · {self.cell_size} unit cells · {self.seam_edges} seam edges\n'
                f'Local collision envelope: X and Z spans ≤ {self.cell_size-QUERY_MARGIN} units before game padding.\n'
                f'Within that envelope: ≤4 segments / ≤484 of 500 candidates. Floor point overlap ≤4 of 7 usable slots.\n'
                'Longer camera/movement sweeps can reach the game’s 10-segment/500-candidate truncation; test your course.\n'
                'BSP order is rebuilt; all segments remain potentially visible, then game frustum culling applies.\n'
                f'Worst-case static track commands: ≤{self.batches*8:,} of the one-player 4,500-command frame pool (objects/HUD need the remainder).\n'
                f'Track heap: {self.runtime_bytes:,}/{TRACK_HEAP:,} B · compressed: {self.packed_bytes:,} B\n'
                'Objects, checkpoint/AI paths and minimap artwork retain their current placements.')


@dataclass(frozen=True)
class _Corner:
    position: tuple[int,int,int]
    color: tuple[float,float,float,float]
    uv: tuple[float,float]


@dataclass(frozen=True)
class _Face:
    corners: tuple[_Corner,_Corner,_Corner]
    slot: int


@dataclass(frozen=True)
class _Segment:
    vertices: tuple[tuple[int,...],...]
    triangles: tuple[tuple[int,...],...]
    batches: tuple[tuple[int,...],...]
    opaque: int
    bounds: tuple[int,...]
    facets: np.ndarray


def _source_faces(mesh: ObjMesh, options: ImportOptions, materials: Mapping[str,int]) -> list[_Face]:
    if not 1 <= len(mesh.faces) <= MAX_INPUT_FACES:
        raise ImportError(f'Segmented import needs 1..{MAX_INPUT_FACES:,} input triangles')
    if (not math.isfinite(options.scale) or options.scale<=0 or len(options.offset)!=3
            or not all(math.isfinite(v) for v in options.offset)):
        raise ImportError('Scale must be positive and transforms finite')
    positions = np.rint(np.asarray(mesh.vertices,np.float64)*options.scale+options.offset)
    if not np.isfinite(positions).all() or np.any(positions < -32768) or np.any(positions > 32767):
        raise ImportError('Transformed OBJ coordinates exceed signed16 storage')
    faces: list[_Face] = []
    for face in mesh.faces:
        corners = tuple(reversed(face.corners)) if options.reverse_winding else face.corners
        points = positions[[c.vertex for c in corners]]
        normal = np.cross(points[1]-points[0],points[2]-points[0])
        axes = [i for i in range(3) if i!=int(np.argmax(np.abs(normal)))]
        lower,extent = points[:,axes].min(axis=0),np.maximum(np.ptp(points[:,axes],axis=0),1)
        data = tuple(_Corner(tuple(map(int,positions[c.vertex])),mesh.colors[c.vertex],
            mesh.uvs[c.uv] if c.uv is not None else tuple((positions[c.vertex][axes]-lower)/extent)) for c in corners)
        slot = materials.get(face.material)
        if type(slot) is not int:
            raise ImportError(f'Choose a texture slot for {face.material!r}')
        faces.append(_Face(data,slot))
    points = np.asarray([[c.position for c in f.corners] for f in faces],np.int32)
    if np.any(np.linalg.norm(collision_base_planes(points)[:,:3],axis=1)<.5):
        raise ImportError('An input triangle collapses after coordinate quantization')
    collision_facets(points)
    return faces


def _appearance(template: bytes, appearance: bytes, refs: Sequence[TextureReference],
                materials: Mapping[str,int], surfaces: Mapping[str,int]) -> tuple[bytes,dict[str,int]]:
    base,current = LevelModel.from_bytes(template),LevelModel.from_bytes(appearance)
    if not len(base.textures)<=len(current.textures)<=255:
        raise ImportError('Appearance must retain the original texture slots')
    textures = list(current.textures)
    result: dict[str,int] = {}
    for name,slot in materials.items():
        if type(slot) is not int or not 0<=slot<len(current.textures):
            raise ImportError(f'Invalid existing texture slot for {name!r}')
        surface = surfaces.get(name,current.textures[slot].surface_type)
        if type(surface) is not int or not 0<=surface<len(SURFACES):
            raise ImportError(f'Choose a verified driving surface for {name!r}')
        info = replace(current.textures[slot],surface_type=surface)
        if not 0<=info.texture_id<len(refs):
            raise ImportError('Texture reference is outside the ROM table')
        if info==current.textures[slot]:
            result[name]=slot
        else:
            if info not in textures:textures.append(info)
            result[name]=textures.index(info)
    if len(textures)>255:
        raise ImportError('Material surface choices exceed 255 texture slots')
    # Temporary template for the existing per-cell static batch compiler. This
    # appended table is never exported; only typed compiler output is serialized.
    out = bytearray(appearance)
    out.extend(bytes((-len(out))%16))
    pointer = len(out)
    out.extend(b''.join(struct.pack('>IBBBb',t.texture_id,t.width,t.height,t.format,t.surface_type) for t in textures))
    struct.pack_into('>I',out,0,pointer)
    struct.pack_into('>h',out,0x18,len(textures))
    struct.pack_into('>i',out,0x48,len(out))
    return bytes(out),result


def _origin(faces: Sequence[_Face], size: int) -> tuple[int,int]:
    points = np.asarray([[c.position for c in f.corners] for f in faces],np.int32)
    return int(points[:,:,0].min())-2,int(points[:,:,2].min())-2


def _clip(poly: list[_Corner], axis: int, cut: int, keep_greater: bool,
          cache: dict[tuple,tuple[int,int,int]]) -> list[_Corner]:
    out: list[_Corner] = []
    for a,b in zip(poly,(*poly[1:],poly[0])):
        da,db = a.position[axis]-cut,b.position[axis]-cut
        inside_a,inside_b = (da>=0,db>=0) if keep_greater else (da<=0,db<=0)
        if inside_a:
            out.append(a)
        if inside_a!=inside_b:
            t = da/(da-db)
            key = (*sorted((a.position,b.position)),axis,cut)
            point = cache.get(key)
            if point is None:
                xyz = np.rint(np.asarray(a.position)+(np.asarray(b.position)-a.position)*t).astype(int)
                xyz[axis] = cut
                point = tuple(map(int,xyz));cache[key] = point
            color = tuple((1-t)*x+t*y for x,y in zip(a.color,b.color))
            uv = tuple((1-t)*x+t*y for x,y in zip(a.uv,b.uv))
            out.append(_Corner(point,color,uv))
    clean = [c for i,c in enumerate(out) if not i or c.position!=out[i-1].position]
    if len(clean)>1 and clean[-1].position==clean[0].position:
        clean.pop()
    return clean


def _triangulate(poly: list[_Corner], normal: np.ndarray) -> list[tuple[_Corner,_Corner,_Corner]]:
    """Convex ear removal retains collinear boundary points at cell junctions."""
    result = []
    while len(poly)>3:
        for i in range(len(poly)):
            a,b,c = poly[i-1],poly[i],poly[(i+1)%len(poly)]
            area = np.cross(np.subtract(b.position,a.position),np.subtract(c.position,a.position))
            if float(area@normal)<=1e-6:
                continue
            remaining = poly[:i]+poly[i+1:]
            p = np.array([v.position for v in remaining],np.float64)
            if float(np.cross(p,np.roll(p,-1,axis=0)).sum(axis=0)@normal)<=1e-6:
                continue
            result.append((a,b,c));poly=remaining
            break
        else:
            raise ImportError('A clipped polygon collapsed or folded after signed16 rounding')
    if len(poly)==3:
        p = np.array([c.position for c in poly],np.float64)
        if float(np.cross(p[1]-p[0],p[2]-p[0])@normal)>1e-6:
            result.append(tuple(poly))
    return result


def _partition(faces: Sequence[_Face], size: int) -> tuple[dict[tuple[int,int],list[_Face]],tuple[int,int]]:
    origin = _origin(faces,size)
    cells: dict[tuple[int,int],list[_Face]] = {}
    cache: dict[tuple,tuple[int,int,int]] = {}
    total = 0
    for face in faces:
        p = np.array([c.position for c in face.corners],np.int32)
        normal = np.cross((p[1]-p[0]).astype(np.float64),p[2]-p[0])
        normal /= np.linalg.norm(normal)
        lower = np.floor_divide(p[:,[0,2]].min(axis=0)-origin,size)
        upper = np.floor_divide(p[:,[0,2]].max(axis=0)-origin,size)
        if int(np.prod(upper-lower+1))>MAX_SEGMENTS*4:
            raise ImportError('A triangle spans too many grid cells; use larger cells or a smaller mesh')
        for x in range(int(lower[0]),int(upper[0])+1):
            for z in range(int(lower[1]),int(upper[1])+1):
                poly = list(face.corners)
                for axis,start in ((0,origin[0]+x*size),(2,origin[1]+z*size)):
                    if poly:poly = _clip(poly,axis,start,True,cache)
                    if poly:poly = _clip(poly,axis,start+size,False,cache)
                if len(poly)<3:
                    continue
                tris = _triangulate(poly,normal)
                if not tris:
                    continue
                data = cells.setdefault((x,z),[])
                data.extend(_Face(t,face.slot) for t in tris)
                total += len(tris)
                if len(data)>MAX_CELL_FACES:
                    raise ImportError(f'Cell ({x},{z}) needs {len(data)} faces; local collision budget permits {MAX_CELL_FACES}. Try smaller cells or reduce dense detail.')
                if len(cells)>MAX_SEGMENTS or total>MAX_OUTPUT_FACES:
                    raise ImportError('Segmented mesh exceeds the 127-segment / 6,000 compiled-face envelope')
    return cells,origin


def _bsp(cells: Sequence[tuple[int,int]], origin: tuple[int,int], size: int
         ) -> tuple[tuple[tuple[int,int],...],tuple[tuple[int,...],...]]:
    ordered: list[tuple[int,int]] = []
    nodes: list[tuple[int,...]] = []
    def visit(items: list[tuple[int,int]]) -> int:
        if len(items)==1:
            ordered.append(items[0]);return -1
        axis = 0 if max(x for x,z in items)-min(x for x,z in items)>=max(z for x,z in items)-min(z for x,z in items) else 1
        values = sorted({c[axis] for c in items})
        cut = values[len(values)//2]
        low,high = [c for c in items if c[axis]<cut],[c for c in items if c[axis]>=cut]
        index = len(nodes);nodes.append(())
        left = visit(low)
        split_index = len(ordered)
        right = visit(high)
        nodes[index] = (left,right,0 if axis==0 else 2,split_index,origin[axis]+cut*size)
        return index
    visit(list(cells))
    return tuple(ordered),tuple(nodes)


def _segment(raw: bytes, bounds: tuple[int,...]) -> _Segment:
    model = LevelModel.from_bytes(raw);s=model.segments[0]
    p = struct.unpack_from('>I',raw,4)[0]
    vp,tp,_,bp,_,fp = struct.unpack_from('>6I',raw,p)
    return _Segment(tuple(struct.iter_unpack('>hhhBBBB',raw[vp:vp+10*s.vertex_count])),
        tuple(struct.iter_unpack('>BBBBhhhhhh',raw[tp:tp+16*s.triangle_count])),
        tuple(BATCH_STRUCT.iter_unpack(raw[bp:bp+12*len(s.batches)])),s.opaque_batch_count,bounds,
        np.frombuffer(raw,'>u2',s.triangle_count*4,fp).reshape(-1,4).copy())


def _links(points: np.ndarray, owners: np.ndarray) -> tuple[np.ndarray,int,int,int]:
    graph,shared,boundary = collision_facets(points)
    seams=sum(int(j>i and owners[i]!=owners[j]) for i,row in enumerate(graph) for j in row[1:])
    return graph,shared,boundary,seams


def _helper_payload(points: np.ndarray, slot: int, vertex_start: int, face_start: int
                    ) -> tuple[tuple[tuple[int,...],...],tuple[tuple[int,...],...],tuple[tuple[int,...],...]]:
    vertices: list[tuple[int,...]]=[];triangles: list[tuple[int,...]]=[];batches: list[tuple[int,...]]=[]
    lookup: dict[tuple[int,...],int]={};batch_start=0
    for tri in points:
        values=[(*map(int,p),255,255,255,255) for p in tri]
        if not batches or len(lookup)+len({v for v in values if v not in lookup})>MAX_BATCH_VERTICES or len(triangles)-batch_start>=MAX_BATCH_FACES:
            lookup={};batch_start=len(triangles)
            batches.append((slot,0,vertex_start+len(vertices),face_start+len(triangles),255,0,0x300))
        ids=[]
        for v in values:
            if v not in lookup:lookup[v]=len(lookup);vertices.append(v)
            ids.append(lookup[v])
        triangles.append((0,*ids,0,0,0,0,0,0))
    return tuple(vertices),tuple(triangles),tuple(batches)


def _add_helpers(segments: Sequence[_Segment], textures: Sequence[TextureInfo]
                 ) -> tuple[tuple[_Segment,...],tuple[TextureInfo,...],int,int,int]:
    arrays=[]
    for s in segments:
        ids=np.array([t[1:4] for t in s.triangles],np.int32)
        for b,e in zip(s.batches,(*s.batches[1:],(0,0,len(s.vertices),len(s.triangles),0,0,0))):
            ids[b[3]:e[3]]+=b[2]
        arrays.append(np.array(s.vertices,np.int32)[ids,:3])
    points=np.concatenate(arrays)
    owners=np.concatenate([np.full(len(s.triangles),i) for i,s in enumerate(segments)])
    graph,shared,boundary,seams=_links(points,owners)
    used={b[0] for s in segments for b in s.batches}
    updated=list(textures)
    slot=next((i for i,t in enumerate(updated) if i not in used and t.surface_type==0),len(updated))
    if slot==len(updated):updated.append(replace(updated[0],surface_type=0))
    if len(updated)>255:raise ImportError('No texture slot remains for protected collision seam helpers')
    result=[];start=0
    for i,s in enumerate(segments):
        stop=start+len(s.triangles)
        needed=sorted({int(j) for row in graph[start:stop] for j in row[1:] if owners[j]!=i})
        hv,ht,hb=_helper_payload(points[needed],slot,len(s.vertices),len(s.triangles))
        local=np.concatenate((arrays[i],points[needed])) if needed else arrays[i]
        facets,_,_=collision_facets(local)
        result.append(replace(s,vertices=(*s.vertices,*hv),triangles=(*s.triangles,*ht),batches=(*s.batches,*hb),facets=facets))
        start=stop
    return tuple(result),tuple(updated),shared,boundary,seams


def _assemble(template: bytes, textures: Sequence[TextureInfo], segments: Sequence[_Segment],
              nodes: Sequence[tuple[int,...]], bounds: tuple[int,...]) -> bytes:
    out = bytearray(template[:0x4c])
    def append(data: bytes) -> int:
        out.extend(bytes((-len(out))%16));p=len(out);out.extend(data);return p
    tex = append(b''.join(struct.pack('>IBBBb',t.texture_id,t.width,t.height,t.format,t.surface_type) for t in textures))
    seg = append(bytes(0x44*len(segments)))
    for i,s in enumerate(segments):
        vp = append(b''.join(struct.pack('>hhhBBBB',*v) for v in s.vertices))
        tp = append(b''.join(struct.pack('>BBBBhhhhhh',*t) for t in s.triangles))
        bp = append(b''.join(BATCH_STRUCT.pack(*b) for b in (*s.batches,(0,0,len(s.vertices),len(s.triangles),255,0,0))))
        fp = append(s.facets.astype('>u2').tobytes())
        p = seg+i*0x44
        struct.pack_into('>7I',out,p,vp,tp,0,bp,0,fp,0)
        struct.pack_into('>3h',out,p+0x1c,len(s.vertices),len(s.triangles),len(s.batches))
        struct.pack_into('>h',out,p+0x28,i*((len(segments)+7)//8))
        out[p+0x40] = s.opaque
    boxes = append(b''.join(struct.pack('>6h',*s.bounds) for s in segments))
    width = (len(segments)+7)//8
    row = ((1<<len(segments))-1).to_bytes(width,'little')
    pvs = append(row*len(segments))
    bsp = append(b''.join(struct.pack('>hhBBh',*n) for n in nodes))
    empty = append(b'')
    struct.pack_into('>6I',out,0,tex,seg,boxes,empty,pvs,bsp)
    struct.pack_into('>4h',out,0x18,len(textures),len(segments),0,0)
    x0,y0,z0,x1,y1,z1 = bounds
    struct.pack_into('>6h',out,0x3c,x0,x1,y0,y1,z0,z1)
    struct.pack_into('>i',out,0x48,len(out))
    return bytes(out)


def _global_bounds(original: LevelModel, segments: Sequence[_Segment]) -> tuple[int,...]:
    lower = np.minimum(np.array([s.bounds[:3] for s in segments]).min(axis=0),original.stored_bounds.minimum)
    upper = np.maximum(np.array([s.bounds[3:] for s in segments]).max(axis=0),original.stored_bounds.maximum)
    return tuple(map(int,(*lower,*upper)))


def compile_segmented_obj(mesh: ObjMesh, template: bytes, refs: Sequence[TextureReference],
                          materials: Mapping[str,int], options: ImportOptions = ImportOptions(), *,
                          appearance: bytes | None = None, surfaces: Mapping[str,int] | None = None,
                          cell_size: int = 0) -> SegmentedTrack:
    appearance,mapping = _appearance(template,appearance or template,refs,materials,surfaces or {})
    faces = _source_faces(mesh,options,mapping)
    errors: list[str] = []
    if cell_size and cell_size not in CELL_SIZES:
        raise ImportError('Choose an available cell size or Automatic')
    for size in ((cell_size,) if cell_size else CELL_SIZES):
        try:
            cells,origin = _partition(faces,size)
            break
        except ImportError as error:
            errors.append(f'{size}: {error}')
    else:
        raise ImportError('Cannot fit this mesh into the spatial collision envelope.\n'+'\n'.join(errors))
    ordered,nodes = _bsp(tuple(cells),origin,size)
    all_points = np.array([[c.position for c in f.corners] for f in faces])
    envelope = _bounds(LevelModel.from_bytes(template),all_points)
    segments: list[_Segment] = []
    for x,z in ordered:
        data = cells[x,z]
        vertices = tuple(c.position for f in data for c in f.corners)
        colors = tuple(c.color for f in data for c in f.corners)
        uvs = tuple(c.uv for f in data for c in f.corners)
        parts = tuple(ObjFace(tuple(ObjCorner(i*3+j,i*3+j) for j in range(3)),str(f.slot)) for i,f in enumerate(data))
        local = ObjMesh(vertices,colors,uvs,parts)
        # Partitioned vertices are already transformed and rounded game coordinates.
        compiled = compile_obj(local,appearance,refs,{str(f.slot):f.slot for f in data},
                               ImportOptions(scale=1.0,double_sided=options.double_sided),_staging=True)
        bounds = (origin[0]+x*size-1,envelope[1],origin[1]+z*size-1,
                  origin[0]+(x+1)*size+1,envelope[4],origin[1]+(z+1)*size+1)
        if any(v < -32768 or v > 32767 for v in bounds):
            raise ImportError('Spatial cell bounds exceed signed16; translate the mesh away from the coordinate limits')
        segments.append(_segment(compiled.raw,bounds))
    segments,textures,shared,boundary,seams=_add_helpers(segments,LevelModel.from_bytes(appearance).textures)
    if sum(len(s.triangles) for s in segments)>MAX_OUTPUT_FACES:
        raise ImportError('Geometry plus seam helpers exceeds 6,000 stored triangles')
    raw = _assemble(appearance,textures,segments,nodes,_global_bounds(LevelModel.from_bytes(template),segments))
    model = LevelModel.from_bytes(raw)
    runtime = validate_segmented_runtime(model)
    packed = compress_segmented_track(raw)
    return SegmentedTrack(raw,model.triangle_count,model.vertex_count,sum(len(s.batches) for s in model.segments),
        shared,boundary,runtime.byte_size,len(packed),len(segments),len(mesh.faces),size,seams,sum(_owned_counts(model)))


def compress_segmented_track(raw: bytes) -> bytes:
    """Keep a full aligned lookahead block after DEFLATE for the source inflater."""
    from src.core.editing import compress_asset
    packed=compress_asset(raw)+bytes(16)
    verify_geometry_stream(raw,packed)
    return packed


def _owned_counts(model: LevelModel) -> tuple[int,...]:
    return tuple(next((b.faces_offset for b in s.batches if b.flags==0x300),s.triangle_count) for s in model.segments)


def collision_helper_faces(model: LevelModel) -> frozenset[tuple[int,int]]:
    """Recognize generated helper records for OBJ export, without a project/ROM."""
    try:
        _grid_parameters(model)
        _check_helpers(model)
    except ValueError:
        return frozenset()
    return frozenset((s.index,f) for s,c in zip(model.segments,_owned_counts(model)) for f in range(c,s.triangle_count))


@dataclass(frozen=True)
class CollisionQuery:
    matching_segments: tuple[int,...]
    candidates: tuple[tuple[int,int],...]

    @property
    def required_entries(self) -> int:
        return len(self.matching_segments)+len(self.candidates)

    @property
    def complete(self) -> bool:
        return len(self.matching_segments)<=10 and self.required_entries<500


def collision_query(model: LevelModel, origins: np.ndarray, targets: np.ndarray, *,
                    vehicle: int = 0, runtime: RuntimeTrack | None = None) -> CollisionQuery:
    """Source assembly's padded rectangle/grid filtering, before truncation.

    Keep all matches so callers can see what the game's10-segment/500-entry
    truncation would discard. Guides are excluded by their real runtime flags.
    """
    a,b=np.asarray(origins,np.float32),np.asarray(targets,np.float32)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or not len(a) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Collision queries need matching finite XYZ point arrays')
    p=np.trunc(np.concatenate((a,b))[:,[0,2]]).astype(np.int64)
    lower,upper=p.min(axis=0)-20,p.max(axis=0)+20
    matches=[];faces=[]
    rt=runtime or validate_import_runtime(model)
    for s,generated in zip(model.segments,rt.segments):
        box=s.bounds
        if any(lower[k]>box.maximum[axis]+5 or upper[k]<box.minimum[axis]-5 for k,axis in enumerate((0,2))):
            continue
        matches.append(s.index)
        mask=0
        for k,axis in enumerate((0,2)):
            lo,hi=int(box.minimum[axis]),int(box.maximum[axis])
            start,end=np.clip((lower[k],upper[k]),lo,hi)
            delta=((hi-lo)>>3)+1
            for cell in range(8):
                if lo+(cell+1)*delta>=start and end>=lo+cell*delta:
                    mask|=1<<(cell+8*k)
        for batch,end in zip(s.batches,(*s.batches[1:],s.terminal_batch)):
            if batch.flags&0x200 or (vehicle==-1 and batch.flags&0x100):continue
            surface=model.textures[batch.texture_index].surface_type if batch.texture_index!=255 else 0
            if surface==11 or (vehicle==2 and surface==17) or (vehicle!=0 and surface==18):continue
            for face in range(batch.faces_offset,end.faces_offset):
                overlap=mask&generated.grid_masks[face]
                if overlap&255 and overlap&0xff00:faces.append((s.index,face))
    return CollisionQuery(tuple(matches),tuple(faces))


def _check_helpers(model: LevelModel, baseline: LevelModel | None = None) -> None:
    counts=_owned_counts(baseline or model)
    arrays=[s.vertices[s.indices[:count]] for s,count in zip(model.segments,counts)]
    points=np.concatenate(arrays)
    owners=np.concatenate([np.full(c,i) for i,c in enumerate(counts)])
    graph,_,_,_=_links(points,owners)
    start=0
    segptr=struct.unpack_from('>I',model.raw_data,4)[0]
    for i,(s,count) in enumerate(zip(model.segments,counts)):
        stop=start+count
        needed=sorted({int(j) for row in graph[start:stop] for j in row[1:] if owners[j]!=i})
        if len(needed)!=s.triangle_count-count or not np.array_equal(s.vertices[s.indices[count:]],points[needed]):
            raise ImportError('Collision seam helpers no longer match their neighboring segment faces')
        helpers=[b for b in s.batches if b.faces_offset>=count]
        if any(b.flags!=0x300 or model.textures[b.texture_index].surface_type in (11,15) for b in helpers):
            raise ImportError('Collision seam helpers must retain Hidden + No collision and a non-water surface')
        expected,_,_=collision_facets(s.vertices[s.indices])
        pointer=struct.unpack_from('>I',model.raw_data,segptr+i*0x44+0x14)[0]
        stored=np.frombuffer(model.raw_data,'>u2',s.triangle_count*4,pointer).reshape(-1,4)
        if not np.array_equal(stored,expected):raise ImportError('Segment collision graph does not match its seam helpers')
        start=stop


def _grid_parameters(model: LevelModel, baseline: LevelModel | None = None) -> tuple[int,tuple[int,int],tuple[tuple[int,int],...]]:
    boxes = [tuple(map(int,(*s.bounds.minimum,*s.bounds.maximum))) for s in model.segments]
    size = boxes[0][3]-boxes[0][0]-2
    if size not in CELL_SIZES or len(boxes)>MAX_SEGMENTS:
        raise ImportError('Unsupported spatial grid/segment count')
    origin = min(b[0]+1 for b in boxes),min(b[2]+1 for b in boxes)
    cells = []
    for b,s,count in zip(boxes,model.segments,_owned_counts(baseline or model)):
        if (b[3]-b[0]!=size+2 or b[5]-b[2]!=size+2 or (b[0]+1-origin[0])%size
                or (b[2]+1-origin[1])%size or not 1<=count<=MAX_CELL_FACES):
            raise ImportError('Spatial cells do not meet the local collision envelope')
        if any(b[a]+8*(((b[a+3]-b[a])>>3)+1)>32767 for a in (0,2)):
            raise ImportError('Spatial collision grid overflows signed16')
        vertices=s.vertices[s.indices[:count]]
        if np.any(vertices < np.array(b[:3])) or np.any(vertices > np.array(b[3:])):
            raise ImportError('Geometry leaves its protected spatial cell')
        cells.append(((b[0]+1-origin[0])//size,(b[2]+1-origin[1])//size))
    if len(set(cells))!=len(cells):
        raise ImportError('Duplicate spatial cells exceed overlap guarantees')
    return size,origin,tuple(cells)


def validate_segmented_runtime(model: LevelModel, baseline: LevelModel | None = None) -> RuntimeTrack:
    _grid_parameters(model,baseline)
    _check_helpers(model,baseline)
    return validate_import_runtime(model)


@lru_cache(maxsize=32)
def validate_segmented_track(original: bytes, raw: bytes, refs: tuple[TextureReference,...],
                             sprites: tuple[SpriteReference,...]) -> LevelModel:
    base,model = LevelModel.from_bytes(original),LevelModel.from_bytes(raw)
    if (len(raw)>TRACK_HEAP or model.byte_size!=len(raw) or model.triangle_count>MAX_OUTPUT_FACES
            or not len(base.textures)<=len(model.textures)<=255):
        raise ImportError('Invalid segmented baseline size or texture slots')
    size,origin,cells = _grid_parameters(model)
    order,nodes = _bsp(cells,origin,size)
    if order!=cells:
        raise ImportError('Segments are not stored in canonical BSP order')
    header = bytearray(original[:0x4c]);minimap=bytearray(original)
    for f in MINIMAP_FIELDS:
        header[f.offset:f.offset+f.size] = raw[f.offset:f.offset+f.size]
        minimap[f.offset:f.offset+f.size] = raw[f.offset:f.offset+f.size]
    validate_minimap_edit(original,bytes(minimap),sprites)
    for i,t in enumerate(model.textures):
        if not 0<=t.texture_id<len(refs) or not (0<=t.surface_type<len(SURFACES) or (i<len(base.textures) and t.surface_type==base.textures[i].surface_type)):
            raise ImportError('Invalid segmented material reference/surface')
        h = refs[t.texture_id].header
        permitted = {(h.width,h.height,h.raw[2])}
        permitted.update((b.width,b.height,b.format) for b in base.textures if b.texture_id==t.texture_id)
        if (t.width,t.height,t.format) not in permitted:
            raise ImportError('Invalid segmented texture metadata')
    start = struct.unpack_from('>I',raw,4)[0]
    segments = []
    for s in model.segments:
        p=start+s.index*0x44
        vp,tp,_,bp = struct.unpack_from('>4I',raw,p)
        vertices=tuple(struct.iter_unpack('>hhhBBBB',raw[vp:vp+10*s.vertex_count]))
        triangles=tuple(struct.iter_unpack('>BBBBhhhhhh',raw[tp:tp+16*s.triangle_count]))
        batches=tuple(BATCH_STRUCT.iter_unpack(raw[bp:bp+12*len(s.batches)]))
        opaque=0;transparent_seen=False;helper_seen=False
        for b,e in zip(s.batches,(*s.batches[1:],s.terminal_batch)):
            if (b.texture_index==255 or b.vertex_override or b.misc_data!=255 or b.texture_offset or b.flags not in (0,0x300)
                    or not 1<=e.vertices_offset-b.vertices_offset<=ENCODED_BATCH_VERTICES or not 1<=e.faces_offset-b.faces_offset<=MAX_BATCH_FACES):
                raise ImportError('Invalid static segmented batch')
            if b.flags==0x300:
                helper_seen=True
                continue
            if helper_seen:raise ImportError('Collision helper batches must follow rendered batches')
            transparent=refs[model.textures[b.texture_index].texture_id].translucent
            if not transparent and transparent_seen:raise ImportError('Invalid segmented render pass order')
            opaque+=not transparent;transparent_seen |= transparent
        if any(t[0] not in (0,0x40) for t in triangles):raise ImportError('Invalid segmented face flags')
        facets,_,_ = collision_facets(s.vertices[s.indices])
        box=tuple(map(int,(*s.bounds.minimum,*s.bounds.maximum)))
        segments.append(_Segment(vertices,triangles,batches,opaque,box,facets))
    envelope=_bounds(base,np.concatenate([s.vertices[s.indices] for s in model.segments]))
    if any((s.bounds[1],s.bounds[4])!=(envelope[1],envelope[4]) for s in segments):
        raise ImportError('Segment vertical bounds do not match the generated envelope')
    expected=_assemble(bytes(header),model.textures,segments,nodes,_global_bounds(base,segments))
    if raw!=expected:raise ImportError('Segmented collision/layout/BSP/PVS or protected metadata is not canonical')
    validate_segmented_runtime(model)
    compress_segmented_track(raw)
    return model


@lru_cache(maxsize=64)
def import_project_version(original: bytes, raw: bytes, refs: tuple[TextureReference,...],
                           sprites: tuple[SpriteReference,...]) -> int:
    try:
        validate_compiled_track(original,raw,refs,sprites)
        return 9
    except ValueError:
        validate_segmented_track(original,raw,refs,sprites)
        return 10
