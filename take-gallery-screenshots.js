#!/usr/bin/env node
/**
 * Wayback Revenue Pipeline - Gallery Screenshot Generator
 *
 * Generates Fiverr gig gallery images from HTML reports.
 * Uses Playwright chromium directly (no test runner needed).
 *
 * Usage: node take-gallery-screenshots.js
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const OUTPUT_DIR = path.join(__dirname, 'output');
const GALLERY_DIR = path.join(__dirname, 'gallery');

const NICHE_REPORTS = [
  'saas-project-management-report.html',
  'ai-writing-tools-report.html',
  'email-marketing-platforms-report.html',
  'crm-tools-for-smbs-report.html',
  'landing-page-builders-report.html',
];
const CASE_STUDY = 'case-study-landing-page-builders.html';

// QA results collector
const qaResults = [];

function qa(name, pass, detail = '') {
  qaResults.push({ name, pass, detail });
  const icon = pass ? '✓' : '✗';
  console.log(`  ${icon} ${name}${detail ? ': ' + detail : ''}`);
}

async function main() {
  fs.mkdirSync(GALLERY_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });

  // ─── 1. NICHE REPORT SCREENSHOTS + QA ───────────────────────────────

  for (const report of NICHE_REPORTS) {
    const slug = report.replace('-report.html', '');
    const filePath = path.join(OUTPUT_DIR, report);
    console.log(`\n── ${slug} ──`);

    if (!fs.existsSync(filePath)) {
      console.log(`  SKIPPED: file not found`);
      continue;
    }

    const page = await context.newPage();
    await page.goto(`file://${filePath}`);
    await page.waitForLoadState('domcontentloaded');

    // Hero screenshot (above-the-fold)
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.screenshot({
      path: path.join(GALLERY_DIR, `${slug}-hero.png`),
      clip: { x: 0, y: 0, width: 1280, height: 800 },
    });
    console.log(`  📸 hero screenshot`);

    // Stats grid screenshot
    const statsGrid = page.locator('.stats-grid');
    if (await statsGrid.count() > 0) {
      await statsGrid.scrollIntoViewIfNeeded();
      await statsGrid.screenshot({ path: path.join(GALLERY_DIR, `${slug}-stats.png`) });
      console.log(`  📸 stats grid`);
    }

    // Timeline screenshot (first competitor's timeline)
    const timeline = page.locator('.snapshot-timeline').first();
    if (await timeline.count() > 0) {
      await timeline.scrollIntoViewIfNeeded();
      await timeline.screenshot({ path: path.join(GALLERY_DIR, `${slug}-timeline.png`) });
      console.log(`  📸 timeline`);
    }

    // Tech grid screenshot
    const techGrid = page.locator('.tech-grid').first();
    if (await techGrid.count() > 0) {
      await techGrid.scrollIntoViewIfNeeded();
      await techGrid.screenshot({ path: path.join(GALLERY_DIR, `${slug}-tech.png`) });
      console.log(`  📸 tech grid`);
    }

    // Full page screenshot
    await page.screenshot({
      path: path.join(GALLERY_DIR, `${slug}-full.png`),
      fullPage: true,
    });
    console.log(`  📸 full page`);

    // ── QA CHECKS ──

    // Title
    const title = page.locator('.header h1');
    const titleVisible = (await title.count() > 0) && (await title.isVisible());
    qa(`${slug}: title visible`, titleVisible);

    // Stat cards
    const statCards = page.locator('.stat-card');
    const statCount = await statCards.count();
    qa(`${slug}: stat cards >= 4`, statCount >= 4, `found ${statCount}`);

    // Stat values > 0
    let allStatsPositive = true;
    for (let i = 0; i < statCount; i++) {
      const numEl = statCards.nth(i).locator('.number');
      if (await numEl.count() > 0) {
        const num = await numEl.textContent();
        if (parseInt(num) <= 0) allStatsPositive = false;
      }
    }
    qa(`${slug}: all stats > 0`, allStatsPositive);

    // Competitor cards
    const compCards = page.locator('.competitor-card');
    const compCount = await compCards.count();
    qa(`${slug}: competitors >= 3`, compCount >= 3, `found ${compCount}`);

    // Tech chips
    const techChips = page.locator('.tech-chip');
    const chipCount = await techChips.count();
    qa(`${slug}: tech chips present`, chipCount > 0, `found ${chipCount}`);

    // Snapshot links validity
    const snapshotLinks = page.locator('a.snapshot-link');
    const linkCount = await snapshotLinks.count();
    let badLinks = 0;
    for (let i = 0; i < linkCount; i++) {
      const href = await snapshotLinks.nth(i).getAttribute('href');
      if (!href || !href.startsWith('https://web.archive.org/web/')) badLinks++;
    }
    qa(`${slug}: snapshot links valid`, badLinks === 0, `${linkCount} links, ${badLinks} bad`);

    // Change tags exist
    const changeTags = page.locator('.change-tag');
    const tagCount = await changeTags.count();
    qa(`${slug}: change tags present`, tagCount > 0, `found ${tagCount}`);

    // Dark background (not white)
    const bgColor = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    qa(`${slug}: dark theme`, bgColor !== 'rgb(255, 255, 255)', bgColor);

    // No horizontal overflow
    const hasOverflow = await page.evaluate(() => document.body.scrollWidth > document.body.clientWidth + 10);
    qa(`${slug}: no overflow`, !hasOverflow);

    // Mobile responsive
    await page.setViewportSize({ width: 375, height: 812 });
    const mobileTitle = page.locator('.header h1');
    const mobileVisible = (await mobileTitle.count() > 0) && (await mobileTitle.isVisible());
    qa(`${slug}: mobile title visible`, mobileVisible);

    const mobileOverflow = await page.evaluate(() => document.body.scrollWidth > document.body.clientWidth + 10);
    qa(`${slug}: mobile no overflow`, !mobileOverflow);

    await page.screenshot({
      path: path.join(GALLERY_DIR, `${slug}-mobile.png`),
      clip: { x: 0, y: 0, width: 375, height: 812 },
    });
    console.log(`  📸 mobile`);

    await page.close();
  }

  // ─── 2. CASE STUDY SCREENSHOTS + QA ────────────────────────────────

  console.log(`\n── case study ──`);
  const csPath = path.join(OUTPUT_DIR, CASE_STUDY);
  if (fs.existsSync(csPath)) {
    const page = await context.newPage();
    await page.goto(`file://${csPath}`);
    await page.setViewportSize({ width: 1280, height: 800 });

    await page.screenshot({
      path: path.join(GALLERY_DIR, 'case-study-hero.png'),
      clip: { x: 0, y: 0, width: 1280, height: 800 },
    });
    console.log(`  📸 hero`);

    // Table screenshot
    const tables = page.locator('table');
    if (await tables.count() > 0) {
      await tables.first().scrollIntoViewIfNeeded();
      await tables.first().screenshot({ path: path.join(GALLERY_DIR, 'case-study-findings-table.png') });
      console.log(`  📸 findings table`);
    }

    // CTA section
    const cta = page.locator('.cta-section');
    if (await cta.count() > 0) {
      await cta.scrollIntoViewIfNeeded();
      await cta.screenshot({ path: path.join(GALLERY_DIR, 'case-study-cta.png') });
      console.log(`  📸 cta`);
    }

    // Full page
    await page.screenshot({ path: path.join(GALLERY_DIR, 'case-study-full.png'), fullPage: true });
    console.log(`  📸 full page`);

    // QA checks
    const badge = page.locator('.badge');
    qa('case-study: badge visible', (await badge.count() > 0) && (await badge.isVisible()));

    const h1 = page.locator('h1');
    qa('case-study: h1 visible', (await h1.count() > 0) && (await h1.isVisible()));

    const stats = page.locator('.stat');
    qa('case-study: stats >= 4', (await stats.count()) >= 4, `found ${await stats.count()}`);

    const findings = page.locator('.finding');
    qa('case-study: findings >= 3', (await findings.count()) >= 3, `found ${await findings.count()}`);

    const tableCount = await tables.count();
    qa('case-study: tables >= 2', tableCount >= 2, `found ${tableCount}`);

    const ctaBtn = page.locator('.cta-btn');
    qa('case-study: CTA button visible', (await ctaBtn.count() > 0) && (await ctaBtn.isVisible()));

    await page.close();
  }

  // ─── 3. GIG GALLERY COMPOSITE IMAGES ──────────────────────────────

  console.log(`\n── gig gallery composites ──`);

  // Cover image
  const coverPage = await context.newPage();
  await coverPage.setViewportSize({ width: 1280, height: 800 });
  await coverPage.setContent(`
  <!DOCTYPE html><html><head><style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      width: 1280px; height: 800px; background: #0f0f13;
      color: #e4e4f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 3rem;
    }
    .badge {
      display: inline-block; background: rgba(124,92,252,0.15); border: 1px solid #7c5cfc;
      border-radius: 24px; padding: 0.4rem 1.2rem; font-size: 0.9rem; color: #7c5cfc;
      text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 1.5rem;
    }
    h1 {
      font-size: 3rem; text-align: center;
      background: linear-gradient(135deg, #7c5cfc, #ff6b6b);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      line-height: 1.2; margin-bottom: 1.5rem; max-width: 900px;
    }
    .subtitle { color: #8888aa; font-size: 1.2rem; text-align: center; max-width: 700px; margin-bottom: 2.5rem; }
    .stats { display: flex; gap: 2rem; margin-bottom: 2.5rem; }
    .stat-box {
      background: #1a1a24; border: 1px solid #2e2e4a; border-radius: 12px;
      padding: 1.2rem 2rem; text-align: center;
    }
    .stat-box .num { font-size: 2.2rem; font-weight: 700; color: #7c5cfc; }
    .stat-box .label { color: #8888aa; font-size: 0.85rem; }
    .tools { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; max-width: 800px; }
    .tool {
      background: #24243a; border: 1px solid #2e2e4a; padding: 0.3rem 0.8rem;
      border-radius: 20px; font-size: 0.8rem; color: #e4e4f0;
    }
  </style></head><body>
    <div class="badge">Competitor Intelligence Report</div>
    <h1>See How Your Competitors Changed Their Funnel</h1>
    <div class="subtitle">Automated Wayback Machine analysis: headlines, CTAs, pricing, and tech stack evolution over years</div>
    <div class="stats">
      <div class="stat-box"><div class="num">126</div><div class="label">Pages Analyzed</div></div>
      <div class="stat-box"><div class="num">90</div><div class="label">Changes Detected</div></div>
      <div class="stat-box"><div class="num">21</div><div class="label">Competitors Tracked</div></div>
      <div class="stat-box"><div class="num">24+</div><div class="label">Tools Detected</div></div>
    </div>
    <div class="tools">
      <div class="tool">Google Analytics</div><div class="tool">HubSpot</div>
      <div class="tool">Stripe</div><div class="tool">Intercom</div>
      <div class="tool">Hotjar</div><div class="tool">Facebook Pixel</div>
      <div class="tool">Next.js</div><div class="tool">Segment</div>
      <div class="tool">Drift</div><div class="tool">Zendesk</div>
      <div class="tool">WordPress</div><div class="tool">Calendly</div>
    </div>
  </body></html>`);
  await coverPage.screenshot({ path: path.join(GALLERY_DIR, 'gig-cover.png') });
  console.log(`  📸 gig cover`);
  await coverPage.close();

  // Process flow image
  const flowPage = await context.newPage();
  await flowPage.setViewportSize({ width: 1280, height: 600 });
  await flowPage.setContent(`
  <!DOCTYPE html><html><head><style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      width: 1280px; height: 600px; background: #0f0f13;
      color: #e4e4f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 3rem;
    }
    h2 { font-size: 1.8rem; color: #7c5cfc; margin-bottom: 3rem; }
    .flow { display: flex; align-items: center; gap: 1.5rem; }
    .step {
      background: #1a1a24; border: 2px solid #2e2e4a; border-radius: 16px;
      padding: 2rem 2.5rem; text-align: center; width: 280px;
    }
    .step .num { font-size: 2.5rem; font-weight: 700; color: #7c5cfc; margin-bottom: 0.5rem; }
    .step h3 { font-size: 1.1rem; margin-bottom: 0.5rem; }
    .step p { color: #8888aa; font-size: 0.85rem; line-height: 1.5; }
    .arrow { font-size: 2rem; color: #7c5cfc; }
    .badge-green {
      margin-top: 2.5rem; background: rgba(52,211,153,0.15); border: 1px solid #34d399;
      color: #34d399; padding: 0.5rem 1.5rem; border-radius: 24px; font-size: 0.95rem;
    }
  </style></head><body>
    <h2>How It Works</h2>
    <div class="flow">
      <div class="step"><div class="num">1</div><h3>Send URLs</h3><p>Give me 3-10 competitor URLs you want analyzed</p></div>
      <div class="arrow">&#8594;</div>
      <div class="step"><div class="num">2</div><h3>Deep Analysis</h3><p>Pipeline pulls years of Wayback snapshots, extracts data, detects changes</p></div>
      <div class="arrow">&#8594;</div>
      <div class="step"><div class="num">3</div><h3>Intel Report</h3><p>Professional report with timeline, diffs, tech stack, and strategy insights</p></div>
    </div>
    <div class="badge-green">Delivered in 24 hours</div>
  </body></html>`);
  await flowPage.screenshot({ path: path.join(GALLERY_DIR, 'gig-process-flow.png') });
  console.log(`  📸 process flow`);
  await flowPage.close();

  // What-you-get image
  const whatPage = await context.newPage();
  await whatPage.setViewportSize({ width: 1280, height: 720 });
  await whatPage.setContent(`
  <!DOCTYPE html><html><head><style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      width: 1280px; height: 720px; background: #0f0f13;
      color: #e4e4f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 3rem;
    }
    h2 { font-size: 2rem; color: #7c5cfc; margin-bottom: 2.5rem; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; max-width: 900px; }
    .item {
      background: #1a1a24; border: 1px solid #2e2e4a; border-radius: 12px;
      padding: 1.25rem 1.5rem; display: flex; align-items: flex-start; gap: 1rem;
    }
    .icon { font-size: 1.5rem; min-width: 2rem; }
    .item h3 { font-size: 1rem; margin-bottom: 0.25rem; }
    .item p { color: #8888aa; font-size: 0.85rem; }
    .tag-changed { background: rgba(124,92,252,0.15); color: #7c5cfc; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .tag-added { background: rgba(52,211,153,0.15); color: #34d399; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .tag-tech { background: rgba(245,158,11,0.15); color: #f59e0b; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .tag-removed { background: rgba(255,107,107,0.15); color: #ff6b6b; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
  </style></head><body>
    <h2>What You Get</h2>
    <div class="grid">
      <div class="item"><div class="icon">&#128200;</div><div><h3>Headline Evolution</h3><p>Track how competitors changed their H1, title, and meta over time</p></div></div>
      <div class="item"><div class="icon">&#128073;</div><div><h3>CTA Tracking</h3><p><span class="tag-added">+ Sign Up Free</span> <span class="tag-removed">- Start Trial</span></p></div></div>
      <div class="item"><div class="icon">&#128176;</div><div><h3>Pricing Signals</h3><p>Visible prices that appeared or disappeared on their pages</p></div></div>
      <div class="item"><div class="icon">&#9881;&#65039;</div><div><h3>Tech Stack (24+ tools)</h3><p><span class="tag-tech">HubSpot</span> <span class="tag-tech">Stripe</span> <span class="tag-tech">Hotjar</span> <span class="tag-tech">Intercom</span></p></div></div>
      <div class="item"><div class="icon">&#128337;</div><div><h3>Change Timeline</h3><p><span class="tag-changed">Title Changed</span> <span class="tag-changed">Content expanded by 276 words</span></p></div></div>
      <div class="item"><div class="icon">&#128279;</div><div><h3>Wayback Links</h3><p>Clickable links to view every analyzed snapshot yourself</p></div></div>
      <div class="item"><div class="icon">&#128196;</div><div><h3>HTML Report</h3><p>Professional dark-theme report, ready to share with your team</p></div></div>
      <div class="item"><div class="icon">&#128190;</div><div><h3>Raw JSON Data</h3><p>Full structured data export for your own analysis or tools</p></div></div>
    </div>
  </body></html>`);
  await whatPage.screenshot({ path: path.join(GALLERY_DIR, 'gig-what-you-get.png') });
  console.log(`  📸 what you get`);
  await whatPage.close();

  await browser.close();

  // ─── 4. QA SUMMARY ────────────────────────────────────────────────

  console.log(`\n${'═'.repeat(50)}`);
  console.log(`QA SUMMARY`);
  console.log(`${'═'.repeat(50)}`);
  const passed = qaResults.filter(r => r.pass).length;
  const failed = qaResults.filter(r => !r.pass).length;
  console.log(`Total: ${qaResults.length} | Passed: ${passed} | Failed: ${failed}`);

  if (failed > 0) {
    console.log(`\nFAILED:`);
    qaResults.filter(r => !r.pass).forEach(r => {
      console.log(`  ✗ ${r.name}${r.detail ? ': ' + r.detail : ''}`);
    });
  }

  // List all gallery files
  console.log(`\n── Gallery Files ──`);
  const files = fs.readdirSync(GALLERY_DIR).sort();
  files.forEach(f => {
    const stat = fs.statSync(path.join(GALLERY_DIR, f));
    console.log(`  ${f} (${Math.round(stat.size / 1024)}KB)`);
  });
  console.log(`\nTotal: ${files.length} images in ${GALLERY_DIR}`);

  process.exit(failed > 0 ? 1 : 0);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
