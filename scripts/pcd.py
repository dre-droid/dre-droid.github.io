"""
PCD2 — the compact point-cloud container the hero viewer reads.

Three things make it small, in order of how much they buy:

  1. Quantise to `bits` per axis. 13 bits over a 100 m scene is ~1.2 cm, far below
     anything visible at hero scale, and it shrinks every delta below.
  2. Sort by Morton (Z-order) code, so points that are near each other in space end
     up near each other in the byte stream.
  3. Delta + zigzag + varint encode each axis as its own plane. After the Morton sort
     the deltas are tiny, so most coordinates cost one byte instead of two.

Point order carries no meaning in a cloud, so the reader never has to undo the sort.

Layout (little-endian):
    magic   4 bytes  "PCD2"
    count   uint32
    bits    uint8
    pad     3 bytes
    bounds  6 x float32   min_x min_y min_z max_x max_y max_z
    stream  varint zigzag deltas: all x, then all y, then all z
"""

import struct

import numpy as np

MAGIC = b"PCD2"
HEADER = 36


def _part1by2(v: np.ndarray) -> np.ndarray:
    """Spread the low 21 bits of each value out to every third bit."""
    v = v.astype(np.uint64) & 0x1FFFFF
    v = (v | (v << 32)) & 0x1F00000000FFFF
    v = (v | (v << 16)) & 0x1F0000FF0000FF
    v = (v | (v << 8)) & 0x100F00F00F00F00F
    v = (v | (v << 4)) & 0x10C30C30C30C30C3
    v = (v | (v << 2)) & 0x1249249249249249
    return v


def _varint(values: np.ndarray) -> bytes:
    out = bytearray()
    for v in values.tolist():
        while True:
            byte = v & 0x7F
            v >>= 7
            out.append(byte | (0x80 if v else 0))
            if not v:
                break
    return bytes(out)


def encode(points: np.ndarray, bits: int = 13) -> bytes:
    """Encode an (N, 3) float array. Returns the complete file bytes."""
    if not 8 <= bits <= 16:
        raise ValueError("bits must be between 8 and 16")

    pts = np.asarray(points, dtype=np.float64)
    lo, hi = pts.min(0), pts.max(0)
    span = np.where(hi - lo < 1e-9, 1.0, hi - lo)

    scale = (1 << bits) - 1
    q = np.clip(np.rint((pts - lo) / span * scale), 0, scale).astype(np.int64)

    code = _part1by2(q[:, 0]) | (_part1by2(q[:, 1]) << 1) | (_part1by2(q[:, 2]) << 2)
    q = q[np.argsort(code)]

    delta = np.diff(q, axis=0, prepend=np.zeros((1, 3), dtype=np.int64))
    zig = (delta << 1) ^ (delta >> 63)

    header = (
        MAGIC
        + struct.pack("<I", len(q))
        + struct.pack("<B3x", bits)
        + struct.pack("<6f", *lo.astype(np.float32), *hi.astype(np.float32))
    )
    assert len(header) == HEADER, len(header)

    return header + b"".join(_varint(zig[:, a]) for a in range(3))


def decode(blob: bytes) -> np.ndarray:
    """Inverse of `encode`, for round-trip testing."""
    if blob[:4] != MAGIC:
        raise ValueError("not a PCD2 cloud")
    count = struct.unpack_from("<I", blob, 4)[0]
    bits = blob[8]
    lo = np.array(struct.unpack_from("<3f", blob, 12))
    hi = np.array(struct.unpack_from("<3f", blob, 24))

    out = np.zeros((count, 3), dtype=np.int64)
    off = HEADER
    for axis in range(3):
        acc = 0
        for i in range(count):
            shift = 0
            raw = 0
            while True:
                byte = blob[off]
                off += 1
                raw |= (byte & 0x7F) << shift
                if not byte & 0x80:
                    break
                shift += 7
            acc += (raw >> 1) ^ -(raw & 1)
            out[i, axis] = acc

    span = np.where(hi - lo < 1e-9, 1.0, hi - lo)
    return lo + out / ((1 << bits) - 1) * span
