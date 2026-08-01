import type { KeyboardEvent } from 'react'

// Enter submits, Shift+Enter starts a new line. Browsers never submit a form
// from inside a textarea, so every multi-line box needs this explicitly or it
// silently behaves differently from the chat composer beside it.
//
// `blocked` mirrors the button's own disabled condition so the keyboard cannot
// trigger an action the button would refuse.
export const submitOnEnter = (
  submit: () => void | Promise<void>,
  blocked = false,
) => (event: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => {
  if (event.key !== 'Enter' || event.shiftKey) return
  // Composing with an IME uses Enter to accept a candidate, not to send.
  if (event.nativeEvent.isComposing) return
  event.preventDefault()
  if (!blocked) void submit()
}
