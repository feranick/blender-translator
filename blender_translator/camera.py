"""camera.py — view presets, the fit solver and our own projection (the model Blender's camera follows).
Version: 2026.10.28.1

The camera looks from `from` to `to` with `up`: right r = d x up, up' = r x d, d the viewing direction; in
Blender's terms its local X = r, Y = up', Z = -d. Sensor fit AUTO with sensor_width S_mm applies to the larger
image side N = max(W, H), with square pixels. A point p, with x = (p - from).r, y = (p - from).up',
z = (p - from).d (the depth), lands at pixel (from the top-left corner; a pixel i covers [i, i + 1)):
  perspective: u = W/2 + (lens/S_mm) N x/z,   v = H/2 - (lens/S_mm) N y/z
  orthographic: u = W/2 + N x/ortho_scale,    v = H/2 - N y/ortho_scale
Blender's bpy_extras.object_utils.world_to_camera_view gives (u/W, 1 - v/H); the run compares the two.

Fit: the scene's points (or one object's, with "target") fill the fraction `fit` of the frame in the limiting
direction, centred: orthographic exactly (ortho_scale and a sideways shift), perspective by bisection on the
distance along the view direction with a sideways recentring (three rounds).
"""
from __future__ import annotations

import math

import numpy as np

SENSOR_MM = 36.0
PRESETS = {  # direction from the target to the camera, up
    "iso": ((1, -1, 1), (0, 0, 1)), "iso_back": ((-1, 1, 1), (0, 0, 1)),
    "front": ((0, -1, 0), (0, 0, 1)), "back": ((0, 1, 0), (0, 0, 1)),
    "left": ((-1, 0, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)), "bottom": ((0, 0, -1), (0, 1, 0)),
}
DEFAULT_FIT = 0.85
DEFAULT_LENS = 50.0


def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n == 0:
        raise ValueError("zero vector")
    return v / n


