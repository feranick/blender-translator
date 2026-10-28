"""Offline tests: sources, mesh checks, the camera model and the reference rasteriser.
Version: 2026.10.28.1
"""
import math

import numpy as np
import pytest

from blender_translator import camera as C
from blender_translator import meshcheck, refrender, sources

needs_b3dt = pytest.mark.skipif(not sources.have_b3dt(), reason="build123d-translator is not installed")


# ----------------------------------------------------------------------------- meshes

def test_box_mesh_closed_and_exact():
    m = sources.object_mesh({"name": "b", "source": {"box": [10, 20, 30]}})
    c = meshcheck.check_object(m)
    assert c["result"]["closed"] and c["checks"]["volume"]["passed"]
    assert c["result"]["volume_mm3"] == pytest.approx(6000.0, abs=1e-9)
    assert c["result"]["area_mm2"] == pytest.approx(2200.0, abs=1e-9)
    assert c["result"]["bbox_min"] == [-5.0, -10.0, 0.0] and c["result"]["bbox_max"] == [5.0, 10.0, 30.0]


def test_sphere_within_tolerance_bound():
    m = sources.object_mesh({"name": "s", "source": {"sphere": 20}, "tessellation": {"tol": 0.02}})
    c = meshcheck.check_object(m)
    assert c["result"]["closed"] and c["checks"]["volume"]["passed"]
    assert abs(c["result"]["volume_error"]) < 3e-3
    assert m["vertices"][:, 2].min() == pytest.approx(0.0, abs=1e-9)          # rests on z = 0


def test_topology_finds_holes_and_flips():
    V, T = sources.box_mesh(1, 1, 1)
    t = meshcheck.topology(V, T[1:])
    assert not t["closed"] and t["boundary_edges"] == 3
    T2 = T.copy()
    T2[0] = T2[0][::-1]
    t2 = meshcheck.topology(V, T2)
    assert not t2["closed"] and t2["repeated_edges"] > 0
    T3 = np.vstack([T, [[0, 0, 1]]])
    assert meshcheck.topology(V, T3)["degenerate_triangles"] == 1


def test_placement_xyz_euler():
    R = sources.rotation([0, 0, 90])
    assert np.allclose(R @ [1, 0, 0], [0, 1, 0])
    R = sources.rotation([90, 0, 90])            # x first, then z
    assert np.allclose(R @ [0, 1, 0], [0, 0, 1]) and np.allclose(R @ [1, 0, 0], [0, 1, 0])
    m = sources.object_mesh({"name": "b", "source": {"box": [2, 2, 2]}, "at": [10, 0, 0]})
    assert m["vertices"][:, 0].min() == pytest.approx(9.0)


@needs_b3dt
def test_goal_tessellation_volume():
    goal = {"features": [{"kind": "base_box", "params": {"w": 80, "d": 40, "h": 10}},
                         {"kind": "hole", "params": {"r": 4, "x": 25, "y": 0}}]}
    m = sources.object_mesh({"name": "p", "source": {"goal": goal}})
    exact = 80 * 40 * 10 - math.pi * 16 * 10
    assert m["cad_volume"] == pytest.approx(exact, rel=1e-9)
    c = meshcheck.check_object(m)
    assert c["result"]["closed"] and c["checks"]["volume"]["passed"]
    assert abs(c["result"]["volume_error"]) < 2e-3                     # 0.2 % at the default tol


@needs_b3dt
def test_step_and_b3dt_sources(tmp_path):
    from build123d_translator import translate as T
    solid, _ = T.build({"features": [{"kind": "base_box", "params": {"w": 30, "d": 20, "h": 5}}]})
    step = T.export(solid, tmp_path / "p", ("step",))["step"]
    m = sources.object_mesh({"name": "p", "source": {"b3dt": {"step": step, "volume": 3000.0}}})
    c = meshcheck.check_object(m)
    assert c["checks"]["b3dt_volume"]["passed"] and c["result"]["volume_mm3"] == pytest.approx(3000.0, rel=1e-9)


# ----------------------------------------------------------------------------- camera

def test_perspective_projection_formula():
    cam = {"type": "persp", "from": [0, -100, 0], "to": [0, 0, 0], "up": [0, 0, 1], "lens_mm": 50,
           "sensor_mm": 36, "width": 360, "height": 240}
    uv, z = C.project(cam, [[10, 0, 5]])
    assert uv[0] == pytest.approx([230.0, 95.0]) and z[0] == pytest.approx(100.0)
    M = np.array(C.matrix_world(cam))
    assert np.allclose(M[:3, 2], [0, -1, 0]) and np.allclose(M[:3, 1], [0, 0, 1]) and np.allclose(M[:3, 3], [0, -100, 0])


def test_ortho_projection_formula():
    cam = {"type": "ortho", "from": [0, -100, 5], "to": [0, 0, 5], "up": [0, 0, 1], "ortho_scale": 20,
           "width": 200, "height": 100}
    uv, _ = C.project(cam, [[10, 0, 5], [0, 0, 0]])
    assert uv[0] == pytest.approx([200.0, 50.0]) and uv[1] == pytest.approx([100.0, 100.0])


