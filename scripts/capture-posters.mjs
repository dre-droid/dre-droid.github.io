import { connect, sleep } from './cdp.mjs';
import { writeFileSync } from 'node:fs';

// Regenerate a hero poster from the live viewer, with everything but the scan hidden.
//
//   python3 -m http.server 8137
//   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
//     --remote-debugging-port=9333 --user-data-dir=/tmp/poster-profile \
//     --use-angle=swiftshader --enable-unsafe-swiftshader about:blank &
//   node scripts/capture-posters.mjs /tmp/hero.png 1440 900 1     # desktop
//   node scripts/capture-posters.mjs /tmp/hero-m.png 390 844 2    # mobile
//   ffmpeg -y -i /tmp/hero.png   -vf scale=1500:-2 -q:v 5 assets/img/pointcloud-poster.jpg
//   ffmpeg -y -i /tmp/hero-m.png -vf scale=780:-2  -q:v 5 assets/img/pointcloud-poster-mobile.jpg
//
// The swiftshader flags matter: without a GL backend the canvas captures blank and
// you get a poster of nothing. The script prints the renderer so you can check.
//
// Why not canvas.toDataURL(): it returns blank on a WebGL canvas unless
// preserveDrawingBuffer is on, and enabling that taxes every visitor to serve a
// build step. So the poster comes off a composited page screenshot instead.
const [out, w, h, scale] = process.argv.slice(2);
const c = await connect();
await c.send('Page.enable'); await c.send('Runtime.enable');
await c.send('Emulation.setDeviceMetricsOverride',
  { width: +w, height: +h, deviceScaleFactor: +scale, mobile: +w < 720 });
await c.send('Page.navigate', { url: 'http://127.0.0.1:8137/' });
await sleep(1500);

const gl = await c.send('Runtime.evaluate', { returnByValue: true, expression:
  `(()=>{const cv=document.createElement('canvas');
    const g=cv.getContext('webgl2')||cv.getContext('webgl');
    return g ? g.getParameter(g.RENDERER) : 'NO WEBGL';})()` });
console.log('renderer:', gl.result.value);

// Wait for the cloud to fetch, decode and paint, then let the idle spin settle
// somewhere that isn't the exact starting azimuth.
await sleep(6000);

const r = await c.send('Runtime.evaluate', { returnByValue: true, expression: `(()=>{
  const cv = document.querySelector('.hero__canvas');
  // Everything that must NOT be baked in: the copy and nav that sit over the hero,
  // the caption, the scrim (it is re-applied over the poster at runtime, so baking
  // it in darkens the hero twice), and the old poster showing through the canvas'
  // transparent background — which is how the stale text got in there to begin with.
  const s = document.createElement('style');
  s.textContent = \`.topnav, .hero__body, .hero__vizlabel, .hero__poster, .skip-link
                     { visibility: hidden !important; }
                     .hero__viz::after { display: none !important; }\`;
  document.head.appendChild(s);
  const viz = document.querySelector('.hero__viz');
  const b = viz.getBoundingClientRect();
  return JSON.stringify({
    canvasOpacity: getComputedStyle(cv).opacity,
    clip: { x: b.x + scrollX, y: b.y + scrollY, width: b.width, height: b.height },
  });})()` });
const { canvasOpacity, clip } = JSON.parse(r.result.value);
console.log('canvas opacity:', canvasOpacity, '(1 means the viewer is live, 0 means poster-only)');
await sleep(400);

const { data } = await c.send('Page.captureScreenshot',
  { format: 'png', clip: { ...clip, scale: +scale }, captureBeyondViewport: true });
writeFileSync(out, Buffer.from(data, 'base64'));
console.log('wrote', out);
c.close(); process.exit(0);
