"""meshcheck.py — checks of a triangle mesh: closed, manifold, consistently oriented, degenerate triangles,
volume, area, bounding box, and the vertex checksum Blender's script recomputes.
Version: 2026.10.28.1

The mesh keeps its vertices per CAD face (sources.py); the topology checks weld coincident points first (on a
grid of 1e-7 x the bounding-box diagonal). A closed, consistently oriented mesh has every directed edge exactly
once and its reverse exactly once. Volume by the divergence theorem (signed: positive for outward triangles).
The tessellation's volume bound: every mesh point lies within the chord tolerance `tol` of the surface, so
|V_mesh - V_cad| <= A_cad x tol (plus rounding).
"""
from __future__ import annotations

import numpy as np


def weld(V: np.ndarray, rel: float = 1e-7) -> tuple[np.ndarray, np.ndarray]:
    """(unique points, index of each input point among them), merging points closer than ~rel x diagonal."""
    if not len(V):
        return V, np.zeros(0, np.int64)
    diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0))) or 1.0
    key = np.round(V / (rel * diag)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[first], np.asarray(inv).reshape(-1)


def triangle_areas(V: np.ndarray, T: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]), axis=1)


def volume(V: np.ndarray, T: np.ndarray) -> float:
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def topology(V: np.ndarray, T: np.ndarray) -> dict:
    """closed, manifold, oriented; counts of boundary and non-manifold edges and degenerate triangles."""
    P, idx = weld(V)
    W = idx[T]
    degenerate = (W[:, 0] == W[:, 1]) | (W[:, 1] == W[:, 2]) | (W[:, 2] == W[:, 0])
    W = W[~degenerate]
    n = np.int64(len(P))
    d = np.concatenate([W[:, [0, 1]], W[:, [1, 2]], W[:, [2, 0]]])
    code = d[:, 0] * n + d[:, 1]
    rev = d[:, 1] * n + d[:, 0]
    uniq, counts = np.unique(code, return_counts=True)
    repeated = int((counts > 1).sum())                 # the same directed edge twice: flipped or non-manifold
    has_rev = np.isin(rev, uniq)
    boundary = int((~has_rev).sum())
    und = np.unique(np.sort(d, axis=1)[:, 0] * n + np.sort(d, axis=1)[:, 1], return_counts=True)[1]
    nonmanifold = int((und > 2).sum())
    return {"closed": boundary == 0 and repeated == 0 and nonmanifold == 0,
            "boundary_edges": boundary, "repeated_edges": repeated, "nonmanifold_edges": nonmanifold,
            "degenerate_triangles": int(degenerate.sum()), "welded_vertices": int(len(P))}


def checksum(V: np.ndarray) -> float:
    """An order-sensitive sum over the float32 coordinates (as Blender stores them); the script recomputes it."""
    v = np.asarray(V, np.float32).astype(np.float64)
    w = (np.arange(len(v), dtype=np.float64) % 997.0) + 1.0
    return float((w * (v[:, 0] + 2.0 * v[:, 1] + 3.0 * v[:, 2])).sum())


def checksum_tris(T: np.ndarray) -> int:
    """An order-sensitive integer checksum of the triangle indices."""
    t = np.asarray(T, np.int64).reshape(-1)
    w = (np.arange(len(t), dtype=np.int64) % 1009) + 1
    return int((w * t).sum() % 2147483647)


def check_object(m: dict) -> dict:
    """The mesh record of one object (sources.object_mesh) -> its results and checks."""
    V, T = m["vertices"], m["triangles"]
    topo = topology(V, T)
    vol, area = volume(V, T), float(triangle_areas(V, T).sum())
    lo, hi = V.min(axis=0), V.max(axis=0)
    out = {"vertices": int(len(V)), "triangles": int(len(T)), **topo,
           "volume_mm3": round(vol, 6), "area_mm2": round(area, 6),
           "bbox_min": [round(float(x), 6) for x in lo], "bbox_max": [round(float(x), 6) for x in hi],
           "tol": m["tol"], "angle_deg": m["angle_deg"]}
    checks = {"closed": {"passed": topo["closed"],
                         "why": None if topo["closed"] else
                         f"{topo['boundary_edges']} open, {topo['repeated_edges']} doubled and "
                         f"{topo['nonmanifold_edges']} non-manifold edges"},
              "no_degenerate": {"passed": topo["degenerate_triangles"] == 0, "count": topo["degenerate_triangles"]}}
    if m.get("cad_volume") is not None:
        cv = float(m["cad_volume"])
        bound = float(m.get("cad_area") or area) * float(m["tol"]) + 1e-9 * abs(cv) + 1e-9
        err = vol - cv
        out.update(cad_volume_mm3=round(cv, 6), volume_error=round(err / cv, 9) if cv else None)
        checks["volume"] = {"passed": abs(err) <= bound, "mesh": round(vol, 6), "cad": round(cv, 6),
                            "error_mm3": round(err, 6), "bound_mm3": round(bound, 6)}
    if m.get("b3dt_volume") is not None and m.get("cad_volume"):
        bv = m["b3dt_volume"]
        checks["b3dt_volume"] = {"passed": abs(bv - m["cad_volume"]) <= 1e-3 * max(abs(bv), 1.0),
                                 "b3dt": bv, "step": round(m["cad_volume"], 3)}
    return {"result": out, "checks": checks}
