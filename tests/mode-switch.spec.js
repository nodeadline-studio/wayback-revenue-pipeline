// @ts-check
// Tests for CSS :has() radio-driven mode switching on the BizSpy landing page.
// These tests are purely front-end and do not require a running backend.
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8889';

test.describe('Mode switch: CSS :has() radio toggle', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE);
  });

  test('Default mode is Clone: correct H1, placeholder, button text', async ({ page }) => {
    await expect(page.locator('.hero-content--clone')).toBeVisible();
    await expect(page.locator('.hero-content--clone h1')).toContainText('before you write a single word');
    await expect(page.locator('.hero-content--clone .mode-url-input')).toHaveAttribute('placeholder', 'Enter target domain to scan...');
    await expect(page.locator('.hero-content--clone button[type="submit"]')).toContainText('Initiate Scan');
    await expect(page.locator('.hero-content--signal')).not.toBeVisible();
  });

  test('Switch to Brief a Prospect: correct H1, placeholder, button text', async ({ page }) => {
    await page.click('label[for="mode-signal"]');

    await expect(page.locator('.hero-content--signal')).toBeVisible();
    await expect(page.locator('.hero-content--signal h1')).toContainText('Personalized Outreach');
    await expect(page.locator('.hero-content--signal .mode-url-input')).toHaveAttribute('placeholder', 'Enter prospect domain to brief...');
    await expect(page.locator('.hero-content--signal button[type="submit"]')).toContainText('Generate Brief');
    await expect(page.locator('.hero-content--clone')).not.toBeVisible();
  });

  test('Switch back to Clone a Startup from Brief', async ({ page }) => {
    await page.click('label[for="mode-signal"]');
    await expect(page.locator('.hero-content--signal')).toBeVisible();

    await page.click('label[for="mode-clone"]');
    await expect(page.locator('.hero-content--clone')).toBeVisible();
    await expect(page.locator('.hero-content--signal')).not.toBeVisible();
  });

  test('Radio state matches visible content', async ({ page }) => {
    // Default: clone radio checked
    await expect(page.locator('#mode-clone')).toBeChecked();
    await expect(page.locator('#mode-signal')).not.toBeChecked();

    // Click signal label -> signal radio becomes checked
    await page.click('label[for="mode-signal"]');
    await expect(page.locator('#mode-signal')).toBeChecked();
    await expect(page.locator('#mode-clone')).not.toBeChecked();
  });

  test('Both mode inputs are present in DOM', async ({ page }) => {
    await expect(page.locator('.hero-content--clone .mode-url-input')).toBeAttached();
    await expect(page.locator('.hero-content--signal .mode-url-input')).toBeAttached();
    await expect(page.locator('.hero-content--clone button[type="submit"]')).toBeAttached();
    await expect(page.locator('.hero-content--signal button[type="submit"]')).toBeAttached();
  });
});
