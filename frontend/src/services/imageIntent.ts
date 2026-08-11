// Telling an edit apart from a question about an image.
//
// These lived inside the image card, which is why asking for an edit only
// worked when typed into that card's follow-up box. Typed into the main
// composer the same words became an ordinary chat turn, the model has no image
// tool, and it answered that it could not edit images — indistinguishable, from
// the outside, from the feature being broken.

// Recognize a general image question, after edit-shaped requests are considered.
export const looksLikeQuestion = (text: string): boolean => {
  const normalized = text.trim().toLowerCase()
  return normalized.endsWith('?')
    || /^(what|which|who|where|when|why|how|is|are|was|were|do|does|did|can|could|would|will|should)\b/.test(normalized)
}

// Recognize polite question-shaped edit commands before general vision Q&A.
export const looksLikeRefinementRequest = (text: string): boolean => {
  const normalized = text.trim().toLowerCase()
  return /^(?:please\s+)?(?:(?:can|could|would|will)\s+(?:you|we)\s+)?(?:please\s+)?(?:make|change|turn|recolor|repaint|replace|remove|add|edit|modify|transform|adjust|brighten|darken|crop|resize|rotate|move)\b/.test(normalized)
}

// Whether this text should edit the image in view rather than ask about it.
//
// Deliberately narrower than the image card's rule. There, anything that is not
// a question edits, because the card is unambiguously about one image. Here the
// same text might be an ordinary chat turn that happens to follow an image, so
// only an explicitly edit-shaped instruction is taken.
export const shouldEditImage = (text: string): boolean => {
  const trimmed = text.trim()
  if (!trimmed) return false
  return looksLikeRefinementRequest(trimmed) && !looksLikeQuestion(trimmed)
}
