"""Frame-rate independent fly/orbit camera with no Qt or GL dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]
WORLD_UP: FloatArray = np.array([0.0, 1.0, 0.0], dtype=np.float32)

if TYPE_CHECKING:
    from src.core.textures import SpriteInstance
    from src.core.level_model import LevelModel
    from src.core.placement import TerrainSurface


def normalized(vector: FloatArray) -> FloatArray:
    """Return a unit vector, preserving zero vectors."""
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-8 else np.zeros(3, dtype=np.float32)


@dataclass
class Camera:
    position: FloatArray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    target: FloatArray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    yaw: float = -130.0
    pitch: float = -25.0
    fov: float = 60.0
    speed: float = 25.0
    near: float = 0.1
    far: float = 10000.0
    view: str = "Perspective"
    ortho_height: float = 100.0
    view_override: FloatArray | None = None

    @property
    def forward(self) -> FloatArray:
        if self.view_override is not None:
            return -self.view_override[2, :3].copy()
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        return np.array(
            [math.cos(yaw) * math.cos(pitch), math.sin(pitch),
             math.sin(yaw) * math.cos(pitch)], dtype=np.float32,
        )

    @property
    def right(self) -> FloatArray:
        if self.view_override is not None:
            return self.view_override[0, :3].copy()
        yaw = math.radians(self.yaw)
        return np.array([-math.sin(yaw), 0., math.cos(yaw)], np.float32)

    def set_view(self, name: str) -> None:
        if name not in ("Perspective", "Top", "Front", "Right"):
            raise ValueError("Unknown camera view")
        distance = max(float(np.linalg.norm(self.target - self.position)), 1.)
        self.view = name
        self.yaw, self.pitch = {"Perspective": (-130., -25.), "Top": (-90., -90.),
                                "Front": (-90., 0.), "Right": (180., 0.)}[name]
        self.ortho_height = max(1., distance * math.tan(math.radians(self.fov) / 2) * 2)
        self.position = self.target - self.forward * distance

    def look(self, dx: float, dy: float, *, orbit: bool = False) -> None:
        if self.view != "Perspective":
            up = self.view_matrix()[1, :3]
            shift = (-self.right * dx + up * dy) * self.ortho_height / 600
            self.position += shift
            self.target += shift
            return
        distance = max(float(np.linalg.norm(self.target - self.position)), 0.1)
        self.yaw = (self.yaw + dx * 0.18) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch - dy * 0.18))
        if orbit:
            self.position = self.target - self.forward * distance
        else:
            self.target = self.position + self.forward * distance

    def move(self, forward: float, right: float, up: float, dt: float, boost: bool) -> None:
        vertical = self.view_matrix()[1, :3] if self.view != "Perspective" else self.forward
        direction = vertical * forward + self.right * right + WORLD_UP * up
        offset = normalized(direction) * self.speed * dt * (4.0 if boost else 1.0)
        self.position += offset
        self.target += offset

    def pan(self, dx: float, dy: float, height: float) -> None:
        """Grab the scene in logical pixels at the orbit target's depth."""
        if height <= 0 or not np.isfinite((dx, dy, height)).all():
            raise ValueError('Panning needs finite deltas and a positive viewport height')
        view = self.view_matrix()
        if self.view == 'Perspective':
            depth = max(float(np.dot(self.target-self.position, -view[2, :3])), self.near, .1)
            span = 2*depth*math.tan(math.radians(self.fov)*.5)
        else:
            span = self.ortho_height
        shift = (-view[0, :3]*dx + view[1, :3]*dy)*(span/height)
        self.position += shift
        self.target += shift

    def zoom(self, steps: float) -> None:
        if self.view != "Perspective":
            self.ortho_height = float(np.clip(self.ortho_height * 0.85 ** steps, .1, 1e7))
            return
        self.fov = max(20.0, min(100.0, self.fov - steps * 3.0))

    def fit_bounds(self, minimum: FloatArray, maximum: FloatArray, aspect: float = 1.0) -> None:
        """Frame bounds without changing the user's movement speed."""
        self.target = (minimum + maximum) * 0.5
        radius = max(float(np.linalg.norm(maximum - minimum)) * 0.5, 1.0)
        if self.view == "Perspective":
            self.yaw, self.pitch, self.fov = -130.0, -25.0, 60.0
        self.ortho_height = radius * 2.3 / min(max(aspect, .01), 1.)
        half_vertical = math.radians(self.fov) * 0.5
        half_horizontal = math.atan(math.tan(half_vertical) * max(aspect, 0.01))
        distance = radius / math.sin(min(half_vertical, half_horizontal)) * 1.15
        self.position = self.target - self.forward * distance
        self.near = max(radius / 1000.0, 0.05)
        self.far = max(distance + radius * 100.0, 1000.0)

    def view_matrix(self) -> FloatArray:
        if self.view_override is not None:
            return self.view_override
        forward = self.forward
        right = self.right
        up = np.cross(right, forward)
        matrix = np.eye(4, dtype=np.float32)
        matrix[0, :3] = right
        matrix[1, :3] = up
        matrix[2, :3] = -forward
        matrix[:3, 3] = -matrix[:3, :3] @ self.position
        return matrix

    def projection_matrix(self, aspect: float) -> FloatArray:
        if self.view != "Perspective":
            matrix = np.eye(4, dtype=np.float32)
            matrix[0, 0] = 2 / (self.ortho_height * max(aspect, .01))
            matrix[1, 1] = 2 / self.ortho_height
            matrix[2, 2] = -2 / (self.far - self.near)
            matrix[2, 3] = -(self.far + self.near) / (self.far - self.near)
            return matrix
        scale = 1.0 / math.tan(math.radians(self.fov) * 0.5)
        matrix = np.zeros((4, 4), dtype=np.float32)
        matrix[0, 0] = scale / max(aspect, 0.01)
        matrix[1, 1] = scale
        matrix[2, 2] = (self.far + self.near) / (self.near - self.far)
        matrix[2, 3] = 2.0 * self.far * self.near / (self.near - self.far)
        matrix[3, 2] = -1.0
        return matrix


