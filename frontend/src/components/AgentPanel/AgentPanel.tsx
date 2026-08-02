import { useCallback, useEffect, useState } from 'react'
import {
  Bot,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Compass,
  Presentation,
  RefreshCw,
} from 'lucide-react'

import { getAgents, type AgentSummary } from '../../services/api'
import ScoutSetup from './ScoutSetup'

interface AgentPanelProps {
  userId: string;
}

// Each agent's live state is polled rather than pushed. A sweep runs on a
// weekly cadence, so a slow refresh is honest about how fast this can change.
const REFRESH_MS = 30_000

const STATUS_STYLE: Record<AgentSummary['status'], { label: string; dot: string; text: string }> = {
  working: { label: 'Working', dot: 'bg-[#0071e3]', text: 'text-[#0071e3]' },
  scheduled: { label: 'Scheduled', dot: 'bg-[#34c759]', text: 'text-[#248a3d]' },
  idle: { label: 'Idle', dot: 'bg-[#86868b]', text: 'text-[#6e6e73]' },
  needs_setup: { label: 'Needs setup', dot: 'bg-[#ff9f0a]', text: 'text-[#b25e00]' },
  disabled: { label: 'Off', dot: 'bg-[#d2d2d7]', text: 'text-[#86868b]' },
}

const ICONS: Record<string, typeof Bot> = {
  discovery: Compass,
  presentation: Presentation,
}

// Show when something last happened without making the reader parse a timestamp.
const formatLastActive = (value: string | null): string => {
  if (!value) return 'Never run'
  const moment = new Date(value)
  if (Number.isNaN(moment.getTime())) return 'Never run'
  const minutes = Math.floor((Date.now() - moment.getTime()) / 60_000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.floor(hours / 24)} d ago`
}

// List the specialized agents and what each is currently doing.
const AgentPanel = ({ userId }: AgentPanelProps) => {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  // Which agent's configuration is open. Only discovery has one today.
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) setIsLoading(true)
    try {
      setAgents(await getAgents(userId))
      setError('')
    } catch {
      setError('Could not load agents.')
    } finally {
      setIsLoading(false)
    }
  }, [userId])

  useEffect(() => {
    let cancelled = false
    const refresh = (spinner: boolean) => {
      if (!cancelled) void load(spinner)
    }
    refresh(true)
    const timer = window.setInterval(() => refresh(false), REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [load])

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-semibold tracking-[-0.02em]">Agents</h2>
            <p className="mt-1 text-sm text-[#6e6e73]">
              Specialized workers that act on your behalf. Each one runs in its own process.
            </p>
          </div>
          <button
            aria-label="Refresh agents"
            onClick={() => void load(true)}
            className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-black/[0.08] bg-white text-[#1d1d1f] hover:bg-[#f5f5f7]"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {error && (
          <p className="mb-4 rounded-2xl bg-[#fff1f0] px-4 py-3 text-sm text-[#b3261e]">{error}</p>
        )}

        {isLoading && agents.length === 0 ? (
          <p className="text-sm text-[#86868b]">Loading agents…</p>
        ) : (
          <div className="space-y-4">
            {agents.map(agent => {
              const style = STATUS_STYLE[agent.status] ?? STATUS_STYLE.idle
              const Icon = ICONS[agent.id] ?? Bot
              return (
                <article
                  key={agent.id}
                  className="rounded-3xl border border-black/[0.06] bg-white p-5 shadow-sm"
                >
                  <div className="flex items-start gap-4">
                    <span className="flex h-11 w-11 flex-none items-center justify-center rounded-2xl bg-[#f5f5f7] text-[#1d1d1f]">
                      <Icon size={20} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <h3 className="text-[17px] font-semibold tracking-[-0.01em]">{agent.name}</h3>
                        <span className={`flex items-center gap-1.5 text-xs font-medium ${style.text}`}>
                          <span className={`h-2 w-2 rounded-full ${style.dot}`} />
                          {style.label}
                        </span>
                      </div>
                      <p className="mt-1 text-sm leading-5 text-[#6e6e73]">{agent.role}</p>
                      <p className="mt-2 text-sm font-medium text-[#1d1d1f]">{agent.detail}</p>

                      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
                        {agent.facts.map(fact => (
                          <span key={fact.label} className="text-xs text-[#6e6e73]">
                            <span className="font-semibold text-[#1d1d1f]">{fact.value}</span>{' '}
                            {fact.label.toLowerCase()}
                          </span>
                        ))}
                      </div>

                      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-black/[0.05] pt-3 text-xs text-[#86868b]">
                        <span className="flex items-center gap-1.5">
                          <CalendarClock size={13} />
                          {agent.trigger}
                        </span>
                        <span>Last active {formatLastActive(agent.last_active_at).toLowerCase()}</span>
                        {agent.id === 'discovery' && (
                          <button
                            onClick={() =>
                              setExpanded(current => (current === agent.id ? null : agent.id))
                            }
                            aria-expanded={expanded === agent.id}
                            className="ml-auto flex items-center gap-1 text-xs font-medium text-[#0071e3]"
                          >
                            {expanded === agent.id ? (
                              <ChevronDown size={13} />
                            ) : (
                              <ChevronRight size={13} />
                            )}
                            Configure
                          </button>
                        )}
                      </div>

                      {expanded === agent.id && agent.id === 'discovery' && (
                        <ScoutSetup userId={userId} onChanged={() => void load(false)} />
                      )}
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default AgentPanel
