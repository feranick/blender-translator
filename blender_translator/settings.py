"""settings.py — the translator's settings, read from the environment only (llm-translators' bin/mcp loads them).
Version: 2026.10.28.1

BLNT_OUT (~/blnt_runs): the output folder. BLNT_PROCS (1): Cycles threads per study (a study's run.procs overrides
it). BLNT_TIMEOUT (1800 s): per study. BLNT_MAX_TIMEOUT (s), BLNT_MAX_MEM, BLNT_MAX_PROCS: ceilings for a study's
"run" (unset: none). The SLURM settings (BLNT_EXECUTOR, BLNT_SLURM_*) are read by executor.py (M5).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

RUN_KEYS = ("timeout_s", "mem", "procs", "queue")


def out_root() -> Path:
    return Path(os.environ.get("BLNT_OUT", "~/blnt_runs")).expanduser()


def default_procs() -> int:
    try:
        return max(1, int(os.environ.get("BLNT_PROCS", "1")))
    except ValueError:
        return 1


def default_timeout_s() -> float:
    try:
        return float(os.environ.get("BLNT_TIMEOUT", "1800"))
    except ValueError:
        return 1800.0


def run_of(study: dict | None) -> dict:
    r = (study or {}).get("run")
    return r if isinstance(r, dict) else {}


def timeout_s(study: dict | None = None) -> float:
    t = run_of(study).get("timeout_s")
    return float(t) if t else default_timeout_s()


def procs_of(study: dict | None) -> int:
    try:
        return max(1, int(run_of(study).get("procs") or default_procs()))
    except (TypeError, ValueError):
        return default_procs()


def mem_mb(v) -> float | None:
    """A SLURM memory size (500M, 8G, 1T, a plain number in MB) in MB; None if malformed."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*", str(v), re.I)
    if not m:
        return None
    return float(m.group(1)) * {"K": 1 / 1024, "": 1, "M": 1, "G": 1024, "T": 1024 ** 2}[m.group(2).upper()]


def caps() -> dict:
    """Ceilings on what a study may ask: BLNT_MAX_TIMEOUT (s), BLNT_MAX_MEM, BLNT_MAX_PROCS (unset: no cap)."""
    out = {}
    for key, var in (("timeout_s", "BLNT_MAX_TIMEOUT"), ("mem", "BLNT_MAX_MEM"), ("procs", "BLNT_MAX_PROCS")):
        v = os.environ.get(var, "").strip()
        if v:
            try:
                out[key] = v if key == "mem" else (float(v) if key == "timeout_s" else int(float(v)))
            except ValueError:
                pass
    return out