def basis(frm, to, up) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(right, up', d): an orthonormal frame; up is replaced when it is parallel to the view direction."""
    d = _unit(np.asarray(to, float) - np.asarray(frm, float))
    up = np.asarray(up, float)
    if np.linalg.norm(np.cross(d, up)) < 1e-9 * np.linalg.norm(up):
        up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    r = _unit(np.cross(d, up))
    return r, np.cross(r, d), d


def matrix_world(cam: dict) -> list:
    """The camera object's 4x4 world matrix for Blender (columns X = r, Y = up', Z = -d, translation = from)."""
    r, u, d = basis(cam["from"], cam["to"], cam["up"])
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = r, u, -d, np.asarray(cam["from"], float)
    return M.tolist()


def project(cam: dict, P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pixels (N, 2: u from the left, v from the top) and depths (N) of points P (N, 3)."""
    P = np.atleast_2d(np.asarray(P, float))
    r, u, d = basis(cam["from"], cam["to"], cam["up"])
    q = P - np.asarray(cam["from"], float)
    x, y, z = q @ r, q @ u, q @ d
    W, H = cam["width"], cam["height"]
    N = max(W, H)
    if cam["type"] == "ortho":
        s = N / cam["ortho_scale"]
        return np.stack([W / 2 + s * x, H / 2 - s * y], 1), z
    k = cam["lens_mm"] / cam.get("sensor_mm", SENSOR_MM) * N
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.stack([W / 2 + k * x / z, H / 2 - k * y / z], 1), z


def achieved_fit(cam: dict, P: np.ndarray) -> dict:
    """How the points sit in the frame: fit (the limiting fraction), centre offset (px), all inside, in front."""
    uv, z = project(cam, P)
    W, H = cam["width"], cam["height"]
    if (z <= 0).any() or not np.isfinite(uv).all():
        return {"fit": None, "inside": False, "in_front": False}
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    fit = max((hi[0] - lo[0]) / W, (hi[1] - lo[1]) / H)
    return {"fit": float(fit), "center_offset_px": [float((lo[0] + hi[0]) / 2 - W / 2), float((lo[1] + hi[1]) / 2 - H / 2)],
            "inside": bool(lo[0] >= 0 and lo[1] >= 0 and hi[0] <= W and hi[1] <= H), "in_front": True}


def _clip(cam: dict, P: np.ndarray) -> None:
    _, z = project(cam, P)
    span = float(z.max() - z.min()) or 1.0
    cam["clip_start"] = float(max(z.min() - 0.5 * span, 1e-3 * max(z.max(), 1e-3)))
    cam["clip_end"] = float(z.max() + 0.5 * span + 1.0)


def solve(view: dict, P: np.ndarray, width: int, height: int, target_pts: np.ndarray | None = None) -> dict:
    """The camera for one view of the points P (all objects) in a W x H image; target_pts: the points to frame
    (default P). Returns the camera dict (type, from, to, up, lens_mm or ortho_scale, sensor_mm, width, height,
    clip_start, clip_end, matrix_world) plus 'fit' as achieved on the framed points."""
    F = P if target_pts is None else target_pts
    lo, hi = F.min(axis=0), F.max(axis=0)
    center = (lo + hi) / 2
    R = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
    proj = view.get("projection", "perspective")
    fit = view.get("fit")
    v = view.get("view", "iso")
    if isinstance(v, dict):
        frm, to = np.asarray(v["from"], float), np.asarray(v["to"], float)
        up = np.asarray(v.get("up", (0, 0, 1)), float)
        s = _unit(frm - to)
        literal = fit is None
    else:
        sdir, up = PRESETS[v]
        s, up, to = _unit(sdir), np.asarray(up, float), center
        frm = to + s * 3 * R
        literal = False
    fit = DEFAULT_FIT if fit is None else float(fit)
    cam = {"type": "ortho" if proj == "ortho" else "persp", "up": up.tolist(), "width": int(width), "height": int(height),
           "sensor_mm": SENSOR_MM}
    W, H = int(width), int(height)
    N = max(W, H)
    if proj == "ortho":
        cam["from"], cam["to"] = frm.tolist(), to.tolist()
        r, u, d = basis(frm, to, up)
        q = F - frm
        x, y = q @ r, q @ u
        if literal:
            cam["ortho_scale"] = float(view.get("ortho_scale") or 2.4 * R)
        else:
            xr, yr = float(x.max() - x.min()), float(y.max() - y.min())
            cam["ortho_scale"] = max(xr * N / (fit * W), yr * N / (fit * H), 1e-9)
            shift = r * (x.max() + x.min()) / 2 + u * (y.max() + y.min()) / 2
            if isinstance(v, dict):          # keep the aim point; only centre a preset view
                shift = np.zeros(3)
            frm, to = frm + shift, to + shift
            back = float(((F - frm) @ d).min())   # keep every point in front of the camera
            if back < R:
                frm = frm - d * (R - back + 0.1 * R)
            cam["from"], cam["to"] = frm.tolist(), to.tolist()
    else:
        cam["lens_mm"] = float(view.get("lens_mm", DEFAULT_LENS))
        if literal:
            cam["from"], cam["to"] = frm.tolist(), to.tolist()
        else:
            aim = np.asarray(to, float)
            for _ in range(3 if not isinstance(v, dict) else 1):
                def f_of(D):
                    c = dict(cam, **{"from": (aim + s * D).tolist(), "to": aim.tolist()})
                    a = achieved_fit(c, F)
                    return a["fit"] if a["in_front"] else math.inf
                lo_d = max(float(np.max((F - aim) @ s)), 0.0) + 1e-3 * R   # every point just in front
                hi_d = lo_d * 2
                while f_of(hi_d) > fit and hi_d < 1e9 * R:
                    hi_d *= 2
                if f_of(lo_d) <= fit:
                    hi_d = lo_d
                for _i in range(80):
                    mid = 0.5 * (lo_d + hi_d)
                    if f_of(mid) > fit:
                        lo_d = mid
                    else:
                        hi_d = mid
                D = hi_d
                cam["from"], cam["to"] = (aim + s * D).tolist(), aim.tolist()
                if isinstance(v, dict):
                    break
                a = achieved_fit(cam, F)
                r, u, d = basis(cam["from"], cam["to"], up)
                depth = float((aim - np.asarray(cam["from"])) @ d)
                k = cam["lens_mm"] / SENSOR_MM * N
                du, dv = a["center_offset_px"]
                aim = aim + r * du / k * depth - u * dv / k * depth
    _clip(cam, P)
    cam["matrix_world"] = matrix_world(cam)
    a = achieved_fit(cam, F)
    cam["fit"] = round(a["fit"], 6) if a["fit"] is not None else None
    cam["inside"] = a["inside"]
    return cam


def corners(lo, hi) -> np.ndarray:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
