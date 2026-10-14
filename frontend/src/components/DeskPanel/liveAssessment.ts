import type {DeskLive, DeskLiveGrade} from '../../services/api'

// Expire candle assessments independently of prices, saved orders and personal inputs.
export const currentAssessments = (live: DeskLive, session: string | undefined, now: number): Record<string, DeskLiveGrade> => {
  if (!session || live.decision_session !== session) return {}
  return Object.fromEntries(Object.entries(live.grades_live ?? {}).filter(([ticker]) =>
    Date.parse(live.grade_valid_until?.[ticker] ?? '') > now))
}

// State only the adopted grade permission; a grade cannot supply funded shares or timing.
export const assessmentPermission = (grade: string): string => grade === 'A' || grade === 'A+'
  ? 'Entry eligible; funded size and timing still required.'
  : grade === 'B' || grade === 'C' ? 'Avoid new entry under the grade-led policy.' : 'Entry assessment unavailable.'
