"""scene.py — the backend's inputs: scene.npz (the meshes), scene.json (cameras, lights, materials, settings) and
scene.py (the fixed script Blender runs, from scene_template.py).
Version: 2026.10.28.1

Everything numeric is decided here, not in Blender: the cameras (camera.solve), the light rig of each view
(placed in the camera's frame, so every view is lit alike), the light power (irradiance x pi x D^2, Blender
units being mm), the check colours, the floor, the check pass's size (the long side at most CHECK_MAX px, the
same aspect), and the test points whose projection Blender reports back.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np

from . import __version__
from . import camera as C
from . import materials as M
from . import meshcheck

CHECK_MAX = 1024
TEMPLATE = Path(__file__).with_name("scene_template.py")


def check_size(W: int, H: int) -> tuple[int, int]:
    s = min(1.0, CHECK_MAX / max(W, H))
    return max(1, int(round(W * s))), max(1, int(round(H * s)))


def light_rig(preset: str, cam: dict, R: float) -> list[dict]:
    """The preset's area lights for one view: positions in the camera's frame, aimed at the camera's target."""
    out = []
    r, u, d = C.basis(cam["from"], cam["to"], cam["up"])
    target = np.asarray(cam["to"], float)
    for name, (a, b, c), irr, size in M.LIGHTS[preset]["lights"]:
        direction = C._unit(a * r + b * u - c * d)
        D = M.LIGHT_DISTANCE * R
        pos = target + direction * D
        L = {"from": pos.tolist(), "to": target.tolist(), "up": [0.0, 0.0, 1.0]}
        out.append({"name": f"blnt_{name}", "size": float(size * R), "energy": float(irr * math.pi * D * D),
                    "location": pos.tolist(), "matrix_world": C.matrix_world(L)})
    return out


def build(study: dict, meshes: list[dict]) -> dict:
    """The scene description (JSON-able, without the arrays) and the cameras per view."""
    o = study.get("output") or {}
    W, H = int(o.get("width", 1600)), int(o.get("height", 1200))
    cw, ch = check_size(W, H)
    P = np.vstack([m["vertices"] for m in meshes])
    lo, hi = P.min(axis=0), P.max(axis=0)
    R = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
    preset = study.get("lights", M.DEFAULT_LIGHTS)
    bg = M.background_spec(study.get("background"))
    objs, by_name = [], {m["name"]: m for m in meshes}
    for k, (ob, m) in enumerate(zip(study["objects"], meshes)):
        col = M.PALETTE[k]
        objs.append({"name": ob["name"], "index": k + 1, "material": M.material_spec(ob), "check_color": col,
                     "check_color_linear": M.hex_linear(col), "vertices": int(len(m["vertices"])),
                     "triangles": int(len(m["triangles"])), "checksum": meshcheck.checksum(m["vertices"]),
                     "triangles_checksum": meshcheck.checksum_tris(m["triangles"])})
    views = []
    for v in study["views"]:
        target = by_name[v["target"]]["vertices"] if v.get("target") else None
        cam = C.solve(v, P, W, H, target)
        tp = np.vstack([C.corners(lo, hi)] + [C.corners(m["vertices"].min(axis=0), m["vertices"].max(axis=0))
                                              for m in meshes])
        views.append({"name": v["name"], "camera": cam, "lights": light_rig(preset, cam, R),
                      "test_points": tp.tolist()})
    floor = None
    if bg["floor"]:
        c, z, s = (lo + hi) / 2, float(lo[2]), 20 * R
        floor = {"z": z, "vertices": [[c[0] - s, c[1] - s, z], [c[0] + s, c[1] - s, z], [c[0] + s, c[1] + s, z],
                                      [c[0] - s, c[1] + s, z]]}
    return {"blnt": __version__, "units": "mm", "objects": objs, "views": views,
            "lights": {"preset": preset, "world": M.LIGHTS[preset]["world"]},
            "background": bg, "floor": floor,
            "output": {"width": W, "height": H, "check_width": cw, "check_height": ch,
                       "samples": int(o.get("samples", 128)), "denoise": bool(o.get("denoise", True)),
                       "format": o.get("format", "png"), "view_transform": M.LIGHTS[preset]["view_transform"],
                       "threads": int(study.get("_threads", 1))},
            "blend": bool(study.get("blend", False)), "radius": R, "bbox": [lo.tolist(), hi.tolist()]}


def write(folder: Path, scene: dict, meshes: list[dict]) -> dict:
    """scene.npz, scene.json and scene.py in the folder. Returns their paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    arr = {}
    for k, m in enumerate(meshes):
        arr[f"v{k}"] = np.asarray(m["vertices"], np.float64)
        arr[f"t{k}"] = np.asarray(m["triangles"], np.int32)
    np.savez(folder / "scene.npz", **arr)
    (folder / "scene.json").write_text(json.dumps(scene, indent=1))
    shutil.copyfile(TEMPLATE, folder / "scene.py")
    return {"npz": str(folder / "scene.npz"), "json": str(folder / "scene.json"), "script": str(folder / "scene.py")}


def load(folder: Path) -> tuple[dict, list[dict]]:
    """(scene.json, meshes [{name, vertices, triangles}]) of a written scene: for render_images and the checks."""
    folder = Path(folder)
    scene = json.loads((folder / "scene.json").read_text())
    z = np.load(folder / "scene.npz")
    meshes = [{"name": ob["name"], "vertices": z[f"v{k}"], "triangles": z[f"t{k}"].astype(np.int64)}
              for k, ob in enumerate(scene["objects"])]
    return scene, meshes
