import { useCallback, useEffect, useState } from 'react'
import { CalendarPlus, EyeOff, Loader2 } from 'lucide-react'

import {
  getDiscoveryRuns,
  markDiscoveryKnown,
  type DiscoveryFind,
  type DiscoveryRun,
} from '../../services/api'

interface ScoutFindingsProps {
  userId: string;
}

// A find is worth reading at a glance: when it is, where, and a way to open it.
const describeWhen = (find: DiscoveryFind): string => {
  if (!find.starts_at) return 'No date given'
  return new Date(find.starts_at).toLocaleString([], {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// What Scout found, on the agent card itself.
//
// This lived inside the setup panel, behind a Configure button and below the
// place, interest and feed editors — so reading what the agent produced meant
// opening its configuration and scrolling past it. Findings are the output; the
// setup is the thing you touch once. They belong the other way round.
const ScoutFindings = ({ userId }: ScoutFindingsProps) => {
  const [runs, setRuns] = useState<DiscoveryRun[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [dismissing, setDismissing] = useState('')

  const load = useCallback(async () => {
    try {
      setRuns(await getDiscoveryRuns(userId, 5))
    } catch {
      setRuns([])
    } finally {
      setIsLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  // Dismissing from here carries the happening's own identity, so it records
  // that event rather than whatever its title happened to be.
  const dismiss = async (find: DiscoveryFind) => {
    setDismissing(find.item_digest ?? find.title)
    try {
      await markDiscoveryKnown(userId, find.title, find.item_digest)
      await load()
    } finally {
      setDismissing('')
    }
  }

  // The most recent sweep, whether or not it found anything. Picking the most
  // recent sweep *with* finds conflated two different states: "no sweep has run"
  // and "the last sweep found nothing" both rendered as "nothing found yet",
  // which reads as the feature being broken when it is working and empty-handed.
  const latest = runs[0]
  const lastWithFinds = runs.find(run => run.found.length > 0)

  if (isLoading) {
    return (
      <p className="mt-4 flex items-center gap-2 text-xs text-[#86868b]">
        <Loader2 size={13} className="animate-spin" /> Loading what Scout found…
      </p>
    )
  }

  if (!latest) {
    // Stated rather than left blank: an empty panel reads as broken, and the
    // honest reason is usually that no sweep has run yet.
    return (
      <p className="mt-4 border-t border-black/[0.05] pt-3 text-xs text-[#86868b]">
        No sweep has run yet. Scout posts what it finds here afterwards — you do
        not need the messaging set up to read it.
      </p>
    )
  }

  // A sweep that ran and found nothing is a different thing from never having
  // run, and saying which is the difference between "it is working" and "it is
  // broken". The date is what makes that checkable.
  if (latest.found.length === 0) {
    return (
      <div className="mt-4 border-t border-black/[0.05] pt-3">
        <p className="text-xs text-[#86868b]">
          Last sweep {new Date(latest.scheduled_for).toLocaleString()} found
          nothing.
        </p>
        {lastWithFinds && (
          <p className="mt-1 text-[11px] text-[#86868b]">
            Previously, on{' '}
            {new Date(lastWithFinds.scheduled_for).toLocaleDateString()}, it
            found {lastWithFinds.found.length}.
          </p>
        )}
      </div>
    )
  }

  const findRow = (find: DiscoveryFind) => (
    <div
      key={find.item_digest ?? find.title}
      className="flex items-start gap-2 rounded-xl bg-[#f5f5f7] px-3 py-2"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-[#1d1d1f]">
          {find.url ? (
            <a
              href={find.url}
              target="_blank"
              rel="noreferrer"
              className="text-[#0071e3] hover:underline"
            >
              {find.title}
            </a>
          ) : (
            find.title
          )}
        </p>
        <p className="text-[11px] text-[#86868b]">
          {describeWhen(find)}
          {find.place ? ` · ${find.place}` : ''}
        </p>
      </div>
      {find.calendar_path && (
        <a
          href={find.calendar_path}
          aria-label={`Add ${find.title} to your calendar`}
          title="Add to calendar"
          className="mt-0.5 shrink-0 text-[#86868b] hover:text-[#0071e3]"
        >
          <CalendarPlus size={13} />
        </a>
      )}
      <button
        onClick={() => void dismiss(find)}
        disabled={dismissing !== ''}
        aria-label={`I already know ${find.title}`}
        title={`Stop showing "${find.title}" around here`}
        className="mt-0.5 shrink-0 text-[#86868b] hover:text-[#b25e00] disabled:opacity-40"
      >
        <EyeOff size={13} />
      </button>
    </div>
  )

  return (
    <div className="mt-4 border-t border-black/[0.05] pt-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
          Latest finds
        </h4>
        <span className="text-[11px] text-[#86868b]">
          {new Date(latest.scheduled_for).toLocaleDateString()}
          {/* Said plainly, because a sweep can succeed and send nothing. */}
          {latest.delivered ? ' · sent' : ' · not sent'}
        </span>
      </div>
      <div className="mt-2 space-y-1.5">
        {latest.found.slice(0, 4).map(findRow)}
      </div>
      {latest.found.length > 4 && (
        <p className="mt-1.5 text-[11px] text-[#86868b]">
          and {latest.found.length - 4} more
        </p>
      )}
      {/* Its own heading, below the matches, saying plainly why these are here.
          They match nothing that was asked for, so presenting them alongside
          real matches would make the digest look padded — and a reader who does
          not want them can skip the section whole. */}
      {(latest.notable?.length ?? 0) > 0 && (
        <div className="mt-3 border-t border-black/[0.05] pt-3">
          <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">
            Unusual around here
          </h4>
          <p className="mb-2 mt-0.5 text-[11px] text-[#86868b]">
            Not what you asked for — surfaced because nothing like it has come up
            before.
          </p>
          <div className="space-y-1.5">{latest.notable?.map(findRow)}</div>
        </div>
      )}
    </div>
  )
}

export default ScoutFindings
