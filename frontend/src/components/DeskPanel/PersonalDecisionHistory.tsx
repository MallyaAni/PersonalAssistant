import type { DeskDecisions, DeskHistoryReceipt } from '../../services/api'

export interface PersonalHistoryContext {
  userId: string
  generation: number
  request: number
  decisions?: DeskDecisions
  receipt: DeskHistoryReceipt
}
