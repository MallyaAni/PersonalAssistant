import { useCallback, useEffect, useState } from 'react'
import {
  Check,
  Clock,
  Eye,
  EyeOff,
  FlaskConical,
  Loader2,
  MapPin,
  Plus,
  Rss,
  Send,
  Sparkles,
  Trash2,
  Undo2,
} from 'lucide-react'

import {
  deleteDiscoveryInterest,
  deleteDiscoveryKnown,
  deleteDiscoverySchedule,
  deleteDiscoverySource,
  deleteDiscoveryTravelMode,
  getDiscoveryProfile,
  getDiscoveryKnown,
  getDiscoverySchedule,
  cancelSubscription,
  getDiscoverySources,
  getSubscription,
  markDiscoveryKnown,
  requestSubscription,
  putDiscoveryInterest,
  putDiscoveryCurrentPlace,
  putDiscoveryLocality,
  putDiscoverySchedule,
  putDiscoverySource,
  resolveDiscoveryLocality,
  previewDiscoveryDigest,
  runDiscoverySweep,
  suggestDiscoveryInterests,
  suggestDiscoverySources,
  type DiscoveryInterest,
  type DiscoveryKnownItem,
  type DiscoveryLocality,
  type DiscoverySchedule,
  type GuestSubscription,
  type DiscoverySource,
  type DigestPreview,
  type FeedCandidate,
  type SweepResult,
  type InterestProposal,
  getSearchUsage,
  type SearchUsage,
} from '../../services/api'

const WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

// A readable clock time. The schedule is stated in the user's own timezone, so
// showing 24-hour values would make them do the conversion.
const formatHour = (value: number, minutes = 0): string => {
  const meridiem = value < 12 ? 'am' : 'pm'
  return `${value % 12 || 12}:${String(minutes).padStart(2, '0')}${meridiem}`
}

// Quarter hours only. The API accepts any minute, but a 60-item list to pick a
// sweep time is a worse choice than four.
const QUARTERS = [0, 15, 30, 45]

// "Arlington, Virginia, US" rather than "Arlington". A town name alone is
// ambiguous across countries, so what is saved is shown in full.
const describePlace = (place: { label: string; region?: string | null }): string =>
  place.region ? `${place.label}, ${place.region}` : place.label

interface ScoutSetupProps {
  userId: string;
  onChanged: () => void;
}

