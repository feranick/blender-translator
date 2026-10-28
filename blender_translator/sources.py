"""sources.py — the study's objects as triangle meshes in our own numbering, with their CAD volume and area.
Version: 2026.10.28.1

Sources: {"goal": b3dt goal} (built with build123d-translator), {"b3dt": {"step", "volume"}} (a b3dt result),
{"step": path} (mm), and the analytic {"box": [lx, ly, lz]} and {"sphere": r} for tests and benchmarks. CAD
shapes are tessellated with OpenCascade through build123d (chord tolerance `tol` in mm, angle `angle_deg`);
the vertices stay per CAD face (faces meet at shared, identical edge points), so Blender's smooth shading
stays within a face and the edges between faces stay sharp. Placement: rotate about the origin by rot_deg
(x, then y, then z: Blender's XYZ Euler), then translate by `at`. Shared conventions: mm, Z up; the analytic
shapes sit on z = 0, centred in X/Y, as b3dt's parts do.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np


class SourceError(Exception):
    pass


def have_b3dt() -> bool:
    try:
        import build123d_translator  # noqa: F401
        return True
    except ImportError:
        return False


def b3dt_version():
    try:
        import build123d_translator
        return getattr(build123d_translator, "__version__", "yes")
    except ImportError:
        return None


# ----------------------------------------------------------------------------- analytic shapes

def box_mesh(lx: float, ly: float, lz: float) -> tuple[np.ndarray, np.ndarray]:
    """A box on z = 0 centred in X/Y: 24 vertices (4 per face), 12 outward-oriented triangles."""
    x0, x1, y0, y1, z0, z1 = -lx / 2, lx / 2, -ly / 2, ly / 2, 0.0, lz
    quads = [  # counter-clockwise seen from outside
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],  # -z
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],  # +z
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],  # -y
        [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)],  # +y
        [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)],  # -x
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],  # +x
    ]
    V = np.array([p for q in quads for p in q], float)
    T = np.array([t for k in range(6) for t in ((4 * k, 4 * k + 1, 4 * k + 2), (4 * k, 4 * k + 2, 4 * k + 3))], np.int64)
    return V, T


def sphere_mesh(r: float, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """An icosphere of radius r resting on z = 0 (centre at (0, 0, r)), subdivided until the chord deviation
    r (1 - cos(theta / 2)) of its longest edge is at most tol (and at most 7 levels: 327,680 triangles)."""
    t = (1 + math.sqrt(5)) / 2
    V = np.array([(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
                  (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)], float)
    V /= np.linalg.norm(V, axis=1)[:, None]
    F = np.array([(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
                  (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
                  (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)], np.int64)
    for _ in range(7):
        e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        cos = np.einsum("ij,ij->i", V[e[:, 0]], V[e[:, 1]])
        theta = float(np.arccos(np.clip(cos.min(), -1, 1)))
        if r * (1 - math.cos(theta / 2)) <= tol:
            break
        V, F = _subdivide(V, F)
    V = V * r
    V[:, 2] += r
    return V, F


def _subdivide(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    edges = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    uniq, inv = np.unique(edges, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    mid = V[uniq[:, 0]] + V[uniq[:, 1]]
    mid /= np.linalg.norm(mid, axis=1)[:, None]
    n, m = len(V), len(F)
    a, b, c = (n + inv[0:m], n + inv[m:2 * m], n + inv[2 * m:3 * m])
    i, j, k = F[:, 0], F[:, 1], F[:, 2]
    F2 = np.concatenate([np.stack([i, a, c], 1), np.stack([j, b, a], 1), np.stack([k, c, b], 1), np.stack([a, b, c], 1)])
    return np.vstack([V, mid]), F2


# ----------------------------------------------------------------------------- CAD shapes

def build_goal(goal: dict):
    try:
        from build123d_translator import translate as T
    except ImportError as exc:
        raise SourceError("a 'goal' source needs build123d-translator (llmt install b3dt)") from exc
    try:
        solid, _ = T.build(goal)
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"the goal does not build: {str(exc)[:300]}") from exc
    return solid


def load_step(path) -> object:
    p = Path(path).expanduser()
    if not p.is_file():
        raise SourceError(f"no STEP file {p}")
    try:
        from build123d import import_step
    except ImportError as exc:
        raise SourceError("a STEP source needs build123d (installed with build123d-translator)") from exc
    try:
        return import_step(str(p))
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"could not read the STEP file {p}: {str(exc)[:300]}") from exc


def shape_bbox(shape) -> tuple[np.ndarray, np.ndarray]:
    bb = shape.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def default_tol(diag: float) -> float:
    """Chord tolerance: 0.1 % of the bounding-box diagonal, at least 0.01 mm."""
    return max(0.001 * diag, 0.01)


def tessellate(shape, tol: float, angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """OpenCascade's triangulation through build123d: (vertices, triangles), vertices per CAD face."""
    verts, tris = shape.tessellate(float(tol), math.radians(float(angle_deg)))
    V = np.array([(v.X, v.Y, v.Z) for v in verts], float).reshape(-1, 3)
    T = np.array(tris, np.int64).reshape(-1, 3)
    if not len(T):
        raise SourceError("the shape tessellates to no triangles (is it a solid?)")
    return V, T


# ----------------------------------------------------------------------------- placement

def rotation(rot_deg) -> np.ndarray:
    """XYZ Euler (degrees): R = Rz @ Ry @ Rx, as Blender's default rotation mode."""
    rx, ry, rz = (math.radians(float(a)) for a in (rot_deg or (0, 0, 0)))
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def place(V: np.ndarray, obj: dict) -> np.ndarray:
    R = rotation(obj.get("rot_deg"))
    at = np.array(obj.get("at") or (0, 0, 0), float)
    return V @ R.T + at


# ----------------------------------------------------------------------------- objects

def object_mesh(obj: dict) -> dict:
    """One study object -> {name, vertices (placed, mm), triangles, cad_volume, cad_area, tol, angle_deg,
    source, seconds}. cad_volume is None when the source does not give one."""
    t0 = time.perf_counter()
    src = obj["source"]
    tes = obj.get("tessellation") or {}
    angle = float(tes.get("angle_deg", 5.0))
    info: dict = {"source": next(iter(src))}
    if "box" in src:
        lx, ly, lz = (float(v) for v in src["box"])
        V, T = box_mesh(lx, ly, lz)
        cad_v, cad_a = lx * ly * lz, 2 * (lx * ly + ly * lz + lx * lz)
        tol = 0.0
    elif "sphere" in src:
        r = float(src["sphere"])
        tol = float(tes.get("tol", default_tol(2 * r * math.sqrt(3))))
        V, T = sphere_mesh(r, tol)
        cad_v, cad_a = 4 / 3 * math.pi * r ** 3, 4 * math.pi * r ** 2
    else:
        if "goal" in src:
            shape = build_goal(src["goal"])
        elif "b3dt" in src:
            shape = load_step(src["b3dt"]["step"])
        else:
            shape = load_step(src["step"])
        lo, hi = shape_bbox(shape)
        tol = float(tes.get("tol", default_tol(float(np.linalg.norm(hi - lo)))))
        V, T = tessellate(shape, tol, angle)
        cad_v, cad_a = float(shape.volume), float(shape.area)
        if "b3dt" in src and src["b3dt"].get("volume") is not None:
            info["b3dt_volume"] = float(src["b3dt"]["volume"])
    return {"name": obj["name"], "vertices": place(V, obj), "triangles": T, "cad_volume": cad_v, "cad_area": cad_a,
            "tol": tol, "angle_deg": angle, **info, "seconds": round(time.perf_counter() - t0, 3)}
