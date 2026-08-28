/* ============================================================
   Andrea Mastroberti — site behaviour
   Two things happen here: the nav gets a border once you scroll,
   and the hero point cloud loads (only where it's worth loading).
   ============================================================ */

/* Browsers restore the previous scroll position on reload. On a single page that
   drops you back into the middle of a section with no context — refreshing should
   put you at the top, unless a #section link asked for somewhere specific. */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
if (!location.hash) addEventListener('load', () => scrollTo(0, 0));

/* ---------- nav ---------- */
function initNav() {
  const nav = document.querySelector('.topnav');
  if (!nav) return;
  const sync = () => nav.classList.toggle('is-scrolled', window.scrollY > 24);
  addEventListener('scroll', sync, { passive: true });
  sync();
}

/* ---------- looping videos ----------
   Marked-up with data-src rather than src so nothing downloads until the section
   is actually approached — these files are megabytes and most visitors never
   reach them. Playback pauses off-screen for the same reason the point cloud does. */
function initVideos() {
  const vids = [...document.querySelectorAll('video[data-autoloop]')];
  if (!vids.length) return;

  /* Poster can't be made responsive in CSS, so swap it here when a portrait
     variant exists and the viewport is narrow. */
  vids.forEach((v) => {
    if (v.dataset.posterMobile && matchMedia('(max-width: 720px)').matches) {
      v.poster = v.dataset.posterMobile;
    }
  });

  /* A video either carries its URL in data-src (single file) or in one or more
     <source data-src> children with media queries (responsive — the browser picks
     the matching one, e.g. portrait loop on mobile, landscape on desktop). */
  const load = (v) => {
    let fresh = false;
    const sources = [...v.querySelectorAll('source[data-src]')];
    if (sources.length) {
      sources.forEach((s) => { if (!s.src) { s.src = s.dataset.src; fresh = true; } });
    } else if (!v.src && v.dataset.src) {
      v.src = v.dataset.src;
      fresh = true;
    }
    /* Only on first load: mobile autoplay is stricter than desktop — iOS Safari
       wants `muted` and `playsInline` as live properties at the moment of play(),
       not just as markup attributes, and an explicit load() so the fresh src
       starts buffering instead of sitting at preload="none". Re-running load() on
       every re-entry would re-buffer a video that is already fetched. */
    if (fresh) {
      v.muted = true;
      v.playsInline = true;
      v.load();
    }
  };

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    // Motion is unwelcome: hand over the controls and let them choose. Drop the
    // native autoplay flag too, or the browser will play despite the preference.
    vids.forEach((v) => { v.removeAttribute('autoplay'); v.removeAttribute('loop'); v.controls = true; load(v); });
    return;
  }

  /* Which videos are currently meant to be playing — a video can become ready
     long after it scrolled back out of view, and it must not start then. */
  const wanted = new WeakSet();

  /* play() must not be called until the element actually has data. load() only
     *starts* asynchronous resource selection, so calling play() straight after it
     is a race: desktop Chrome tolerates it, iOS Safari rejects. That rejection
     then handed the video a control bar — which is why iOS showed its native
     player over a video that was supposed to be autoplaying. */
  const start = (v) => {
    const attempt = () => {
      if (!wanted.has(v)) return;
      v.play().catch((err) => {
        // AbortError is our own pause() interrupting a pending play() — not a refusal.
        if (!err || err.name === 'AbortError') return;
        // A real block (iOS Low Power Mode, data saver): offer the controls instead.
        v.controls = true;
      });
    };
    if (v.readyState >= 3) attempt();                              // HAVE_FUTURE_DATA
    else v.addEventListener('canplay', attempt, { once: true });
  };

  const io = new IntersectionObserver((entries) => {
    for (const { target: v, isIntersecting } of entries) {
      if (isIntersecting) {
        wanted.add(v);
        load(v);
        start(v);
      } else {
        wanted.delete(v);
        if (!v.paused) v.pause();
      }
    }
  }, { rootMargin: '300px 0px', threshold: 0.2 });

  vids.forEach((v) => io.observe(v));
}

