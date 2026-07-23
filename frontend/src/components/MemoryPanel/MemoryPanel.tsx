import { useEffect, useRef, useState } from 'react'
import {
  createMemory,
  clearPreferredName,
  deleteAllMemory,
  deleteMemory,
  exportMemory,
  getAgentMemorySnapshot,
  getMemorySnapshot,
  getToolMemorySnapshot,
  saveProfile,
  updateMemory,
  type AgentMemorySnapshot,
  type MemoryExport,
  type MemorySnapshot,
  type ToolMemorySnapshot,
} from '../../services/api'

interface MemoryPanelProps {
  userId: string
  onUserIdChange: (userId: string) => void
}

type MemoryDetailKey =
  | 'llm_context'
  | 'working'
  | 'semantic_cache'
  | 'procedures'
  | 'toolbox'
  | 'entities'
  | 'knowledge'
  | 'persona'
  | 'semantic'
  | 'episodic'
  | 'summaries'
  | 'conversations'

interface MemoryMapItem {
  key: MemoryDetailKey
  label: string
  value: string
  explanation: string
}

interface SelectedMemoryDetail extends MemoryMapItem {
  records: Array<Record<string, unknown>>
}

// Build an empty personal-memory snapshot for a user.
const emptySnapshot = (userId: string): MemorySnapshot => ({
  profile: { user_id: userId, preferences: {} },
  episodic: [],
  semantic: [],
  facts: [],
})

const emptyAgentSnapshot: AgentMemorySnapshot = {
  semantic_cache: 0,
  working: 0,
  procedures: 0,
  entities: 0,
  entity_relations: 0,
  knowledge_documents: 0,
  knowledge_chunks: 0,
  summaries: 0,
}

const emptyToolSnapshot: ToolMemorySnapshot = {
  descriptors: [],
  preferences: [],
  outcomes: [],
}