@pytest.mark.parametrize("view", list(C.PRESETS))
@pytest.mark.parametrize("proj", ["perspective", "ortho"])
def test_fit_every_preset(view, proj):
    V, _ = sources.box_mesh(30, 10, 20)
    cam = C.solve({"view": view, "projection": proj, "fit": 0.7}, V, 800, 600)
    a = C.achieved_fit(cam, V)
    assert a["inside"] and a["fit"] == pytest.approx(0.7, abs=0.01)
    assert max(abs(x) for x in a["center_offset_px"]) < 1.0


def test_literal_and_aimed_views():
    V, _ = sources.box_mesh(10, 10, 10)
    lit = C.solve({"view": {"from": [0, -80, 5], "to": [0, 0, 5]}}, V, 400, 400)
    assert lit["from"] == [0, -80, 5] and lit["to"] == [0, 0, 5]
    aimed = C.solve({"view": {"from": [0, -80, 5], "to": [0, 0, 5]}, "fit": 0.5}, V, 400, 400)
    assert aimed["to"] == [0, 0, 5] and aimed["fit"] == pytest.approx(0.5, abs=1e-3)


def test_target_frames_one_object():
    A, _ = sources.box_mesh(10, 10, 10)
    B = A + [100, 0, 0]
    cam = C.solve({"view": "front", "projection": "ortho", "fit": 0.5}, np.vstack([A, B]), 400, 400, target_pts=B)
    assert cam["to"][0] == pytest.approx(100.0) and C.achieved_fit(cam, B)["fit"] == pytest.approx(0.5)


# ----------------------------------------------------------------------------- reference rasteriser

def _mesh(V, T):
    return {"vertices": V, "triangles": T}


def test_cube_ortho_exact_pixels():
    V, T = sources.box_mesh(10, 10, 10)
    cam = C.solve({"view": "front", "projection": "ortho", "fit": 0.5}, V, 100, 100)
    assert cam["ortho_scale"] == pytest.approx(20.0)
    r = refrender.rasterise(cam, [_mesh(V, T)])
    idx = r["index"]
    assert int((idx > 0).sum()) == 2500
    assert (idx[25:75, 25:75] == 1).all()


def test_sphere_coverage_area():
    V, T = sources.sphere_mesh(20, 0.005)
    cam = C.solve({"view": "front", "projection": "ortho", "fit": 0.8}, V, 400, 400)
    r = refrender.rasterise(cam, [_mesh(V, T)])
    px_per_mm = 400 / cam["ortho_scale"]
    expected = math.pi * (20 * px_per_mm) ** 2
    assert int((r["index"] > 0).sum()) == pytest.approx(expected, rel=5e-3)


def test_perspective_square_area():
    s = 10.0                                      # a square facing the camera at depth 100
    V = np.array([[-s, 0, -s], [s, 0, -s], [s, 0, s], [-s, 0, s]], float)
    T = np.array([[0, 1, 2], [0, 2, 3]])
    cam = {"type": "persp", "from": [0, -100, 0], "to": [0, 0, 0], "up": [0, 0, 1], "lens_mm": 50,
           "sensor_mm": 36, "width": 360, "height": 360, "clip_start": 1.0}
    r = refrender.rasterise(cam, [_mesh(V, T)])
    side = 2 * s / 100 * 50 / 36 * 360           # 100 px
    assert int((r["index"] > 0).sum()) == pytest.approx(side * side, rel=0.02)


def test_occlusion_nearest_wins():
    A, T = sources.box_mesh(10, 10, 10)
    B = A + [0, 20, 0]                             # behind A seen from the front
    B2 = sources.box_mesh(20, 2, 20)[0] + [0, 30, -5]
    for proj in ("ortho", "perspective"):
        cam = C.solve({"view": "front", "projection": proj, "fit": 0.8}, np.vstack([A, B, B2]), 300, 300)
        r = refrender.rasterise(cam, [_mesh(A, T), _mesh(B, T), _mesh(B2, T)])
        uv, _ = C.project(cam, [[0, -5, 5]])
        u, vv = (int(x) for x in uv[0])
        assert r["index"][vv, u] == 1                     # A in front
        assert not (r["index"] == 2).any()                # B hidden behind A (same size, farther)
        if proj == "ortho":                               # (in perspective the near box hides the plate)
            assert (r["index"] == 3).sum() == 43200       # 20 x 20 plate minus A's 10 x 10, at 18 px/mm


def test_decode_and_compare():
    from blender_translator import materials as M
    ref = np.zeros((40, 40), np.int16)
    ref[10:30, 5:20] = 1
    ref[10:30, 20:35] = 2
    rgba = np.zeros((40, 40, 4), np.uint8)
    for k, c in ((1, M.PALETTE[0]), (2, M.PALETTE[1])):
        rgba[ref == k, :3] = M.hex_rgb8(c)
        rgba[ref == k, 3] = 255
    got = refrender.decode_check(rgba, M.PALETTE[:2])
    assert np.array_equal(got, ref)
    cmp = refrender.compare_maps(ref, got, 2)
    assert cmp["coverage_iou"] == 1.0 and cmp["objects_iou"] == {1: 1.0, 2: 1.0}
    shifted = np.roll(got, 3, axis=1)
    assert refrender.compare_maps(ref, shifted, 2)["objects_iou"][1] < 0.9
    flat = refrender.compare_flat(ref, rgba, M.PALETTE[:2])
    assert flat[1]["max"] == 0 and flat[2]["mean"] == 0.0
