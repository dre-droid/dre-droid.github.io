#!/usr/bin/env python3
"""
Generate a SYNTHETIC point cloud so the hero viewer can be developed and tested
before Andrea's real scan arrives.

    python3 scripts/make_placeholder_cloud.py

This is fabricated geometry. It exists only to exercise the renderer — it must be
replaced with a real scan before the site is published, and the hero caption says
"placeholder" until it is. Writes assets/data/scene.placeholder.bin.
"""

from pathlib import Path

import numpy as np

import pcd

rng = np.random.default_rng(7)
OUT = Path("assets/data/scene.placeholder.bin")

parts = []


def ring_sweep():
    """A rotating-LiDAR style sweep: 48 elevation rings intersecting a ground plane."""
    az = np.deg2rad(np.linspace(0, 360, 2200, endpoint=False))
    el = np.deg2rad(np.linspace(-24, 3, 48))
    A, E = np.meshgrid(az, el, indexing="ij")
    A, E = A.ravel(), E.ravel()

    # Range to a flat road at z = -1.9 m (sensor height), capped at 60 m.
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(E < -0.005, -1.9 / np.sin(E), np.inf)
    keep = np.isfinite(r) & (r < 60)
    r, A, E = r[keep], A[keep], E[keep]
    r += rng.normal(0, 0.02, r.shape)

    return np.stack([r * np.cos(E) * np.cos(A),
                     r * np.cos(E) * np.sin(A),
                     r * np.sin(E)], axis=1)


def facade(x0, x1, y, n=9000):
    """A building wall running along x at a fixed y."""
    x = rng.uniform(x0, x1, n)
    z = rng.uniform(-1.9, 9.0, n)
    yy = np.full(n, y) + rng.normal(0, 0.05, n)
    return np.stack([x, yy, z], axis=1)


def box(cx, cy, cz, sx, sy, sz, n=2600):
    """Hollow box surface — stands in for a vehicle."""
    p = rng.uniform(-0.5, 0.5, (n, 3)) * np.array([sx, sy, sz])
    face = rng.integers(0, 3, n)
    sign = rng.choice([-0.5, 0.5], n)
    for ax in range(3):
        m = face == ax
        p[m, ax] = sign[m] * [sx, sy, sz][ax]
    return p + np.array([cx, cy, cz])


def pole(x, y, h=7.0, n=900):
    t = rng.uniform(-1.9, h, n)
    a = rng.uniform(0, 2 * np.pi, n)
    return np.stack([x + 0.09 * np.cos(a), y + 0.09 * np.sin(a), t], axis=1)


parts.append(ring_sweep())
parts.append(facade(-40, 40, 11.5))
parts.append(facade(-40, 40, -11.5))
for cx, cy in [(9, 4.2), (-14, 4.0), (23, -4.1), (-3, -4.3), (36, 3.9)]:
    parts.append(box(cx, cy, -1.1, 4.4, 1.9, 1.5))
for x in range(-36, 40, 12):
    parts.append(pole(x, 9.6))

pts = np.concatenate(parts).astype(np.float32)
pts = pts[np.linalg.norm(pts, axis=1) < 60]
rng.shuffle(pts)
pts = pts[:60000]

blob = pcd.encode(pts, bits=13)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(blob)

import gzip
print(f"wrote {OUT} — {len(pts):,} synthetic points, "
      f"{len(blob) / 1024:.0f} KB ({len(gzip.compress(blob, 9)) / 1024:.0f} KB gzipped)")
print("PLACEHOLDER ONLY. Replace with a real scan before publishing.")