// Configure the discovery agent: where to look, what to look for, and which
// feeds to read. Everything here writes through the owned API, so the panel
// never holds state the backend does not already have.
const ScoutSetup = ({ userId, onChanged }: ScoutSetupProps) => {
  const [place, setPlace] = useState('')
  const [savedPlace, setSavedPlace] = useState<DiscoveryLocality | null>(null)
  const [localities, setLocalities] = useState<DiscoveryLocality[]>([])
  const [activeTravel, setActiveTravel] = useState<DiscoveryLocality | null>(null)
  const [interests, setInterests] = useState<DiscoveryInterest[]>([])
  const [known, setKnown] = useState<DiscoveryKnownItem[]>([])
  const [knownLocality, setKnownLocality] = useState<string | null>(null)
  const [sources, setSources] = useState<DiscoverySource[]>([])
  const [interestDraft, setInterestDraft] = useState('')
  const [usage, setUsage] = useState<SearchUsage | null>(null)
  const [feedCandidates, setFeedCandidates] = useState<FeedCandidate[]>([])
  const [interestProposals, setInterestProposals] = useState<InterestProposal[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  // Set only when a reported location differs from home. Visiting and moving
  // are indistinguishable from a coordinate, so this asks once instead of
  // silently picking the answer that rewrites where someone lives.
  const [movedPrompt, setMovedPrompt] = useState('')
  const [preview, setPreview] = useState<DigestPreview | null>(null)
  const [trial, setTrial] = useState<SweepResult | null>(null)
  const [subscription, setSubscription] = useState<GuestSubscription | null>(null)
  const [addressDraft, setAddressDraft] = useState('')
  const [schedule, setSchedule] = useState<DiscoverySchedule | null>(null)
  const [cadence, setCadence] = useState<'daily' | 'weekly'>('weekly')
  const [hour, setHour] = useState(9)
  const [minute, setMinute] = useState(0)
  const [weekday, setWeekday] = useState(4)

  const reload = useCallback(async () => {
    const [profile, feeds, saved, familiar] = await Promise.all([
      getDiscoveryProfile(userId),
      getDiscoverySources(userId),
      getDiscoverySchedule(userId),
      getDiscoveryKnown(userId),
    ])
    setInterests(profile.interests)
    setLocalities(profile.localities)
    setSources(feeds)
    setSchedule(saved)
    setKnown(familiar.known)
    setKnownLocality(familiar.locality)
    if (saved) {
      setCadence(saved.cadence)
      setHour(saved.hour)
      setMinute(saved.minute ?? 0)
      setWeekday(saved.weekday)
    }
    const primary = profile.localities.find(item => item.is_primary) ?? profile.localities[0]
    setActiveTravel(profile.localities.find(item => item.is_travel_active) ?? null)
    setSavedPlace(primary ?? null)
    if (primary && !place) setPlace(primary.label)
  }, [userId, place])

  useEffect(() => {
    void reload().catch(() => setError('Could not load the configuration.'))
    // Usage is read separately: it changes as searches are spent, and a
    // failure here must not stop the rest of the panel loading.
    void getSearchUsage(userId)
      .then(setUsage)
      .catch(() => setUsage(null))
    // Loading once per user is deliberate: reload() depends on the draft place,
    // and re-running on every keystroke would fight the user's typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  // Run one action with a busy label, refreshing afterwards.
  const perform = async (label: string, action: () => Promise<void>) => {
    setBusy(label)
    setError('')
    setNotice('')
    try {
      await action()
      await reload()
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong.')
    } finally {
      setBusy('')
    }
  }

  const savePlace = () =>
    perform('place', async () => {
      const label = place.trim()
      if (!label) throw new Error('Enter a town or city.')
      const saved = await putDiscoveryLocality(userId, {
        label,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
      setNotice(`Saved. Looking around ${describePlace(saved)}.`)
    })

  // Ask the browser, then hand the backend a coordinate it will blunt further
  // before its single lookup. The precise fix never leaves this machine.
  const useMyLocation = () =>
    perform('locate', async () => {
      if (!('geolocation' in navigator)) {
        throw new Error('This browser cannot report a location.')
      }
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: false,
          timeout: 15_000,
          maximumAge: 600_000,
        })
      }).catch(() => {
        throw new Error('Location permission was declined.')
      })
      const resolved = await resolveDiscoveryLocality(
        userId,
        position.coords.latitude,
        position.coords.longitude,
      )
      // Where you are, never where you live. This used to save the home
      // locality, which also records the approved memory fact that the user
      // lives there — so one press from a hotel rewrote their home, stranded
      // the familiarity they had built up at home, and made their memory say
      // they had moved. Pressing it again on the way back said so twice.
      const outcome = await putDiscoveryCurrentPlace(userId, {
        label: resolved.label,
        // Region carries the country too: a town name alone is ambiguous, and
        // there is an Arlington in more than one country.
        region: resolved.stored_region ?? resolved.region,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
      await reload()
      if (outcome.away) {
        // The one thing that cannot be inferred. Visiting and moving look
        // identical from a coordinate, and guessing "moved" is the expensive
        // wrong answer, so being away is assumed and moving is one tap.
        setMovedPrompt(describePlace(outcome.locality))
        setNotice(
          `Looking around ${describePlace(outcome.locality)} for now. ` +
            `Only the town was stored, never coordinates.`,
        )
        return
      }
      setPlace(resolved.label)
      setMovedPrompt('')
      setNotice(
        `You're around ${resolved.display}. Only the town was stored, never coordinates.`,
      )
    })

  // Promote where the user is to where they live, which is the only path that
  // rewrites the approved home fact — and it now takes someone saying so.
  const confirmMoved = () =>
    perform('locate', async () => {
      const current = activeTravel
      if (!current) throw new Error('No new place to move to.')
      await deleteDiscoveryTravelMode(userId)
      await putDiscoveryLocality(userId, {
        label: current.label,
        region: current.region,
        timezone: current.timezone,
        is_primary: true,
      })
      setMovedPrompt('')
      await reload()
      setNotice(`Home is now ${describePlace(current)}.`)
    })

  const addInterest = (label: string) =>
    perform('interest', async () => {
      const value = label.trim()
      if (!value) throw new Error('Enter an interest.')
      await putDiscoveryInterest(userId, value)
      setInterestDraft('')
      setInterestProposals(current => current.filter(item => item.label !== label))
    })

  const addFeed = (kind: string, url: string) =>
    perform('feed', async () => {
      // Only reachable from a suggestion Scout found, so the URL is one it
      // already validated rather than something typed by hand.
      const value = url.trim()
      if (!value) return
      await putDiscoverySource(userId, { kind, url: value })
      setFeedCandidates(current => current.filter(item => item.url !== url))
    })

  const suggestFeeds = () =>
    perform('suggest-feeds', async () => {
      const candidates = await suggestDiscoverySources(userId)
      setFeedCandidates(candidates)
      if (candidates.length === 0) {
        setNotice('No feeds found. Add one by address instead.')
      }
    })

  const suggestInterests = () =>
    perform('suggest-interests', async () => {
      const proposals = await suggestDiscoveryInterests(userId)
      setInterestProposals(proposals)
      if (proposals.length === 0) {
        setNotice('Nothing in memory to suggest yet.')
      }
    })

  const sweepNow = () =>
    perform('sweep', async () => {
      const result = await runDiscoverySweep(userId, true)
      setPreview(null)
      setTrial(result)
      // The hidden count is stated rather than left to be inferred from a thin
      // digest, because that is the only way a wrong dismissal is ever noticed.
      const hidden = result.hidden_count
        ? ` ${result.hidden_count} hidden as already known.`
        : ''
      setNotice(
        `Read ${result.candidate_count} events, ${result.novel_count} new, ` +
          `${result.selected.length} worth telling you about.${hidden}`,
      )
    })

  // "I know this" is scoped to the current place, so the same dismissal does not
  // follow the user somewhere they have never been. It carries the happening's
  // own identity, so it dismisses the thing named rather than its title text.
  const markKnown = (label: string, itemDigest?: string | null) =>
    perform('known', async () => {
      const result = await markDiscoveryKnown(userId, label, itemDigest)
      setTrial(current =>
        current
          ? {
              ...current,
              selected: current.selected.filter(item => item.title !== label),
            }
          : current,
      )
      setNotice(
        `Noted — you already know that around ${result.locality ?? 'here'}. ` +
          'It will not come up again there.',
      )
    })

  // Change ranking weight for an existing interest without creating another fact.
  const updateInterestStrength = (interest: DiscoveryInterest, strength: number) =>
    perform('interest', async () => {
      await putDiscoveryInterest(userId, interest.label, strength)
      const label = strength === 1 ? 'Low' : strength === 3 ? 'High' : 'Normal'
      setNotice(`${interest.label} importance set to ${label.toLowerCase()}.`)
    })

  // Stop being away and return Scout to the saved home.
  const stopTravel = () =>
    perform('travel', async () => {
      await deleteDiscoveryTravelMode(userId)
      setNotice(`Travel mode off. Scout is back around ${savedPlace?.label ?? 'home'}.`)
    })

  // Restore one dismissed family to the current locality's future results.
  const undoKnown = (item: DiscoveryKnownItem) =>
    perform('known', async () => {
      await deleteDiscoveryKnown(userId, item.id)
      setNotice(`Restored ${item.label}. Similar finds can appear here again.`)
    })

  // A rehearsal: everything runs, nothing is recorded, so this can be repeated
  // while adjusting interests and comparing what comes back.
  const tryIt = () =>
    perform('try', async () => {
      const result = await runDiscoverySweep(userId, false)
      setPreview(null)
      setTrial(result)
      if (result.message === null) {
        setNotice('Nothing matched. Try a broader interest.')
      }
    })

  const showPreview = () =>
    perform('preview', async () => {
      const result = await previewDiscoveryDigest(userId)
      setPreview(result)
      if (result.message === null) {
        setNotice('Nothing to send yet. Run "Look now" first.')
      }
    })

  const subscribe = () =>
    perform('subscribe', async () => {
      const value = addressDraft.trim()
      if (!value) throw new Error('Enter the number or Apple ID to message.')
      const result = await requestSubscription(userId, 'imessage', value)
      setAddressDraft('')
      setNotice(
        result.approved
          ? 'Subscribed.'
          : 'Asked. It starts once the operator allows messages to that address.',
      )
    })

  const unsubscribe = () =>
    perform('subscribe', async () => {
      await cancelSubscription(userId)
      setNotice('Unsubscribed.')
    })

  const saveSchedule = () =>
    perform('schedule', async () => {
      const saved = await putDiscoverySchedule(userId, {
        cadence,
        hour,
        minute,
        weekday,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
      setNotice(`Scheduled. Next sweep ${new Date(saved.next_run_at).toLocaleString()}.`)
    })

  const stopSchedule = () =>
    perform('schedule', async () => {
      await deleteDiscoverySchedule(userId)
      setNotice('Schedule turned off. It will only run when you ask.')
    })

  // A sweep needs somewhere to look and something to look for. It does not need
  // a feed: search enumerates events from the place and interests alone, and
  // the runner treats feeds and search as independent contributors. Requiring
  // one here left "Look now" permanently dead for an account with a place, two
  // interests and no feeds - which a rehearsal proved finds real local events -
  // while "Try it", the same pipeline one flag apart, stayed enabled.
  const ready = Boolean(savedPlace) && interests.length > 0
  const missing = [
    savedPlace ? '' : 'a place',
    interests.length > 0 ? '' : 'at least one interest',
  ].filter(Boolean)

  return (
    <div className="mt-5 border-t border-black/[0.05] pt-5">
      {error && (
        <p className="mb-3 rounded-xl bg-[#fff1f0] px-3 py-2 text-xs text-[#b3261e]">{error}</p>
      )}
      {notice && (
        <p className="mb-3 rounded-xl bg-[#f0f7ff] px-3 py-2 text-xs text-[#0055b3]">{notice}</p>
      )}

      <section className="mb-5">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
          Where to look
        </h4>
        <div className="flex flex-wrap gap-2">
          <input
            value={place}
            onChange={event => setPlace(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void savePlace()
              }
            }}
            placeholder="Town or city"
            aria-label="Town or city"
            className="h-10 min-w-0 flex-1 rounded-xl border border-black/[0.08] px-3 text-sm outline-none focus:border-[#0071e3]"
          />
          <button
            onClick={() => void savePlace()}
            disabled={busy !== ''}
            className="flex h-10 items-center gap-1.5 rounded-xl bg-[#1d1d1f] px-3 text-sm font-medium text-white disabled:opacity-40"
          >
            <Check size={15} /> Save
          </button>
          <button
            onClick={() => void useMyLocation()}
            disabled={busy !== ''}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-black/[0.08] px-3 text-sm font-medium text-[#1d1d1f] disabled:opacity-40"
          >
            {busy === 'locate' ? <Loader2 size={15} className="animate-spin" /> : <MapPin size={15} />}
            Use my location
          </button>
        </div>
        {savedPlace ? (
          <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-[#248a3d]">
            <Check size={13} />
            Saved — looking around {describePlace(savedPlace)}
            {place.trim() && place.trim() !== savedPlace.label && (
              <span className="font-normal text-[#b25e00]">· unsaved edit</span>
            )}
          </p>
        ) : (
          <p className="mt-2 text-xs font-medium text-[#b25e00]">No place saved yet.</p>
        )}
        <p className="mt-2 text-[11px] leading-4 text-[#86868b]">
          Your browser will ask permission. The coordinate is rounded to about a kilometre
          before a single lookup names the town, and only the town is stored — never
          coordinates.
        </p>
      </section>

      {/* Being away is a fact, not a mode. It used to be a switch someone had
          to remember to turn off, and a forgotten one left Scout searching a
          city they had left months ago — silently, because a digest about the
          wrong place still looks like a working digest. Now reporting a
          location says it, and it lapses on its own. */}
      {activeTravel && (
        <section className="mb-5 rounded-2xl border border-black/[0.06] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <MapPin size={14} className="text-[#248a3d]" />
            <span className="min-w-0 flex-1 text-sm font-medium text-[#1d1d1f]">
              Looking around {describePlace(activeTravel)}
              {savedPlace && (
                <span className="font-normal text-[#86868b]">
                  {' '}· you live in {describePlace(savedPlace)}
                </span>
              )}
            </span>
            <button
              onClick={() => void stopTravel()}
              disabled={busy !== ''}
              className="h-9 rounded-full border border-black/[0.08] px-3 text-xs font-medium disabled:opacity-40"
            >
              Back to {savedPlace?.label ?? 'home'}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-[#86868b]">
            {activeTravel.travel_expires_at
              ? `Back to ${savedPlace?.label ?? 'home'} by itself on ${new Date(activeTravel.travel_expires_at).toLocaleDateString()}. What you already know at home is kept separate.`
              : 'What you already know at home is kept separate.'}
          </p>
          {/* Asked once, because a coordinate cannot tell visiting from moving,
              and silently choosing "moved" rewrites where someone lives. */}
          {movedPrompt && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-[#f5f5f7] p-2">
              <span className="min-w-0 flex-1 text-xs text-[#1d1d1f]">
                Visiting {movedPrompt}, or did you move here?
              </span>
              <button
                onClick={() => setMovedPrompt('')}
                disabled={busy !== ''}
                className="h-8 rounded-full border border-black/[0.08] bg-white px-3 text-xs font-medium disabled:opacity-40"
              >
                Just visiting
              </button>
              <button
                onClick={() => void confirmMoved()}
                disabled={busy !== ''}
                className="h-8 rounded-full bg-[#1d1d1f] px-3 text-xs font-medium text-white disabled:opacity-40"
              >
                I moved here
              </button>
            </div>
          )}
        </section>
      )}

      {known.length > 0 && (
        <section className="mb-5 rounded-2xl border border-black/[0.06] bg-[#f5f5f7] p-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Hidden {knownLocality ? `around ${knownLocality}` : 'here'}
          </h4>
          <p className="mt-1 text-[11px] leading-4 text-[#86868b]">
            These were dismissed as already familiar. Undo one to let similar finds appear again.
          </p>
          <div className="mt-2 space-y-1.5">
            {known.map(item => (
              <div key={item.id} className="flex items-center gap-2 rounded-xl bg-white px-3 py-2">
                <span className="min-w-0 flex-1 truncate text-sm">{item.label}</span>
                <button
                  onClick={() => void undoKnown(item)}
                  disabled={busy !== ''}
                  aria-label={`Undo dismissal of ${item.label}`}
                  className="flex h-7 items-center gap-1 rounded-full px-2 text-xs font-medium text-[#0071e3] hover:bg-[#e8f2ff] disabled:opacity-40"
                >
                  <Undo2 size={12} /> Undo
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mb-5">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Interests
          </h4>
          <button
            onClick={() => void suggestInterests()}
            disabled={busy !== ''}
            className="flex items-center gap-1 text-xs font-medium text-[#0071e3] disabled:opacity-40"
          >
            <Sparkles size={13} /> Suggest from memory
          </button>
        </div>
        <div className="mb-2 flex flex-wrap gap-2">
          {interests.map(interest => (
            <div
              key={interest.id}
              className="flex items-center gap-1.5 rounded-xl bg-[#f5f5f7] py-1 pl-3 pr-1.5 text-sm"
            >
              <span>{interest.label}</span>
              <select
                value={interest.strength}
                onChange={event =>
                  void updateInterestStrength(interest, Number(event.target.value))
                }
                disabled={busy !== ''}
                aria-label={`Importance of ${interest.label}`}
                className="h-6 rounded-md border-0 bg-white px-1 text-[11px] text-[#6e6e73] outline-none"
              >
                <option value={1}>Low</option>
                <option value={2}>Normal</option>
                <option value={3}>High</option>
              </select>
              <button
                aria-label={`Remove ${interest.label}`}
                onClick={() =>
                  void perform('interest', () => deleteDiscoveryInterest(userId, interest.id))
                }
                className="flex h-5 w-5 items-center justify-center rounded-full text-[#86868b] hover:bg-black/[0.06] hover:text-[#1d1d1f]"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {interests.length === 0 && (
            <span className="text-sm text-[#86868b]">Nothing yet.</span>
          )}
        </div>
        {interestProposals.length > 0 && (
          <div className="mb-2 rounded-xl bg-[#f5f5f7] p-3">
            <p className="mb-2 text-[11px] text-[#6e6e73]">From memory you already approved:</p>
            <div className="flex flex-wrap gap-2">
              {interestProposals.map(proposal => (
                <button
                  key={proposal.label}
                  title={proposal.evidence}
                  onClick={() => void addInterest(proposal.label)}
                  className="flex items-center gap-1 rounded-full bg-white px-3 py-1 text-sm hover:bg-[#0071e3] hover:text-white"
                >
                  <Plus size={12} /> {proposal.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <input
            value={interestDraft}
            onChange={event => setInterestDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void addInterest(interestDraft)
              }
            }}
            placeholder="Add an interest"
            aria-label="Add an interest"
            className="h-10 min-w-0 flex-1 rounded-xl border border-black/[0.08] px-3 text-sm outline-none focus:border-[#0071e3]"
          />
          <button
            onClick={() => void addInterest(interestDraft)}
            disabled={busy !== ''}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-black/[0.08] px-3 text-sm font-medium disabled:opacity-40"
          >
            <Plus size={15} /> Add
          </button>
        </div>
      </section>

      {usage && (
        <section className="mb-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Internet searches
          </h4>
          <div className="rounded-xl bg-[#f5f5f7] px-3 py-2.5">
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-[#1d1d1f]">
                <strong>{usage.today.used}</strong> of {usage.today.limit} today
              </span>
              <span className="text-[12px] text-[#86868b]">
                {usage.month.used} of {usage.month.limit} this month
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-black/[0.07]">
              <div
                className={`h-full rounded-full ${
                  usage.today.remaining === 0 ? 'bg-[#b42318]' : 'bg-[#0071e3]'
                }`}
                style={{
                  width: `${Math.min(
                    100,
                    usage.today.limit > 0
                      ? (usage.today.used / usage.today.limit) * 100
                      : 0,
                  )}%`,
                }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-[#86868b]">
              {usage.today.remaining === 0
                ? 'Daily limit reached. It resets at midnight UTC.'
                : 'Shared across everyone using this machine. Resets daily.'}
            </p>
          </div>
        </section>
      )}

      <section className="mb-5">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Places to watch
          </h4>
          <button
            onClick={() => void suggestFeeds()}
            disabled={busy !== '' || !savedPlace}
            className="flex items-center gap-1 text-xs font-medium text-[#0071e3] disabled:opacity-40"
          >
            {busy === 'suggest-feeds' ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Sparkles size={13} />
            )}
            Look again
          </button>
        </div>
        <div className="mb-2 space-y-1.5">
          {sources.map(source => (
            <div
              key={source.id}
              className="flex items-center gap-2 rounded-xl bg-[#f5f5f7] px-3 py-2"
            >
              <Rss size={14} className="flex-none text-[#86868b]" />
              <span className="min-w-0 flex-1 truncate text-sm">{source.label || source.url}</span>
              {source.last_error && (
                <span className="flex-none text-[11px] text-[#b25e00]">unreadable</span>
              )}
              <button
                aria-label={`Remove ${source.url}`}
                onClick={() =>
                  void perform('feed', () => deleteDiscoverySource(userId, source.id))
                }
                className="flex h-6 w-6 flex-none items-center justify-center rounded-full text-[#86868b] hover:bg-black/[0.06] hover:text-[#1d1d1f]"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {sources.length === 0 && <span className="text-sm text-[#86868b]">Nothing yet.</span>}
        </div>
        {feedCandidates.length > 0 && (
          <div className="mb-2 space-y-2 rounded-xl bg-[#f5f5f7] p-3">
            <p className="text-[11px] text-[#6e6e73]">
              Each one was fetched and parsed before being offered:
            </p>
            {feedCandidates.map(candidate => (
              <div key={candidate.url} className="rounded-lg bg-white p-2.5">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {candidate.title}
                  </span>
                  <span className="flex-none text-[11px] text-[#86868b]">
                    {candidate.event_count} events
                  </span>
                  <button
                    onClick={() => void addFeed(candidate.kind, candidate.url)}
                    className="flex h-7 flex-none items-center gap-1 rounded-full bg-[#1d1d1f] px-2.5 text-xs font-medium text-white"
                  >
                    <Plus size={12} /> Add
                  </button>
                </div>
                {candidate.sample_titles.length > 0 && (
                  <p className="mt-1 truncate text-[11px] text-[#86868b]">
                    {candidate.sample_titles.join(' · ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="mb-2 text-[12px] leading-5 text-[#86868b]">
          Scout finds these itself from your location. Nothing to set up — this
          is only here so you can see what it is watching and drop anything you
          do not want.
        </p>
      </section>

      <section className="mb-5">
        <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
          <Send size={13} /> Where to send it
        </h4>
        {subscription ? (
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${subscription.approved ? 'bg-[#e8f5ec] text-[#248a3d]' : 'bg-[#fff4e5] text-[#b25e00]'}`}
            >
              {subscription.approved ? 'Subscribed' : 'Waiting for approval'}
            </span>
            <span className="text-xs text-[#6e6e73]">
              {subscription.channel} · {subscription.delivery_count} sent
            </span>
            <button
              onClick={() => void unsubscribe()}
              disabled={busy !== ''}
              className="ml-auto text-xs font-medium text-[#b3261e] disabled:opacity-40"
            >
              Unsubscribe
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <input
              value={addressDraft}
              onChange={event => setAddressDraft(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void subscribe()
                }
              }}
              placeholder="Your number or Apple ID"
              aria-label="Your number or Apple ID"
              className="h-10 min-w-0 flex-1 rounded-xl border border-black/[0.08] px-3 text-sm outline-none focus:border-[#0071e3]"
            />
            <button
              onClick={() => void subscribe()}
              disabled={busy !== ''}
              className="flex h-10 items-center gap-1.5 rounded-xl bg-[#1d1d1f] px-3 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy === 'subscribe' ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
              Subscribe
            </button>
          </div>
        )}
        <p className="mt-2 text-[11px] leading-4 text-[#86868b]">
          Messages come from the operator&apos;s iMessage, so a new address has to be
          allowed once before anything is sent.
        </p>
      </section>

      <section className="mb-5">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            <Clock size={13} /> When to look
          </h4>
          {schedule && (
            <button
              onClick={() => void stopSchedule()}
              disabled={busy !== ''}
              className="text-xs font-medium text-[#b3261e] disabled:opacity-40"
            >
              Turn off
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={cadence}
            onChange={event => setCadence(event.target.value as 'daily' | 'weekly')}
            aria-label="How often"
            className="h-10 rounded-xl border border-black/[0.08] bg-white px-3 text-sm outline-none focus:border-[#0071e3]"
          >
            <option value="weekly">Weekly</option>
            <option value="daily">Daily</option>
          </select>
          {cadence === 'weekly' && (
            <select
              value={weekday}
              onChange={event => setWeekday(Number(event.target.value))}
              aria-label="Day of the week"
              className="h-10 rounded-xl border border-black/[0.08] bg-white px-3 text-sm outline-none focus:border-[#0071e3]"
            >
              {WEEKDAYS.map((label, index) => (
                <option key={label} value={index}>
                  {label}
                </option>
              ))}
            </select>
          )}
          <select
            value={hour}
            onChange={event => setHour(Number(event.target.value))}
            aria-label="Hour"
            className="h-10 rounded-xl border border-black/[0.08] bg-white px-3 text-sm outline-none focus:border-[#0071e3]"
          >
            {Array.from({ length: 24 }, (_, value) => (
              <option key={value} value={value}>
                {formatHour(value)}
              </option>
            ))}
          </select>
          <select
            value={minute}
            onChange={event => setMinute(Number(event.target.value))}
            aria-label="Minutes past the hour"
            className="h-10 rounded-xl border border-black/[0.08] bg-white px-3 text-sm outline-none focus:border-[#0071e3]"
          >
            {QUARTERS.map(value => (
              <option key={value} value={value}>
                :{String(value).padStart(2, '0')}
              </option>
            ))}
          </select>
          <button
            onClick={() => void saveSchedule()}
            disabled={busy !== '' || !ready}
            className="flex h-10 items-center gap-1.5 rounded-xl bg-[#1d1d1f] px-3 text-sm font-medium text-white disabled:opacity-40"
          >
            {busy === 'schedule' ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Check size={15} />
            )}
            {schedule ? 'Update' : 'Schedule'}
          </button>
        </div>
        {schedule ? (
          <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-[#248a3d]">
            <Check size={13} />
            Next sweep {new Date(schedule.next_run_at).toLocaleString()}
          </p>
        ) : (
          <p className="mt-2 text-xs font-medium text-[#b25e00]">
            Not scheduled — it only runs when you press “Look now”.
          </p>
        )}
      </section>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => void sweepNow()}
          disabled={busy !== '' || !ready}
          className="flex h-10 items-center gap-2 rounded-xl bg-[#0071e3] px-4 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy === 'sweep' ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          Look now
        </button>
        <button
          onClick={() => void tryIt()}
          disabled={busy !== '' || !Boolean(savedPlace) || interests.length === 0}
          className="flex h-10 items-center gap-2 rounded-xl border border-black/[0.08] px-4 text-sm font-medium disabled:opacity-40"
        >
          {busy === 'try' ? <Loader2 size={15} className="animate-spin" /> : <FlaskConical size={15} />}
          Try it
        </button>
        <button
          onClick={() => void showPreview()}
          disabled={busy !== ''}
          className="flex h-10 items-center gap-2 rounded-xl border border-black/[0.08] px-4 text-sm font-medium disabled:opacity-40"
        >
          {busy === 'preview' ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />}
          Preview message
        </button>
      </div>

      {trial?.message && (
        <div className="mt-3 rounded-xl border border-black/[0.08] bg-white p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            {trial.committed ? 'Found and saved' : 'Rehearsal — nothing was saved'}
          </p>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-5 text-[#1d1d1f]">
            {trial.message}
          </pre>
          {trial.selected.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {trial.selected.map(item => (
                <button
                  key={item.item_digest ?? item.title}
                  onClick={() => void markKnown(item.title, item.item_digest)}
                  disabled={busy !== ''}
                  title={`Stop showing "${item.title}" around here`}
                  className="flex items-center gap-1 rounded-full border border-black/[0.08] px-2.5 py-1 text-left text-[11px] text-[#6e6e73] hover:border-[#b25e00] hover:text-[#b25e00] disabled:opacity-40"
                >
                  <EyeOff size={11} className="shrink-0" />
                  {/* The full name, because this dismisses exactly this thing
                      and a truncated one reads as a category. */}
                  I know {item.title}
                </button>
              ))}
            </div>
          )}
          <p className="mt-3 border-t border-black/[0.05] pt-2 text-[11px] leading-4 text-[#86868b]">
            Read {trial.candidate_count} listings using {trial.requests_spent} search
            {trial.requests_spent === 1 ? ' request' : ' requests'}.
            {!trial.committed &&
              ' Run this as often as you like — it records nothing, so results stay comparable.'}
          </p>
        </div>
      )}

      {preview?.message && (
        <div className="mt-3 rounded-xl border border-black/[0.08] bg-white p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            What would be sent
          </p>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-5 text-[#1d1d1f]">
            {preview.message}
          </pre>
          <p className="mt-3 border-t border-black/[0.05] pt-2 text-[11px] leading-4 text-[#86868b]">
            {preview.recipients.length === 0
              ? 'No subscribers yet, so this would go nowhere.'
              : `To ${preview.recipients.length} subscriber${preview.recipients.length > 1 ? 's' : ''}.`}
            {!preview.egress_enabled && ' Sending is turned off.'}
            {!preview.calendar_links_reachable &&
              ' Calendar links would not open on a phone.'}
          </p>
          <p className="mt-1 text-[11px] leading-4 text-[#86868b]">
            Open an “Add” link on your phone to check the calendar half before any
            message is ever sent.
          </p>
        </div>
      )}
      {/* Name what is actually missing. "Needs a place, an interest and a feed"
          left someone holding two of the three with no way to tell which. */}
      {!ready && (
        <p className="mt-2 text-[11px] text-[#86868b]">
          Needs {missing.join(' and ')} before it can look.
        </p>
      )}
      {ready && sources.length === 0 && savedPlace && (
        <p className="mt-2 text-[11px] text-[#86868b]">
          Scout will search the web around {describePlace(savedPlace)}. Adding a
          feed gives it venue calendars with proper start times too.
        </p>
      )}
    </div>
  )
}

export default ScoutSetup
