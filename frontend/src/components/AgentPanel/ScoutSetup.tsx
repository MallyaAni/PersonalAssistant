import { useCallback, useEffect, useState } from 'react'
import { Check, Eye, Loader2, MapPin, Plus, Rss, Sparkles, Trash2 } from 'lucide-react'

import {
  deleteDiscoveryInterest,
  deleteDiscoverySource,
  getDiscoveryProfile,
  getDiscoverySources,
  putDiscoveryInterest,
  putDiscoveryLocality,
  putDiscoverySource,
  resolveDiscoveryLocality,
  previewDiscoveryDigest,
  runDiscoverySweep,
  suggestDiscoveryInterests,
  suggestDiscoverySources,
  type DiscoveryInterest,
  type DiscoveryLocality,
  type DiscoverySource,
  type DigestPreview,
  type FeedCandidate,
  type InterestProposal,
} from '../../services/api'

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
  const [interests, setInterests] = useState<DiscoveryInterest[]>([])
  const [sources, setSources] = useState<DiscoverySource[]>([])
  const [interestDraft, setInterestDraft] = useState('')
  const [feedDraft, setFeedDraft] = useState('')
  const [feedCandidates, setFeedCandidates] = useState<FeedCandidate[]>([])
  const [interestProposals, setInterestProposals] = useState<InterestProposal[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [preview, setPreview] = useState<DigestPreview | null>(null)

  const reload = useCallback(async () => {
    const [profile, feeds] = await Promise.all([
      getDiscoveryProfile(userId),
      getDiscoverySources(userId),
    ])
    setInterests(profile.interests)
    setSources(feeds)
    const primary = profile.localities.find(item => item.is_primary) ?? profile.localities[0]
    setSavedPlace(primary ?? null)
    if (primary && !place) setPlace(primary.label)
  }, [userId, place])

  useEffect(() => {
    void reload().catch(() => setError('Could not load the configuration.'))
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
      setPlace(resolved.label)
      await putDiscoveryLocality(userId, {
        label: resolved.label,
        // Region carries the country too: a town name alone is ambiguous, and
        // there is an Arlington in more than one country.
        region: resolved.stored_region ?? resolved.region,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      })
      setNotice(
        `Saved ${resolved.display}. Only the town was stored, never coordinates.`,
      )
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
      const value = url.trim()
      if (!value) throw new Error('Enter a feed address.')
      await putDiscoverySource(userId, { kind, url: value })
      setFeedDraft('')
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
      const result = await runDiscoverySweep(userId)
      setNotice(
        `Read ${result.candidate_count} events, ${result.novel_count} new, ` +
          `${result.selected.length} worth telling you about.`,
      )
    })

  const showPreview = () =>
    perform('preview', async () => {
      const result = await previewDiscoveryDigest(userId)
      setPreview(result)
      if (result.message === null) {
        setNotice('Nothing to send yet. Run "Look now" first.')
      }
    })

  const ready = Boolean(savedPlace) && interests.length > 0 && sources.length > 0

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
            <span
              key={interest.id}
              className="flex items-center gap-1.5 rounded-full bg-[#f5f5f7] py-1 pl-3 pr-1.5 text-sm"
            >
              {interest.label}
              <button
                aria-label={`Remove ${interest.label}`}
                onClick={() =>
                  void perform('interest', () => deleteDiscoveryInterest(userId, interest.id))
                }
                className="flex h-5 w-5 items-center justify-center rounded-full text-[#86868b] hover:bg-black/[0.06] hover:text-[#1d1d1f]"
              >
                <Trash2 size={12} />
              </button>
            </span>
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

      <section className="mb-5">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Feeds
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
            Find feeds near me
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
        <div className="flex gap-2">
          <input
            value={feedDraft}
            onChange={event => setFeedDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void addFeed('ics', feedDraft)
              }
            }}
            placeholder="Add a calendar feed address"
            aria-label="Add a calendar feed address"
            className="h-10 min-w-0 flex-1 rounded-xl border border-black/[0.08] px-3 text-sm outline-none focus:border-[#0071e3]"
          />
          <button
            onClick={() => void addFeed('ics', feedDraft)}
            disabled={busy !== ''}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-black/[0.08] px-3 text-sm font-medium disabled:opacity-40"
          >
            <Plus size={15} /> Add
          </button>
        </div>
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
          onClick={() => void showPreview()}
          disabled={busy !== ''}
          className="flex h-10 items-center gap-2 rounded-xl border border-black/[0.08] px-4 text-sm font-medium disabled:opacity-40"
        >
          {busy === 'preview' ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />}
          Preview message
        </button>
      </div>

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
      {!ready && (
        <p className="mt-2 text-[11px] text-[#86868b]">
          Needs a place, at least one interest, and at least one feed.
        </p>
      )}
    </div>
  )
}

export default ScoutSetup
