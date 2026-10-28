"""scene.py — run by Blender: blender -b --factory-startup --python-exit-code 1 -P scene.py -- scene.json OUTDIR
Written by blender-translator (blnt) 2026.10.28.1; the same script for every study: the study is in scene.json and
scene.npz (vertices in mm and triangles, in blnt's numbering). For each view it renders the picture
(<view>_raw.png, RGBA with a transparent background) and the check pass (<view>_check.png: every object an
unlit emission of its check colour, 1 sample, pixel filter 0.01 px, view transform Standard), and prints one line
'BLNT_OK {json}' with what it built: per object the vertex and triangle counts and checksums, per view the
camera's projection of the test points (world_to_camera_view) and the render times.
Blender 5.2 LTS (Principled BSDF socket names of Blender 4.0+). Units: 1 Blender unit = 1 mm.
"""
import json
import sys
import time
import traceback
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(a) < 2:
        raise SystemExit("usage: blender -b -P scene.py -- scene.json OUTDIR")
    return Path(a[0]), Path(a[1])


def checksum(co):
    v = co.astype(np.float64).reshape(-1, 3)
    w = (np.arange(len(v), dtype=np.float64) % 997.0) + 1.0
    return float((w * (v[:, 0] + 2.0 * v[:, 1] + 3.0 * v[:, 2])).sum())


def checksum_tris(t):
    t = t.astype(np.int64).reshape(-1)
    w = (np.arange(len(t), dtype=np.int64) % 1009) + 1
    return int((w * t).sum() % 2147483647)


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for d in list(coll):
            coll.remove(d)


def node_tree(idblock):
    try:
        idblock.use_nodes = True            # deprecated in 5.x (always true); harmless where it still exists
    except (AttributeError, TypeError):
        pass
    return idblock.node_tree


