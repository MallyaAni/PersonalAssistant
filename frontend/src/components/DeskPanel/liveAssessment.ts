import type {DeskLive, DeskLiveGrade} from '../../services/api'
import {ENTRY_GRADES, GRADES, isLabel} from '../../services/labels'

// Expire candle assessments independently of prices, saved orders and personal inputs.
export const currentAssessments = (live: DeskLive, session: string | undefined, now: number): Record<string, DeskLiveGrade> => {
  if (!session || live.decision_session !== session) return {}
  return Object.fromEntries(Object.entries(live.grades_live ?? {}).filter(([ticker]) =>
    Date.parse(live.grade_valid_until?.[ticker] ?? '') > now))
}

// State only the adopted grade permission; a grade cannot supply funded shares or timing.
export const assessmentPermission = (grade: string): string => isLabel(ENTRY_GRADES, grade)
  ? 'Entry eligible; funded size and timing still required.'
  : isLabel(GRADES, grade) ? 'Avoid new entry under the grade-led policy.' : 'Entry assessment unavailable.'
