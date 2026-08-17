import { expect, test } from '@playwright/test'

// Give the workspace one server-derived identity and empty owned history.
test.beforeEach(async ({ page }) => {
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: 'ani.mallya',
      expires_at: '2036-08-09T00:00:00Z',
      is_admin: false,
    }),
  }))
  for (const [url, body] of [
    ['http://localhost:8000/api/v1/conversations/ani.mallya', { conversations: [] }],
    ['http://localhost:8000/api/v1/discovery/ani.mallya/subscription', { subscription: null, egress_enabled: false }],
    ['http://localhost:8000/api/v1/discovery/ani.mallya/runs?limit=5', { runs: [] }],
    ['http://localhost:8000/api/v1/discovery/ani.mallya/search-usage', {
      today: { used: 0, limit: 10, remaining: 10 },
      month: { used: 0, limit: 1000, remaining: 1000 },
    }],
  ] as const) {
    await page.route(url, route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    }))
  }
  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ agents: [] }),
  }))
})

// The reply tells the user to open the Scout panel and links to it. That link
// is only worth writing if it arrives somewhere, and it did not: the workspace
// was pure component state, so nothing outside the app could address a panel.
test('a link to #agents opens the agents panel', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: /agents/i }).first()).toBeVisible()

  await page.evaluate(() => {
    const link = document.createElement('a')
    link.href = '#agents'
    link.id = 'scout-setup-probe'
    link.textContent = 'Scout setup'
    document.body.appendChild(link)
  })
  await page.click('#scout-setup-probe')

  await expect(page).toHaveURL(/#agents$/)
  // The panel itself, not merely the URL: a hash that changes nothing on screen
  // is exactly the failure being tested.
  await expect(page.getByRole('heading', { name: /agents/i }).first()).toBeVisible({
    timeout: 5000,
  })
})

// Opening the URL directly must land on the panel too, or a link shared or
// reopened from history quietly returns the user to chat.
test('loading #agents directly opens the agents panel', async ({ page }) => {
  await page.goto('/#agents')

  await expect(page.getByRole('heading', { name: /agents/i }).first()).toBeVisible({
    timeout: 5000,
  })
})