// Prefix records when one card combines several related stores.
const categorizedRecords = (
  category: string,
  records: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> => records.map(record => ({
  category,
  ...record,
}))

// Select the user-readable records represented by one memory-map card.
const recordsForDetail = (
  key: MemoryDetailKey,
  exported: MemoryExport,
  toolSnapshot: ToolMemorySnapshot,
): Array<Record<string, unknown>> => {
  const agent = exported.agent_memory
  switch (key) {
    case 'working':
      return agent.working || []
    case 'semantic_cache':
      return agent.semantic_cache || []
    case 'procedures':
      return agent.procedures || []
    case 'toolbox':
      return [
        ...categorizedRecords('descriptor', toolSnapshot.descriptors || []),
        ...categorizedRecords('preference', toolSnapshot.preferences || []),
        ...categorizedRecords('outcome', toolSnapshot.outcomes || []),
      ]
    case 'entities':
      return [
        ...categorizedRecords('entity', agent.entities || []),
        ...categorizedRecords('relation', agent.entity_relations || []),
      ]
    case 'knowledge':
      return [
        ...categorizedRecords('document', agent.knowledge_documents || []),
        ...categorizedRecords('chunk', agent.knowledge_chunks || []),
      ]
    case 'persona':
      return [
        { category: 'profile', ...exported.memory.profile },
        ...categorizedRecords('fact', exported.memory.facts || []),
      ]
    case 'semantic':
      return (exported.memory.semantic || []).map(record => ({ ...record }))
    case 'episodic':
      return (exported.memory.episodic || []).map(record => ({ ...record }))
    case 'summaries':
      return agent.summaries || []
    case 'conversations':
      return exported.conversations || []
    case 'llm_context':
      return []
  }
  return []
}

// Hide bulky vector and storage fields while retaining useful record details.
const visibleRecordEntries = (
  record: Record<string, unknown>,
): Array<[string, unknown]> => Object.entries(record).filter(([key]) => (
  !key.toLowerCase().includes('embedding')
  && key !== '_storage_key'
))

// Format one detail value without reducing nested provenance to "[object Object]".
const formatDetailValue = (value: unknown): string => {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

// Turn an internal field name into a compact readable label.
const formatDetailLabel = (key: string): string => (
  key.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase())
)

// Render memory controls and summaries for the active user.
const MemoryPanel: React.FC<MemoryPanelProps> = ({ userId, onUserIdChange }) => {
  const [snapshot, setSnapshot] = useState<MemorySnapshot>(() => emptySnapshot(userId))
  const [agentSnapshot, setAgentSnapshot] = useState<AgentMemorySnapshot>(emptyAgentSnapshot)
  const [toolSnapshot, setToolSnapshot] = useState<ToolMemorySnapshot>(emptyToolSnapshot)
  const [draftUserId, setDraftUserId] = useState(userId)
  const [name, setName] = useState('')
  const [responseStyle, setResponseStyle] = useState('')
  const [episodic, setEpisodic] = useState('')
  const [semantic, setSemantic] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedDetail, setSelectedDetail] = useState<SelectedMemoryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [cachedExport, setCachedExport] = useState<MemoryExport | null>(null)
  const [editing, setEditing] = useState<{
    type: 'episodic' | 'semantic'
    id: string
    content: string
  } | null>(null)
  const activeUserRef = useRef(userId)

  // Apply a loaded snapshot to the panel and editable profile fields.
  const applySnapshot = (next: MemorySnapshot) => {
    setSnapshot(next)
    setName(next.profile.name || '')
    setResponseStyle(String(next.profile.preferences.response_style || ''))
  }

  useEffect(() => {
    activeUserRef.current = userId
    setDraftUserId(userId)
    setSnapshot(emptySnapshot(userId))
    setAgentSnapshot(emptyAgentSnapshot)
    setToolSnapshot(emptyToolSnapshot)
    setSelectedDetail(null)
    setDetailError('')
    setCachedExport(null)
    setName('')
    setResponseStyle('')
    const controller = new AbortController()
    setIsLoading(true)
    setError('')

    void Promise.all([
      getMemorySnapshot(userId, controller.signal),
      getAgentMemorySnapshot(userId, controller.signal),
      getToolMemorySnapshot(userId, controller.signal),
    ])
      .then(([next, nextAgent, nextTools]) => {
        applySnapshot(next)
        setAgentSnapshot({ ...emptyAgentSnapshot, ...nextAgent })
        setToolSnapshot({ ...emptyToolSnapshot, ...nextTools })
      })
      .catch(err => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Unable to load memory.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => controller.abort()
  }, [userId])

  // Run a memory mutation and refresh all visible memory categories.
  const run = async (action: () => Promise<unknown>, clear?: () => void) => {
    const actionUserId = userId
    setIsLoading(true)
    setError('')
    try {
      await action()
      clear?.()
      setCachedExport(null)
      setSelectedDetail(null)
      const [next, nextAgent, nextTools] = await Promise.all([
        getMemorySnapshot(actionUserId),
        getAgentMemorySnapshot(actionUserId),
        getToolMemorySnapshot(actionUserId),
      ])
      if (activeUserRef.current === actionUserId) {
        applySnapshot(next)
        setAgentSnapshot({ ...emptyAgentSnapshot, ...nextAgent })
        setToolSnapshot({ ...emptyToolSnapshot, ...nextTools })
      }
    } catch (err) {
      if (activeUserRef.current === actionUserId) {
        setError(err instanceof Error ? err.message : 'Memory operation failed.')
      }
    } finally {
      if (activeUserRef.current === actionUserId) setIsLoading(false)
    }
  }

  // Download the active user's memory export as JSON.
  const downloadExport = async () => {
    setIsLoading(true)
    setError('')
    try {
      const exported = await exportMemory(userId)
      const url = URL.createObjectURL(new Blob(
        [JSON.stringify(exported, null, 2)],
        { type: 'application/json' },
      ))
      const link = document.createElement('a')
      link.href = url
      link.download = `anios-memory-${userId}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to export memory.')
    } finally {
      setIsLoading(false)
    }
  }

  // Load and show the owned records behind one selected memory-map card.
  const openMemoryDetail = async (item: MemoryMapItem) => {
    setDetailError('')
    if (item.key === 'llm_context') {
      setSelectedDetail({ ...item, records: [] })
      return
    }

    const detailUserId = userId
    setSelectedDetail({ ...item, records: [] })
    setDetailLoading(true)
    try {
      const exported = cachedExport || await exportMemory(detailUserId)
      if (activeUserRef.current !== detailUserId) return
      setCachedExport(exported)
      setSelectedDetail({
        ...item,
        records: recordsForDetail(item.key, exported, toolSnapshot),
      })
    } catch (err) {
      if (activeUserRef.current === detailUserId) {
        setDetailError(err instanceof Error ? err.message : 'Unable to load memory details.')
      }
    } finally {
      if (activeUserRef.current === detailUserId) setDetailLoading(false)
    }
  }

  return (
    <section className="memory-panel flex-1 space-y-6 overflow-y-auto bg-[#f5f5f7] p-5 md:p-8" aria-label="Personal memory">
      <div>
        <p className="mb-2 text-sm font-medium text-[#0071e3]">Your context</p>
        <h2 className="text-[34px] font-semibold tracking-[-0.04em] md:text-[42px]">Personal Memory</h2>
        <p className="mt-2 text-sm text-slate-400">Review and control what AniOS remembers for the active local user.</p>
      </div>

      <form
        className="flex items-end gap-2"
        onSubmit={event => {
          event.preventDefault()
          onUserIdChange(draftUserId)
        }}
      >
        <label className="block flex-1 space-y-1">
          <span className="text-sm text-slate-300">Active user ID</span>
          <input
            aria-label="Active user ID"
            value={draftUserId}
            onChange={event => setDraftUserId(event.target.value)}
            minLength={1}
            maxLength={50}
            required
            className="w-full rounded border border-slate-700 bg-slate-900 p-2"
          />
        </label>
        <button
          disabled={isLoading || !draftUserId.trim() || draftUserId.trim() === userId}
          className="rounded bg-blue-600 px-3 py-2 disabled:bg-slate-700"
        >Switch user</button>
      </form>

      {error && <p role="alert" className="rounded border border-red-800 bg-red-950 p-3 text-red-200">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <form
          className="space-y-3 rounded border border-slate-800 bg-slate-900/50 p-4"
          onSubmit={event => {
            event.preventDefault()
            void run(() => saveProfile(userId, name, responseStyle))
          }}
        >
          <h3 className="font-semibold">Profile</h3>
          <input aria-label="Profile name" value={name} onChange={event => setName(event.target.value)} placeholder="Name" className="w-full rounded bg-slate-950 p-2" />
          <input aria-label="Response style" value={responseStyle} onChange={event => setResponseStyle(event.target.value)} placeholder="Response style" className="w-full rounded bg-slate-950 p-2" />
          <button disabled={isLoading} className="rounded bg-blue-600 px-3 py-2 disabled:bg-slate-700">Save profile</button>
          {snapshot.profile.name && (
            <button
              type="button"
              disabled={isLoading}
              onClick={() => void run(
                () => clearPreferredName(userId),
                () => setName(''),
              )}
              className="ml-2 rounded border border-red-800 px-3 py-2 text-red-300 disabled:text-slate-600"
            >Delete preferred name</button>
          )}
        </form>

      </div>

      <section aria-labelledby="agent-memory-map-heading" className="space-y-4">
        <div>
          <h3 id="agent-memory-map-heading" className="text-xl font-semibold">Agent memory map</h3>
          <p className="mt-1 text-sm text-slate-400">
            Short-term state is managed automatically. Durable memory is user-scoped, exportable, and deletable.
          </p>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <MemoryGroup
            title="Short term"
            items={[
              {
                key: 'llm_context',
                label: 'LLM context window',
                value: 'Bounded runtime context',
                explanation: 'The temporary prompt assembled for the current turn. It is not a durable store.',
              },
              {
                key: 'working',
                label: 'Session based',
                value: `${agentSnapshot.working} active items`,
                explanation: 'Active goals and facts kept available while work is in progress.',
              },
              {
                key: 'semantic_cache',
                label: 'Semantic cache',
                value: `${agentSnapshot.semantic_cache} cached plans`,
                explanation: 'Reusable plans matched by meaning so repeated requests can avoid duplicate reasoning.',
              },
            ]}
            onSelect={item => void openMemoryDetail(item)}
          />
          <MemoryGroup
            title="Long term"
            items={[
              {
                key: 'procedures',
                label: 'Procedural / workflow',
                value: `${agentSnapshot.procedures} approved procedures`,
                explanation: 'Approved reusable steps for completing recurring work.',
              },
              {
                key: 'toolbox',
                label: 'Toolbox',
                value: `${toolSnapshot.descriptors?.length || 0} tool descriptors`,
                explanation: 'Known tool descriptions, user preferences, and observed outcomes.',
              },
              {
                key: 'entities',
                label: 'Entity memory',
                value: `${agentSnapshot.entities} entities, ${agentSnapshot.entity_relations} relations`,
                explanation: 'Named people, places, projects, and the relationships between them.',
              },
              {
                key: 'knowledge',
                label: 'Knowledge base',
                value: `${agentSnapshot.knowledge_documents} documents, ${agentSnapshot.knowledge_chunks} chunks`,
                explanation: 'Durable source documents and their retrievable passages.',
              },
              {
                key: 'persona',
                label: 'Persona',
                value: `${snapshot.facts.length + (snapshot.profile.name ? 1 : 0)} approved profile facts`,
                explanation: 'The active user profile and explicitly approved personal facts.',
              },
              {
                key: 'semantic',
                label: 'Semantic',
                value: `${snapshot.semantic.length} facts and preferences`,
                explanation: 'Durable facts and preferences recalled by meaning.',
              },
              {
                key: 'episodic',
                label: 'Episodic',
                value: `${snapshot.episodic.length} events and experiences`,
                explanation: 'User-specific events and experiences with their provenance.',
              },
              {
                key: 'summaries',
                label: 'Summaries',
                value: `${agentSnapshot.summaries} conversation digests`,
                explanation: 'Bounded conversation digests used when full history is too large.',
              },
              {
                key: 'conversations',
                label: 'Conversational',
                value: 'Persistent user-scoped turn history',
                explanation: 'Persisted conversation turns and their identifiers.',
              },
            ]}
            onSelect={item => void openMemoryDetail(item)}
          />
        </div>
        {selectedDetail && (
          <section
            aria-label={`${selectedDetail.label} details`}
            className="rounded-2xl border border-black/[0.08] bg-white p-4 shadow-sm md:p-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h4 className="text-lg font-semibold text-[#1d1d1f]">{selectedDetail.label}</h4>
                <p className="mt-1 text-sm text-[#6e6e73]">{selectedDetail.explanation}</p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDetail(null)}
                className="rounded-full px-3 py-1.5 text-sm font-medium text-[#0066cc] hover:bg-[#f5f5f7]"
              >
                Close
              </button>
            </div>
            {detailLoading && <p className="mt-4 text-sm text-[#6e6e73]">Loading details...</p>}
            {detailError && <p role="alert" className="mt-4 text-sm text-[#c9342f]">{detailError}</p>}
            {!detailLoading && !detailError && selectedDetail.key === 'llm_context' && (
              <p className="mt-4 rounded-xl bg-[#f5f5f7] p-3 text-sm text-[#424245]">
                This context is assembled only while a message runs, then discarded. Durable inputs are shown in the other memory stores.
              </p>
            )}
            {!detailLoading && !detailError && selectedDetail.key !== 'llm_context' && selectedDetail.records.length === 0 && (
              <p className="mt-4 text-sm text-[#6e6e73]">No records are stored in this category.</p>
            )}
            {!detailLoading && !detailError && selectedDetail.records.length > 0 && (
              <div className="mt-4 space-y-3">
                <p className="text-xs font-medium uppercase tracking-wide text-[#86868b]">
                  {selectedDetail.records.length} {selectedDetail.records.length === 1 ? 'record' : 'records'}
                </p>
                {selectedDetail.records.slice(0, 50).map((record, index) => (
                  <dl key={String(record.id || index)} className="grid gap-2 rounded-xl bg-[#f5f5f7] p-3 sm:grid-cols-2">
                    {visibleRecordEntries(record).map(([key, value]) => (
                      <div key={key} className="min-w-0">
                        <dt className="text-xs font-medium text-[#6e6e73]">{formatDetailLabel(key)}</dt>
                        <dd className="mt-0.5 whitespace-pre-wrap break-words text-sm text-[#1d1d1f]">
                          {formatDetailValue(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ))}
                {selectedDetail.records.length > 50 && (
                  <p className="text-xs text-[#86868b]">Showing the first 50 records. Export memory to review the full set.</p>
                )}
              </div>
            )}
          </section>
        )}
      </section>

      <details className="rounded border border-slate-800 bg-slate-900/30 p-4">
        <summary className="cursor-pointer font-semibold">Advanced: add memory manually</summary>
        <p className="mt-2 text-sm text-slate-400">
          Normally AniOS should propose memories during conversation. These controls let you add one explicitly.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <form
            className="space-y-3 rounded border border-slate-800 bg-slate-900/50 p-4"
            onSubmit={event => {
              event.preventDefault()
              if (episodic.trim()) void run(() => createMemory(userId, 'episodic', episodic.trim()), () => setEpisodic(''))
            }}
          >
            <h3 className="font-semibold">Event or experience</h3>
            <textarea aria-label="Event or experience" value={episodic} onChange={event => setEpisodic(event.target.value)} placeholder="Something that happened" className="w-full rounded bg-slate-950 p-2" />
            <button disabled={isLoading || !episodic.trim()} className="rounded bg-blue-600 px-3 py-2 disabled:bg-slate-700">Add event or experience</button>
          </form>

          <form
            className="space-y-3 rounded border border-slate-800 bg-slate-900/50 p-4"
            onSubmit={event => {
              event.preventDefault()
              if (semantic.trim()) void run(() => createMemory(userId, 'semantic', semantic.trim()), () => setSemantic(''))
            }}
          >
            <h3 className="font-semibold">Fact or preference</h3>
            <textarea aria-label="Fact or preference" value={semantic} onChange={event => setSemantic(event.target.value)} placeholder="A durable fact or preference" className="w-full rounded bg-slate-950 p-2" />
            <button disabled={isLoading || !semantic.trim()} className="rounded bg-blue-600 px-3 py-2 disabled:bg-slate-700">Add fact or preference</button>
          </form>
        </div>
      </details>

      {(['episodic', 'semantic'] as const).map(memoryType => (
        <div key={memoryType} className="space-y-2">
          <h3 className="font-semibold">
            {memoryType === 'episodic' ? 'Events and experiences' : 'Facts and preferences'}
          </h3>
          {snapshot[memoryType].length === 0 && (
            <p className="text-sm text-slate-500">
              No {memoryType === 'episodic' ? 'events or experiences' : 'facts or preferences'} saved.
            </p>
          )}
          {snapshot[memoryType].map(memory => (
            <div key={memory.id} className="flex items-start justify-between gap-4 rounded border border-slate-800 bg-slate-900/50 p-3">
              {editing?.type === memoryType && editing.id === memory.id ? (
                <form
                  className="flex flex-1 gap-2"
                  onSubmit={event => {
                    event.preventDefault()
                    if (!editing.content.trim()) return
                    void run(
                      () => updateMemory(userId, memoryType, memory.id, editing.content.trim()),
                      () => setEditing(null),
                    )
                  }}
                >
                  <input
                    aria-label={`Correct ${memoryType} record`}
                    value={editing.content}
                    onChange={event => setEditing({ ...editing, content: event.target.value })}
                    className="flex-1 rounded bg-slate-950 p-2"
                  />
                  <button disabled={isLoading || !editing.content.trim()} className="text-sm text-blue-300">Save</button>
                  <button type="button" onClick={() => setEditing(null)} className="text-sm text-slate-300">Cancel</button>
                </form>
              ) : (
                <p className="flex-1">{memory.content}</p>
              )}
              <div className="flex gap-3">
                <button
                  aria-label={`Edit ${memoryType} record`}
                  disabled={isLoading}
                  onClick={() => setEditing({ type: memoryType, id: memory.id, content: memory.content })}
                  className="text-sm text-blue-300 hover:text-blue-200"
                >Edit</button>
                <button
                  aria-label={`Delete ${memoryType} record`}
                  disabled={isLoading}
                  onClick={() => void run(() => deleteMemory(userId, memoryType, memory.id))}
                  className="text-sm text-red-300 hover:text-red-200"
                >Delete</button>
              </div>
            </div>
          ))}
        </div>
      ))}

      <div className="flex gap-3">
        <button
          disabled={isLoading}
          onClick={() => void downloadExport()}
          className="rounded border border-blue-800 px-3 py-2 text-blue-300 disabled:text-slate-600"
        >Export personal memory</button>
        <button
          disabled={isLoading}
          onClick={() => {
            if (window.confirm(`Delete all personal memory for ${userId}?`)) {
              void run(() => deleteAllMemory(userId), () => {
                setName('')
                setResponseStyle('')
              })
            }
          }}
          className="rounded border border-red-800 px-3 py-2 text-red-300 disabled:text-slate-600"
        >Delete all personal memory</button>
      </div>
    </section>
  )
}

export default MemoryPanel

// Render one group of clickable memory-store summary cards.
const MemoryGroup: React.FC<{
  title: string
  items: MemoryMapItem[]
  onSelect: (item: MemoryMapItem) => void
}> = ({ title, items, onSelect }) => (
  <div className="rounded border border-slate-800 bg-slate-900/50 p-4">
    <h4 className="font-semibold">{title}</h4>
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      {items.map(item => (
        <button
          type="button"
          key={item.key}
          aria-label={`View ${item.label} details`}
          onClick={() => onSelect(item)}
          className="rounded-xl bg-white/70 p-3 text-left shadow-sm transition hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0071e3]"
        >
          <span className="block text-sm font-medium text-[#1d1d1f]">{item.label}</span>
          <span className="mt-1 block text-xs text-[#6e6e73]">{item.value}</span>
        </button>
      ))}
    </div>
  </div>
)
