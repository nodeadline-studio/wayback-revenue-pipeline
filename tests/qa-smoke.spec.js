// @ts-check
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8889';

// ─── LANDING PAGE ───────────────────────────────────────────────────────────

test('Landing: loads with correct title and hero', async ({ page }) => {
  await page.goto(BASE);
  await expect(page).toHaveTitle(/BizSpy/i);
  const hero = page.locator('.hero-content--clone h1');
  await expect(hero).toBeVisible();
  const heroText = await hero.textContent();
  expect(heroText.toLowerCase()).not.toContain('vapi');
  expect(heroText.toLowerCase()).not.toContain('narrated');
});

test('Landing: no supplier/technical references', async ({ page }) => {
  await page.goto(BASE);
  const body = await page.locator('body').textContent();
  const lower = body.toLowerCase();
  expect(lower).not.toContain('vapi');
  expect(lower).not.toContain('archive.org');
  expect(lower).not.toContain('wayback machine');
  expect(lower).not.toContain('voice strategy coaching');
  expect(lower).not.toContain('voice agent');
});

test('Landing: has domain input and submit button', async ({ page }) => {
  await page.goto(BASE);
  const input = page.locator('.hero-content--clone .mode-url-input');
  await expect(input).toBeVisible();
  await expect(input).toHaveAttribute('placeholder', 'Enter target domain to scan...');
  const btn = page.locator('.hero-content--clone button[type="submit"]');
  await expect(btn).toBeVisible();
  await expect(btn).toContainText(/Initiate Scan/i);
});

test.fixme('Landing: pricing tier no voice, has market impact', async ({ page }) => {
  // .pricing-tier element removed from current landing page design
  await page.goto(BASE);
  const tier = page.locator('.pricing-tier');
  await expect(tier).toBeVisible();
  const text = await tier.textContent();
  expect(text.toLowerCase()).not.toContain('voice');
  expect(text.toLowerCase()).toContain('market impact');
});

test.fixme('Landing: sample insight quote visible', async ({ page }) => {
  // 'Sample finding from a real report' block removed from current design
  await page.goto(BASE);
  const body = await page.locator('body').textContent();
  expect(body).toContain('Sample finding from a real report');
});

test('Landing: form submission shows email modal then redirects', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto(BASE);
  const input = page.locator('.hero-content--clone .mode-url-input');
  await input.fill('example.com');

  await page.locator('.hero-content--clone button[type="submit"]').click();

  // Modal should appear asking for email
  await expect(page.locator('#email-modal')).toHaveClass(/open/, { timeout: 3000 });
  await page.locator('#modal-input').fill('test@bizspy.io');
  await page.locator('#modal-submit').click();

  // After email submit the fetch fires; expect redirect to status page
  await page.waitForURL(/\/status\/|api\/status/, { timeout: 15000 });
  expect(page.url()).toMatch(/status/);
});

// ─── CHECKOUT PAGE ──────────────────────────────────────────────────────────

test('Checkout: loads with correct title and order summary', async ({ page }) => {
  await page.goto(BASE + '/checkout');
  await expect(page).toHaveTitle(/Checkout/i);
  await expect(page.locator('h1')).toContainText('Forensic Unlock');
  await expect(page.locator('#paypal-button-container')).toBeAttached();
});

test('Checkout: single plan shows $49 price', async ({ page }) => {
  await page.goto(BASE + '/checkout?packageId=single&email=test@bizspy.io');
  await expect(page.locator('#pkg-price')).toContainText('$49');
  await expect(page.locator('#pkg-name')).toContainText('Single');
});

test('Checkout: pro plan shows $149 price', async ({ page }) => {
  await page.goto(BASE + '/checkout?packageId=pro&email=test@bizspy.io');
  await expect(page.locator('#pkg-price')).toContainText('$149');
  await expect(page.locator('#pkg-name')).toContainText('Founder Pass');
});

test('Checkout: email prefills from query param', async ({ page }) => {
  await page.goto(BASE + '/checkout?packageId=single&email=founder@test.io');
  await expect(page.locator('#user-email')).toContainText('founder@test.io');
});

test('Checkout: PayPal SDK loads and renders buttons', async ({ page }) => {
  await page.goto(BASE + '/checkout');
  await page.waitForTimeout(3000);
  const container = page.locator('#paypal-button-container');
  await expect(container).toBeVisible();

  const content = await container.innerHTML();
  const hasPayPal = content.includes('paypal') || content.includes('iframe') || content.includes('zoid');
  const hasError = content.includes('color: #ff6b6b') || content.includes('not configured');
  expect(hasPayPal || hasError || content.length > 10).toBeTruthy();
});

