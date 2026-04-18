#!/usr/bin/env node
/**
 * Fiverr Gig Gallery - Ad-Factory Style (3 frames)
 * Bold, minimal text, high contrast, neon gradients.
 * Fiverr recommended: 1280x769
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const GALLERY_DIR = path.join(__dirname, 'gallery');
const W = 1280, H = 769;

async function main() {
  fs.mkdirSync(GALLERY_DIR, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: H } });

  // ═══ FRAME 1: COVER — "Spy on competitors" ═══
  const p1 = await ctx.newPage();
  await p1.setContent(`<!DOCTYPE html><html><head><style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      width:${W}px; height:${H}px;
      background: #08080f;
      font-family: 'Inter', -apple-system, sans-serif;
      overflow: hidden;
      position: relative;
    }
    /* glow orbs */
    .orb1 { position:absolute; width:500px; height:500px; border-radius:50%;
      background: radial-gradient(circle, rgba(124,92,252,0.35) 0%, transparent 70%);
      top:-100px; left:-100px; }
    .orb2 { position:absolute; width:400px; height:400px; border-radius:50%;
      background: radial-gradient(circle, rgba(255,107,107,0.25) 0%, transparent 70%);
      bottom:-80px; right:-60px; }
    .content {
      position: relative; z-index: 2;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      height: 100%; padding: 2rem;
    }
    .pill {
      background: rgba(124,92,252,0.2); border: 2px solid #7c5cfc;
      border-radius: 50px; padding: 0.5rem 1.8rem;
      font-size: 1rem; font-weight: 700; color: #a78bfa;
      text-transform: uppercase; letter-spacing: 0.15em;
      margin-bottom: 2rem;
    }
    h1 {
      font-size: 4.5rem; font-weight: 900; text-align: center;
      line-height: 1.05; margin-bottom: 1.5rem;
      color: #fff;
    }
    h1 .accent {
      background: linear-gradient(135deg, #7c5cfc, #ff6b6b);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .sub {
      font-size: 1.35rem; color: #888; text-align: center;
      max-width: 650px; margin-bottom: 2.5rem; line-height: 1.4;
    }
    .stats {
      display: flex; gap: 3rem;
    }
    .stat { text-align: center; }
    .stat .num {
      font-size: 3rem; font-weight: 900; color: #7c5cfc;
    }
    .stat .lbl {
      font-size: 0.85rem; color: #666; text-transform: uppercase;
      letter-spacing: 0.1em; margin-top: 0.2rem;
    }
  </style></head><body>
    <div class="orb1"></div><div class="orb2"></div>
    <div class="content">
      <div class="pill">Competitor Intelligence</div>
      <h1>Spy on <span class="accent">Their Funnel.</span><br>Steal What Works.</h1>
      <div class="sub">I analyze years of competitor changes using the Wayback Machine</div>
      <div class="stats">
        <div class="stat"><div class="num">126+</div><div class="lbl">Pages Scanned</div></div>
        <div class="stat"><div class="num">90</div><div class="lbl">Changes Found</div></div>
        <div class="stat"><div class="num">24h</div><div class="lbl">Delivery</div></div>
      </div>
    </div>
  </body></html>`);
  await p1.screenshot({ path: path.join(GALLERY_DIR, 'frame-1-cover.png') });
  console.log('frame 1 done');
  await p1.close();

  // ═══ FRAME 2: WHAT I TRACK — visual grid ═══
  const p2 = await ctx.newPage();
  await p2.setContent(`<!DOCTYPE html><html><head><style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      width:${W}px; height:${H}px;
      background: #08080f;
      font-family: 'Inter', -apple-system, sans-serif;
      overflow: hidden; position: relative;
    }
    .orb { position:absolute; width:600px; height:600px; border-radius:50%;
      background: radial-gradient(circle, rgba(52,211,153,0.2) 0%, transparent 70%);
      top:50%; left:50%; transform:translate(-50%,-50%); }
    .content {
      position: relative; z-index: 2;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      height: 100%; padding: 2rem;
    }
    h2 {
      font-size: 2.8rem; font-weight: 900; color: #fff;
      margin-bottom: 2.5rem; text-align: center;
    }
    h2 .accent { color: #34d399; }
    .grid {
      display: grid; grid-template-columns: 1fr 1fr 1fr;
      gap: 1rem; max-width: 900px; width: 100%;
    }
    .card {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px; padding: 1.5rem;
      text-align: center;
    }
    .card .icon { font-size: 2.2rem; margin-bottom: 0.6rem; }
    .card h3 { font-size: 1.15rem; font-weight: 700; color: #fff; margin-bottom: 0.3rem; }
    .card .tag {
      display: inline-block; font-size: 0.75rem; font-weight: 700;
      padding: 0.2rem 0.6rem; border-radius: 6px; margin-top: 0.3rem;
    }
    .tag-purple { background: rgba(124,92,252,0.25); color: #a78bfa; }
    .tag-green { background: rgba(52,211,153,0.2); color: #34d399; }
    .tag-red { background: rgba(255,107,107,0.2); color: #ff6b6b; }
    .tag-orange { background: rgba(245,158,11,0.2); color: #f59e0b; }
    .tag-blue { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .tag-pink { background: rgba(236,72,153,0.2); color: #f472b6; }
  </style></head><body>
    <div class="orb"></div>
    <div class="content">
      <h2>What I <span class="accent">Track</span></h2>
      <div class="grid">
        <div class="card">
          <div class="icon">&#128200;</div>
          <h3>Headlines</h3>
          <span class="tag tag-purple">H1 &bull; Title &bull; Meta</span>
        </div>
        <div class="card">
          <div class="icon">&#127919;</div>
          <h3>CTAs</h3>
          <span class="tag tag-green">+ Added</span>
          <span class="tag tag-red">- Removed</span>
        </div>
        <div class="card">
          <div class="icon">&#128176;</div>
          <h3>Pricing</h3>
          <span class="tag tag-orange">$49 &rarr; $79</span>
        </div>
        <div class="card">
          <div class="icon">&#9881;&#65039;</div>
          <h3>Tech Stack</h3>
          <span class="tag tag-blue">24+ tools</span>
        </div>
        <div class="card">
          <div class="icon">&#128337;</div>
          <h3>Timeline</h3>
          <span class="tag tag-purple">Year by year</span>
        </div>
        <div class="card">
          <div class="icon">&#128279;</div>
          <h3>Proof Links</h3>
          <span class="tag tag-pink">Wayback URLs</span>
        </div>
      </div>
    </div>
  </body></html>`);
  await p2.screenshot({ path: path.join(GALLERY_DIR, 'frame-2-what-i-track.png') });
  console.log('frame 2 done');
  await p2.close();

  // ═══ FRAME 3: HOW IT WORKS — 3 steps ═══
  const p3 = await ctx.newPage();
  await p3.setContent(`<!DOCTYPE html><html><head><style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      width:${W}px; height:${H}px;
      background: #08080f;
      font-family: 'Inter', -apple-system, sans-serif;
      overflow: hidden; position: relative;
    }
    .orb1 { position:absolute; width:350px; height:350px; border-radius:50%;
      background: radial-gradient(circle, rgba(124,92,252,0.25) 0%, transparent 70%);
      top:30%; left:5%; }
    .orb2 { position:absolute; width:300px; height:300px; border-radius:50%;
      background: radial-gradient(circle, rgba(255,107,107,0.2) 0%, transparent 70%);
      bottom:10%; right:10%; }
    .content {
      position: relative; z-index: 2;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      height: 100%; padding: 2rem;
    }
    h2 {
      font-size: 2.8rem; font-weight: 900; color: #fff;
      margin-bottom: 3rem; text-align: center;
    }
    .steps { display: flex; align-items: center; gap: 1.5rem; }
    .step {
      width: 300px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 20px; padding: 2rem 1.8rem;
      text-align: center; position: relative;
    }
    .step .num {
      position: absolute; top: -20px; left: 50%; transform: translateX(-50%);
      width: 42px; height: 42px; border-radius: 50%;
      background: linear-gradient(135deg, #7c5cfc, #ff6b6b);
      color: #fff; font-weight: 900; font-size: 1.2rem;
      display: flex; align-items: center; justify-content: center;
    }
    .step h3 { font-size: 1.4rem; font-weight: 900; color: #fff; margin: 0.8rem 0 0.4rem; }
    .step p { font-size: 0.95rem; color: #888; line-height: 1.4; }
    .arrow { font-size: 2rem; color: #7c5cfc; font-weight: 900; }
    .badge {
      margin-top: 2.5rem;
      background: linear-gradient(135deg, #7c5cfc, #ff6b6b);
      color: #fff; font-weight: 900; font-size: 1.1rem;
      padding: 0.7rem 2.5rem; border-radius: 50px;
    }
  </style></head><body>
    <div class="orb1"></div><div class="orb2"></div>
    <div class="content">
      <h2>3 Steps. Full Intel.</h2>
      <div class="steps">
        <div class="step">
          <div class="num">1</div>
          <h3>Send URLs</h3>
          <p>Give me 3-10 competitor links</p>
        </div>
        <div class="arrow">&rarr;</div>
        <div class="step">
          <div class="num">2</div>
          <h3>I Analyze</h3>
          <p>Years of Wayback data, scraped and diffed</p>
        </div>
        <div class="arrow">&rarr;</div>
        <div class="step">
          <div class="num">3</div>
          <h3>Get Report</h3>
          <p>HTML + JSON with every change mapped</p>
        </div>
      </div>
      <div class="badge">Starts at $35</div>
    </div>
  </body></html>`);
  await p3.screenshot({ path: path.join(GALLERY_DIR, 'frame-3-how-it-works.png') });
  console.log('frame 3 done');
  await p3.close();

  await browser.close();

  // List output
  console.log('\n── Gallery ──');
  for (const f of fs.readdirSync(GALLERY_DIR).filter(f => f.startsWith('frame-')).sort()) {
    const sz = Math.round(fs.statSync(path.join(GALLERY_DIR, f)).size / 1024);
    console.log(`  ${f} (${sz}KB)`);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