/* ---------- point cloud hero ---------- */

const MAGIC = 0x32444350; // "PCD2" little-endian
const HEADER = 36;

/* The floor of this ramp is deliberately well clear of the page background. In a
   real driving sweep almost everything sits in a ~4 m band — the road surface alone
   is ~40% of the returns — so a near-black low end renders most of the scan
   invisible. Ground reads as a calm slate blue; height lifts it through teal to the
   accent, so vertical structure (facades, poles, vehicles) is what stands out. */
const RAMP = [
  [0.00, 0x2c, 0x4a, 0x6b],
  [0.28, 0x2f, 0x7d, 0x8d],
  [0.52, 0x38, 0xb0, 0x9b],
  [0.76, 0x6e, 0xe7, 0xc7],
  [1.00, 0xf0, 0xf5, 0xcc],
];

function rampColor(t, out, i) {
  let a = RAMP[0], b = RAMP[RAMP.length - 1];
  for (let k = 0; k < RAMP.length - 1; k++) {
    if (t >= RAMP[k][0] && t <= RAMP[k + 1][0]) { a = RAMP[k]; b = RAMP[k + 1]; break; }
  }
  const f = b[0] === a[0] ? 0 : (t - a[0]) / (b[0] - a[0]);
  out[i]     = (a[1] + (b[1] - a[1]) * f) / 255;
  out[i + 1] = (a[2] + (b[2] - a[2]) * f) / 255;
  out[i + 2] = (a[3] + (b[3] - a[3]) * f) / 255;
}

/** Decode the PCD2 container written by scripts/pcd.py.
 *  Each axis is a plane of zigzag varint deltas over Morton-sorted points; point
 *  order is meaningless in a cloud, so we never undo the sort. */
function decodeCloud(buffer) {
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== MAGIC) throw new Error('not a PCD2 cloud');

  const count = view.getUint32(4, true);
  const bits = view.getUint8(8);
  const lo = [12, 16, 20].map((o) => view.getFloat32(o, true));
  const hi = [24, 28, 32].map((o) => view.getFloat32(o, true));

  const span = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
  const scale = (1 << bits) - 1;

  const bytes = new Uint8Array(buffer);
  let off = HEADER;

  const axis = [new Int32Array(count), new Int32Array(count), new Int32Array(count)];
  for (let a = 0; a < 3; a++) {
    const out = axis[a];
    let acc = 0;
    for (let i = 0; i < count; i++) {
      let raw = 0, shift = 0, b;
      do {
        b = bytes[off++];
        raw |= (b & 0x7f) << shift;
        shift += 7;
      } while (b & 0x80);
      acc += (raw >>> 1) ^ -(raw & 1);   // zigzag → signed
      out[i] = acc;
    }
  }

  const positions = new Float32Array(count * 3);
  const ups = new Float32Array(count);

  /* Source is z-up (LiDAR convention); three.js is y-up, so swap on the way in
     and centre the cloud on the origin as we go. */
  const mid = [lo[0] + span[0] / 2, lo[1] + span[1] / 2, lo[2] + span[2] / 2];

  for (let i = 0; i < count; i++) {
    const x = lo[0] + (axis[0][i] / scale) * span[0];
    const y = lo[1] + (axis[1][i] / scale) * span[1];
    const z = lo[2] + (axis[2][i] / scale) * span[2];
    positions[i * 3]     = x - mid[0];
    positions[i * 3 + 1] = z - mid[2];
    positions[i * 3 + 2] = y - mid[1];
    ups[i] = z;
  }

  /* Clamp the colour range to the 2nd–98th percentile so a single stray
     return above the rooflines doesn't flatten the whole ramp. */
  const sorted = Float32Array.from(ups).sort();
  const cLo = sorted[Math.floor(count * 0.02)];
  const cHi = sorted[Math.floor(count * 0.98)];
  const cSpan = cHi - cLo || 1;

  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    rampColor(Math.min(1, Math.max(0, (ups[i] - cLo) / cSpan)), colors, i * 3);
  }

  const radius = Math.hypot(span[0], span[1], span[2]) / 2;
  return { positions, colors, count, radius };
}

