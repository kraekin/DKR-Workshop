"""Scene-wide back-to-front ordering for blended draw ranges, without GL state."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class TransparentDraw:
    center: NDArray[np.float32]
    draw: Callable[[], None]


def draw_back_to_front(draws: Iterable[TransparentDraw], view: NDArray[np.float32]) -> None:
    """Sort by camera-space Z; radial distance is wrong for off-axis surfaces.

    Opaque/cutout draws must finish first. Each command retains its mesh's blend,
    depth-write, culling and animation behavior. Centers are range-level samples;
    intersecting transparent polygons still require splitting to order exactly.
    """
    for command in sorted(draws, key=lambda item: float(view[2, :3] @ item.center)):
        command.draw()
