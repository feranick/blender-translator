"""Offline tests: the format, validation (with the run caps), the estimate, the scene writer and the template.
Version: 2026.10.28.1
"""
import ast
import json
from pathlib import Path

import numpy as np
import pytest

from blender_translator import __version__
from blender_translator import format as F
from blender_translator import materials as M
from blender_translator import meshcheck, scene, sources

BOX = {"objects": [{"name": "b", "source": {"box": [10, 20, 30]}}], "views": [{"name": "iso"}]}


def v(st):
    return F.validate({"s": st})["s"]


def test_version_everywhere():
    root = Path(__file__).resolve().parents[1]
    assert f'version = "{__version__}"' in (root / "pyproject.toml").read_text()
    for p in (root / "blender_translator").glob("*.py"):
        txt = p.read_text()
        assert __version__ in txt, f"{p.name} has no 'Version: {__version__}'"


def test_format_compact_and_example_valid():
    f = F.study_format({"translator": __version__})
    assert len(json.dumps(f)) < 12000
    assert f["status"]["translator"] == __version__
    if sources.have_b3dt():
        assert all(r["ok"] for r in F.validate(F.EXAMPLE).values())


def test_valid_box_and_estimate():
    r = v(BOX)
    assert r["ok"], r["errors"]
    e = r["estimate"]
    assert set(e) == {"minutes", "procs", "mem_mb"} and e["minutes"] > 0 and e["mem_mb"] > 600


@pytest.mark.parametrize("st,frag", [
    ({"objects": []}, "objects: a non-empty list"),
    ({"objects": [{"name": "a", "source": {"cube": 3}}]}, "exactly one of"),
    ({"objects": [{"name": "a", "source": {"box": [1, 2]}}]}, "box: [lx, ly, lz]"),
    ({"objects": [{"name": "a", "source": {"sphere": -1}}]}, "sphere: the radius"),
    ({"objects": [{"name": "a", "source": {"step": "/no/such.step"}}]}, "no file /no/such.step"),
    ({"objects": [{"name": "a", "source": {"box": [1, 1, 1]}, "color": "red"}]}, "'#rrggbb'"),
    ({"objects": [{"name": "a", "source": {"box": [1, 1, 1]}, "material": "gold"}]}, "material: one of"),
    ({"objects": [{"name": "a", "source": {"box": [1, 1, 1]}, "roughness": 2}]}, "roughness: a number from 0 to 1"),
    ({"objects": [{"name": "a", "source": {"box": [1, 1, 1]}}, {"name": "a", "source": {"box": [1, 1, 1]}}]},
     "names must be unique"),
    ({**BOX, "views": [{"name": "x y"}]}, "views[0].name"),
    ({**BOX, "views": [{"name": "x", "view": "diagonal"}]}, "views[0].view: one of"),
    ({**BOX, "views": [{"name": "x", "target": "nope"}]}, "target: one of the objects"),
    ({**BOX, "views": [{"name": "x", "view": {"from": [0, 0, 0], "to": [0, 0, 0]}}]}, "from and to must differ"),
    ({**BOX, "views": [{"name": "x", "ortho_scale": 5}]}, "ortho_scale: only with"),
    ({**BOX, "views": [{"name": "x", "fit": 2}]}, "fit: 0.05 to 1"),
    ({**BOX, "lights": "disco"}, "lights: one of"),
    ({**BOX, "background": "grey"}, "background:"),
    ({**BOX, "output": {"width": 10000}}, "output.width"),
    ({**BOX, "output": {"samples": 0}}, "output.samples"),
    ({**BOX, "colour": 1}, "unknown keys ['colour']"),
    ({**BOX, "run": {"procs": 2.5}}, "run.procs: a whole number"),
    ({**BOX, "run": {"mem": "lots"}}, "run.mem"),
    ({**BOX, "run": {"host": "mochi"}}, "run: unknown keys ['host']"),
])
def test_errors_say_the_fix(st, frag):
    r = v(st)
    assert not r["ok"]
    assert any(frag in e for e in r["errors"]), r["errors"]


def test_run_caps(monkeypatch):
    monkeypatch.setenv("BLNT_MAX_PROCS", "4")
    monkeypatch.setenv("BLNT_MAX_MEM", "8G")
    monkeypatch.setenv("BLNT_MAX_TIMEOUT", "3600")
    r = v({**BOX, "run": {"procs": 8, "mem": "16G", "timeout_s": 7200}})
    errs = " ".join(r["errors"])
    assert "BLNT_MAX_PROCS=4" in errs and "BLNT_MAX_MEM=8G" in errs and "BLNT_MAX_TIMEOUT=3600" in errs
    assert v({**BOX, "run": {"procs": 4, "mem": "8G", "timeout_s": 3600, "queue": True}})["ok"]


