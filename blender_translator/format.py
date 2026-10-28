"""format.py — the study format: study_format(), validate(studies), validate_study(study), estimate(study).
Version: 2026.10.28.1

Static checks only (no tessellation, no Blender): every error says what to change. A goal source is checked with
build123d-translator's own goal validation; STEP paths must exist on this machine. `estimate` is the upper-bound
size the router and the SLURM sizing use: {minutes, procs, mem_mb}.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import camera as C
from . import materials as M
from . import settings as S

STUDY_KEYS = ("objects", "views", "lights", "background", "output", "blend", "expect", "run")
OBJECT_KEYS = ("name", "source", "at", "rot_deg", "material", "color", "metallic", "roughness", "tessellation")
SOURCE_KEYS = ("goal", "b3dt", "step", "box", "sphere")
VIEW_KEYS = ("name", "view", "projection", "lens_mm", "fit", "target", "ortho_scale")
OUTPUT_KEYS = ("width", "height", "samples", "denoise", "format")
MAX_VIEWS = 12
MAX_SIDE = 4096
_NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")

# estimate constants (upper bounds; to be measured on mochi and carbonio, planning.md §10.E)
K_SAMPLE_S = 1.0e-6        # seconds per pixel-sample per thread (Cycles CPU)
K_DENOISE_S = 5.0e-8       # seconds per pixel (OpenImageDenoise)
T_START_S = 10.0           # Blender start, scene build
T_OBJECT_S = 3.0           # build + tessellation per CAD object
TRI_GUESS = 200_000        # triangles per CAD object (memory)

CONVENTIONS = ("mm, Z up; b3dt parts sit on z = 0 centred in X/Y; angles in degrees; colours as sRGB hex '#rrggbb'; "
               "rot_deg is XYZ Euler (x, then y, then z) about the origin, then 'at' translates; result paths dotted")

EXAMPLE = {"bracket_iso": {
    "objects": [{"name": "bracket", "material": "anodised", "color": "#7f8c99",
                 "source": {"goal": {"features": [{"kind": "base_box", "params": {"w": 80, "d": 40, "h": 10}},
                                                  {"kind": "hole", "params": {"r": 4, "x": 25, "y": 0}}]}}}],
    "views": [{"name": "iso", "view": "iso"}, {"name": "front", "view": "front", "projection": "ortho"}],
    "lights": "studio", "background": "white", "output": {"width": 1600, "height": 1200, "samples": 128}}}


def study_format(status: dict | None = None) -> dict:
    out = {
        "format": "render study (blender-translator): b3dt parts -> headless Blender (Cycles, CPU) -> checked PNGs",
        "conventions": CONVENTIONS,
        "study_keys": {
            "objects": f"list (1-{M.MAX_OBJECTS}) of objects, below",
            "views": f"list (1-{MAX_VIEWS}) of views, below; each gives images.<name>",
            "lights": f"{'|'.join(M.LIGHTS)} (default {M.DEFAULT_LIGHTS}): studio = key/fill/rim area lights placed "
                      "around each view's camera + a soft world; soft = world only; flat = unlit, every object exactly "
                      "its colour (diagrams; also checks the colours)",
            "background": "white (default) | transparent | '#rrggbb' | floor (white with a shadow-catcher floor at the "
                          "lowest z)",
            "output": f"{{width, height (px, 16-{MAX_SIDE}; default 1600 x 1200), samples (1-4096, 128), denoise "
                      "(true: OpenImageDenoise), format (png | png16)}}",
            "blend": "true also saves scene.blend (open it in Blender to refine)",
            "expect": "[{quantity: dotted result path, value, tol (relative)}]",
            "run": "{timeout_s, mem ('4G'), procs (Cycles threads), queue}: overrides the machine's defaults within "
                   "the caps in status"},
        "object_keys": {
            "name": "unique in the study",
            "source": "exactly one of: {goal: <build123d-translator goal>} | {b3dt: {step, volume}} (a b3dt result; "
                      "on this machine) | {step: path} (mm) | {box: [lx, ly, lz]} | {sphere: r}",
            "at": "[x, y, z] mm (default [0, 0, 0])", "rot_deg": "[rx, ry, rz] degrees (default [0, 0, 0])",
            "material": f"{'|'.join(M.MATERIALS)} (default {M.DEFAULT_MATERIAL})",
            "color": "'#rrggbb': overrides the material's colour",
            "metallic": "0-1: overrides the material's", "roughness": "0-1: overrides the material's",
            "tessellation": "{tol: chord tolerance mm (default 0.1 % of the part's bbox diagonal, >= 0.01), "
                            "angle_deg (default 5)}"},
        "view_keys": {
            "name": "unique; letters, digits, _ and - (the file name)",
            "view": f"{'|'.join(C.PRESETS)} (default iso) or {{from: [x,y,z], to: [x,y,z], up: [0,0,1]}}",
            "projection": "perspective (default) | ortho", "lens_mm": f"perspective focal length (default {C.DEFAULT_LENS:g}, "
                                                                     f"36 mm sensor on the long side)",
            "fit": f"0.05-1: the fraction of the frame the framed parts fill in the limiting direction, centred "
                   f"(default {C.DEFAULT_FIT}); with explicit from/to the aim point stays and only the distance changes; "
                   "omit fit with from/to for a literal camera",
            "target": "an object's name: frame that object instead of all of them",
            "ortho_scale": "ortho with literal from/to only: the view's width in mm on the long side"},
        "materials": M.MATERIALS,
        "results": "images.<view>.{path, what, width, height, coverage}; views.<view>.{from, to, up, lens_mm or ortho_scale, "
                   "fit}; objects.<name>.{vertices, triangles, closed, volume_mm3, cad_volume_mm3, volume_error, area_mm2, "
                   "bbox_min, bbox_max}; render.{engine, device, samples, denoised, threads, blender}; checks; "
                   "reliable; warnings; files; execution",
        "example": EXAMPLE,
    }
    if status is not None:
        out["status"] = status
    return out


# ----------------------------------------------------------------------------- helpers

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _vec3(x) -> bool:
    return isinstance(x, (list, tuple)) and len(x) == 3 and all(_num(v) for v in x)


def _unknown(d: dict, allowed, where: str) -> list[str]:
    extra = sorted(set(d) - set(allowed))
    return [f"{where}: unknown keys {extra} (allowed: {', '.join(allowed)})"] if extra else []


def _source_errors(src, where: str) -> list[str]:
    if not isinstance(src, dict) or len(src) != 1 or next(iter(src)) not in SOURCE_KEYS:
        return [f"{where}: exactly one of {{{', '.join(SOURCE_KEYS)}}}, e.g. {{'goal': {{...}}}}"]
    k, v = next(iter(src.items()))
    errs = []
    if k == "goal":
        try:
            from build123d_translator.goalformat import validate_goal
        except ImportError:
            return [f"{where}.goal: build123d-translator is not installed here (llmt install b3dt), or give a STEP file"]
        r = validate_goal(v)
        if not r.get("ok", False):
            errs += [f"{where}.goal: {e}" for e in r.get("errors", [])] or [f"{where}.goal: invalid goal"]
    elif k in ("b3dt", "step"):
        path = v.get("step") if k == "b3dt" and isinstance(v, dict) else v
        if k == "b3dt" and not isinstance(v, dict):
            return [f"{where}.b3dt: a b3dt result {{step, volume}}"]
        if not isinstance(path, str) or not path:
            return [f"{where}.{k}: the STEP file's path"]
        if not Path(path).expanduser().is_file():
            errs.append(f"{where}.{k}: no file {path} on this machine: run where it is (run.host), or pass the goal")
        if k == "b3dt" and "volume" in v and not (_num(v["volume"]) and v["volume"] > 0):
            errs.append(f"{where}.b3dt.volume: the part's volume in mm3, > 0")
        if k == "b3dt":
            errs += _unknown(v, ("step", "volume", "bbox", "files"), f"{where}.b3dt")
    elif k == "box":
        if not (_vec3(v) and all(x > 0 for x in v)):
            errs.append(f"{where}.box: [lx, ly, lz] mm, each > 0")
    elif k == "sphere":
        if not (_num(v) and v > 0):
            errs.append(f"{where}.sphere: the radius in mm, > 0")
    return errs


def _object_errors(ob, k: int) -> list[str]:
    where = f"objects[{k}]"
    if not isinstance(ob, dict):
        return [f"{where}: an object {{name, source, ...}}"]
    errs = _unknown(ob, OBJECT_KEYS, where)
    if not isinstance(ob.get("name"), str) or not ob["name"].strip():
        errs.append(f"{where}.name: a non-empty name")
    if "source" not in ob:
        errs.append(f"{where}.source: missing (e.g. {{'goal': <b3dt goal>}} or {{'step': path}})")
    else:
        errs += _source_errors(ob["source"], f"{where}.source")
    for key in ("at", "rot_deg"):
        if key in ob and not _vec3(ob[key]):
            errs.append(f"{where}.{key}: [x, y, z] numbers")
    if "material" in ob and ob["material"] not in M.MATERIALS:
        errs.append(f"{where}.material: one of {', '.join(M.MATERIALS)}")
    if "color" in ob and not M.is_hex(ob["color"]):
        errs.append(f"{where}.color: '#rrggbb' (sRGB hex)")
    for key in ("metallic", "roughness"):
        if key in ob and not (_num(ob[key]) and 0 <= ob[key] <= 1):
            errs.append(f"{where}.{key}: a number from 0 to 1")
    t = ob.get("tessellation")
    if t is not None:
        if not isinstance(t, dict):
            errs.append(f"{where}.tessellation: {{tol, angle_deg}}")
        else:
            errs += _unknown(t, ("tol", "angle_deg"), f"{where}.tessellation")
            if "tol" in t and not (_num(t["tol"]) and t["tol"] >= 1e-4):
                errs.append(f"{where}.tessellation.tol: chord tolerance in mm, >= 0.0001")
            if "angle_deg" in t and not (_num(t["angle_deg"]) and 0.5 <= t["angle_deg"] <= 45):
                errs.append(f"{where}.tessellation.angle_deg: 0.5 to 45 degrees")
    return errs


def _view_errors(v, k: int, names: set) -> list[str]:
    where = f"views[{k}]"
    if not isinstance(v, dict):
        return [f"{where}: an object {{name, view, ...}}"]
    errs = _unknown(v, VIEW_KEYS, where)
    if not isinstance(v.get("name"), str) or not _NAME.fullmatch(v["name"]):
        errs.append(f"{where}.name: 1-40 letters, digits, _ or - (it names the image file)")
    vw = v.get("view", "iso")
    literal = False
    if isinstance(vw, dict):
        errs += _unknown(vw, ("from", "to", "up"), f"{where}.view")
        if not (_vec3(vw.get("from")) and _vec3(vw.get("to"))):
            errs.append(f"{where}.view: {{from: [x,y,z], to: [x,y,z], up: [0,0,1]}} in mm")
        elif list(vw["from"]) == list(vw["to"]):
            errs.append(f"{where}.view: from and to must differ")
        if "up" in vw and not (_vec3(vw["up"]) and any(vw["up"])):
            errs.append(f"{where}.view.up: a non-zero [x, y, z]")
        literal = "fit" not in v
    elif vw not in C.PRESETS:
        errs.append(f"{where}.view: one of {', '.join(C.PRESETS)}, or {{from, to, up}}")
    if v.get("projection", "perspective") not in ("perspective", "ortho"):
        errs.append(f"{where}.projection: perspective or ortho")
    if "lens_mm" in v and not (_num(v["lens_mm"]) and 1 <= v["lens_mm"] <= 1000):
        errs.append(f"{where}.lens_mm: 1 to 1000")
    if "fit" in v and not (_num(v["fit"]) and 0.05 <= v["fit"] <= 1):
        errs.append(f"{where}.fit: 0.05 to 1")
    if "target" in v and v["target"] not in names:
        errs.append(f"{where}.target: one of the objects' names ({', '.join(sorted(names))})")
    if "ortho_scale" in v:
        if not (literal and v.get("projection") == "ortho"):
            errs.append(f"{where}.ortho_scale: only with projection ortho and a literal from/to (no fit)")
        elif not (_num(v["ortho_scale"]) and v["ortho_scale"] > 0):
            errs.append(f"{where}.ortho_scale: mm, > 0")
    return errs


def _run_errors(st: dict) -> list[str]:
    if "run" not in st:
        return []
    r, cap = st["run"], S.caps()
    if not isinstance(r, dict):
        return ["run: an object {timeout_s, mem, procs, queue} (all optional)"]
    errs = _unknown(r, S.RUN_KEYS, "run")
    if "timeout_s" in r:
        if not _num(r["timeout_s"]) or r["timeout_s"] <= 0:
            errs.append("run.timeout_s: seconds per study, > 0")
        elif "timeout_s" in cap and r["timeout_s"] > cap["timeout_s"]:
            errs.append(f"run.timeout_s: {r['timeout_s']} s is above BLNT_MAX_TIMEOUT={cap['timeout_s']:g}")
    if "mem" in r:
        mb = S.mem_mb(r["mem"]) if isinstance(r["mem"], str) else None
        if not mb:
            errs.append(f"run.mem: {r['mem']!r} is not a SLURM memory size such as '500M' or '4G'")
        elif "mem" in cap and S.mem_mb(cap["mem"]) and mb > S.mem_mb(cap["mem"]):
            errs.append(f"run.mem: {r['mem']} is above BLNT_MAX_MEM={cap['mem']}")
    if "procs" in r:
        p = r["procs"]
        if not _num(p) or int(p) != p or p < 1:
            errs.append("run.procs: a whole number of threads, at least 1")
        elif "procs" in cap and p > cap["procs"]:
            errs.append(f"run.procs: {p} is above BLNT_MAX_PROCS={cap['procs']}")
    if "queue" in r and not isinstance(r["queue"], bool):
        errs.append("run.queue: true or false")
    return errs


# ----------------------------------------------------------------------------- validation

def validate_study(st) -> dict:
    if not isinstance(st, dict):
        return {"ok": False, "errors": ["a study must be an object {objects, views, ...}"], "warnings": []}
    errs, warns = _unknown(st, STUDY_KEYS, "study"), []
    obs = st.get("objects")
    if not isinstance(obs, list) or not obs:
        errs.append("objects: a non-empty list of {name, source, ...}")
        obs = []
    elif len(obs) > M.MAX_OBJECTS:
        errs.append(f"objects: at most {M.MAX_OBJECTS}; join parts into one goal, or render them in several studies")
    names = [o.get("name") for o in obs if isinstance(o, dict)]
    dup = sorted({n for n in names if names.count(n) > 1 and isinstance(n, str)})
    if dup:
        errs.append(f"objects: names must be unique ({', '.join(dup)} repeated)")
    for k, ob in enumerate(obs):
        errs += _object_errors(ob, k)
    vs = st.get("views", [{"name": "iso", "view": "iso"}])
    if "views" not in st:
        warns.append("views: none given; one iso view (name 'iso')")
    if not isinstance(vs, list) or not vs:
        errs.append("views: a non-empty list of {name, view, ...}")
        vs = []
    elif len(vs) > MAX_VIEWS:
        errs.append(f"views: at most {MAX_VIEWS}")
    vnames = [v.get("name") for v in vs if isinstance(v, dict)]
    vdup = sorted({n for n in vnames if vnames.count(n) > 1 and isinstance(n, str)})
    if vdup:
        errs.append(f"views: names must be unique ({', '.join(vdup)} repeated)")
    for k, v in enumerate(vs):
        errs += _view_errors(v, k, {n for n in names if isinstance(n, str)})
    if st.get("lights", M.DEFAULT_LIGHTS) not in M.LIGHTS:
        errs.append(f"lights: one of {', '.join(M.LIGHTS)}")
    bg = st.get("background", "white")
    if bg not in ("white", "transparent", "floor") and not M.is_hex(bg):
        errs.append("background: white, transparent, floor or '#rrggbb'")
    o = st.get("output", {})
    if not isinstance(o, dict):
        errs.append(f"output: {{{', '.join(OUTPUT_KEYS)}}}")
    else:
        errs += _unknown(o, OUTPUT_KEYS, "output")
        for key in ("width", "height"):
            if key in o and not (isinstance(o[key], int) and not isinstance(o[key], bool) and 16 <= o[key] <= MAX_SIDE):
                errs.append(f"output.{key}: a whole number of pixels, 16 to {MAX_SIDE}")
        if "samples" in o and not (isinstance(o["samples"], int) and 1 <= o["samples"] <= 4096):
            errs.append("output.samples: 1 to 4096")
        if "denoise" in o and not isinstance(o["denoise"], bool):
            errs.append("output.denoise: true or false")
        if o.get("format", "png") not in ("png", "png16"):
            errs.append("output.format: png or png16")
    if "blend" in st and not isinstance(st["blend"], bool):
        errs.append("blend: true or false")
    ex = st.get("expect", [])
    if not isinstance(ex, list) or not all(isinstance(e, dict) and isinstance(e.get("quantity"), str)
                                           and _num(e.get("value")) for e in ex):
        errs.append("expect: [{quantity: 'objects.part.volume_mm3', value, tol}] (tol relative, default 1e-3)")
    errs += _run_errors(st)
    if st.get("lights") == "flat" and bg == "floor":
        warns.append("background floor with lights flat: an unlit scene casts no shadow on the floor")
    out = {"ok": not errs, "errors": errs, "warnings": warns}
    if not errs:
        out["estimate"] = estimate(st)
    return out


def validate(studies) -> dict:
    if not isinstance(studies, dict) or not studies:
        return {"_": {"ok": False, "errors": ["studies: an object {name: study}"], "warnings": []}}
    out = {}
    for name, st in studies.items():
        if not _NAME.fullmatch(str(name)):
            out[name] = {"ok": False, "errors": [f"study name {name!r}: 1-40 letters, digits, _ or -"], "warnings": []}
        else:
            out[name] = validate_study(st)
    return out


def normalise(st: dict) -> dict:
    """The study with its defaults filled in (what the runner uses)."""
    s = dict(st)
    s.setdefault("views", [{"name": "iso", "view": "iso"}])
    s.setdefault("lights", M.DEFAULT_LIGHTS)
    s.setdefault("background", "white")
    o = {"width": 1600, "height": 1200, "samples": 128, "denoise": True, "format": "png"}
    o.update(st.get("output") or {})
    s["output"] = o
    return s


# ----------------------------------------------------------------------------- size

def threads_for(st: dict) -> int:
    n = S.procs_of(st)
    return max(1, min(n, os.cpu_count() or n))


def estimate(st: dict) -> dict:
    """Upper bounds: {minutes, procs (threads), mem_mb}."""
    s = normalise(st)
    o = s["output"]
    W, H, spp = int(o["width"]), int(o["height"]), int(o["samples"])
    nv = len(s["views"])
    th = threads_for(s)
    cad = sum(1 for ob in s["objects"] if isinstance(ob, dict) and next(iter(ob.get("source", {})), "") in
              ("goal", "b3dt", "step"))
    secs = T_START_S + T_OBJECT_S * cad + nv * (K_SAMPLE_S * W * H * spp / th + K_DENOISE_S * W * H * o["denoise"]
                                                + K_SAMPLE_S * min(W * H, 1024 * 1024) / th)
    mem = 600 + 64e-6 * W * H + 1e-3 * TRI_GUESS * max(cad, 1)
    return {"minutes": round(secs / 60 * 1.3, 2), "procs": th, "mem_mb": int(mem * 1.3)}
