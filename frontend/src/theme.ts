// Choosing light or dark from the time where the user actually is.
//
// This needs no location and no memory. `new Date()` is already in the device's
// own timezone, so a phone in London and a desktop in Virginia each report their
// own evening without being told where they are. Asking the profile for a
// locality would add a lookup, a failure mode, and a way to be wrong for anyone
// travelling — to learn something the browser already knows.
//
// The system preference wins over the clock when the user has expressed one,
// because an OS that is already switching at sunset knows more than a fixed
// hour does. An explicit choice in the app wins over both, and is remembered.

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
  if (systemPrefersDark !== null) return systemPrefersDark ? 'dark' : 'light'
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
