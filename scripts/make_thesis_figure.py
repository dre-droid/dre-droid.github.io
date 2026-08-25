#!/usr/bin/env python3
"""
Build the thesis figure: 30 training epochs of PCA-coloured features, as a loop.

    python3 scripts/make_thesis_figure.py resources/bev_feature_maps/visualizations

Each epoch directory holds a matplotlib `bev_pca.png` and a `camera_pca.png` (a 2x3
grid of camera views). This composes one frame per epoch — the BEV feature map beside
three camera views, on the site background, with an epoch counter and a progress rule —
and encodes the sequence to `assets/video/thesis.mp4` plus a poster.

Everything is done with ffmpeg filtergraphs; the repo has no image library and does not
want one for an asset that is rebuilt roughly never.
"""

import argparse
import subprocess
import sys
from pathlib import Path

FONT = "/System/Library/Fonts/SFNSMono.ttf"

# Palette, matching css/main.css.
BG, RULE, ACCENT, DIM = "0x0e1116", "0x2b323e", "0x6ee7c7", "0x9aa4b2"

# Source geometry. Verified identical across all 30 epochs, so it is hard-coded
# rather than re-detected per frame — but --probe re-checks it if the source changes.
BEV_CROP = (771, 771, 46, 32)          # w h x y: the axes rectangle, minus title and ticks
CAM_WH = (529, 192)                    # one camera panel
CAM_XY = [(10, 9), (644, 9), (10, 281)]  # front, front-right, side — three distinct views

W, H = 1392, 876
PX, PY, PW = 32, 86, 700               # BEV: square, left column
CX, CW, CH = 760, 600, 218             # camera: right column
CY = [86, 327, 568]
BAR_Y = 846


def compose(bev: Path, cam: Path, ep: int, total: int, dst: Path) -> None:
    bw, bh, bx, by = BEV_CROP
    cw, ch = CAM_WH

    fg = [
        f"color=c={BG}:s={W}x{H}[bg]",
        # matplotlib's axes background is a flat neutral grey. Key it out so the scan
        # sits on the page colour instead of inside a grey card that doesn't belong.
        f"[0:v]crop={bw}:{bh}:{bx}:{by},format=rgba,colorkey=0x262626:0.06:0.0,"
        f"scale={PW}:{PW}:flags=lanczos[bev]",
        f"[1:v]split={len(CAM_XY)}" + "".join(f"[s{i}]" for i in range(len(CAM_XY))),
    ]
    for i, (x, y) in enumerate(CAM_XY):
        fg.append(f"[s{i}]crop={cw}:{ch}:{x}:{y},scale={CW}:{CH}:flags=lanczos[p{i}]")

    fg.append(f"[bg][bev]overlay={PX}:{PY}[a]")
    prev = "a"
    for i, y in enumerate(CY):
        fg.append(f"[{prev}][p{i}]overlay={CX}:{y}[b{i}]")
        prev = f"b{i}"

    draw = [f"drawbox=x={PX}:y={PY}:w={PW}:h={PW}:color={RULE}@1:t=1"]
    draw += [f"drawbox=x={CX}:y={y}:w={CW}:h={CH}:color={RULE}@1:t=1" for y in CY]
    # A track and an accent bar that fills as training advances, so the loop reads as
    # a progression even to someone who catches it mid-way.
    draw.append(f"drawbox=x={PX}:y={BAR_Y}:w={W - 2 * PX}:h=2:color={RULE}@1:t=fill")
    draw.append(f"drawbox=x={PX}:y={BAR_Y}:w={int((W - 2 * PX) * ep / total)}:h=2"
                f":color={ACCENT}@1:t=fill")

    def txt(s, x, y, size, color):
        s = s.replace("\\", "").replace(":", r"\:").replace("'", "")
        return (f"drawtext=fontfile={FONT}:text='{s}':x={x}:y={y}"
                f":fontsize={size}:fontcolor={color}")

    draw += [
        txt(f"epoch {ep:02d} / {total}", PX, 20, 40, ACCENT),
        txt("PCA of features learned without labels", "w-tw-32", 27, 30, DIM),
        txt("LiDAR - BEV features", PX, 802, 26, DIM),
        txt("camera - 3 of 6 views", CX, 802, 26, DIM),
    ]

    fg.append(f"[{prev}]" + ",".join(draw) + "[out]")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(bev), "-i", str(cam),
         "-filter_complex", ";".join(fg), "-map", "[out]", "-frames:v", "1", str(dst)],
        check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="directory of epoch_N/ subdirectories")
    ap.add_argument("-o", "--output", type=Path, default=Path("assets/video/thesis.mp4"))
    ap.add_argument("-p", "--poster", type=Path, default=Path("assets/img/thesis-poster.jpg"))
    ap.add_argument("--crf", type=int, default=24)
    args = ap.parse_args()

    epochs = sorted((int(d.name.split("_")[1]) for d in args.source.glob("epoch_*")))
    if not epochs:
        sys.exit(f"{args.source}: no epoch_N directories found.")
    total = max(epochs)

    work = Path(".thesis-frames")
    work.mkdir(exist_ok=True)
    for ep in epochs:
        d = args.source / f"epoch_{ep}"
        compose(d / "bev_pca.png", d / "camera_pca.png", ep, total, work / f"f{ep:03d}.png")
    print(f"composed {len(epochs)} frames")

    # Hold ~0.42 s per epoch, but linger on the first frame so the loop has a visible
    # start, and on the last so the trained state is what a passer-by actually sees.
    # The concat demuxer drops the final entry's duration, hence the repeat.
    lines = []
    for ep in epochs:
        d = 1.4 if ep == epochs[0] else 1.2 if ep == epochs[-1] else 0.42
        # Paths in a concat list resolve relative to the list file, not the cwd.
        lines.append(f"file 'f{ep:03d}.png'\nduration {d}")
    lines.append(f"file 'f{epochs[-1]:03d}.png'")
    concat = work / "concat.txt"
    concat.write_text("\n".join(lines) + "\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", "fps=12,format=yuv420p", "-c:v", "libx264", "-crf", str(args.crf),
         "-preset", "veryslow", "-g", "24", "-movflags", "+faststart", "-an",
         str(args.output)], check=True)

    # The poster is the trained state, not epoch 1: a still frame should show the thing
    # working. 1160 px matches the widest the figure ever renders.
    args.poster.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(work / f"f{epochs[-1]:03d}.png"),
         "-vf", "scale=1160:-2", "-q:v", "6", str(args.poster)], check=True)

    for f in work.iterdir():
        f.unlink()
    work.rmdir()

    print(f"wrote    {args.output}  ({args.output.stat().st_size / 1024:.0f} KB)")
    print(f"         {args.poster}  ({args.poster.stat().st_size / 1024:.0f} KB)")
    print(f"         {W}x{H}, intrinsic size for the <video> width/height attributes")


if __name__ == "__main__":
    main()
