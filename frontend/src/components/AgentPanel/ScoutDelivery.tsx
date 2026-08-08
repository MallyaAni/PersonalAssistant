import { useCallback, useEffect, useState } from 'react'
import { Loader2, Send } from 'lucide-react'

import {
  cancelSubscription,
  getSubscription,
  requestSubscription,
  type GuestSubscription,
} from '../../services/api'

interface ScoutDeliveryProps {
  userId: string;
  onChanged?: () => void;
}

// The same field takes a US number or an Apple ID, so the phone mask applies
// only while what is typed could still become a number.
const looksLikeAPhone = (value: string): boolean => !/[a-z@]/i.test(value)

// Group digits as they are typed. Formatting never mattered to the backend —
// the address is reduced to one canonical form before it is stored or compared
// — but being shown the shape is what stops the question being asked.
const formatPhoneDigits = (value: string): string => {
  const digits = value.replace(/\D/g, '').slice(0, 10)
  if (digits.length <= 3) return digits
  if (digits.length <= 6) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`
}

// Whether Scout is messaging you, and the one place that changes it.
//
// It sits on the agent card rather than inside Configure. Whether an agent is
// reaching you is the first thing you want to know about it and the thing most
// likely to need changing in a hurry, and both were behind an expander, below
// the place, interest and feed editors.
const ScoutDelivery = ({ userId, onChanged }: ScoutDeliveryProps) => {
  const [subscription, setSubscription] = useState<GuestSubscription | null>(null)
  const [open, setOpen] = useState(false)
  const [addressDraft, setAddressDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setSubscription(await getSubscription(userId))
    } catch {
      setSubscription(null)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  const subscribe = async () => {
    const typed = addressDraft.trim()
    if (!typed) {
      setError('Enter the number or Apple ID to message.')
      return
    }
    if (looksLikeAPhone(typed) && typed.replace(/\D/g, '').length !== 10) {
      setError('A US number needs ten digits.')
      return
    }
    // The prefix is shown rather than typed, so it is added back here.
    const address = looksLikeAPhone(typed) ? `+1${typed.replace(/\D/g, '')}` : typed
    setBusy(true)
    setError('')
    try {
      await requestSubscription(userId, 'imessage', address)
      setAddressDraft('')
      setOpen(false)
      await load()
      onChanged?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not subscribe.')
    } finally {
      setBusy(false)
    }
  }

  const unsubscribe = async () => {
    setBusy(true)
    setError('')
    try {
      await cancelSubscription(userId)
      setOpen(false)
      await load()
      onChanged?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not unsubscribe.')
    } finally {
      setBusy(false)
    }
  }

  // A dot carries the state at a glance: green when it is live, amber while the
  // operator has not allowed the address yet, grey when nobody is subscribed.
  const dot = !subscription
    ? 'bg-[#c7c7cc]'
    : subscription.approved
      ? 'bg-[#248a3d]'
      : 'bg-[#b25e00]'
  const label = !subscription
    ? 'Subscribe'
    : subscription.approved
      ? 'Subscribed'
      : 'Waiting for approval'

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        className="ml-auto flex h-8 flex-none items-center gap-2 rounded-full border border-black/[0.08] px-3 text-xs font-medium text-[#1d1d1f] hover:border-black/20"
      >
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        {label}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Where Scout sends your digest"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl"
            onClick={event => event.stopPropagation()}
          >
            {error && (
              <p className="mb-3 rounded-xl bg-[#fff1f0] px-3 py-2 text-xs text-[#b3261e]">
                {error}
              </p>
            )}
            {subscription ? (
              <>
                {/* Asked rather than assumed: this is the switch that decides
                    whether anyone hears from Scout at all, and one stray click
                    should not quietly end the digests. */}
                <h3 className="text-[15px] font-semibold">Stop the messages?</h3>
                <p className="mt-1.5 text-xs leading-5 text-[#6e6e73]">
                  Scout will keep finding things and showing them here — it just
                  will not message you. You can subscribe again whenever.
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    onClick={() => setOpen(false)}
                    className="h-9 rounded-xl border border-black/[0.08] px-3 text-sm font-medium"
                  >
                    Keep them
                  </button>
                  <button
                    onClick={() => void unsubscribe()}
                    disabled={busy}
                    className="h-9 rounded-xl bg-[#b3261e] px-3 text-sm font-medium text-white disabled:opacity-40"
                  >
                    {busy ? 'Stopping…' : 'Unsubscribe'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 className="text-[15px] font-semibold">Get Scout&rsquo;s digest</h3>
                <p className="mt-1.5 text-xs leading-5 text-[#6e6e73]">
                  Where should it message you? An operator approves the address
                  before anything is sent.
                </p>
                <div className="mt-3 flex h-10 items-center rounded-xl border border-black/[0.08] focus-within:border-[#0071e3]">
                  {looksLikeAPhone(addressDraft) && (
                    <span className="pl-3 text-sm text-[#6e6e73]">+1</span>
                  )}
                  <input
                    value={addressDraft}
                    onChange={event => {
                      const next = event.target.value
                      setAddressDraft(
                        looksLikeAPhone(next) ? formatPhoneDigits(next) : next,
                      )
                    }}
                    onKeyDown={event => {
                      if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                        event.preventDefault()
                        void subscribe()
                      }
                    }}
                    autoFocus
                    inputMode="tel"
                    placeholder="xxx-xxx-xxxx or you@icloud.com"
                    aria-label="Your number or Apple ID"
                    className="h-full min-w-0 flex-1 rounded-xl bg-transparent px-2 text-sm outline-none"
                  />
                </div>
                <p className="mt-1.5 text-[11px] text-[#86868b]">
                  Just the ten digits — or type an Apple ID instead.
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    onClick={() => setOpen(false)}
                    className="h-9 rounded-xl border border-black/[0.08] px-3 text-sm font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => void subscribe()}
                    disabled={busy}
                    className="flex h-9 items-center gap-1.5 rounded-xl bg-[#1d1d1f] px-3 text-sm font-medium text-white disabled:opacity-40"
                  >
                    {busy ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Send size={14} />
                    )}
                    Subscribe
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export default ScoutDelivery
