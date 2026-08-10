// Choosing light or dark from the time where the user actually is.
//
// This needs no location and no memory. `new Date()` is already in the device's
// own timezone, so a phone in London and a desktop in Virginia each report their
// own evening without being told where they are. Asking the profile for a
// locality would add a lookup, a failure mode, and a way to be wrong for anyone
// travelling — to learn something the browser already knows.
//
// An explicit choice in the app wins, and is remembered. Otherwise the clock
// decides, and a system preference for dark can only add darkness, never
// prevent it.
//
// The order used to put the system preference above the clock, which read well
// and meant the clock never ran at all: browsers answer `prefers-color-scheme`
// with light or dark rather than with nothing, so the "no opinion" case the
// clock waited for effectively does not occur. Verified in the browser — it
// reported `light: true` at 13:00 and would have reported it at 01:00 too.

export type Theme = 'light' | 'dark'
export type ThemePreference = Theme | 'auto'

const STORAGE_KEY = 'anios.theme'

// Dark from 19:00 to 06:59, which is roughly lamps-on to curtains-open across
// the year without pretending to know sunset.
export const DARK_FROM_HOUR = 19
export const DARK_UNTIL_HOUR = 7

// What the clock alone says, for a given moment in the device's own timezone.
export const themeForHour = (hour: number): Theme =>
  hour >= DARK_FROM_HOUR || hour < DARK_UNTIL_HOUR ? 'dark' : 'light'

// What should be shown, given a stored preference and the current moment.
//
// `systemPrefersDark` is passed in rather than read here so the decision stays
// a pure function: it is the part worth testing, and a test cannot move a
// media query.
export const resolveTheme = (
  preference: ThemePreference,
  now: Date,
  systemPrefersDark: boolean | null,
): Theme => {
  if (preference !== 'auto') return preference
  // The clock decides, which is what "automatic" was asked to mean. The system
  // preference used to win here and it swallowed the clock entirely: every
  // modern browser answers one of the two `prefers-color-scheme` queries, so
  // `systemPrefersDark` is almost never null and `themeForHour` never ran. An
  // OS pinned to light kept the app light at midnight.
  //
  // It is still consulted, but only to break the tie the clock cannot see —
  // an OS already in dark mode during daylight hours is a user who wants dark.
  if (systemPrefersDark === true) return 'dark'
  return themeForHour(now.getHours())
}

// Read the stored choice, treating anything unrecognised as automatic.
export const storedPreference = (): ThemePreference => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw === 'light' || raw === 'dark' || raw === 'auto' ? raw : 'auto'
  } catch {
    // Private browsing and blocked storage both throw. Neither is a reason to
    // fail to render.
    return 'auto'
  }
}

export const rememberPreference = (preference: ThemePreference): void => {
  try {
    window.localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // Forgetting the choice is survivable; refusing to apply it is not.
  }
}

const systemPrefersDark = (): boolean | null => {
  if (typeof window.matchMedia !== 'function') return null
  const query = window.matchMedia('(prefers-color-scheme: dark)')
  // A browser that has no opinion reports `false` for both queries, which is
  // not the same as preferring light — that is when the clock should decide.
  if (!query.matches && !window.matchMedia('(prefers-color-scheme: light)').matches) {
    return null
  }
  return query.matches
}

// Put the decision on the document. One class, which is what `theme.css` and
// Tailwind's `dark:` variant both key off.
export const applyTheme = (theme: Theme): void => {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.style.colorScheme = theme
}

export const currentTheme = (preference = storedPreference()): Theme =>
  resolveTheme(preference, new Date(), systemPrefersDark())

// Keep the page in step: with the system while it is set to automatic, and with
// the clock, so an evening that arrives while the tab is open is noticed.
export const watchTheme = (preferenceNow: () => ThemePreference): (() => void) => {
  const sync = () => applyTheme(currentTheme(preferenceNow()))
  sync()
  const media = typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null
  media?.addEventListener('change', sync)
  // A minute is fine: nobody notices the switch arriving 40 seconds late, and
  // it costs one comparison.
  const timer = window.setInterval(sync, 60_000)
  return () => {
    media?.removeEventListener('change', sync)
    window.clearInterval(timer)
  }
}
