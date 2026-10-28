"""materials.py — material and light presets, colours (sRGB hex <-> linear) and the check palette.
Version: 2026.10.28.1

Materials become Principled BSDF settings (Blender 4.0+ socket names) in scene.json; 'flat' lighting replaces
every material by an emission of the object's colour, so the image shows each colour exactly (view transform
Standard). Light power is scaled with the scene: Blender's units here are millimetres, and Cycles' falloff is per
unit squared, so a light at distance D gets energy = irradiance x pi x D^2.
"""
from __future__ import annotations

import re

import numpy as np

# preset: Principled BSDF inputs (base colour as sRGB hex; the study's "color" overrides it)
MATERIALS = {
    "matte":         {"color": "#b8b8b8", "metallic": 0.0, "roughness": 0.9},
    "satin":         {"color": "#b8b8b8", "metallic": 0.0, "roughness": 0.45},
    "plastic":       {"color": "#d0d0d0", "metallic": 0.0, "roughness": 0.35, "coat": 0.2},
    "metal_brushed": {"color": "#c8c9cb", "metallic": 1.0, "roughness": 0.35, "anisotropic": 0.6},
    "anodised":      {"color": "#8a95a3", "metallic": 0.8, "roughness": 0.4},
    "polished":      {"color": "#d6d7d9", "metallic": 1.0, "roughness": 0.08},
    "rubber":        {"color": "#262626", "metallic": 0.0, "roughness": 0.95},
    "glass":         {"color": "#f4f8fa", "metallic": 0.0, "roughness": 0.0, "transmission": 1.0, "ior": 1.5},
}
DEFAULT_MATERIAL = "satin"

# lights: (name, direction from the target in the camera's frame [right, up, back], irradiance, size / scene radius)
LIGHTS = {
    "studio": {"lights": [("key", (-0.8, 0.9, 1.0), 3.0, 1.0),
                          ("fill", (1.0, 0.2, 0.8), 1.0, 1.5),
                          ("rim", (0.3, 0.8, -1.0), 2.0, 0.8)],
               "world": 0.25, "view_transform": "AgX"},
    "soft": {"lights": [], "world": 1.0, "view_transform": "AgX"},
    "flat": {"lights": [], "world": 0.0, "view_transform": "Standard"},
}
DEFAULT_LIGHTS = "studio"
LIGHT_DISTANCE = 4.0        # x the scene's bounding radius, from the target

# the check render: each object an emission of one of these colours (well apart in RGB), background transparent
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6", "#bcf60c",
           "#008080", "#9a6324", "#800000", "#808000", "#000075", "#ffe119", "#aaffc3", "#fabebe"]
MAX_OBJECTS = len(PALETTE)

_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


def is_hex(c) -> bool:
    return isinstance(c, str) and bool(_HEX.fullmatch(c.strip()))


def hex_rgb8(c: str) -> tuple[int, int, int]:
    h = _HEX.fullmatch(c.strip()).group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def srgb_to_linear(c) -> np.ndarray:
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c) -> np.ndarray:
    c = np.clip(np.asarray(c, float), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def hex_linear(c: str) -> list[float]:
    """sRGB hex -> scene-linear RGB (what Blender's colour inputs take)."""
    return [float(x) for x in srgb_to_linear(np.array(hex_rgb8(c)) / 255.0)]


def material_spec(obj: dict) -> dict:
    """The object's material for scene.json: the preset, the colour and the overrides."""
    preset = obj.get("material", DEFAULT_MATERIAL)
    m = dict(MATERIALS[preset])
    color = obj.get("color", m.pop("color"))
    m.pop("color", None)
    for k in ("metallic", "roughness"):
        if k in obj:
            m[k] = float(obj[k])
    return {"preset": preset, "color": color, "base_color": hex_linear(color), **m}


def background_spec(bg) -> dict:
    """'white' | 'transparent' | '#rrggbb' | 'floor' -> how blnt composites the background after the render."""
    if bg in (None, "white"):
        return {"kind": "color", "color": "#ffffff", "floor": False}
    if bg == "transparent":
        return {"kind": "transparent", "color": None, "floor": False}
    if bg == "floor":
        return {"kind": "color", "color": "#ffffff", "floor": True}
    return {"kind": "color", "color": bg, "floor": False}
