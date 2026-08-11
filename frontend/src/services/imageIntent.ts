// Telling an edit apart from a question about an image.
//
// This was a regular expression over the first word typed, and it was wrong
// often enough to look like the edit feature was broken: "edit this image to
// give me a straw hat" routed to an edit, while "give me a straw hat", "put a
// hat on me" and "draw a hat on this" all routed to a description. Its one
// concession to politeness — a branch for "can you edit this..." — could never
// fire, because the same text was then rejected for starting with "can".
//
// The routing decision now belongs to the model, on the server, so every path
// that needs it agrees and none of them keeps a list of verbs. See
// `backend/services/image_intent.py`.

import { classifyImageIntent } from './api'

// A guess, for a button label only — never for routing.
//
// The label updates on every keystroke, and asking a model per keystroke to
// choose a word on a button would be absurd. It is allowed to be wrong: the
// send that follows asks the server, and the in-flight label is corrected from
// that answer.
// A question mark is deliberately not consulted. "Can you make this car red?"
// is an edit wearing a question mark, and labelling it "Ask" was the closest
// this heuristic ever came to actively lying about what the button would do.
export const looksLikeEditHint = (text: string): boolean => {
  const normalized = text.trim().toLowerCase()
  if (!normalized) return false
  return !/^(what|which|who|where|when|why|how|is|are|was|were|do|does|did)\b/.test(normalized)
}

// Whether this text should edit the image in view rather than ask about it.
//
// Answers false when the classifier is unreachable, matching the server: an
// image described when an edit was meant can be edited from the follow-up box,
// and describing is what these paths did before any of this existed.
export const shouldEditImage = async (userId: string, text: string): Promise<boolean> => {
  const trimmed = text.trim()
  if (!trimmed) return false
  try {
    return await classifyImageIntent(userId, trimmed)
  } catch {
    return false
  }
}