def set_input(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def principled(name, m):
    mat = bpy.data.materials.new(name)
    nt = node_tree(mat)
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_input(b, ["Base Color"], (*m["base_color"], 1.0))
    set_input(b, ["Metallic"], float(m.get("metallic", 0.0)))
    set_input(b, ["Roughness"], float(m.get("roughness", 0.5)))
    if m.get("coat"):
        set_input(b, ["Coat Weight", "Coat"], float(m["coat"]))
    if m.get("anisotropic"):
        set_input(b, ["Anisotropic"], float(m["anisotropic"]))
    if m.get("transmission"):
        set_input(b, ["Transmission Weight", "Transmission"], float(m["transmission"]))
    if m.get("ior"):
        set_input(b, ["IOR"], float(m["ior"]))
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def emission(name, rgb_linear):
    mat = bpy.data.materials.new(name)
    nt = node_tree(mat)
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    e = nt.nodes.new("ShaderNodeEmission")
    set_input(e, ["Color"], (*rgb_linear, 1.0))
    set_input(e, ["Strength"], 1.0)
    nt.links.new(e.outputs[0], out.inputs["Surface"])
    return mat


def make_mesh(name, V, T):
    me = bpy.data.meshes.new(name)
    nv, nt = len(V), len(T)
    me.vertices.add(nv)
    me.vertices.foreach_set("co", V.astype(np.float32).ravel())
    me.loops.add(3 * nt)
    me.loops.foreach_set("vertex_index", T.astype(np.int32).ravel())
    me.polygons.add(nt)
    me.polygons.foreach_set("loop_start", np.arange(0, 3 * nt, 3, dtype=np.int32))
    try:                                     # read-only since Blender 4.0 (sizes come from loop_start)
        me.polygons.foreach_set("loop_total", np.full(nt, 3, dtype=np.int32))
    except Exception:  # noqa: BLE001
        pass
    me.update(calc_edges=True)
    changed = bool(me.validate(verbose=False))
    try:
        me.shade_smooth()
    except AttributeError:
        me.polygons.foreach_set("use_smooth", np.ones(nt, dtype=bool))
    co = np.empty(3 * len(me.vertices), dtype=np.float32)
    me.vertices.foreach_get("co", co)
    vi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", vi)
    rec = {"vertices": len(me.vertices), "triangles": len(me.polygons), "checksum": checksum(co),
           "triangles_checksum": checksum_tris(vi), "validate_changed": changed}
    return me, rec


def set_camera(scene, cam_obj, c):
    cd = cam_obj.data
    cd.type = "ORTHO" if c["type"] == "ortho" else "PERSP"
    cd.sensor_fit = "AUTO"
    cd.sensor_width = float(c.get("sensor_mm", 36.0))
    cd.shift_x = cd.shift_y = 0.0
    if cd.type == "ORTHO":
        cd.ortho_scale = float(c["ortho_scale"])
    else:
        cd.lens = float(c["lens_mm"])
    cd.clip_start, cd.clip_end = float(c["clip_start"]), float(c["clip_end"])
    cam_obj.matrix_world = Matrix(c["matrix_world"])


def set_lights(scene, specs, made):
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    made.clear()
    for s in specs:
        ld = bpy.data.lights.new(s["name"], type="AREA")
        ld.size = float(s["size"])
        ld.energy = float(s["energy"])
        o = bpy.data.objects.new(s["name"], ld)
        scene.collection.objects.link(o)
        o.matrix_world = Matrix(s["matrix_world"])
        try:
            o.visible_camera = False
        except AttributeError:
            pass
        made.append(o)


def set_world(scene, strength):
    w = bpy.data.worlds.new("blnt_world")
    nt = node_tree(w)
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    set_input(bg, ["Color"], (1.0, 1.0, 1.0, 1.0))
    set_input(bg, ["Strength"], float(strength))
    out = nt.nodes.get("World Output") or nt.nodes.new("ShaderNodeOutputWorld")
    if not bg.outputs[0].links:
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
    scene.world = w


def render_settings(scene, o, check):
    r, cy = scene.render, scene.cycles
    r.engine = "CYCLES"
    cy.device = "CPU"
    cy.seed = 0
    r.film_transparent = True
    r.resolution_percentage = 100
    r.threads_mode = "FIXED"
    r.threads = int(o["threads"])
    s = r.image_settings
    try:
        s.media_type = "IMAGE"               # Blender 5.0+
    except (AttributeError, TypeError):
        pass
    s.file_format = "PNG"
    s.color_mode = "RGBA"
    vs = scene.view_settings
    vs.look = "None"
    vs.exposure, vs.gamma = 0.0, 1.0
    scene.display_settings.display_device = "sRGB"
    if check:
        r.resolution_x, r.resolution_y = int(o["check_width"]), int(o["check_height"])
        cy.samples = 1
        cy.use_adaptive_sampling = False
        cy.use_denoising = False
        cy.filter_width = 0.01
        s.color_depth = "8"
        vs.view_transform = "Standard"
    else:
        r.resolution_x, r.resolution_y = int(o["width"]), int(o["height"])
        cy.samples = int(o["samples"])
        cy.use_denoising = bool(o["denoise"])
        if o["denoise"]:
            try:
                cy.denoiser = "OPENIMAGEDENOISE"
            except TypeError:
                pass
        cy.filter_width = 1.5
        s.color_depth = "16" if o.get("format") == "png16" else "8"
        vs.view_transform = o["view_transform"]


def main():
    sj, outdir = args()
    S = json.loads(sj.read_text())
    Z = np.load(sj.with_suffix(".npz"))
    outdir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    clear_scene()
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    try:
        scene.unit_settings.length_unit = "MILLIMETERS"
    except TypeError:
        pass
    out = {"blender": bpy.app.version_string, "numpy": np.__version__,
           "oidn": bool(getattr(bpy.app.build_options, "openimagedenoise", False)), "objects": {}, "views": {}}
    t0 = time.perf_counter()
    objs, beauty, check = [], {}, {}
    flat = S["lights"]["preset"] == "flat"
    for k, ob in enumerate(S["objects"]):
        me, rec = make_mesh(ob["name"], Z[f"v{k}"], Z[f"t{k}"])
        o = bpy.data.objects.new(ob["name"], me)
        scene.collection.objects.link(o)
        o.pass_index = k + 1
        m = ob["material"]
        beauty[o.name] = emission(f"{ob['name']}_flat", m["base_color"]) if flat else principled(f"{ob['name']}_mat", m)
        check[o.name] = emission(f"{ob['name']}_check", ob["check_color_linear"])
        me.materials.append(beauty[o.name])
        objs.append(o)
        out["objects"][ob["name"]] = rec
    floor = None
    if S.get("floor"):
        f = S["floor"]
        V = np.array(f["vertices"], float)
        me, _ = make_mesh("blnt_floor", V, np.array([[0, 1, 2], [0, 2, 3]]))
        floor = bpy.data.objects.new("blnt_floor", me)
        scene.collection.objects.link(floor)
        floor.is_shadow_catcher = True
        me.materials.append(principled("blnt_floor_mat", {"base_color": [0.8, 0.8, 0.8], "roughness": 0.8}))
    set_world(scene, S["lights"]["world"])
    cam = bpy.data.objects.new("blnt_camera", bpy.data.cameras.new("blnt_camera"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    out["build_seconds"] = round(time.perf_counter() - t0, 3)
    lights = []
    o_set = S["output"]
    for v in S["views"]:
        rec = {}
        set_camera(scene, cam, v["camera"])
        set_lights(scene, v["lights"], lights)
        bpy.context.view_layer.update()
        render_settings(scene, o_set, check=False)
        W, H = scene.render.resolution_x, scene.render.resolution_y
        pts = []
        for p in v["test_points"]:
            c = world_to_camera_view(scene, cam, Vector(p))
            pts.append([c.x * W, (1.0 - c.y) * H, c.z])
        rec["test_points_px"] = pts
        for o in objs:
            o.data.materials[0] = beauty[o.name]
        if floor is not None:
            floor.hide_render = False
        t1 = time.perf_counter()
        scene.render.filepath = str(outdir / f"{v['name']}_raw.png")
        bpy.ops.render.render(write_still=True)
        rec["render_seconds"] = round(time.perf_counter() - t1, 3)
        render_settings(scene, o_set, check=True)
        for o in objs:
            o.data.materials[0] = check[o.name]
        if floor is not None:
            floor.hide_render = True
        for li in lights:
            li.hide_render = True
        t1 = time.perf_counter()
        scene.render.filepath = str(outdir / f"{v['name']}_check.png")
        bpy.ops.render.render(write_still=True)
        rec["check_seconds"] = round(time.perf_counter() - t1, 3)
        for li in lights:
            li.hide_render = False
        out["views"][v["name"]] = rec
    for o in objs:
        o.data.materials[0] = beauty[o.name]
    if floor is not None:
        floor.hide_render = False
    render_settings(scene, o_set, check=False)
    out["threads"] = scene.render.threads
    out["denoiser"] = scene.cycles.denoiser if o_set["denoise"] else None
    if S.get("blend"):
        p = outdir / "scene.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(p), copy=True)
        out["blend"] = str(p)
    out["seconds"] = round(time.perf_counter() - t0, 3)
    print("BLNT_OK " + json.dumps(out), flush=True)


try:
    main()
except SystemExit:
    raise
except Exception:  # noqa: BLE001
    print("BLNT_ERROR " + json.dumps({"traceback": traceback.format_exc()[-4000:]}), flush=True)
    raise
