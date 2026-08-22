import { useEffect, useState } from 'react'
import { CalendarClock, Pause, Play, RefreshCw, Trash2, Zap } from 'lucide-react'

import {
  deleteScheduledTask,
  deleteSkill,
  getAutomations,
  setScheduledTaskEnabled,
  type Automations,
} from '../../services/api'

interface AutomationPanelProps {
  userId: string;
}

// Show what the user has automated - the skills they taught and the tasks
// they scheduled - and let them pause, resume, or remove each. Both are
// created in conversation; this panel is where they are seen afterwards.
const AutomationPanel = ({ userId }: AutomationPanelProps) => {
  const [automations, setAutomations] = useState<Automations>({ skills: [], tasks: [] })
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  // Load again when the user or a refresh request changes.
  useEffect(() => {
    const controller = new AbortController()

    // Fetch owned automations and expose a visible failure when loading fails.
    const load = async () => {
      setIsLoading(true)
      setError('')
      try {
        setAutomations(await getAutomations(userId, controller.signal))
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : 'Unable to load automations.')
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }

    void load()
    return () => controller.abort()
  }, [refreshKey, userId])

  // Run one change, then reload so the panel shows what the server holds.
  const perform = async (action: () => Promise<unknown>, failure: string) => {
    setError('')
    try {
      await action()
      setRefreshKey(key => key + 1)
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : failure)
    }
  }

  return (
    <section className="min-h-0 flex-1 overflow-y-auto bg-[#f5f5f7] px-5 py-8 md:px-8 md:py-12">
      <div className="mx-auto max-w-[980px]">
        <header className="mb-7 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#0071e3]">Skills and scheduled tasks</p>
            <h2 className="mt-1 text-3xl font-semibold tracking-[-0.035em] text-[#1d1d1f]">Automations</h2>
            <p className="mt-2 max-w-[640px] text-sm text-[#6e6e73]">
              Teach a skill in chat (&ldquo;when I say morning brief, give me the weather and my tasks&rdquo;)
              and schedule anything (&ldquo;every weekday at 7am, check the spark temps&rdquo;). They show up here.
            </p>
          </div>
          <button
            type="button"
            aria-label="Refresh automations"
            onClick={() => setRefreshKey(key => key + 1)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-black/10 bg-white hover:bg-[#f5f5f7]"
          >
            <RefreshCw size={17} />
          </button>
        </header>
        {error && <p role="alert" className="mb-4 text-sm text-[#c9342f]">{error}</p>}
        {isLoading ? (
          <p role="status" className="animate-pulse text-sm text-[#6e6e73]">Loading automations...</p>
        ) : (
          <div className="space-y-10">
            <section aria-label="Skills">
              <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold text-[#1d1d1f]">
                <Zap size={17} className="text-[#0071e3]" /> Skills
              </h3>
              {automations.skills.length === 0 ? (
                <div className="rounded-3xl border border-black/[0.06] bg-white p-6 text-sm text-[#6e6e73]">
                  No skills yet. Tell the assistant what a routine should do and what to call it.
                </div>
              ) : (
                <ul className="space-y-3">
                  {automations.skills.map(skill => (
                    <li key={skill.id} className="rounded-3xl border border-black/[0.06] bg-white p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="font-semibold text-[#1d1d1f]">
                            {skill.name}
                            {skill.source === 'pack' && (
                              <span className="ml-2 rounded-full bg-[#f5f5f7] px-2 py-0.5 text-[11px] font-medium text-[#6e6e73]">built in</span>
                            )}
                          </p>
                          <p className="mt-1 whitespace-pre-wrap text-sm text-[#6e6e73]">{skill.instruction}</p>
                          <p className="mt-2 text-xs text-[#86868b]">
                            {skill.use_count === 0 ? 'Never used' : `Used ${skill.use_count} time${skill.use_count === 1 ? '' : 's'}`}
                            {skill.last_used_at ? ` · last ${new Date(skill.last_used_at).toLocaleString()}` : ''}
                          </p>
                        </div>
                        {skill.source === 'user' && (
                          <button
                            type="button"
                            aria-label={`Delete skill ${skill.name}`}
                            onClick={() => void perform(() => deleteSkill(userId, skill.id), 'Unable to delete skill.')}
                            className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-black/10 hover:bg-[#f5f5f7]"
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-label="Scheduled tasks">
              <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold text-[#1d1d1f]">
                <CalendarClock size={17} className="text-[#0071e3]" /> Scheduled tasks
              </h3>
              {automations.tasks.length === 0 ? (
                <div className="rounded-3xl border border-black/[0.06] bg-white p-6 text-sm text-[#6e6e73]">
                  Nothing scheduled. Ask for something to happen later or on a schedule.
                </div>
              ) : (
                <ul className="space-y-3">
                  {automations.tasks.map(task => (
                    <li key={task.id} className={`rounded-3xl border border-black/[0.06] bg-white p-5 ${task.enabled ? '' : 'opacity-70'}`}>
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="font-semibold text-[#1d1d1f]">{task.instruction}</p>
                          <p className="mt-1 text-sm text-[#6e6e73]">
                            {task.schedule}
                            {task.enabled && task.next_run ? ` · next ${task.next_run}` : ''}
                            {!task.enabled ? ' · paused' : ''}
                          </p>
                          <p className="mt-2 text-xs text-[#86868b]">
                            Delivers by {task.channel === 'imessage' ? 'iMessage' : 'web'}
                            {task.last_status ? ` · last run ${task.last_status}` : ''}
                          </p>
                        </div>
                        <div className="flex flex-none gap-2">
                          {task.cadence !== 'once' && (
                            <button
                              type="button"
                              aria-label={task.enabled ? `Pause task ${task.instruction}` : `Resume task ${task.instruction}`}
                              onClick={() => void perform(
                                () => setScheduledTaskEnabled(userId, task.id, !task.enabled),
                                'Unable to update task.',
                              )}
                              className="flex h-9 w-9 items-center justify-center rounded-full border border-black/10 hover:bg-[#f5f5f7]"
                            >
                              {task.enabled ? <Pause size={15} /> : <Play size={15} />}
                            </button>
                          )}
                          <button
                            type="button"
                            aria-label={`Delete task ${task.instruction}`}
                            onClick={() => void perform(() => deleteScheduledTask(userId, task.id), 'Unable to delete task.')}
                            className="flex h-9 w-9 items-center justify-center rounded-full border border-black/10 hover:bg-[#f5f5f7]"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </section>
  )
}

export default AutomationPanel
