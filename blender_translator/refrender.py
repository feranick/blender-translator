"""refrender.py — the independent reference: a z-buffer rasteriser (numpy) of the scene's meshes, and the
comparisons with Blender's check pass.
Version: 2026.10.28.1

From scene.npz and a camera (camera.py's model, at the check pass's size) it draws which object covers each
pixel centre (0: none), nearest first. Perspective depth is interpolated as 1/z (linear in screen space),
orthographic depth linearly. Triangles are rasterised in vectorised chunks of candidate pixels from their
bounding boxes. Blender's check pass (every object an unlit emission of its check colour, 1 sample, pixel filter
0.01 px) samples the same pixel centres, so the two maps should agree except on edges.

Comparisons (on the reference's terms):
- coverage IoU and per-object IoU, leaving out a band of `band` px around every edge of the reference map
  (antialiasing and ties on the edges);
- flat colours: on interior pixels (`band` + 1 px from any edge), the mean and largest difference per channel
  between Blender's picture and each object's own colour.
"""
from __future__ import annotations

import numpy as np

from . import camera as C

CHUNK = 4_000_000


def rasterise(cam: dict, meshes: list[dict]) -> dict:
    """{'index': (H, W) int16 object index (k + 1; 0 none), 'depth': (H, W) float, 'skipped_triangles': n}."""
    W, H = int(cam["width"]), int(cam["height"])
    depth = np.full(H * W, np.inf)
    index = np.zeros(H * W, np.int16)
    persp = cam["type"] != "ortho"
    skipped = 0
    for k, m in enumerate(meshes):
        uv, z = C.project(cam, m["vertices"])
        T = np.asarray(m["triangles"], np.int64)
        if persp:
            bad = (z[T] <= cam.get("clip_start", 0.0)).any(axis=1) | ~np.isfinite(uv[T]).all(axis=(1, 2))
            skipped += int(bad.sum())
            T = T[~bad]
        a, b, c = uv[T[:, 0]], uv[T[:, 1]], uv[T[:, 2]]
        area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        umin = np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0])
        umax = np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0])
        vmin = np.minimum(np.minimum(a[:, 1], b[:, 1]), c[:, 1])
        vmax = np.maximum(np.maximum(a[:, 1], b[:, 1]), c[:, 1])
        i0 = np.clip(np.ceil(umin - 0.5), 0, W).astype(np.int64)
        i1 = np.clip(np.floor(umax - 0.5), -1, W - 1).astype(np.int64)
        j0 = np.clip(np.ceil(vmin - 0.5), 0, H).astype(np.int64)
        j1 = np.clip(np.floor(vmax - 0.5), -1, H - 1).astype(np.int64)
        nx, ny = i1 - i0 + 1, j1 - j0 + 1
        keep = (nx > 0) & (ny > 0) & (np.abs(area) > 1e-12)
        sel = np.nonzero(keep)[0]
        counts = (nx * ny)[sel]
        if not len(sel):
            continue
        zt = z[T]
        start = 0
        cum = np.cumsum(counts)
        while start < len(sel):
            base = cum[start - 1] if start else 0
            stop = int(np.searchsorted(cum, base + CHUNK, side="right"))
            stop = max(stop, start + 1)
            ts, cn = sel[start:stop], counts[start:stop]
            rep = np.repeat(np.arange(len(ts)), cn)
            off = np.arange(int(cn.sum())) - np.repeat(np.cumsum(cn) - cn, cn)
            t = ts[rep]
            px = i0[t] + off % nx[t]
            py = j0[t] + off // nx[t]
            x, y = px + 0.5, py + 0.5
            A, B, Cc = a[t], b[t], c[t]
            w0 = (B[:, 0] - x) * (Cc[:, 1] - y) - (B[:, 1] - y) * (Cc[:, 0] - x)
            w1 = (Cc[:, 0] - x) * (A[:, 1] - y) - (Cc[:, 1] - y) * (A[:, 0] - x)
            w2 = (A[:, 0] - x) * (B[:, 1] - y) - (A[:, 1] - y) * (B[:, 0] - x)
            s = np.sign(area[t])
            inside = (w0 * s >= 0) & (w1 * s >= 0) & (w2 * s >= 0)
            if inside.any():
                w0, w1, w2, t, px, py = w0[inside], w1[inside], w2[inside], t[inside], px[inside], py[inside]
                ar = area[t]
                b0, b1, b2 = w0 / ar, w1 / ar, w2 / ar
                zz = zt[t]
                if persp:
                    d = 1.0 / (b0 / zz[:, 0] + b1 / zz[:, 1] + b2 / zz[:, 2])
                else:
                    d = b0 * zz[:, 0] + b1 * zz[:, 1] + b2 * zz[:, 2]
                pix = py * W + px
                order = np.lexsort((d, pix))
                pix, d = pix[order], d[order]
                first = np.ones(len(pix), bool)
                first[1:] = pix[1:] != pix[:-1]
                pix, d = pix[first], d[first]
                better = d < depth[pix]
                depth[pix[better]] = d[better]
                index[pix[better]] = k + 1
            start = stop
    return {"index": index.reshape(H, W), "depth": depth.reshape(H, W), "skipped_triangles": skipped}


