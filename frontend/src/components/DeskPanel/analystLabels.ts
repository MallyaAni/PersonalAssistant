const ANALYST_LABELS: Record<string, string> = {
  fundamental: 'Growth & margins',
  technical: 'Price trend',
  sentiment: 'Earnings-release tone',
  value: 'Relative valuation',
  rotation: 'Group leadership',
}

export const ANALYST_MEANINGS = 'F growth & margins; T price trend; S earnings-release tone; V relative valuation, not intrinsic fair value; R group leadership.'
export const EVENING_VOTE_CONTEXT = 'Evening votes use a three-session confirmation rule; the latest readings may differ from those that established a vote. Intraday price-sensitive votes can update without that wait.'

// Name an analyst's evidence precisely without changing its stored identifier or prose.
export const analystLabel = (key: string): string => ANALYST_LABELS[key] ?? key