def test_estimate_scales_with_threads(monkeypatch):
    monkeypatch.setattr(F.os, "cpu_count", lambda: 64)
    a = F.estimate({**BOX, "output": {"width": 1000, "height": 1000, "samples": 256}})
    b = F.estimate({**BOX, "output": {"width": 1000, "height": 1000, "samples": 256}, "run": {"procs": 16}})
    assert b["procs"] == 16 and b["minutes"] < a["minutes"] / 4


def test_bad_study_name():
    assert not F.validate({"a b": BOX})["a b"]["ok"]


def test_colours():
    assert M.hex_rgb8("#3366cc") == (51, 102, 204)
    lin = M.hex_linear("#3366cc")
    back = np.round(M.linear_to_srgb(lin) * 255).astype(int).tolist()
    assert back == [51, 102, 204]
    spec = M.material_spec({"material": "anodised", "color": "#ff0000", "roughness": 0.2})
    assert spec["base_color"] == [1.0, 0.0, 0.0] and spec["roughness"] == 0.2 and spec["metallic"] == 0.8


def _scene(study):
    st = F.normalise(study)
    ms = [sources.object_mesh(o) for o in st["objects"]]
    return st, ms, scene.build(st, ms)


def test_scene_build_and_write(tmp_path):
    st, ms, sc = _scene({"objects": [{"name": "a", "source": {"box": [10, 10, 10]}},
                                     {"name": "b", "source": {"sphere": 5}, "at": [20, 0, 0], "material": "polished"}],
                         "views": [{"name": "iso"}, {"name": "top", "view": "top", "projection": "ortho"}],
                         "background": "floor", "blend": True})
    assert [o["check_color"] for o in sc["objects"]] == M.PALETTE[:2]
    assert sc["floor"]["z"] == pytest.approx(0.0)
    assert len(sc["views"][0]["lights"]) == 3 and sc["lights"]["world"] == M.LIGHTS["studio"]["world"]
    for vw in sc["views"]:
        assert vw["camera"]["inside"] and len(vw["test_points"]) == 8 * 3
        for L in vw["lights"]:      # each light aims at the camera's target: its -Z axis points there
            Mw = np.array(L["matrix_world"])
            to = np.array(vw["camera"]["to"]) - Mw[:3, 3]
            assert np.dot(-Mw[:3, 2], to / np.linalg.norm(to)) == pytest.approx(1.0)
    files = scene.write(tmp_path, sc, ms)
    sc2, ms2 = scene.load(tmp_path)
    assert sc2["objects"][1]["name"] == "b"
    assert np.array_equal(ms2[1]["triangles"], ms[1]["triangles"])
    assert sc2["objects"][1]["checksum"] == meshcheck.checksum(ms2[1]["vertices"])
    assert Path(files["script"]).read_text() == scene.TEMPLATE.read_text()
    assert sc["output"]["check_width"] <= scene.CHECK_MAX


def test_check_size():
    assert scene.check_size(1600, 1200) == (1024, 768)
    assert scene.check_size(800, 600) == (800, 600)


def _template_functions(*names):
    """The template's own functions (it imports bpy, so it is not imported here): compiled from its source."""
    tree = ast.parse(scene.TEMPLATE.read_text())
    ns = {"np": np}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), "scene_template", "exec"), ns)
    return [ns[n] for n in names]


def test_template_checksums_match_ours():
    V = np.random.default_rng(1).normal(size=(500, 3)) * 37.0
    T = np.random.default_rng(2).integers(0, 500, size=(300, 3))
    cs, ct = _template_functions("checksum", "checksum_tris")
    assert cs(np.asarray(V, np.float32).ravel()) == meshcheck.checksum(V)
    assert ct(T.astype(np.int32).ravel()) == meshcheck.checksum_tris(T)


def test_template_compiles_and_imports_only_blender_and_stdlib():
    tree = ast.parse(scene.TEMPLATE.read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"json", "sys", "time", "traceback", "pathlib", "bpy", "numpy", "bpy_extras", "mathutils"}
    assert __version__ in scene.TEMPLATE.read_text()
