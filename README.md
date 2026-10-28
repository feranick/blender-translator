# blender-translator (blnt)

Render studies of [build123d-translator](https://github.com/feranick/build123d-translator) parts with headless Blender (Cycles), with checked framing and geometry. Part of [llm-translators](https://github.com/feranick/llm-translators): key `blnt`, MCP server `blnt-mcp`, settings `BLNT_*`, output `~/blnt_runs`.

**Status: M1** (the format, the translation and the reference, offline). Blender is not driven yet (M2); there is no CLI or MCP server yet (M4). See `planning.md`.

## What it is

An LLM writes a *study*: the parts (b3dt goals, b3dt results or STEP files), their materials and placement, the views, lights, background and image size. blnt computes everything else deterministically:

- the tessellation, in its own numbering;
- the cameras, with automatic framing;
- the light rig and its power;
- the Blender script.

Then it checks what Blender made against its own reference.

- **In v1:** stills of one or more parts, on Cycles CPU.
- **Later:** feat and cfdt fields, GPU rendering, mesh exports, turntables.
- **Not its job:** interactive scene work. Use Blender Lab's MCP server for that. blnt can hand over a `.blend`.

| Translator | Relation |
|---|---|
| b3dt (build123d-translator) | parts: `{"goal": ...}`, `{"b3dt": {step, volume}}`, `{"step": path}` |
| feat, cfdt | later: fields on the part (planning.md §15) |

## Install

1. **Blender 5.2 LTS** (the official linux-x64 tarball, e.g. in `/opt/blender`), found through `BLNT_BLENDER`, then `PATH`, then `/opt/blender*`.
2. **The translator:** `llmt install blnt` in llm-translators.

build123d-translator is an optional companion: it is needed for goal and STEP sources.

## A study

```json
{"bracket_iso": {
   "objects": [{"name": "bracket", "material": "anodised", "color": "#7f8c99",
                "source": {"goal": {"features": [
                   {"kind": "base_box", "params": {"w": 80, "d": 40, "h": 10}},
                   {"kind": "hole", "params": {"r": 4, "x": 25, "y": 0}}]}}}],
   "views": [{"name": "iso", "view": "iso"},
             {"name": "front", "view": "front", "projection": "ortho"}],
   "lights": "studio", "background": "white",
   "output": {"width": 1600, "height": 1200, "samples": 128}}}
```

- **Units:** mm, Z up (b3dt parts sit on z = 0, centred in X/Y); degrees; colours as sRGB hex.
- **Objects** (up to 16):
  - `source`: one of `goal`, `b3dt`, `step`, `box`, `sphere`;
  - placement: `at`, `rot_deg` (XYZ Euler about the origin, then the translation);
  - `material`: matte, satin, plastic, metal_brushed, anodised, polished, rubber, glass;
  - `color`, `metallic`, `roughness`: overrides;
  - `tessellation`: `{tol, angle_deg}`.
- **Views** (up to 12):
  - `view`: iso, iso_back, front, back, left, right, top, bottom, or `{from, to, up}`;
  - `projection`: perspective or ortho;
  - `lens_mm`;
  - `fit`: the fraction of the frame the parts fill in the limiting direction, centred;
  - `target`: frame one object only.
- **Lights:**
  - `studio`: key, fill and rim area lights in each view's camera frame, plus a soft world;
  - `soft`: world only;
  - `flat`: unlit; each object is exactly its colour.
- **Background:** white, transparent, `#rrggbb`, or floor (a shadow catcher).
- **Output:**
  - `width`, `height`: 16–4096 px;
  - `samples`;
  - `denoise`: OpenImageDenoise;
  - `format`: png or png16.
- **`blend: true`** also saves the scene.
- **`expect`, `run`** as in the family. `run` is `{timeout_s, mem, procs (threads), queue}` within `BLNT_MAX_*`.

`validate` returns `estimate: {minutes, procs, mem_mb}` per study (upper bounds, for the router and SLURM).

### Results (from M2)

| Key | Content |
|---|---|
| `images.<view>` | `path`, `what`, `width`, `height`, `coverage` |
| `views.<view>` | the camera: `from`, `to`, `up`, `lens_mm` or `ortho_scale`, `fit` |
| `objects.<name>` | `vertices`, `triangles`, `closed`, `volume_mm3`, `cad_volume_mm3`, `volume_error`, `area_mm2`, `bbox_min`, `bbox_max` |
| shared keys | `render`, `checks`, `reliable`, `unreliable_because`, `warnings`, `files`, `seconds`, `execution` |

## The checker

On every run:

1. **Tessellation.** Closed and consistently oriented, with no degenerate triangles. The mesh volume is within `A_cad × tol` of the CAD volume, since every mesh point lies within the chord tolerance of the surface.
2. **What Blender built.** Per object, the vertex and triangle counts and order-sensitive checksums, recomputed by the script from Blender's own mesh data.
3. **Framing.** blnt's own pinhole/ortho model (`camera.py`) against Blender's `world_to_camera_view` on test points (≤ 0.5 px). Every part is inside the frame, and `fit` is as asked.
4. **The reference.** blnt's own z-buffer rasteriser (`refrender.py`) draws which object covers each pixel centre. Blender renders a check pass (each object an unlit emission of its check colour, 1 sample, pixel filter 0.01 px). Their coverage and per-object IoU must be ≥ 0.995 off a 1 px edge band. With `lights: flat`, the picture's interior colours must be within 2/255 of each object's colour.

A failure of 1–4 makes the result `reliable: false`. Image sanity (blank, clipped, tiny coverage) gives warnings.

**Benchmarks** (planned, M3): `cube_ortho`, `sphere_coverage`, `box_perspective`, `flat_color`, `two_objects`, `tess_volume` (b3dt chain), `beauty_smoke`; tolerances in planning.md §6.

**Offline tests** (M1, 65): the format and its errors, the run caps, the estimate, the sources and their volumes, the topology checks, the camera formulas and the fit for every preset, the reference rasteriser against closed forms (cube 2500 px exact, sphere πr² within 0.5 %, a perspective square, occlusion), the decoding and comparisons, the scene files, and the template's checksums equal to ours.

### Assumptions about Blender

See planning.md §7. Each assumption has a check or a benchmark that catches it (Cycles headless on CPU, numpy in Blender's Python, the Standard view transform, the 0.01 px filter, the camera's sensor fit, `foreach_set` keeping our order, determinism, OIDN).

## How it works

1. **`format.py`:** validation and the estimate.
2. **`sources.py`:** objects to triangle meshes (OCCT through build123d; analytic box and icosphere), placed.
3. **`meshcheck.py`:** topology, volume, area, checksums.
4. **`camera.py`:** presets, fit solver, projection.
5. **`materials.py`:** material, light and background presets; sRGB ↔ linear; the check palette.
6. **`scene.py`:** writes `scene.npz`, `scene.json` and `scene.py` (from `scene_template.py`, the script Blender runs: `blender -b --factory-startup --python-exit-code 1 -P scene.py -- scene.json OUTDIR`).
7. **`refrender.py`:** the reference rasteriser and the comparisons.
8. **Next:** `blender.py` (find, probe, run), `results.py`, `runner.py` (M2); `bench.py` (M3); `api.py`, `cli.py`, `mcp_server.py` (M4); `executor.py` (M5); `stale.py` (M6).

## Files

| Path | What |
|---|---|
| `blender_translator/` | the package |
| `tests/` | `test_blnt.py` (format, scene), `test_geometry.py` (sources, meshes, camera, reference) |
| `examples/studies.json` | four studies covering v1 |
| `planning.md` | the session context |

## Versions

| Version | Changes |
|---|---|
| 2026.10.28.1 | M1: the study format and validation (run caps, estimate), sources and tessellation, mesh checks, camera model and fit, material and light presets, the scene writer and the Blender script, the reference rasteriser; 65 offline tests |
