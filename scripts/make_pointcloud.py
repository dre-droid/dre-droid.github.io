#!/usr/bin/env python3
"""
Convert a LiDAR scan into the compact binary the hero viewer reads.

    python3 scripts/make_pointcloud.py <input> [-o assets/data/scene.bin] [-n 60000]

Supported inputs: .bin (raw float32 sweeps — KITTI's 4 fields or nuScenes' 5 are
auto-detected), .npy, .pcd (ascii), .ply (ascii), .txt/.csv (x y z per line).

Writes the PCD2 container documented in scripts/pcd.py. ~60k points at the default
13-bit precision lands near 140 KB gzipped, comfortably inside the hero budget.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

import pcd


def load(path: Path) -> np.ndarray:
    """Return an (N, 3) float32 array of XYZ."""
    ext = path.suffix.lower()

    if ext == ".bin":
        return _load_raw_bin(path)

    if ext == ".npy":
        arr = np.load(path)
        if arr.ndim != 2 or arr.shape[1] < 3:
            sys.exit(f"{path.name}: expected an (N, >=3) array, got {arr.shape}")
        return arr[:, :3].astype(np.float32)

    if ext in (".pcd", ".ply"):
        text = path.read_text(errors="replace").splitlines()
        marker = "DATA" if ext == ".pcd" else "end_header"
        for i, line in enumerate(text):
            if line.strip().lower().startswith(marker.lower()):
                if ext == ".pcd" and "ascii" not in line.lower():
                    sys.exit(f"{path.name}: binary .pcd is not supported — export as ascii.")
                body = text[i + 1:]
                break
        else:
            sys.exit(f"{path.name}: no '{marker}' found; is the header intact?")
        return _parse_rows(body, path)

    if ext in (".txt", ".csv", ".xyz"):
        return _parse_rows(path.read_text(errors="replace").splitlines(), path)

    sys.exit(f"Unsupported extension '{ext}'. Convert to .npy or ascii .pcd/.ply first.")


# Raw .bin sweeps are just interleaved float32 with no header, so the stride has
# to be inferred. KITTI packs 4 (x, y, z, intensity); nuScenes packs 5, adding a
# ring index. A file's byte count is usually divisible by both, so guessing from
# the extension gets it wrong silently — and a wrong stride still "loads",
# producing a sheared cloud that looks vaguely plausible. Read the columns instead.
_BIN_STRIDES = (5, 4, 6)


def _score_stride(raw: np.ndarray, stride: int) -> float:
    """Score interpreting `raw` as (N, stride). Negative means impossible."""
    if raw.size % stride:
        return -1.0
    a = raw.reshape(-1, stride)
    if not np.isfinite(a).all():
        return -1.0

    xyz, extra = a[:, :3], a[:, 3:]

    # Coordinates are continuous metres about the sensor. A wrong stride mixes
    # quantised channels into them, which shows up as absurd range or integrality.
    if np.abs(xyz).max() > 500 or np.allclose(xyz, np.round(xyz)):
        return -1.0

    # Trailing channels should look like sensor data: small non-negative integers.
    score = 0.0
    for col in extra.T:
        if not np.allclose(col, np.round(col)) or col.min() < 0:
            return -1.0          # a smeared coordinate, not a sensor channel
        if col.max() <= 255:
            score += 1.0         # intensity, or a ring index
        if len(np.unique(col)) <= 128:
            score += 0.5         # a small discrete set — almost certainly ring
    return score


def _load_raw_bin(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype=np.float32)
    scored = sorted(
        ((_score_stride(raw, s), s) for s in _BIN_STRIDES),
        reverse=True,
    )
    best_score, stride = scored[0]
    if best_score < 0:
        sys.exit(
            f"{path.name}: could not read this as a raw float32 sweep "
            f"(tried {_BIN_STRIDES} floats per point). Convert it to .npy instead."
        )
    named = {4: "KITTI-style", 5: "nuScenes-style", 6: "6-field"}[stride]
    print(f"layout   {stride} float32/point ({named})")
    return raw.reshape(-1, stride)[:, :3]


def _parse_rows(lines, path: Path) -> np.ndarray:
    rows = []
    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    if not rows:
        sys.exit(f"{path.name}: found no parseable XYZ rows.")
    return np.asarray(rows, dtype=np.float32)


def voxel_downsample(pts: np.ndarray, target: int) -> np.ndarray:
    """Voxel-grid downsample, binary-searching the voxel size to hit ~target points.

    Preferred over random sampling: it keeps structure (walls, poles, road surface)
    instead of thinning everything uniformly, which is what makes a scan legible.
    """
    if len(pts) <= target:
        return pts

    extent = float(np.max(pts.max(0) - pts.min(0)))
    lo, hi = extent / 4000.0, extent / 4.0
    best = pts

    for _ in range(24):
        size = (lo + hi) / 2
        keys = np.floor((pts - pts.min(0)) / size).astype(np.int64)
        _, idx = np.unique(keys, axis=0, return_index=True)
        kept = pts[np.sort(idx)]
        if len(kept) > target:
            lo = size
        else:
            best = kept
            hi = size
        if 0.9 * target <= len(kept) <= target:
            return kept
    return best if len(best) <= target else best[:target]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("assets/data/scene.bin"))
    ap.add_argument("-n", "--points", type=int, default=60000, help="target point count (default 60000)")
    ap.add_argument("-b", "--bits", type=int, default=13,
                    help="quantisation bits per axis (default 13, ~1.2 cm over a 100 m scene)")
    ap.add_argument("--clip", type=float, default=0.0,
                    help="drop points further than this many metres from the origin (0 = keep all)")
    args = ap.parse_args()

    pts = load(args.input)
    print(f"loaded   {len(pts):>9,} points from {args.input.name}")

    pts = pts[np.isfinite(pts).all(axis=1)]

    if args.clip > 0:
        pts = pts[np.linalg.norm(pts, axis=1) <= args.clip]
        print(f"clipped  {len(pts):>9,} points within {args.clip} m")

    pts = voxel_downsample(pts, args.points)
    print(f"sampled  {len(pts):>9,} points")

    blob = pcd.encode(pts, bits=args.bits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)

    import gzip
    kb = len(blob) / 1024
    gz = len(gzip.compress(blob, 9)) / 1024
    span = float(np.max(pts.max(0) - pts.min(0)))
    print(f"wrote    {args.output}  ({kb:.0f} KB, {gz:.0f} KB gzipped)")
    print(f"         {args.bits}-bit quantisation → {span / ((1 << args.bits) - 1) * 100:.2f} cm over a {span:.0f} m scene")
    if gz > 400:
        print(f"  ⚠  over the 400 KB hero budget — rerun with -n {int(args.points * 380 / gz)} or a lower --bits")


if __name__ == "__main__":
    main()
