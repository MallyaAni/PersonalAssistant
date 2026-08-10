import { expect, test } from '@playwright/test'

// The theme engine decided correctly from the first commit and was applied
// exactly once, at load, with no way for a user to disagree with it. These
// cover the two things that were missing: a control, and the page keeping in
// step while it is open.
//
// The assertions read the `dark` class on <html>, which is what theme.css and
// Tailwind's `dark:` variant both key off — the same thing the styling reads,
// rather than a colour that a restyle would change.

const isDark = (page: import('@playwright/test').Page) =>
  page.evaluate(() => document.documentElement.classList.contains('dark'))

// The workspace only renders behind a resolved session, so the header that
// carries the control does not exist without one.
test.beforeEach(async ({ page }) => {
  await page.route('http://localhost:8000/api/v1/auth/session', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authentication_required: true,
        user_id: 'ani.mallya',
        expires_at: '2026-08-09T00:00:00Z',
        is_admin: false,
      }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/conversations/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [] }),
    }),
  )
  await page.route(/\/api\/v1\/discovery\//, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  )
})

test.describe('theme', () => {
  test('the toggle cycles automatic, light, dark and survives a reload', async ({ page }) => {
    await page.goto('/')
    const toggle = page.getByRole('button', { name: /^Theme:/ }).first()
    await expect(toggle).toBeVisible()

    // Whatever the clock says at the moment this runs, the first press must
    // land on light and the second on dark — the cycle is what is under test,
    // not the starting point.
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: automatic')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: light')
    expect(await isDark(page)).toBe(false)

    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: dark')
    expect(await isDark(page)).toBe(true)

    // Remembered: a choice that resets on reload is not a choice.
    await page.reload()
    expect(await isDark(page)).toBe(true)
    await expect(page.getByRole('button', { name: 'Theme: dark' }).first()).toBeVisible()

    await page.getByRole('button', { name: 'Theme: dark' }).first().click()
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: automatic')
  })

  test('an explicit choice outranks the system preference', async ({ page }) => {
    // Automatic follows the system; light must not.
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/')
    expect(await isDark(page)).toBe(true)

    const toggle = page.getByRole('button', { name: /^Theme:/ }).first()
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: light')
    expect(await isDark(page)).toBe(false)

    // Still light after the system changes underneath it.
    await page.emulateMedia({ colorScheme: 'light' })
    await page.emulateMedia({ colorScheme: 'dark' })
    expect(await isDark(page)).toBe(false)
  })

  test('exactly one theme control is on screen at each width', async ({ page }) => {
    // Two sign-out buttons once shipped this way, so the breakpoint pairing is
    // asserted rather than assumed.
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: /^Theme:/ })).toHaveCount(1)

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.getByRole('button', { name: /^Theme:/ })).toHaveCount(1)
  })
})