async function initHero() {
  const host = document.getElementById('hero-viz');
  const canvas = host?.querySelector('.hero__canvas');
  if (!host || !canvas) return;

  /* The viewer runs everywhere, phones included: a 34k-point cloud is well within
     a modern handset, and the hero is the one thing here worth the budget.
     prefers-reduced-motion suppresses the idle rotation but does NOT remove the
     viewer — the preference is about motion the page starts on its own, and a drag
     is the visitor's own doing. Killing interaction outright also silently made the
     hero static for the many people who leave iOS "Reduce Motion" on. */
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const small = matchMedia('(max-width: 720px)').matches;

  const src = host.dataset.cloud;
  if (!src) return;

  let THREE, cloud;
  try {
    [THREE, cloud] = await Promise.all([
      import('../vendor/three.module.min.js'),
      fetch(src).then((r) => {
        if (!r.ok) throw new Error(`${src}: HTTP ${r.status}`);
        return r.arrayBuffer();
      }).then(decodeCloud),
    ]);
  } catch (err) {
    console.warn('Point cloud unavailable, keeping poster.', err);
    return;
  }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (err) {
    console.warn('WebGL unavailable, keeping poster.', err);
    return;
  }
  renderer.setClearAlpha(0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(52, 1, 0.5, 4000);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(cloud.positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(cloud.colors, 3));

  const points = new THREE.Points(geometry, new THREE.PointsMaterial({
    size: cloud.radius * 0.0052,
    sizeAttenuation: true,
    vertexColors: true,
    transparent: true,
    opacity: 0.95,
    depthWrite: false,
  }));
  scene.add(points);

  /* ---- orbit state (hand-rolled: we only need azimuth, elevation, damping) ----
     A driving sweep is mostly ground plane, so the camera looks down on it at ~26°:
     low enough that the scan still bleeds off the frame edges, high enough to read
     the concentric scan rings and the shadows objects cast through them. Nearly
     edge-on (the framing a facade-heavy scene wants) flattens all of that away. */
  let dist = cloud.radius * 0.82;
  let azimuth = 0.6, elevation = 0.46;
  let vAz = 0, vEl = 0;
  let dragging = false, lastX = 0, lastY = 0, idleSpin = !reducedMotion;
  let touched = false;   // once the viewer drags, stop re-framing under them

  /* A sweep is far wider than it is tall, so in a narrow viewport the horizontal
     FOV runs out first and leaves dead space above and below. Pulling in and
     looking down harder makes the ground plane project rounder, which fills a
     tall frame instead of floating in the middle of it. */
  function frameForAspect(aspect) {
    const tight = Math.min(1, Math.max(0, (1.5 - aspect) / 0.9));
    dist = cloud.radius * (0.82 - 0.20 * tight);
    if (!touched) elevation = 0.46 + 0.34 * tight;
  }

  const EL_MIN = 0.08, EL_MAX = 1.05;
  /* Radians per SECOND, not per frame — per-frame drift runs at double speed on a
     120 Hz display. One revolution takes ~21 s. The earlier value worked out to
     ~7°/s, which is invisible here: a sweep is concentric rings about the sensor,
     so it is very nearly symmetric under exactly this rotation and only the distant
     structures give the motion away. It has to be quick enough for those to read. */
  const SPIN_RATE = 0.26;   // ~24 s per revolution
  const DAMP_PER_S = 0.0066;   // matches the old 0.92/frame at 60 fps
  const RESUME_MS = 2500;      // idle before the drift starts up again

  let resumeTimer = 0;
  function resumeIdleSoon() {
    clearTimeout(resumeTimer);
    if (reducedMotion) return;        // the one case that must stay still
    resumeTimer = setTimeout(() => { idleSpin = true; }, RESUME_MS);
  }

  /* Take the gesture outright: with pan-y the browser stole vertical drags for
     scrolling, so the scan could only be spun on one axis and felt like it was
     fighting the page. The band is under half the viewport, so there is always
     page below it to scroll on. pointerEvents is enabled only here — a canvas that
     never initialised must not sit on top of the page eating touches. */
  canvas.style.touchAction = 'none';
  canvas.style.pointerEvents = 'auto';
  canvas.addEventListener('pointerdown', (e) => {
    dragging = true; idleSpin = false; touched = true;
    clearTimeout(resumeTimer);
    lastX = e.clientX; lastY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
    canvas.style.cursor = 'grabbing';
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    vAz -= (e.clientX - lastX) * 0.0045;
    vEl -= (e.clientY - lastY) * 0.0035;
    lastX = e.clientX; lastY = e.clientY;
  });
  const release = () => {
    dragging = false;
    canvas.style.cursor = 'grab';
    resumeIdleSoon();
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.style.cursor = 'grab';

  function resize() {
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, small ? 1.75 : 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    frameForAspect(camera.aspect);
    camera.updateProjectionMatrix();
  }
  addEventListener('resize', resize, { passive: true });
  resize();

  /* Stop drawing when the hero is off-screen or the tab is hidden.
     A background canvas spinning at 60fps is a battery leak, not a feature. */
  let onScreen = true;
  new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; },
    { threshold: 0 }).observe(host);

  let frame = 0, prevT = 0;
  function tick(now) {
    frame = requestAnimationFrame(tick);
    if (!onScreen || document.hidden) { prevT = now; return; }

    /* Clamped so a backgrounded tab returning after a long gap doesn't jump. */
    const dt = prevT ? Math.min((now - prevT) / 1000, 0.05) : 0.016;
    prevT = now;

    azimuth += vAz + (idleSpin ? SPIN_RATE * dt : 0);
    elevation = Math.min(EL_MAX, Math.max(EL_MIN, elevation + vEl));
    const damp = Math.pow(DAMP_PER_S, dt);
    vAz *= damp;
    vEl *= damp;

    place();
    renderer.render(scene, camera);
  }

  /* Put the camera on its orbit. Kept out of tick() so the very first paint can use
     it too — rendering before the camera is placed leaves it at the origin, inside
     the cloud, which flashed a ground-level view on every load. */
  function place() {
    const cosEl = Math.cos(elevation);
    camera.position.set(
      Math.sin(azimuth) * cosEl * dist,
      Math.sin(elevation) * dist,
      Math.cos(azimuth) * cosEl * dist,
    );
    camera.lookAt(0, cloud.radius * 0.04, 0);
  }

  place();
  renderer.render(scene, camera);
  host.classList.add('is-live');
  frame = requestAnimationFrame(tick);

  addEventListener('pagehide', () => cancelAnimationFrame(frame));
}