# ----------------------------------------------------------------------------- comparisons

def edge_band(index: np.ndarray, band: int = 1) -> np.ndarray:
    """Pixels within `band` px (8-neighbourhood) of a change of index in the map."""
    e = np.zeros(index.shape, bool)
    e[:, 1:] |= index[:, 1:] != index[:, :-1]
    e[:, :-1] |= index[:, 1:] != index[:, :-1]
    e[1:, :] |= index[1:, :] != index[:-1, :]
    e[:-1, :] |= index[1:, :] != index[:-1, :]
    out = e.copy()
    for _ in range(max(band - 1, 0)):
        g = out.copy()
        g[1:, :] |= out[:-1, :]
        g[:-1, :] |= out[1:, :]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def decode_check(rgba: np.ndarray, colors: list[str]) -> np.ndarray:
    """Blender's check pass (H, W, 4) uint8 -> object index map: alpha >= 128 and the nearest check colour
    (k + 1); -1 where covered but no colour is within 48 (in 8-bit units)."""
    from .materials import hex_rgb8

    rgb = rgba[..., :3].astype(np.int32)
    pal = np.array([hex_rgb8(c) for c in colors], np.int32)
    dist = np.abs(rgb[..., None, :] - pal[None, None, :, :]).max(axis=-1)
    k = dist.argmin(axis=-1)
    out = (k + 1).astype(np.int16)
    out[dist.min(axis=-1) > 48] = -1
    out[rgba[..., 3] < 128] = 0
    return out


def compare_maps(ref: np.ndarray, got: np.ndarray, n_objects: int, band: int = 1) -> dict:
    """Coverage IoU and per-object IoU off the edge band; pixels of an unknown colour; the edge band's size."""
    if ref.shape != got.shape:
        return {"error": f"sizes differ: reference {ref.shape[::-1]}, Blender {got.shape[::-1]}"}
    keep = ~edge_band(ref, band)

    def iou(a, b):
        a, b = a & keep, b & keep
        u = int((a | b).sum())
        return 1.0 if u == 0 else float((a & b).sum()) / u

    per = {k: round(iou(ref == k, got == k), 6) for k in range(1, n_objects + 1)}
    return {"coverage_iou": round(iou(ref > 0, got != 0), 6), "objects_iou": per,
            "unknown_pixels": int(((got == -1) & keep).sum()), "compared_pixels": int(keep.sum()),
            "edge_pixels": int((~keep).sum())}


def compare_flat(ref: np.ndarray, rgba: np.ndarray, colors: list[str], band: int = 2) -> dict:
    """Flat lighting: on interior pixels of each object, |picture - the object's colour| (8-bit units)."""
    from .materials import hex_rgb8

    inner = ~edge_band(ref, band)
    out = {}
    for k, c in enumerate(colors, start=1):
        m = inner & (ref == k)
        if not m.any():
            out[k] = None
            continue
        d = np.abs(rgba[..., :3][m].astype(np.int32) - np.array(hex_rgb8(c)))
        out[k] = {"mean": round(float(d.mean()), 4), "max": int(d.max()), "pixels": int(m.sum())}
    return out
