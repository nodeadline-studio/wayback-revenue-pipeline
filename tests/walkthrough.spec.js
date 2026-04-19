const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

test.describe('Wayback Revenue Pipeline Monetization Walkthrough', () => {
    const TARGET_URL = 'https://landingfunnel.com'; // Use a consistent target for testing
    const TEST_EMAIL = 'tester@vibe.ai';
    const BASE_URL = 'http://127.0.0.1:5005';

    test('End-to-End: Free Scan -> Redacted Report -> Unlock Premium', async ({ page }) => {
        // 1. Visit Landing Page
        await page.goto(BASE_URL);
        await expect(page).toHaveTitle(/Business Spy/);

        // 2. Start Scan
        console.log('Starting scan for:', TARGET_URL);
        await page.fill('#target-url', TARGET_URL);
        await page.fill('#user-email', TEST_EMAIL);
        await page.click('button:has-text("Start Intelligence Scan")');

        // 3. Monitor Status Screen
        await expect(page).toHaveURL(/status/);
        console.log('Waiting for report generation...');
        
        // Wait for completion (status 'completed')
        // We poll for the 'View Full Report' button which only appears on completion
        const viewReportBtn = page.locator('a:has-text("View Strategic Intelligence Report")');
        await viewReportBtn.waitFor({ state: 'visible', timeout: 300000 }); // 5 min timeout for real scan

        const reportUrl = await viewReportBtn.getAttribute('href');
        console.log('Report ready at:', reportUrl);

        // 4. Verify Redacted State
        await page.goto(`${BASE_URL}${reportUrl}`);
        
        // Check for 'Detailed Forensic Evidence Locked' banner
        await expect(page.locator('text=Detailed Forensic Evidence Locked')).toBeVisible();
        
        // Check for redacted tasks [LOCKED]
        await expect(page.locator('text=[LOCKED]').first()).toBeVisible();
        
        // Check for blurred ROI (Backend redaction should show [LOCKED] text now)
        await expect(page.locator('text=[LOCKED]').first()).toBeVisible();

        // 5. Go to Checkout
        console.log('Navigating to checkout...');
        const unlockBtn = page.locator('a:has-text("Unlock Full Intelligence")');
        await unlockBtn.click();
        await expect(page).toHaveURL(/checkout/);

        // 6. Simulate Mock Payment Bypass
        // We get the jobId from the report URL if possible, or we use the API to confirm for the email+url
        const jobId = reportUrl.split('/').pop().replace('.html', '').replace('report-', '');
        
        console.log('Simulating payment capture for Job:', jobId);
        const response = await page.evaluate(async ({ jobId, targetUrl }) => {
            const res = await fetch('/api/orders/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    orderId: `MOCK-PAY-${Date.now()}`,
                    targetUrl: targetUrl 
                })
            });
            return await res.json();
        }, { jobId, targetUrl: TARGET_URL });

        expect(response.success).toBe(true);
        console.log('Payment confirmed. Unlocked report URL:', response.report_url);

        // 7. Verify Unlocked Report
        await page.goto(`${BASE_URL}${response.report_url}`);
        
        // Locked banner should be GONE
        await expect(page.locator('text=Detailed Forensic Evidence Locked')).not.toBeVisible();
        
        // [LOCKED] strings should be replaced with real data
        await expect(page.locator('text=[LOCKED]')).not.toBeVisible();
        
        // Verify we have real tasks/insights (non-empty)
        const taskText = await page.locator('.competitor-card').first().textContent();
        expect(taskText.length).toBeGreaterThan(10);

        console.log('E2E Walkthrough Verified: Monetization pipeline is functional.');
    });
});