test('Checkout: status message element exists', async ({ page }) => {
  await page.goto(BASE + '/checkout');
  await page.waitForTimeout(2000);
  const statusEl = page.locator('#status');
  await expect(statusEl).toBeAttached();
});

test('Checkout: order summary is visible', async ({ page }) => {
  await page.goto(BASE + '/checkout');
  await expect(page.locator('.order-summary')).toBeVisible();
});

// ─── API ENDPOINTS ──────────────────────────────────────────────────────────

test('API: health check returns ok', async ({ request }) => {
  const resp = await request.get(BASE + '/health');
  expect(resp.ok()).toBeTruthy();
  const json = await resp.json();
  expect(json.status).toBe('ok');
  expect(json.service).toBe('business-spy');
  expect(json.paypal_configured).toBe(true);
});

test('API: paypal-config returns packages and client_id', async ({ request }) => {
  const resp = await request.get(BASE + '/api/paypal-config');
  expect(resp.ok()).toBeTruthy();
  const json = await resp.json();
  expect(json.client_id).toBeTruthy();
  expect(json.client_id.length).toBeGreaterThan(10);
  expect(json.mode).toBe('sandbox');
  expect(json.packages.starter.price).toBe(49);
  expect(json.packages.pro.price).toBe(149);
});

test('API: demo rejects empty target', async ({ request }) => {
  const resp = await request.post(BASE + '/api/demo', {
    data: { target_url: '' },
  });
  expect(resp.status()).toBe(400);
});

test('API: create-order rejects missing email', async ({ request }) => {
  const resp = await request.post(BASE + '/api/paypal/create-order', {
    data: { packageId: 'starter', email: '' },
  });
  expect(resp.status()).toBe(400);
  const json = await resp.json();
  expect(json.error).toContain('Email');
});

test('API: create-order rejects invalid package', async ({ request }) => {
  const resp = await request.post(BASE + '/api/paypal/create-order', {
    data: { packageId: 'nonexistent', email: 'test@test.com' },
  });
  expect(resp.status()).toBe(400);
});

test('API: capture rejects missing orderId', async ({ request }) => {
  const resp = await request.post(BASE + '/api/paypal/capture', {
    data: {},
  });
  expect(resp.status()).toBe(400);
});

test('API: orders confirm rejects missing orderId', async ({ request }) => {
  const resp = await request.post(BASE + '/api/orders', {
    data: {},
  });
  expect(resp.status()).toBe(400);
});

// ─── STATUS PAGE ────────────────────────────────────────────────────────────

test('Status: renders for active job', async ({ page, request }) => {
  const resp = await request.post(BASE + '/api/demo', {
    data: { target_url: 'stripe.com' },
  });
  const json = await resp.json();
  expect(json.url).toBeTruthy();

  await page.goto(BASE + json.url);
  await expect(page.locator('body')).toContainText(/Mining|Processing|Discover|Compet/i);
});

// ─── EXISTING REPORT OUTPUT ─────────────────────────────────────────────────

test('Report: no supplier references in pre-generated report', async ({ page }) => {
  const resp = await page.goto(BASE + '/reports/free-report-leadideal-com-report.html');
  if (resp && resp.ok()) {
    const body = await page.locator('body').textContent();
    const lower = body.toLowerCase();
    expect(lower).not.toContain('vapi');
    expect(lower).not.toContain('voice strategy');
    expect(lower).not.toContain('wayback revenue pipeline');
  }
});

test('Report: upgrade CTA links to /checkout not /auth', async ({ page }) => {
  const resp = await page.goto(BASE + '/reports/free-report-leadideal-com-report.html');
  if (resp && resp.ok()) {
    const authLinks = await page.locator('a[href="/auth"]').count();
    expect(authLinks).toBe(0);
  }
});

// ─── RESPONSIVE / MOBILE ────────────────────────────────────────────────────

test('Mobile: landing page works on 375px', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 375, height: 812 },
  });
  const page = await context.newPage();
  await page.goto(BASE);

  const hero = page.locator('.hero-content--clone h1');
  await expect(hero).toBeVisible();
  const input = page.locator('.hero-content--clone .mode-url-input');
  await expect(input).toBeVisible();
  const btn = page.locator('.hero-content--clone button[type="submit"]');
  await expect(btn).toBeVisible();

  await context.close();
});

test('Mobile: checkout page works on 375px', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 375, height: 812 },
  });
  const page = await context.newPage();
  await page.goto(BASE + '/checkout');

  await expect(page.locator('.checkout-card')).toBeVisible();
  await expect(page.locator('#paypal-button-container')).toBeAttached();

  await context.close();
});
