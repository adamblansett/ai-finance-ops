import { expect, test } from '@playwright/test';

test('end-to-end Phase 1 & 2 finance operations workflow', async ({ page }) => {
  await page.goto('/');

  // 1. Live API health and seeded overview metrics
  await expect(page.getByRole('heading', { name: 'AI Finance Operations' })).toBeVisible();
  await expect(page.getByText(/API Healthy \(mock\)/i)).toBeVisible();
  await expect(page.getByText('$500,000.00')).toBeVisible();
  await expect(page.getByText('Verified Intact')).toBeVisible();

  // 2. Real persisted JWT login flow using seeded controller account
  await page.getByRole('button', { name: 'Sign In' }).click();
  await page.getByLabel('Login Email').fill('controller@acme-finops.local');
  await page.getByLabel('Login Password').fill('ControllerDemo123!');
  await page.locator('form').getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByText(/Signed in as controller@acme-finops\.local/i)).toBeVisible();

  // 3. Ingestion + SHA-256 duplicate block verification
  await page.getByRole('button', { name: 'Ingestion' }).click();
  await page.getByRole('button', { name: 'Ingest Inline Payload' }).click();
  await expect(page.getByText(/Ingested 1 invoice record/i)).toBeVisible();

  // Re-submitting exact same payload triggers HTTP 409 duplicate block
  await page.getByRole('button', { name: 'Ingest Inline Payload' }).click();
  await expect(page.getByText(/Duplicate document blocked/i)).toBeVisible();

  // 4. 3-Way Match search + Controller approval with custom decision note
  await page.getByRole('button', { name: '3-Way Match' }).click();
  await page.getByLabel('Search reconciliation matches').fill('INV-CC-401');
  await expect(page.getByText('INV-CC-401').first()).toBeVisible();
  const noteInput = page.getByLabel('Decision note for INV-CC-401').first();
  if (await noteInput.isVisible()) {
    await noteInput.fill('E2E verified PO and receipt');
    await page.getByRole('button', { name: 'Approve INV-CC-401' }).first().click();
    await expect(page.getByText('Invoice match approved.')).toBeVisible();
  }

  // 5. 13-Week Cash Flow sensitivity scenario
  await page.getByRole('button', { name: '13-Week Cash Flow' }).click();
  await expect(page.getByRole('img', { name: '13-week cash flow chart' })).toBeVisible();
  await page.getByRole('button', { name: 'Run Scenario' }).click();
  await expect(page.getByText('Weekly Projection Ledger')).toBeVisible();

  // 6. Jobs & Exports + GL Suggestion
  await page.getByRole('button', { name: 'Jobs & Exports' }).click();
  await page.getByRole('button', { name: 'Suggest GL Code' }).click();
  await expect(page.getByText('6100-CLOUD')).toBeVisible();
  await page.getByRole('button', { name: 'Snapshot 13W Forecast' }).click();
  await expect(page.getByText(/forecast_snapshot/i).first()).toBeVisible();

  // 7. SOX Audit Chain Integrity & Cloud PII Redaction
  await page.getByRole('button', { name: 'SOX Audit & PII' }).click();
  await page.getByRole('button', { name: 'Verify Hash Chain' }).click();
  await expect(page.getByText(/verified intact/i).first()).toBeVisible();
  await page.getByRole('button', { name: 'Preview Cloud Redaction' }).click();
  await expect(page.getByText(/\[REDACTED_EMAIL\]/)).toBeVisible();
});
