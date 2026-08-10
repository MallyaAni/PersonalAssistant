import React, { useEffect, useState } from 'react'
import { Moon, Sun, SunMoon } from 'lucide-react'
import {
  applyTheme,
  currentTheme,
  rememberPreference,
  storedPreference,
  watchTheme,
  type ThemePreference,
} from '../../theme'

// The three states in the order they cycle. Automatic sits first because it is
// the default and the one a user returns to, not a third option after the two
// real ones.
const ORDER: ThemePreference[] = ['auto', 'light', 'dark']

const LABEL: Record<ThemePreference, string> = {
  auto: 'Theme: automatic',
  light: 'Theme: light',
  dark: 'Theme: dark',
}

const ICON: Record<ThemePreference, React.ReactNode> = {
  auto: <SunMoon size={17} />,
  light: <Sun size={17} />,
  dark: <Moon size={17} />,
}

interface ThemeToggleProps {
  // Rendered in two places at different breakpoints, exactly as sign-out is:
  // the header from md up, the drawer's account section below it. They are
  // mutually exclusive, which is what keeps one control from becoming two on
  // screen at once.
  className?: string
  withLabel?: boolean
}

// Cycle automatic → light → dark, and keep the page in step while it is open.
export const ThemeToggle: React.FC<ThemeToggleProps> = ({ className = '', withLabel = false }) => {
  const [preference, setPreference] = useState<ThemePreference>(storedPreference)

  // `watchTheme` follows both the system setting and the clock, so an evening
  // that arrives while the tab is open is noticed. Without this the engine only
  // ever ran once, at load.
  useEffect(() => watchTheme(() => storedPreference()), [])

  const advance = () => {
    const next = ORDER[(ORDER.indexOf(preference) + 1) % ORDER.length]
    setPreference(next)
    rememberPreference(next)
    // Applied here rather than waiting for the watcher's next tick, which is a
    // minute away and would make the button feel broken.
    applyTheme(currentTheme(next))
  }

  return (
    <button
      type="button"
      onClick={advance}
      aria-label={LABEL[preference]}
      title={LABEL[preference]}
      className={className}
    >
      {ICON[preference]}
      {withLabel && <span>{LABEL[preference].replace('Theme: ', 'Theme — ')}</span>}
    </button>
  )
}

export default ThemeToggle
