"""Single-segment OBJ compiler, without GUI/OpenGL dependencies.

Local sources: structs.h:601–763, f3ddkr.h:161–173, collision.h:7,
tracks.c:1741–1764,1885–1980,2832–3222; hasm/collision.c:120–178.
All new faces have a base plane; neighbors use geometric directed edges. One
segment needs no BSP, and its visibility row contains just the self bit.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re
import struct

import numpy as np

from src.core.geometry import TRACK_HEAP, collision_base_planes, verify_geometry_stream
from src.core.level_model import LevelModel, TextureInfo, BATCH_STRUCT
from src.core.materials import TextureReference, SURFACES
from src.core.minimap import MINIMAP_FIELDS, SpriteReference, validate_minimap_edit
from src.core.obj_units import GAME_UNITS_PER_OBJ_UNIT
from src.core.track_rebuild import RuntimeTrack, runtime_track
from src.core.render_batches import MAX_BATCH_VERTICES, MAX_BATCH_FACES, ENCODED_BATCH_VERTICES

MAX_OBJ_BYTES = 4*1024*1024
MAX_OBJ_VERTICES = 20000
MAX_FACES = 499  # collision.h:500 slots, including the segment marker.


class ImportError(ValueError):
    """Invalid or unsupported small-track geometry; no project has been changed."""


@dataclass(frozen=True)
class ObjCorner:
    vertex: int
    uv: int | None


@dataclass(frozen=True)
class ObjFace:
    corners: tuple[ObjCorner, ObjCorner, ObjCorner]
    material: str


@dataclass(frozen=True)
class ObjMesh:
    vertices: tuple[tuple[float, float, float], ...]
    colors: tuple[tuple[float, float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    faces: tuple[ObjFace, ...]

    @property
    def materials(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(face.material for face in self.faces))


@dataclass(frozen=True)
class ImportOptions:
    """Convert OBJ units once to game units, then add a game-space offset."""

    scale: float = GAME_UNITS_PER_OBJ_UNIT
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    reverse_winding: bool = False
    double_sided: bool = False


@dataclass(frozen=True)
class CompiledTrack:
    raw: bytes
    faces: int
    vertices: int
    batches: int
    shared_edges: int
    boundary_edges: int
    runtime_bytes: int
    packed_bytes: int

    def to_text(self) -> str:
        return (f'{self.faces} triangles · {self.vertices} stored vertices · {self.batches} batches\n'
                f'{self.shared_edges} shared collision edges · {self.boundary_edges} boundary edges\n'
                f'One visible segment; BSP is empty. Collision candidates: {self.faces+1}/500.\n'
                f'Track heap: {self.runtime_bytes:,}/{TRACK_HEAP:,} B · compressed: {self.packed_bytes:,} B\n'
                'Existing objects, checkpoints, minimap artwork and level settings are retained.')


def _numbers(values: Sequence[str], line: int) -> tuple[float, ...]:
    try:
        result = tuple(float(v) for v in values)
    except ValueError as error:
        raise ImportError(f'Line {line}: expected numeric OBJ values') from error
    if not all(math.isfinite(v) for v in result):
        raise ImportError(f'Line {line}: OBJ values must be finite')
    return result


def parse_obj(text: str, *, max_faces: int = MAX_FACES) -> ObjMesh:
    if len(text.encode('utf-8')) > MAX_OBJ_BYTES:
        raise ImportError('OBJ exceeds the 4 MiB small-track limit')
    vertices: list[tuple[float, float, float]] = []
    colors: list[tuple[float, float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals = 0
    faces: list[ObjFace] = []
    material = '(default)'

    def index(value: str, count: int, line: int) -> int:
        try:
            i = int(value)
        except ValueError as error:
            raise ImportError(f'Line {line}: invalid OBJ index') from error
        target = i-1 if i > 0 else count+i
        if i == 0 or not 0 <= target < count:
            raise ImportError(f'Line {line}: OBJ index outside defined data')
        return target

    for line, raw in enumerate(text.splitlines(), 1):
        parts = raw.partition('#')[0].split()
        if not parts:
            continue
        kind, values = parts[0], parts[1:]
        if kind == 'v':
            v = _numbers(values, line)
            if len(v) not in (3,4,6,7):
                raise ImportError(f'Line {line}: vertex needs XYZ, optional W, or RGB/RGBA')
            xyz = v[:3]
            if len(v) == 4:
                if v[3] == 0:
                    raise ImportError(f'Line {line}: homogeneous W cannot be zero')
                xyz = tuple(x/v[3] for x in xyz)
                if not all(math.isfinite(x) for x in xyz):
                    raise ImportError(f'Line {line}: homogeneous vertex overflow')
            color = (*v[3:6], v[6] if len(v) == 7 else 1.0) if len(v) >= 6 else (1.,1.,1.,1.)
            if any(c < 0 or c > 1 for c in color):
                raise ImportError(f'Line {line}: vertex colors must be in 0..1')
            vertices.append(xyz)
            colors.append(color)
            if len(vertices) > MAX_OBJ_VERTICES:
                raise ImportError('OBJ has too many input vertices for the small-track importer')
        elif kind == 'vt':
            v = _numbers(values,line)
            if len(v) not in (2,3):
                raise ImportError(f'Line {line}: texture coordinates need U,V')
            uvs.append(v[:2])
        elif kind == 'vn':
            if len(_numbers(values,line)) != 3:
                raise ImportError(f'Line {line}: normal needs XYZ')
            normals += 1
        elif kind == 'usemtl':
            if not values:
                raise ImportError(f'Line {line}: missing material name')
            material = ' '.join(values)
        elif kind == 'f':
            if not 3 <= len(values) <= 64:
                raise ImportError(f'Line {line}: face needs 3..64 corners')
            corners: list[ObjCorner] = []
            for value in values:
                fields = value.split('/')
                if not 1 <= len(fields) <= 3:
                    raise ImportError(f'Line {line}: invalid face corner')
                vi = index(fields[0],len(vertices),line)
                ti = index(fields[1],len(uvs),line) if len(fields)>1 and fields[1] else None
                if len(fields)>2 and fields[2]:
                    index(fields[2],normals,line)
                corners.append(ObjCorner(vi,ti))
            points = np.asarray([vertices[c.vertex] for c in corners],np.float64)
            extent = float(np.max(np.ptp(points,axis=0)))
            normal = np.cross(points,np.roll(points,-1,axis=0)).sum(axis=0)
            magnitude = float(np.linalg.norm(normal))
            if not math.isfinite(magnitude) or magnitude <= max(extent*extent,1)*1e-12:
                raise ImportError(f'Line {line}: degenerate face')
            if len(corners)>3:
                n = normal/magnitude
                if np.max(np.abs((points-points[0])@n)) > max(extent,1)*1e-6:
                    raise ImportError(f'Line {line}: triangulate nonplanar polygons before import')
                xy = np.delete(points,int(np.argmax(np.abs(n))),axis=1)
                edges = np.roll(xy,-1,axis=0)-xy
                following = np.roll(edges,-1,axis=0)
                cross = edges[:,0]*following[:,1]-edges[:,1]*following[:,0]
                if not (np.all(cross > 1e-12) or np.all(cross < -1e-12)):
                    raise ImportError(f'Line {line}: triangulate concave/collinear polygons before import')
            for j in range(1,len(corners)-1):
                faces.append(ObjFace((corners[0],corners[j],corners[j+1]),material))
            if len(faces)>max_faces:
                raise ImportError(f'This import mode supports at most {max_faces:,} input triangles')
        elif kind not in ('o','g','s','mtllib'):
            raise ImportError(f'Line {line}: unsupported OBJ statement {kind!r}')
    if not faces:
        raise ImportError('OBJ has no triangle faces')
    return ObjMesh(tuple(vertices),tuple(colors),tuple(uvs),tuple(faces))


def read_obj(path: Path, *, max_faces: int = MAX_FACES) -> ObjMesh:
    if path.stat().st_size > MAX_OBJ_BYTES:
        raise ImportError('OBJ exceeds the 4 MiB small-track limit')
    with path.open('rb') as stream:
        data = stream.read(MAX_OBJ_BYTES+1)
    if len(data)>MAX_OBJ_BYTES:
        raise ImportError('OBJ exceeds the 4 MiB small-track limit')
    try:
        return parse_obj(data.decode('utf-8-sig'), max_faces=max_faces)
    except UnicodeDecodeError as error:
        raise ImportError('OBJ must be UTF-8 text') from error


def default_materials(mesh: ObjMesh, model: LevelModel) -> dict[str,int]:
    result: dict[str,int] = {}
    for name in mesh.materials:
        slot = re.fullmatch(r'(?:texture_)?slot_(\d+)',name)
        texture = re.fullmatch(r'texture_(\d+)_frame_\d+',name)
        value = int(slot[1]) if slot and int(slot[1]) < len(model.textures) else 0
        if texture:
            value = next((i for i,t in enumerate(model.textures) if t.texture_id == int(texture[1])),0)
        result[name] = value
    return result


def collision_facets(points: np.ndarray) -> tuple[np.ndarray,int,int]:
    """Generate a manifold face-neighbor graph using welded integer XYZ edges."""
    count = len(points)
    facets = np.repeat(np.arange(count,dtype=np.uint16)[:,None],4,axis=1)
    edges: dict[tuple, list[tuple[int,int,tuple,tuple]]] = {}
    triangles: set[tuple] = set()
    for face, tri in enumerate(points):
        vertices = [tuple(map(int,p)) for p in tri]
        key = tuple(sorted(vertices))
        if len(set(vertices)) != 3 or key in triangles:
            raise ImportError('Duplicate or collapsed triangles after coordinate quantization')
        triangles.add(key)
        for i,a in enumerate(vertices):
            b = vertices[(i+1)%3]
            edges.setdefault(tuple(sorted((a,b))),[]).append((face,i,a,b))
    shared = boundary = 0
    for rows in edges.values():
        if len(rows)>2:
            raise ImportError('Nonmanifold collision edge: more than two faces share an edge')
        if len(rows)==1:
            boundary += 1
            continue
        a,b = rows
        if a[2] != b[3] or a[3] != b[2]:
            raise ImportError('Inconsistent face winding at a shared edge')
        facets[a[0],a[1]+1] = b[0]
        facets[b[0],b[1]+1] = a[0]
        shared += 1
    return facets,shared,boundary


def _assemble(template: bytes, textures: tuple[TextureInfo,...], vertices: Sequence[tuple[int,...]],
              triangles: Sequence[tuple[int,...]], batches: Sequence[tuple[int,...]], opaque: int,
              bounds: tuple[int,...], facets: np.ndarray) -> bytes:
    """Canonical zero-padded serialized layout, with source runtime members zeroed."""
    output = bytearray(template[:0x4C])
    def append(data: bytes) -> int:
        output.extend(bytes((-len(output)) % 16))
        pointer = len(output)
        output.extend(data)
        return pointer
    texture_pointer = append(b''.join(struct.pack('>IBBBb',t.texture_id,t.width,t.height,t.format,t.surface_type) for t in textures))
    segment_pointer = append(bytes(0x44))
    vertex_pointer = append(b''.join(struct.pack('>hhhBBBB',*v) for v in vertices))
    face_pointer = append(b''.join(struct.pack('>BBBBhhhhhh',*t) for t in triangles))
    terminal = (0,0,len(vertices),len(triangles),255,0,0)
    batch_pointer = append(b''.join(BATCH_STRUCT.pack(*b) for b in (*batches,terminal)))
    facet_pointer = append(facets.astype('>u2').tobytes())
    box_pointer = append(struct.pack('>6h',*bounds))
    pvs_pointer = append(b'\x01')
    empty_pointer = append(b'')
    struct.pack_into('>6I',output,0,texture_pointer,segment_pointer,box_pointer,empty_pointer,pvs_pointer,empty_pointer)
    struct.pack_into('>4h',output,0x18,len(textures),1,0,0)
    x0,y0,z0,x1,y1,z1 = bounds
    struct.pack_into('>6h',output,0x3C,x0,x1,y0,y1,z0,z1)
    struct.pack_into('>i',output,0x48,len(output))
    struct.pack_into('>7I',output,segment_pointer,vertex_pointer,face_pointer,0,batch_pointer,0,facet_pointer,0)
    struct.pack_into('>3h',output,segment_pointer+0x1C,len(vertices),len(triangles),len(batches))
    output[segment_pointer+0x40] = opaque
    return bytes(output)


def _bounds(template: LevelModel, points: np.ndarray) -> tuple[int,...]:
    lower = np.minimum(points.min(axis=(0,1))-1,np.asarray(template.stored_bounds.minimum)).astype(np.int64)
    upper = np.maximum(points.max(axis=(0,1))+1,np.asarray(template.stored_bounds.maximum)).astype(np.int64)
    lower[1] = max(-32768,min(int(lower[1]),int(points[:,:,1].min())-1000))
    upper[1] = min(32767,max(int(upper[1]),int(points[:,:,1].max())+1000))
    if np.any(lower < -32768) or np.any(upper > 32767):
        raise ImportError('Geometry leaves no signed16 room for track bounds')
    for axis in (0,2):
        if lower[axis]+8*(((upper[axis]-lower[axis]) >> 3)+1) > 32767:
            raise ImportError('Track bounds would overflow the game collision grid')
    return tuple(map(int,(*lower,*upper)))


def compile_obj(mesh: ObjMesh, template: bytes, refs: Sequence[TextureReference],
                materials: Mapping[str,int], options: ImportOptions = ImportOptions(),
                *, appearance: bytes | None = None, _staging: bool = False) -> CompiledTrack:
    model = LevelModel.from_bytes(template)
    current = LevelModel.from_bytes(appearance or template)
    if not model.textures or len(model.textures)>255:
        raise ImportError('Target must have 1..255 existing texture slots')
    if len(current.textures) != len(model.textures):
        raise ImportError('Appearance must retain the target texture slot count')
    if not 1 <= len(mesh.faces) <= MAX_FACES:
        raise ImportError('Small-track import needs 1..499 triangles')
    if not math.isfinite(options.scale) or options.scale <= 0 or len(options.offset)!=3 or not all(math.isfinite(v) for v in options.offset):
        raise ImportError('Scale must be positive and transforms finite')
    positions = np.rint(np.asarray(mesh.vertices,np.float64)*options.scale+np.asarray(options.offset))
    if not np.isfinite(positions).all() or np.any(positions < -32768) or np.any(positions > 32767):
        raise ImportError('Transformed OBJ coordinates exceed signed16 storage')
    records: list[tuple[int,int,tuple[int,...],tuple[int,...]]] = []
    for face in mesh.faces:
        slot = materials.get(face.material)
        if type(slot) is not int or not 0 <= slot < len(model.textures):
            raise ImportError(f'Choose an existing texture slot for material {face.material!r}')
        info = current.textures[slot]
        if not 0 <= info.texture_id < len(refs):
            raise ImportError('Texture ID outside the ROM table')
        h = refs[info.texture_id].header
        corners = tuple(reversed(face.corners)) if options.reverse_winding else face.corners
        face_points = positions[[c.vertex for c in corners]]
        face_normal = np.cross(face_points[1]-face_points[0],face_points[2]-face_points[0])
        axes = [i for i in range(3) if i != int(np.argmax(np.abs(face_normal)))]
        uv_lower = face_points[:,axes].min(axis=0)
        uv_extent = np.maximum(np.ptp(face_points[:,axes],axis=0),1)
        verts: list[tuple[int,...]] = []
        uv: list[int] = []
        for c in corners:
            color = tuple(int(round(v*255)) for v in mesh.colors[c.vertex])
            if color[:2] == (1,1):
                color = (0,*color[1:])  # Nearest literal RGB; R=G=1 is a loader sentinel.
            point = tuple(map(int,positions[c.vertex]))
            verts.append((*point,*color))
            pair = mesh.uvs[c.uv] if c.uv is not None else tuple((np.asarray(point)[axes]-uv_lower)/uv_extent)
            uv.extend((int(round(pair[0]*h.width*32)),int(round((1-pair[1])*h.height*32))))
        if any(v < -32768 or v > 32767 for v in uv):
            raise ImportError('UVs exceed signed s10.5 storage; reduce UV tiling before import')
        records.append((int(refs[info.texture_id].translucent),slot,tuple(verts),tuple(uv)))
    records.sort(key=lambda r:(r[0],r[1]))
    vertices: list[tuple[int,...]] = []
    triangles: list[tuple[int,...]] = []
    batches: list[tuple[int,...]] = []
    batch_vertices: dict[tuple[int,...],int] = {}
    active_slot = -1
    batch_start = 0
    opaque = 0
    for translucent,slot,verts,uv in records:
        new = {v for v in verts if v not in batch_vertices}
        if (slot != active_slot or len(batch_vertices)+len(new)>MAX_BATCH_VERTICES
                or len(triangles)-batch_start >= MAX_BATCH_FACES):
            active_slot = slot
            batch_vertices = {}
            batch_start = len(triangles)
            batches.append((slot,0,len(vertices),len(triangles),255,0,0))
            opaque += not translucent
        indices: list[int] = []
        for v in verts:
            if v not in batch_vertices:
                batch_vertices[v] = len(batch_vertices)
                vertices.append(v)
            indices.append(batch_vertices[v])
        triangles.append((0x40 if options.double_sided else 0,*indices,*uv))
    points = np.asarray([tuple(v[:3] for v in r[2]) for r in records],np.int32)
    normals = collision_base_planes(points)
    if np.any(np.linalg.norm(normals[:,:3],axis=1) < .5):
        raise ImportError('Triangle collapses after signed16 coordinate quantization')
    facets,shared,boundary = collision_facets(points)
    bounds = _bounds(model,points)
    if opaque > 255:
        raise ImportError('Imported opaque batches exceed the game’s 255-batch field')
    header = bytearray(template[:0x4C])
    for f in MINIMAP_FIELDS:
        header[f.offset:f.offset+f.size] = (appearance or template)[f.offset:f.offset+f.size]
    raw = _assemble(bytes(header),current.textures,vertices,triangles,batches,opaque,bounds,facets)
    from src.core.editing import compress_asset
    runtime = validate_import_runtime(LevelModel.from_bytes(raw))
    packed = compress_asset(raw)
    if not _staging:
        verify_geometry_stream(raw,packed)
    return CompiledTrack(raw,len(triangles),len(vertices),len(batches),shared,boundary,runtime.byte_size,len(packed))


def validate_import_runtime(model: LevelModel) -> RuntimeTrack:
    """Validate newly generated planes after import and subsequent geometry edits."""
    runtime = runtime_track(model)
    if any(np.any(np.linalg.norm(s.planes[:,:3],axis=1)<.5) for s in runtime.segments):
        raise ImportError('A folded edge produces a degenerate collision bisector')
    return runtime


@lru_cache(maxsize=64)
def validate_compiled_track(original: bytes, raw: bytes, refs: tuple[TextureReference,...],
                            sprites: tuple[SpriteReference,...]) -> LevelModel:
    """Validate the canonical imported baseline, independently of its OBJ file."""
    base = LevelModel.from_bytes(original)
    model = LevelModel.from_bytes(raw)
    if len(raw)>TRACK_HEAP or model.byte_size != len(raw) or len(model.segments)!=1 or model.bsp_nodes:
        raise ImportError('Imported baseline must use one canonical segment')
    s = model.segments[0]
    if not 1 <= s.triangle_count <= MAX_FACES or len(model.textures)!=len(base.textures) or not model.textures:
        raise ImportError('Imported counts exceed the small-track envelope')
    template = bytearray(original[:0x4C])
    minimap = bytearray(original)
    for f in MINIMAP_FIELDS:
        template[f.offset:f.offset+f.size] = raw[f.offset:f.offset+f.size]
        minimap[f.offset:f.offset+f.size] = raw[f.offset:f.offset+f.size]
    validate_minimap_edit(original,bytes(minimap),sprites)
    for a,b in zip(base.textures,model.textures):
        if not 0 <= b.texture_id < len(refs):
            raise ImportError('Imported texture reference is outside the ROM')
        h = refs[b.texture_id].header
        metadata = (b.width,b.height,b.format)
        expected = (a.width,a.height,a.format) if a.texture_id==b.texture_id else (h.width,h.height,h.raw[2])
        if metadata != expected or (a.surface_type!=b.surface_type and not 0 <= b.surface_type < len(SURFACES)):
            raise ImportError('Imported texture metadata or surface is invalid')
    vp,tp,_,bp = struct.unpack_from('>4I',raw,struct.unpack_from('>I',raw,4)[0])
    vertices = tuple(struct.iter_unpack('>hhhBBBB',raw[vp:vp+s.vertex_count*10]))
    triangles = tuple(struct.iter_unpack('>BBBBhhhhhh',raw[tp:tp+s.triangle_count*16]))
    batches = tuple(BATCH_STRUCT.iter_unpack(raw[bp:bp+len(s.batches)*12]))
    opaque = 0
    transparent_seen = False
    for i,b in enumerate(s.batches):
        following = (*s.batches[1:],s.terminal_batch)[i]
        if (b.texture_index==255 or b.vertex_override or b.misc_data!=255 or b.texture_offset or b.flags
                or not 1 <= following.vertices_offset-b.vertices_offset <= ENCODED_BATCH_VERTICES
                or not 1 <= following.faces_offset-b.faces_offset <= MAX_BATCH_FACES):
            raise ImportError('Imported batch exceeds the static microcode envelope')
        transparent = refs[model.textures[b.texture_index].texture_id].translucent
        if not transparent:
            if transparent_seen:
                raise ImportError('Imported batches must preserve opaque/transparent pass order')
            opaque += 1
        transparent_seen |= transparent
    if any(t[0] not in (0,0x40) for t in triangles):
        raise ImportError('Imported face flags must use the supported collision form')
    points = s.vertices[s.indices]
    if np.any(np.linalg.norm(collision_base_planes(points)[:,:3],axis=1)<.5):
        raise ImportError('Degenerate imported triangle')
    facets,_,_ = collision_facets(points)
    bounds = _bounds(base,points)
    expected_raw = _assemble(bytes(template),model.textures,vertices,triangles,batches,opaque,bounds,facets)
    if raw != expected_raw:
        raise ImportError('Imported layout, collision links, bounds, visibility or protected metadata is not canonical')
    validate_import_runtime(model)
    runtime_track(model,cutscene=True)
    from src.core.editing import compress_asset
    verify_geometry_stream(raw,compress_asset(raw))
    return model
