# blender-translator: planning (session context)

Version: 2026.10.28.1 (M1 done: format, translation, reference, offline tests)
Author: Nicola Ferralis <ferralis@generalflash.com>

A new chat starts with "Read planning.md and start."

**Status (2026-10-28):** **M1 done** (65 offline tests pass). Scope: b3dt parts only, Cycles on CPU; key `blnt`, port 8771, mochi and carbonio.

**Next: M2, the Blender driver.** It needs §10.B, C and E run on mochi and carbonio first.

---

## 1. What this is

**blender-translator** (key **`blnt`**) turns a JSON *study* into a headless Blender render of build123d-translator parts, with checked framing and geometry. It produces presentation images of a part or a small assembly: materials, views, lights and background, at a chosen size.

- **In v1:** b3dt goals, b3dt results and STEP files, tessellated by blnt; one or more parts with placement; view presets with automatic framing; material, light and background presets; PNG output and an optional `.blend`; Cycles on CPU.
- **Later** (§15, all designed in M0 and kept below for reference): feat and cfdt fields on the part, GPU rendering, mesh prep and exports (STL/3MF/GLB), turntables.
- **Out of scope:** interactive editing, sculpting, rigging, physics, Geometry Nodes, the user's own `.blend` scenes. For those, use Blender Lab's official MCP server ([blender.org/lab/mcp-server](https://www.blender.org/lab/mcp-server/)). blnt can write a `.blend` that the user then opens and refines with it.

**Why a translator and not only the connector:**

- It runs headless on the servers, under SLURM.
- It runs no LLM-written code: the study is validated JSON, and the Blender script is generated deterministically.
- It takes b3dt goals directly.

### The family

| Key | Repository | Backend | Relation to blnt |
|---|---|---|---|
| b3dt | build123d-translator | build123d (OCCT) | **v1:** parts as goals, results or STEP |
| feat | fea-translator | Gmsh + CalculiX | later: `.inp` + `.frd` fields |
| cfdt | cfd-translator | Gmsh + OpenFOAM | later: wall fields from `state.npz` |
| lmpt, omct | lammps-, openmodelica-translator | LAMMPS, OpenModelica | none |
| p3dt | print3d-translator | OrcaSlicer | later: meshes from blnt's mesh prep |

## 2. The backend: Blender

### Versions and builds (checked 2026-10-27 on download.blender.org)

- **Use Blender 5.2 LTS:** 5.2.0 came out 2026-07-14 and is supported until 2028-07; the latest is 5.2.3 (2026-10-22). Pin to the LTS because the `bpy` API changes between feature releases.
- **Use the official `linux-x64` tarball, not Ubuntu's package.** Ubuntu 26.04's `blender` package is 5.0.1+dfsg: not the LTS, and Debian rebuilds differ from the official build. There is no official Linux ARM64 build (the Sparks are out).
- **blnt does not import `bpy`.** The `bpy` wheels on PyPI are CPython 3.11 only, and our venvs are newer. blnt runs `blender -b --factory-startup -P scene.py -- <args>` as a subprocess in its own process group (timeout, cancel). That also keeps Blender out of the server's memory.

### How it is found

1. `BLNT_BLENDER` (the executable);
2. `blender` on PATH;
3. `/opt/blender/blender`, then the newest `/opt/blender-*/blender`;
4. on the Mac, `/Applications/Blender.app/Contents/MacOS/Blender`.

The version is the first line of `blender --version`. A short probe (`--python-expr`) reports Python, numpy and OIDN availability. A successful probe is kept 60 s; a failed one is asked again.

### Machines (inventory run 2026-10-27; Blender not installed yet)

| Machine | Arch, OS | CPUs (SLURM) | Memory (SLURM) | GPU (not used in v1) | v1 |
|---|---|---|---|---|---|
| mochi | x86_64, Ubuntu 26.04.1 | 40 = 20 cores × 2 | 60000M | 2 × Quadro RTX 6000 (`gpu:2,shard:24`) | yes |
| carbonio | x86_64, Ubuntu 26.04.1 | 12 = 6 cores × 2 | 38000M | RTX 5060 Ti (`gpu:1,mps:100`) | yes |
| spark1, spark2 | aarch64, Ubuntu 24.04.5 | 20 | 124000M / 120000M | GB10 (`gpu:1`) | no (no ARM64 build) |
| Mac | arm64 | | | Metal | development only |

### Inputs and outputs

- **Inputs (all written by blnt):**
  - `scene.npz`: per object, vertices (mm, per CAD face) and triangles in blnt's own numbering; Blender computes the smooth normals within each face;
  - `scene.json`: camera, lights, materials, render settings;
  - `scene.py`: a fixed, versioned script that reads the two and builds the scene with `foreach_set` (no importers).

  `get_inputs` returns all three. `blender -b -P scene.py` reruns a study by hand.
- **Outputs:**
  - `<view>_raw.png` (transparent background), then `<view>.png` with the background composited by blnt;
  - `<view>_check.png`, the check pass: each object an unlit emission of its palette colour, 1 sample, filter 0.01 px, at most 1024 px on the long side;
  - `scene.blend` (optional);
  - `blender.log`.

  The script's last line is `BLNT_OK {json}`, with what Blender built: per object the vertex count, triangle count and a checksum; per view the camera and the projected corners. Without that line, the study failed, and the result carries the log's traceback.

### Engine

**Cycles on CPU only:** no display needed, and deterministic with a fixed seed. EEVEE and Workbench need a GPU context, and that is unverified headless. GPU Cycles comes later (§15).

## 3. Typical requests

1. "Render this bracket (b3dt goal) in anodised aluminium on white, 3/4 view, 1920×1080."
2. "Front, top and iso views of the part, orthographic, for a datasheet."
3. "The housing and its lid side by side, lid in black ABS, housing in grey PLA."
4. "Same part, transparent background, so I can put it on a slide."
5. "A quick preview at 800×600, low samples."
6. "Give me the `.blend` so I can tweak the lighting myself."

## 4. The study format (proposal for v1)

Conventions: mm, Z up, the base on z = 0 centred in X/Y (as b3dt); colours as sRGB hex; angles in degrees; dotted result paths; `expect` and `run` as in the family.

```json
{"bracket_hero": {
   "objects": [
     {"name": "bracket",
      "source": {"goal": {"features": [
          {"kind": "base_box", "params": {"w": 80, "d": 40, "h": 10}},
          {"kind": "hole", "params": {"r": 4, "x": 25, "y": 0}}]}},
      "material": "anodised",
      "color": "#7f8c99"}],
   "views": [{"name": "iso", "view": "iso"},
             {"name": "front", "view": "front", "projection": "ortho"}],
   "lights": "studio",
   "background": "white",
   "output": {"width": 1920, "height": 1080, "samples": 128},
   "blend": false}}
```

### `objects[]`

| Key | Meaning |
|---|---|
| `name` | unique in the study |
| `source` | one of:<br>- `{"goal": {...}}`: a b3dt goal, built through build123d-translator (an optional import);<br>- `{"b3dt": {"step", "volume"}}`: a b3dt result; `volume` becomes the tessellation check;<br>- `{"step": path}`: a STEP file (mm);<br>- `{"box": [lx, ly, lz]}` or `{"sphere": r}`: tests and benchmarks. |
| `at`, `rot_deg` | placement: translation in mm, then rotation (x, y, z, degrees). Default: as built. |
| `material` | a preset: `matte`, `satin`, `plastic`, `metal_brushed`, `anodised`, `polished`, `rubber`, `glass` |
| `color` | sRGB hex. It overrides the preset's base colour. |
| `tessellation` | `{tol, angle_deg}`: chord tolerance in mm (default 0.1 % of the part's bounding-box diagonal, at least 0.01 mm) and angle (default 5°) |

### Views

| Key | Meaning |
|---|---|
| `view` | `iso` (default), `front`, `back`, `left`, `right`, `top`, `bottom`, `iso_back`, or `{"from": [x, y, z], "to": [x, y, z], "up": [0, 0, 1]}` |
| `projection` | `perspective` (default) or `ortho` |
| `lens_mm` | 50 (perspective) |
| `fit` | the fraction of the frame's shorter side that the scene's bounds fill (default 0.85). blnt computes the camera distance or the ortho scale. |

### Scene and output

| Key | Meaning |
|---|---|
| `lights` | `studio` (key, fill and rim area lights + soft world), `soft` (world only), or `flat` (unlit: each object exactly its colour; for diagrams and the colour check) |
| `background` | `white`, `transparent`, a hex colour, or `floor` (a shadow-catcher plane at the lowest z) |
| `output` | `width` and `height` in px (default 1600 × 1200, at most 4096 each), `samples` (default 128), `denoise` (default true, OpenImageDenoise), `format` (`png` or `png16`) |
| `blend` | true also saves `scene.blend` |
| `expect`, `run` | as in the family. `run` has `timeout_s`, `mem`, `procs` (threads) and `queue`, within the caps. |

Validation:

- names unique;
- a known source, and exactly one;
- at least one object and one view;
- sizes, samples and colours in range;
- STEP paths exist (on this machine);
- a goal source without build123d-translator → an error saying to install it.

Every error says the fix.

**Questions to challenge before M1:**

- Is `fit` against the scene's bounds right, or should a view frame one object?
- Is a material preset + `color` enough, or are `metallic` / `roughness` overrides needed?

## 5. Results

| Key | Content |
|---|---|
| `images.<view>.path`, `what`, `width`, `height`, `coverage` | the family's `images`, plus the fraction of the frame the parts cover |
| `views.<view>` | the camera as built: `from`, `to`, `up`, `lens_mm` or `ortho_scale`, and `fit` as achieved |
| `objects.<name>` | `vertices`, `triangles`, `closed`, `volume_mm3` (mesh), `cad_volume_mm3`, `volume_error`, `area_mm2`, `bbox` (after placement) |
| `files` | `scene.npz`, `scene.json`, `scene.py`, `blender.log`, the images, `scene.blend` |
| `render` | `engine`, `device` (`CPU`), `samples`, `denoised`, `threads`, `blender` (version) |
| shared keys | `checks`, `expect`, `reliable`, `unreliable_because`, `warnings`, `seconds`, `execution` (with `limits`) |

**Interface** (read by other tools): `images.<view>.path` with `get_image`; `files.blend`.

## 6. Checks and the reference implementation

### Every run

1. **Tessellation** (blnt, before Blender):
   - closed and manifold: every edge in exactly two triangles, consistent orientation;
   - no degenerate triangles;
   - mesh volume vs. the CAD volume within a bound from `tol` (relative error ≤ ~3·tol/(the part's smallest radius of curvature), conservatively 1 %);
   - a failure here → `reliable: false`.
2. **What Blender built:** per object, the vertex and triangle counts and the vertex checksum printed by the script equal blnt's. This catches reordering or lost data in `foreach_set`.
3. **Framing:**
   - blnt projects the bounding-box corners with its own pinhole or ortho model (`camera.py`, numpy) and compares them with Blender's `world_to_camera_view` from the script: ≤ 0.5 px;
   - every object is inside the frame, and `fit` is within 1 %.
4. **Silhouette (the reference):** blnt's own z-buffer rasteriser (`refrender.py`, numpy) draws, from `scene.npz` and the camera:
   - the coverage mask: compared with Blender's alpha, IoU ≥ 0.995, leaving out a 1 px band on the edges (antialiasing);
   - the object-index map: the same IoU per object, so placement and occlusion are right;
   - with `lights: flat`, the flat-colour image: the mean error ≤ 2/255 on interior pixels. This checks the colour management (view transform "Standard", sRGB).

   It compares at the check pass's resolution, at most 1024 px on the long side.
5. **The image:** the size as asked; not blank; clipped (saturated) pixels < 1 % (a warning); coverage > 0.5 % of the frame (a warning).
6. **`expect`** on any dotted path.

**Reliability verdict:** false when 1–4 fail. Image sanity (5) gives warnings only.

### Benchmarks (tolerances to confirm on the first server run)

| Case | Known answer | Tolerance |
|---|---|---|
| `cube_ortho` | axis-aligned cube, ortho front view: the covered square = a/s · W px | ±1 px per side; IoU vs. reference ≥ 0.999 |
| `sphere_coverage` | sphere, ortho: coverage = πr² / (frame area) | 0.5 % |
| `box_perspective` | the 8 projected corners vs. the pinhole formula | ≤ 0.5 px |
| `flat_color` | `lights: flat`, a box in #3366cc: interior pixels = (51, 102, 204) | ≤ 2/255 per channel |
| `two_objects` | two boxes, one in front of the other: the object-index map vs. the reference | IoU ≥ 0.995 each |
| `tess_volume` (b3dt chain) | b3dt box with a hole: V = abh − πr²h | 0.2 % at the default `tol` |
| `beauty_smoke` | a studio render of a b3dt bracket, 800 × 600, 64 samples | checks 1–4 pass; time recorded for the estimate |

## 7. Assumptions about Blender (each with what catches it)

| Assumption | Caught by |
|---|---|
| `blender -b --factory-startup -P` renders Cycles on CPU without a display on the servers | `beauty_smoke`; the status probe |
| Blender's bundled Python has numpy | the probe |
| View transform "Standard", look none, exposure 0, gamma 1: an emission of linear c gives sRGB(c) in an 8-bit PNG | `flat_color` |
| A pixel filter of width 0.01 px makes the check pass sample pixel centres | `cube_ortho`, `flat_color` |
| `sensor_fit`, `lens`, `sensor_width`, `ortho_scale` map to blnt's camera model as computed | `box_perspective`, `cube_ortho` |
| `foreach_set` keeps blnt's vertex and triangle order | check 2 (the checksum) |
| Cycles on CPU with a fixed seed renders the same image twice | a repeat run in the backend tests (bitwise) |
| OpenImageDenoise is in the official Linux build | the probe; `render.denoised` says what was used |
| build123d's tessellation is closed and manifold for a valid solid | check 1 on every run |

## 8. Size and cost

- **What makes a study big:** pixels × samples × views (Cycles), then triangles (tessellation, BVH, memory).
- **Upper bounds before running:**
  - triangles ≈ (area / tol) × c, from b3dt's `check` (volume, bbox in ≈1 s) or the STEP's bbox;
  - time ≈ t0 + k · W·H·samples·views / threads, with t0 = Blender start + scene load (≈ 3–10 s, measure), k measured per machine (§10.E);
  - memory ≈ 600 MB + 1 kB × triangles + 64 B × W·H (to measure).
- **Threads:** Cycles is threaded, so blnt is a **threads** translator (`--cpus-per-task`, `-t N`), as feat and omct are. Threads are capped at the node's CPUs. Measure 1, 4, 8, 16 and all threads on mochi, and 1, 6 and 12 on carbonio.
- **Typical cost:** a 1600 × 1200, 128-sample still of a part: tens of seconds on mochi with 16 threads (unverified). carbonio has only 6 cores, so it is slower; the router places by the estimate. So most studies are short. `BLNT_SLURM_MIN_MINUTES` default 2: short studies run locally, larger ones go to SLURM.

## 9. Interconnections

- **b3dt → blnt (v1):**
  - **Goals inline:** built locally through `build123d_translator`, an optional import; b3dt is in the same release on every machine. blnt tessellates with build123d (OCCT) at its own `tol`, and the CAD volume comes from the solid.
  - **`{"b3dt": {step, volume}}`:** the result keys p3dt also takes.
  - **STEP files:** paths on the machine that runs blnt (as p3dt does).
  - **Without build123d-translator:** a validation error for goal and STEP sources, and the tests skip.
- **No local paths between machines,** except STEP files given by the user. A b3dt result passed as a path must be on the same machine. The router's affinity covers request folders it knows; otherwise validation says to use the goal itself.
- **Later:** feat and cfdt fields (§15). blnt would read feat's `.inp` + `.frd` and cfdt's `state.npz` with no change to either. That needs the router to re-read `router_paths.json` on a miss.

## 10. Commands for the servers (mochi and carbonio)

**A. Inventory: done** (§2).

**B. Install Blender 5.2.3** (admin; ≈1–2 min, 385 MB):

```bash
cd /opt && sudo curl -LO https://download.blender.org/release/Blender5.2/blender-5.2.3-linux-x64.tar.xz
curl -s https://download.blender.org/release/Blender5.2/blender-5.2.3.sha256 | grep linux-x64 | sha256sum -c
sudo tar xf blender-5.2.3-linux-x64.tar.xz && sudo ln -sfn /opt/blender-5.2.3-linux-x64 /opt/blender
/opt/blender/blender --version | head -1
```

Expected: `blender-5.2.3-linux-x64.tar.xz: OK`, then `Blender 5.2.3`. If it complains about missing shared libraries:

```bash
sudo apt install -y libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libxkbcommon0 libsm6 libegl1
```

**C. The probe** (≈3 s):

```bash
/opt/blender/blender -b --factory-startup --python-expr "import sys,numpy,bpy; print('PROBE', sys.version.split()[0], numpy.__version__, bpy.app.version_string, 'OIDN', bpy.app.build_options.openimagedenoise)" 2>&1 | grep PROBE
```

Expected: `PROBE 3.1x.y 2.x.y 5.2.3 OIDN True`.

**E. Headless Cycles CPU render, timed** (≈10 s – 2 min in all). The thread counts are for mochi; use `1 6 12` on carbonio:

```bash
for T in 1 4 8 16 40; do /usr/bin/time -f "T=$T wall=%e s maxrss=%M kB" /opt/blender/blender -b --factory-startup -t $T --python-expr "
import bpy; s = bpy.context.scene; s.render.engine = 'CYCLES'; s.cycles.device = 'CPU'
s.cycles.samples = 64; s.cycles.seed = 0; s.render.resolution_x, s.render.resolution_y = 800, 600
s.render.filepath = '/tmp/blnt_cpu_$T.png'; bpy.ops.render.render(write_still=True)" 2>&1 | grep -E "Saved|T=|rror"; done
```

Expected: `Saved: '/tmp/blnt_cpu_T.png'` and a time for each. Then the same 64-sample render twice at one thread count, to compare the files: `cmp /tmp/a.png /tmp/b.png` should print nothing (determinism).

D, F, G and H (GPU devices, EEVEE, Sparks, GPU timing) are not needed for v1.

## 11. Decisions

| # | Decision | State |
|---|---|---|
| D1 | Key | **`blnt`** (decided 2026-10-27): CLI `blnt`, server `blnt-mcp`, settings `BLNT_*`, output `~/blnt_runs` |
| D2 | HTTP port | **8771** (decided) |
| D3 | Machines | **mochi and carbonio** (decided) |
| D-scope | v1 scope | **b3dt parts only, Cycles on CPU** (decided). Fields, GPU, mesh prep, turntables later. |
| D-format | Study format (§4) | **Approved 2026-10-28.** The two open questions were settled with cheap additions:<br>- `fit` frames all parts, and a view's `target` frames one object;<br>- `metallic` and `roughness` override the material preset. |

## 12. Architecture (v1)

```
blender-translator/
  pyproject.toml, README.md, planning.md, examples/studies.json
  blender_translator/
    __init__.py         version
    format.py           study_format (with status), validate (run caps, estimate)
    sources.py          goal / b3dt / STEP / box / sphere → triangles (our numbering), CAD volume
    meshcheck.py        closed, manifold, degenerate, volume, area (numpy)
    camera.py           view presets, fit solver, pinhole/ortho projection
    materials.py        material and light presets → scene.json
    scene.py            writes scene.npz / scene.json; scene_template.py (what Blender runs)
    blender.py          find, probe, run (own process group, timeout, cancel flag)
    refrender.py        the reference rasteriser (coverage, object index, flat colour)
    results.py          the outputs, the comparisons, checks, verdict
    runner.py           run_study(name, study, folder, ...)
    bench.py, executor.py (threads, from feat), stale.py (from cfdt/lmpt), api.py, cli.py, mcp_server.py
  tests/  test_blnt.py, test_meshcheck.py, test_camera.py, test_refrender.py, fake_slurm.py,
          test_slurm.py, test_stale.py
```

- **MCP tools:** `study_format`, `validate_studies`, `run_studies`, `study_status`, `run_benchmarks`, `bench_status`, `jobs`, `cancel`, `get_file`, `get_inputs`, `get_image`, `render_images`. `render_images` makes new views of a finished study from its saved `scene.npz` (no rebuild or tessellation).
- **Dependencies:** numpy, Pillow (PNG reading, check images), OpenEXR reading through Pillow or imageio (to decide in M1; or write the check pass as 16-bit PNGs instead of EXR); `mcp` and `test` extras. Blender is never a pip dependency.

## 13. The environment

- **The Mac** develops and commits, and runs the Claude app and the router.
- **mochi and carbonio:** single-node SLURM, shared install `/opt/llm-translators/current`.
- **This sandbox** has no Blender. Offline tests cover the format, the sources, the mesh checks, the camera, the reference rasteriser and the result checks. Backend tests skip.
- **Reference repositories:** `~/Software/cfd-translator` and `~/Software/fea-translator` are connected for reading only. **Never change them.** Code to reuse (`executor.py`, `mcp_server.py`, `stale.py`) is copied into this repo and adapted here.
- **Git:** you commit and push from the Mac. I don't run git in your folders without asking, and I don't use `sed -i` on executables.

## 14. State log

- **2026-10-28: M1 (2026.10.28.1).**
  - **Written:**
    - `format.py`: validation with fixable errors, run caps, estimate;
    - `sources.py`: goal, b3dt, STEP, box, sphere; placement;
    - `meshcheck.py`: weld, topology, volume bound A·tol, checksums;
    - `camera.py`: model, presets, fit solver;
    - `materials.py`: presets, sRGB↔linear, palette;
    - `scene.py` + `scene_template.py`: the Blender script, written for 5.2; untested until M2;
    - `refrender.py`: rasteriser, decode, compare;
    - `settings.py`; `examples/studies.json`; README.
  - **Tests:** 65 offline tests pass in the sandbox (aarch64, Python 3.10, build123d 0.12 + cadquery-ocp-novtk, b3dt 2026.10.21.1 from the umbrella's submodule). Without b3dt, 63 pass and 2 skip.
  - **Measured offline:** the bracket goal tessellates in 2.0 s (602 vertices, 592 triangles, closed, volume +5e-6 against the CAD volume); a 1024×768 reference raster takes 0.76 s.
  - **Design details settled while writing:**
    - **Mesh vertices stay per CAD face**, so Blender's smooth shading keeps face edges sharp; topology checks weld first.
    - **Rendering is transparent, and blnt composites the background afterwards** (exact white or hex colour).
    - **The check pass is a second render in the same Blender run:** emission per object in a palette colour, 1 sample, filter 0.01, Standard, at most 1024 px on the long side. It replaces the EXR passes from M0, so no EXR reader is needed.
    - **The light rig is placed in each view's camera frame.** Power = irradiance·π·D² (mm units).
    - `views[].target` and the `metallic`/`roughness` overrides were added.

- **2026-10-27 (4):** scope cut to the basic version: b3dt parts, Cycles on CPU. Key `blnt`, port 8771. Server commands reduced to B, C, E.
- **2026-10-27 (3):** read cfd-translator 2026.10.25.6 (`render.py`, `runner.py`, `post.py`) and fea-translator 2026.10.25.1 (`results.py`, `deck.py`, `runner.py`). Result: cfdt saves `state.npz` for every finished study, and feat writes `.inp` + `.frd`, so a later field version needs no change to either (§15).
- **2026-10-27 (2):** inventory on mochi, carbonio and spark1 (§2). Decided: mochi and carbonio only.
- **2026-10-27 (1):** M0. Read the umbrella docs (create_new_translators, EXECUTION, SHARED, ROUTER), lmpt's `refcalc.py`/`stale.py`/`api.py`, feat's README, and the router's path affinity. Checked Blender's downloads: 5.2.3 LTS, no Linux ARM64 build; the `bpy` wheels are cp311 only.

## 15. Later (designed in M0, not in v1)

- **feat and cfdt fields** on the part, with a colormap (viridis, cividis, turbo, coolwarm), `range`, a colorbar drawn by blnt (exact numbers), and `deform` for feat.
  - **Sources:**
    - feat: `<name>.inp` (nodes, C3D10; outer surface = faces of one element only, 6-node triangles split in 4) and `<name>.frd` (ASCII: ` -4 NAME` blocks, ` -1` + node (10 chars) + values (12 chars each), ` -3` end; DISP, STRESS → von Mises, NDTEMP);
    - cfdt: `state.npz` (`points` mm, `faces` padded −1, `patch/<name>/{p, wss, T, whf}`) and `state.json` (`patches`, `plan`). Fields as cfdt's `render._surface`: p kinematic × ρ without energy, − p_op with it.
  - **Cross-checks:** feat `max_displacement` and `max_von_mises_nodal`; cfdt `forces.<wall>.pressure` vs. ∫p n dA.
  - **The colour check:** the flat-colour reference compares the colormap pixel by pixel (`colormap_ramp` benchmark).
  - **Placement:** the study names the producing folder, and runs on its machine (router affinity; the router must re-read `router_paths.json` on a miss).
- **GPU Cycles:**
  - settings `BLNT_DEVICE`, `BLNT_SLURM_GRES` (`gpu:1`; `shard:12` on mochi, `mps:50` on carbonio to share) and `run.device`;
  - GPU jobs ask for 2 CPUs;
  - tests D and H from the first plan; check carbonio's Blackwell support in 5.2;
  - a new key for EXECUTION.md.
- **Mesh prep:** check, repair (merge, fill holes, normals), decimate with a Hausdorff bound, export STL/3MF/GLB/PLY/OBJ; `exports.*` for p3dt and for GLB viewers in artifacts.
- **Turntables** (MP4 through Blender's FFmpeg), exploded views.
- **EEVEE previews,** if headless EGL works.
- **The Sparks,** with a source build for aarch64 + CUDA.
