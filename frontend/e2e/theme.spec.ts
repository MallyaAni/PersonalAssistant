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

// The control is rendered twice, once per breakpoint, and CSS hides one. Taking
// `.first()` sometimes takes the hidden one, which then never accepts a click —
// so the visible one is asked for by name.
const themeButton = (page: import('@playwright/test').Page) =>
  page.locator('button[aria-label^="Theme:"]:visible')

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
        // Comfortably in the future: an expiry in the past survives the first
        // load and then drops to the sign-in screen on reload, which reads as
        // the theme control vanishing.
        expires_at: '2030-01-01T00:00:00Z',
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
    const toggle = themeButton(page)
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
    // The applied class above already proves the choice was re-read on load —
    // main.tsx applies the theme before React renders, so it holds even on the
    // sign-in screen. This asserts what was actually kept, rather than
    // re-finding a control whose presence depends on the session.
    expect(await page.evaluate(() => window.localStorage.getItem('anios.theme'))).toBe(
      'dark',
    )

  })

  test('automatic follows the clock, not the operating system', async ({ page }) => {
    // The defect this replaces: the system preference outranked the clock, and
    // because browsers always answer `prefers-color-scheme` with light or dark
    // rather than with nothing, the clock never ran. An OS pinned to light kept
    // the workspace light at one in the morning.
    await page.emulateMedia({ colorScheme: 'light' })

    await page.clock.setFixedTime(new Date('2026-08-10T01:30:00'))
    await page.goto('/')
    expect(await isDark(page)).toBe(true)

    await page.clock.setFixedTime(new Date('2026-08-10T13:30:00'))
    await page.goto('/')
    expect(await isDark(page)).toBe(false)
  })

  test('an explicit choice outranks both the clock and the system', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' })
    await page.clock.setFixedTime(new Date('2026-08-10T01:30:00'))
    await page.goto('/')
    expect(await isDark(page)).toBe(true)

    // Awake at 01:30 and wanting light is a real thing to want.
    const toggle = themeButton(page)
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-label', 'Theme: light')
    expect(await isDark(page)).toBe(false)
  })

  test('a system preference for dark can add darkness but never remove it', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.clock.setFixedTime(new Date('2026-08-10T13:30:00'))
    await page.goto('/')
    // Daylight by the clock, but an OS in dark mode is a user who wants dark.
    expect(await isDark(page)).toBe(true)
  })

  test('exactly one theme control is on screen at each width', async ({ page }) => {
    // Two sign-out buttons once shipped this way, so the breakpoint pairing is
    // asserted rather than assumed.
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto('/')
    await expect(themeButton(page)).toHaveCount(1)

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(themeButton(page)).toHaveCount(1)
  })
})
