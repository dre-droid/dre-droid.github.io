# andrea-mastroberti.com

Single-page personal site. Plain HTML, CSS and JS — no framework, no build step,
no `npm install`. Editing a file and pushing is the entire deploy.

```
index.html                  the page
css/main.css                design system + layout
js/main.js                  nav state, lazy video loops, the hero point-cloud viewer
vendor/three.module.min.js  three.js, vendored (no CDN)
assets/                     data, fonts, img, video
scripts/                    asset pipeline
```

## Local preview

```bash
python3 -m http.server 8137
```

<http://127.0.0.1:8137/>. A `file://` open will not work: the viewer fetches the
point cloud over HTTP and ES modules need a real origin.

## Deploy

GitHub Pages, `main` / root. `.nojekyll` is present so Jekyll leaves `assets/`
alone. `git push` and the site rebuilds.

Served at `andrea-mastroberti.com`. The `CNAME` file is what binds the domain —
**do not delete it**; Pages drops back to the `github.io` URL without it. DNS is
at IONOS: four A and four AAAA records on the apex pointing at GitHub's edge,
plus `www` as a CNAME.

## Assets

```bash
# Point cloud -> the compact binary the hero reads
python3 scripts/make_pointcloud.py <scan.bin|.npy|.pcd|.ply> -o assets/data/scene.bin --clip 40

# Thesis figure: one frame per epoch, encoded to a loop
python3 scripts/make_thesis_figure.py <dir of epoch_N/ subdirectories>

# Hero posters (needs a headless Chrome on port 9333 — see the script header)
node scripts/capture-posters.mjs /tmp/hero.png 1440 900 1
```

Video is transcoded with ffmpeg to H.264, `-an`, `+faststart`, `-g 48`.

## Notes

- **Point cloud format.** Quantised to 13 bits, sorted by Morton code so spatial
  neighbours are byte-stream neighbours, then delta + zigzag + varint per axis.
  About 2.4x smaller than raw interleaved 16-bit XYZ.
- **Raw `.bin` stride is inferred, not assumed.** KITTI packs 4 floats per point,
  nuScenes 5, and a file's byte count is usually divisible by both — so the loader
  reads the columns and reports what it chose.
- **`--clip` matters.** A few returns at 90 m stretch the bounding box the viewer
  sizes its camera from, which makes everything else tiny. 40 m keeps ~97% of points.
- **The viewer runs everywhere, phones included.** `prefers-reduced-motion` stops the
  idle rotation but keeps it interactive — the preference is about motion the page
  starts by itself. Rendering pauses when the hero scrolls out of view or the tab hides.
- **Camera framing is aspect-aware:** `frameForAspect()` pulls in and looks down harder
  as the frame narrows, and stops re-framing once dragged.
- **Videos marked `data-autoloop`** load nothing until scrolled near, then autoplay
  muted on loop and pause when they leave the viewport. `play()` waits for
  `readyState >= 3`; calling it earlier makes iOS reject and fall back to a control bar.
- **IBM Plex Mono, self-hosted** (`assets/fonts/`, two woff2 files). Declare it
  `format('woff2')` — the older `woff2-variations` is not reliably accepted.
- **Posters and the share card are captured from the page**, so they carry the real
  type and the real scan. Regenerate them whenever the palette, the scan, the camera
  framing or the hero copy changes; the hero poster must contain the scan and nothing
  else, since it renders behind the hero copy.