def screen_ray(x: float, y: float, width: float, height: float,
               view_projection: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Logical Qt pixels to a normalized world ray; works with HiDPI widgets."""
    if width <= 0 or height <= 0:
        raise ValueError('Viewport dimensions must be positive')
    inverse = np.linalg.inv(np.asarray(view_projection, dtype=np.float64))
    ndc = np.array([2*x/width-1, 1-2*y/height, -1, 1], np.float64)
    first = inverse @ ndc; ndc[2]=1;last=inverse @ ndc
    first=first[:3]/first[3];last=last[:3]/last[3]
    return first, normalized(last-first)


def ground_placement(camera: Camera, terrain: TerrainSurface, width: float,
                     height: float) -> tuple[int, int, int] | None:
    """Place in the view centre, or on visible ground below that centre line.

    Look/flight targets are navigation anchors, not surface coordinates. Side
    orthographic views need a vertical query at the centre's viewing depth,
    followed by a visibility check against the actual camera ray.
    """
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError('Viewport dimensions must be positive and finite')
    matrix = camera.projection_matrix(width/height) @ camera.view_matrix()
    for fraction in (.5, .55, .6, .65, .7, .75, .8, .85, .9, .95):
        origin, direction = screen_ray(width*.5, height*fraction, width, height, matrix)
        point = terrain.grounded_position(origin, direction)
        if point is not None:
            pixel = project_point(np.asarray(point), matrix, width, height)
            if pixel is not None and 0 <= pixel[0] <= width and 0 <= pixel[1] <= height:
                return point
    if camera.view not in ('Front', 'Right'):
        return None
    depth = max(float(np.dot(camera.target-camera.position, camera.forward)), camera.near)
    column = np.asarray(camera.position+camera.forward*depth, np.float64)
    column[1] = float(camera.position[1])+camera.ortho_height*.5
    point = terrain.grounded_position(column, np.array((0., -1., 0.)))
    if point is None:
        return None
    pixel = project_point(np.asarray(point), matrix, width, height)
    if pixel is None or not (0 <= pixel[0] <= width and 0 <= pixel[1] <= height):
        return None
    origin, direction = screen_ray(*pixel, width, height, matrix)
    obstruction = terrain.raycast(origin, direction)
    if obstruction is not None and np.dot(obstruction-origin, direction) < np.dot(np.asarray(point)-origin, direction)-.01:
        return None
    return point


def pick_track_vertex(model: LevelModel, x: float, y: float, width: float, height: float,
                      matrix: FloatArray, *, segment: int = -1,
                      cull_backfaces: bool = False, radius: float = 14.) -> tuple[int, int] | None:
    """Logical-pixel vertex targets, with front-face and terrain occlusion checks.

    The pointer may be just outside a triangle at its corner. Test the ray at
    the projected vertex itself rather than requiring the pointer to hit a face.
    """
    from src.core.materials import pick_track_face
    if width <= 0 or height <= 0 or not np.isfinite((x, y, radius)).all() or radius <= 0:
        return None
    candidates: list[tuple[float, float, int, int, FloatArray, FloatArray, float]] = []
    for s in model.segments:
        if segment >= 0 and s.index != segment:
            continue
        faces = np.zeros(s.triangle_count, bool)
        for batch, end in zip(s.batches, (*s.batches[1:], s.terminal_batch)):
            if not batch.hidden:
                faces[batch.faces_offset:end.faces_offset] = True
        points = np.column_stack((s.vertices, np.ones(s.vertex_count))) @ np.asarray(matrix, np.float64).T
        valid = points[:, 3] > 0
        ndc = np.divide(points[:, :3], points[:, 3:4], out=np.full((s.vertex_count, 3), np.inf), where=valid[:,None])
        pixels = (ndc[:, :2]*np.array((1.,-1.))+1)*np.array((width,height))/2
        distance = np.linalg.norm(pixels-(x,y),axis=1)
        for i in np.flatnonzero(valid & (distance <= radius) & (np.abs(ndc[:,2]) <= 1)):
            incident = faces & np.any(s.indices == i, axis=1)
            if not incident.any():
                continue
            origin, direction = screen_ray(*pixels[i],width,height,matrix)
            if cull_backfaces:
                triangle = s.vertices[s.indices[incident]].astype(np.float64)
                normal = np.cross(triangle[:,1]-triangle[:,0],triangle[:,2]-triangle[:,0])
                front = (normal@direction < -1e-9) | ((s.triangle_flags[incident] & 0x40) != 0)
                if not front.any():
                    continue
            depth = float(np.dot(s.vertices[i]-origin,direction))
            if depth >= 0:
                candidates.append((float(distance[i]),depth,s.index,int(i),origin,direction,depth))
    candidates.sort(key=lambda item:item[:4])
    for _,_,s,i,origin,direction,depth in candidates:
        hit = pick_track_face(model,origin,direction,segment=segment,cull_backfaces=cull_backfaces)
        if hit is not None:
            part = model.segments[hit[0]]
            triangle = part.vertices[part.indices[hit[1]]].astype(np.float64)
            normal = np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
            denominator = float(normal@direction)
            if abs(denominator) > 1e-10:
                front_depth = float(normal@(triangle[0]-origin))/denominator
                if front_depth+max(.01,depth*1e-6) < depth:
                    continue
        return s,i
    return None


def ray_sphere_distance(origin: FloatArray, direction: FloatArray, center: FloatArray, radius: float) -> float | None:
    """Nearest nonnegative ray/sphere hit, including an origin inside the sphere."""
    if radius <= 0: return None
    delta = origin-center
    b=float(np.dot(delta,direction));c=float(np.dot(delta,delta))-radius*radius
    discriminant=b*b-c
    if discriminant < 0: return None
    root=math.sqrt(discriminant)
    near,far=-b-root,-b+root
    return max(near,0.0) if far>=0 else None


def project_point(point: FloatArray, matrix: FloatArray, width: float, height: float) -> tuple[float, float] | None:
    """World position to Qt logical pixels; reject points behind/outside depth."""
    clip = np.asarray(matrix, np.float64) @ np.array([*point, 1.], np.float64)
    if not np.isfinite(clip).all() or clip[3] <= 0 or abs(clip[2]) > clip[3]:
        return None
    return (float((clip[0]/clip[3]+1)*width*.5), float((1-clip[1]/clip[3])*height*.5))


def translation_length(camera: Camera, center: FloatArray, height: float, pixels: float = 90.) -> float | None:
    depth = float(np.dot(np.asarray(center)-camera.position, camera.forward))
    if height <= 0 or depth <= camera.near:
        return None
    if camera.view != "Perspective":
        return camera.ortho_height * pixels / height
    return 2*depth*math.tan(math.radians(camera.fov)*.5)*pixels/height


def pick_translation_handle(x: float, y: float, center: FloatArray, length: float,
                            matrix: FloatArray, width: float, height: float) -> int | None:
    """-1 = center, 0/1/2 = X/Y/Z; use screen pixels for consistent hit areas."""
    origin = project_point(center, matrix, width, height)
    if origin is None:
        return None
    mouse = np.array([x, y], np.float64)
    first = np.asarray(origin)
    if float(np.linalg.norm(mouse-first)) <= 10:
        return -1
    hits: list[tuple[float, int]] = []
    for axis in range(3):
        endpoint = np.array(center, np.float64)
        endpoint[axis] += length
        projected = project_point(endpoint, matrix, width, height)
        if projected is None:
            continue
        delta = np.asarray(projected)-first
        squared = float(np.dot(delta, delta))
        if squared < 18**2:
            continue  # An end-on axis has no useful screen-space direction.
        t = float(np.dot(mouse-first, delta)/squared)
        nearest = first + np.clip(t, .18, 1.)*delta
        distance = float(np.linalg.norm(mouse-nearest))
        if distance <= 8:
            hits.append((distance, axis))
    return min(hits)[1] if hits else None


def ray_plane_point(origin: FloatArray, direction: FloatArray, point: FloatArray, normal: FloatArray) -> FloatArray | None:
    denominator = float(np.dot(direction, normal))
    if abs(denominator) < 1e-7:
        return None
    distance = float(np.dot(np.asarray(point)-origin, normal)/denominator)
    result = origin + direction*distance
    return result if distance >= 0 and np.isfinite(result).all() else None


@dataclass(frozen=True)
class TranslationDrag:
    position: FloatArray
    anchor: FloatArray
    normal: FloatArray
    axis: int | None
    matrix: FloatArray
    width: float
    height: float

    @classmethod
    def begin(cls, position: FloatArray, axis: int | None, x: float, y: float,
              forward: FloatArray, matrix: FloatArray, width: float, height: float) -> TranslationDrag | None:
        if axis is not None and axis not in (0, 1, 2):
            raise ValueError("Translation axis must be X, Y, Z or the view plane")
        normal = np.array(forward, np.float64)
        if axis is not None:
            normal[axis] = 0
        norm = float(np.linalg.norm(normal))
        if norm < 1e-4:
            return None
        normal /= norm
        start = np.array(position, np.float64)
        origin, direction = screen_ray(x, y, width, height, matrix)
        anchor = ray_plane_point(origin, direction, start, normal)
        if anchor is None:
            return None
        return cls(start, anchor, normal, axis, np.array(matrix, np.float64), width, height)

    def position_at(self, x: float, y: float, step: int = 1) -> tuple[int, int, int] | None:
        if step < 1:
            raise ValueError("Snap step must be positive")
        point = self.world_at(x, y, step)
        return tuple(int(value) for value in np.clip(point, -32768, 32767)) if point is not None else None

    def world_at(self, x: float, y: float, step: float = 0) -> FloatArray | None:
        """Unbounded target for derived handles; stored lane bytes have their own bounds."""
        if step < 0 or not math.isfinite(step):
            raise ValueError("Snap step must be finite and nonnegative")
        origin, direction = screen_ray(x, y, self.width, self.height, self.matrix)
        point = ray_plane_point(origin, direction, self.position, self.normal)
        if point is None:
            return None
        delta = point-self.anchor
        if self.axis is not None:
            delta = np.eye(3)[self.axis]*delta[self.axis]
        if step:
            delta = np.rint(delta/step)*step
        return self.position + delta


def billboard_axes(view: FloatArray, camera_position: FloatArray, center: FloatArray,
                   *, upright: bool = False) -> tuple[FloatArray, FloatArray]:
    """Scenery stays vertical and faces the eye; other sprites follow the view."""
    if not upright:
        return view[0, :3], view[1, :3]
    delta = np.asarray(camera_position)-np.asarray(center)
    right = np.array([delta[2], 0., -delta[0]], np.float32)
    if float(np.dot(right, right)) < 1e-8:
        right = np.array([view[0, 0], 0., view[0, 2]], np.float32)
        if float(np.dot(right, right)) < 1e-8:
            right = np.array([1., 0., 0.], np.float32)
    return normalized(right), WORLD_UP.copy()


def ray_sprite_distance(origin: FloatArray, direction: FloatArray, sprite: SpriteInstance,
                        view: FloatArray, *, camera_position: FloatArray | None = None,
                        upright_sceneries: bool = True) -> float | None:
    """Pick actual billboard pixels, respecting the renderer's alpha cutout."""
    if sprite.scale <= 0:
        return None
    center = np.asarray(sprite.position, np.float64)
    right, up = billboard_axes(view, origin if camera_position is None else camera_position, center,
                               upright=sprite.upright and upright_sceneries)
    hit = ray_plane_point(origin, direction, center, np.cross(right, up))
    if hit is None:
        return None
    offset = hit-center
    x = float(np.dot(offset, right))/sprite.scale
    y = float(np.dot(offset, up))/sprite.scale
    for tile in sprite.tiles:
        if tile.right <= tile.left or tile.top <= tile.bottom or not tile.left <= x <= tile.right or not tile.bottom <= y <= tile.top:
            continue
        header = tile.frame.header
        # Same UV endpoints and GL_LINEAR/CLAMP_TO_EDGE texel centers as SpriteMesh.
        u = (x-tile.left)/(tile.right-tile.left)
        v = (tile.top-y)/(tile.top-tile.bottom)
        px = float(np.clip(1/32+u*(header.width-1-1/32)-.5, 0, header.width-1))
        py = float(np.clip(v*(header.height-1)-.5, 0, header.height-1))
        x0, y0 = int(px), int(py)
        x1, y1 = min(x0+1, header.width-1), min(y0+1, header.height-1)
        dx, dy = px-x0, py-y0
        pixels = tile.frame.pixels
        alpha = (float(pixels[y0,x0,3])*(1-dx)*(1-dy) + float(pixels[y0,x1,3])*dx*(1-dy)
                 + float(pixels[y1,x0,3])*(1-dx)*dy + float(pixels[y1,x1,3])*dx*dy)
        if alpha >= 25.5:
            return float(np.dot(hit-origin, direction))
    return None


def pick_rotation_handle(x: float, y: float, center: FloatArray, length: float,
                         axes: tuple[int, ...], matrix: FloatArray, width: float, height: float) -> int | None:
    mouse = np.array([x, y])
    hits: list[tuple[float, int]] = []
    for axis in axes:
        points = []
        for angle in np.linspace(0, math.tau, 65):
            point = np.asarray(center, np.float64).copy()
            point[(axis + 1) % 3] += math.cos(angle) * length * .8
            point[(axis + 2) % 3] += math.sin(angle) * length * .8
            points.append(project_point(point, matrix, width, height))
        for first, last in zip(points[:-1], points[1:]):
            if first is None or last is None:
                continue
            a, b = np.asarray(first), np.asarray(last)
            delta = b - a
            t = float(np.clip(np.dot(mouse - a, delta) / max(float(np.dot(delta, delta)), 1e-10), 0, 1))
            distance = float(np.linalg.norm(mouse - a - delta * t))
            if distance <= 8:
                hits.append((distance, axis))
    return min(hits)[1] if hits else None


@dataclass(frozen=True)
class ScalarDrag:
    mode: str
    axis: int | None
    position: FloatArray
    press: tuple[float, float]
    anchor: FloatArray | None
    matrix: FloatArray
    width: float
    height: float

    @classmethod
    def begin(cls, mode: str, axis: int | None, position: FloatArray, x: float, y: float,
              matrix: FloatArray, width: float, height: float) -> ScalarDrag | None:
        anchor = None
        if mode == "Rotate":
            if axis not in (0, 1, 2):
                return None
            origin, ray = screen_ray(x, y, width, height, matrix)
            point = ray_plane_point(origin, ray, position, np.eye(3)[axis])
            if point is None or np.linalg.norm(point - position) < 1e-5:
                return None
            anchor = normalized(point - position)
        return cls(mode, axis, np.array(position), (x, y), anchor, np.array(matrix), width, height)

    def value_at(self, x: float, y: float, snap: bool = False) -> float | None:
        if self.mode == "Scale":
            value = 2 ** float(np.clip(((x - self.press[0]) - (y - self.press[1])) / 120, -6, 6))
            return max(.01, round(value * 10) / 10) if snap else value
        assert self.axis is not None and self.anchor is not None
        normal = np.eye(3)[self.axis]
        origin, ray = screen_ray(x, y, self.width, self.height, self.matrix)
        point = ray_plane_point(origin, ray, self.position, normal)
        if point is None or np.linalg.norm(point - self.position) < 1e-5:
            return None
        vector = normalized(point - self.position)
        angle = math.degrees(math.atan2(float(np.dot(normal, np.cross(self.anchor, vector))), float(np.dot(self.anchor, vector))))
        return round(angle / 15) * 15 if snap else angle