/* ---------------------------------------------------------------------------
   Language toggle

   English is the language on every load. No navigator.language sniffing, no
   geo lookup, no stored preference — switching is an explicit act, and a
   reload starts from English again.

   Both languages live in the DOM and CSS hides one (see `:root[data-lang]`),
   so this only flips an attribute. The exceptions are aria-labels, which
   cannot be duplicated as elements; those carry a `data-aria-it` twin.
--------------------------------------------------------------------------- */
function initLang() {
  const btn = document.querySelector('[data-lang-toggle]');
  if (!btn) return;
  const root = document.documentElement;
  const labelled = [...document.querySelectorAll('[data-aria-it]')];
  labelled.forEach((el) => { el.dataset.ariaEn = el.getAttribute('aria-label') || ''; });

  function apply(lang) {
    root.dataset.lang = lang;
    root.lang = lang;                       // so screen readers switch voice
    btn.setAttribute('aria-label',
      lang === 'en' ? "Passa all'italiano" : 'Switch to English');
    labelled.forEach((el) => {
      el.setAttribute('aria-label', lang === 'it' ? el.dataset.ariaIt : el.dataset.ariaEn);
    });
  }

  btn.hidden = false;                       // only now is the control functional
  btn.addEventListener('click', () => {
    apply(root.dataset.lang === 'it' ? 'en' : 'it');
  });
}

initNav();
initVideos();
initHero();
initLang();
