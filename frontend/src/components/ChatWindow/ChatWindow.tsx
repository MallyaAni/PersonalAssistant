import React, { useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import MessageList from '../MessageList/MessageList'
import Composer from '../Composer/Composer'
import {
  approveEntity,
  approveKnowledge,
  approvePreferredName,
  approveProcedure,
  approveResponseStyle,
  getConversationSnapshot,
  type MemoryProposal,
  type ImageArtifact,
  type SearchSource,
  type ToolActivity,
  type VisualArtifact,
} from '../../services/api'

interface Message {
  role: 'user' | 'assistant';
  content: string;
  artifact?: VisualArtifact;
  artifactId?: string;
  artifactStatus?: 'generating' | 'failed';
  artifactError?: string;
  artifactActivity?: string;
  imageMatches?: ImageArtifact[];
  isSearching?: boolean;
  searchSources?: SearchSource[];
  searchMinimized?: boolean;
  searchBlocked?: string[];
  toolActivities?: ToolActivity[];
}

interface ChatWindowProps {
  userId: string;
  conversationId: string;
  restoreConversation: boolean;
}

// Return the accessible label for one proposal card.
const proposalLabel = (proposal: MemoryProposal) => ({
  preferred_name: 'Preferred name memory proposal',
  response_style: 'Response style memory proposal',
  entity: 'Entity memory proposal',
  procedure: 'Procedure memory proposal',
  knowledge: 'Knowledge memory proposal',
})[proposal.kind]

// Return the primary value shown for one proposal.
const proposalValue = (proposal: MemoryProposal) => {
  if (proposal.kind === 'preferred_name' || proposal.kind === 'response_style') {
    return proposal.value
  }
  if (proposal.kind === 'entity') return proposal.canonical_name
  if (proposal.kind === 'procedure') return proposal.name
  return proposal.title
}

// Return a plain-language name for one durable memory form.
const proposalType = (proposal: MemoryProposal) => ({
  preferred_name: 'preferred name',
  response_style: 'response style',
  entity: 'person or organization',
  procedure: 'reusable workflow',
  knowledge: 'reference knowledge',
})[proposal.kind]

// Find the newest assistant message without requiring a newer JavaScript runtime.
const latestAssistantIndex = (messages: Message[]) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'assistant') return index
  }
  return -1
}

// Find the assistant message that owns one streamed artifact identifier.
const artifactMessageIndex = (messages: Message[], artifactId: string) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].artifactId === artifactId) return index
  }
  return -1
}

// Rebuild persisted user and assistant messages and attach their visual artifacts.
const restoredMessages = (
  snapshot: Awaited<ReturnType<typeof getConversationSnapshot>>,
): Message[] => {
  const artifacts = new Map(
    snapshot.artifacts
      .filter(record => typeof record.id === 'string')
      .map(record => [record.id as string, record]),
  )
  const linkedArtifacts = new Set<string>()
  const transcript = snapshot.turns.flatMap(turn => {
    const artifactIds = Array.isArray(turn.metadata.artifact_ids)
      ? turn.metadata.artifact_ids.filter(id => typeof id === 'string') as string[]
      : []
    const artifactRecord = artifactIds.length ? artifacts.get(artifactIds[0]) : undefined
    if (artifactRecord) linkedArtifacts.add(artifactRecord.id as string)
    const assistant: Message = { role: 'assistant', content: turn.response }
    if (artifactRecord?.status === 'ready') {
      assistant.artifact = artifactRecord as unknown as VisualArtifact
      assistant.artifactId = artifactRecord.id as string
      assistant.content = `Trace: ${artifactRecord.trace_id}\nConversation: ${turn.conversation_id}\nResponse: ${turn.response}`
    } else if (artifactRecord?.status === 'failed') {
      assistant.artifactId = artifactRecord.id as string
      assistant.artifactStatus = 'failed'
      assistant.artifactError = 'Unable to create the diagram.'
    }
    return [
      { role: 'user', content: turn.query } satisfies Message,
      assistant,
    ]
  })
  const standaloneImages: Message[] = []
  for (const record of snapshot.artifacts) {
    if (
      linkedArtifacts.has(String(record.id)) ||
      !['generated_image', 'uploaded_image'].includes(String(record.kind))
    ) continue
    if (record.status === 'ready') {
      const artifact = record as ImageArtifact
      standaloneImages.push({
        role: 'assistant' as const,
        content: artifact.kind === 'generated_image'
          ? 'Restored generated image.'
          : 'Restored uploaded image analysis.',
        artifact,
        artifactId: artifact.id,
      })
    } else if (record.status === 'failed') {
      standaloneImages.push({
        role: 'assistant' as const,
        content: 'A previous visual request did not complete.',
        artifactId: String(record.id),
        artifactStatus: 'failed' as const,
        artifactError: 'Unable to complete the visual request.',
      })
    }
  }
  return [...transcript, ...standaloneImages]
}

// Render the chat transcript, memory approvals, and message composer.
const ChatWindow: React.FC<ChatWindowProps> = ({
  userId,
  conversationId,
  restoreConversation,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [memoryProposal, setMemoryProposal] = useState<MemoryProposal | null>(null)
  const [memoryNotice, setMemoryNotice] = useState('')
  const [memoryError, setMemoryError] = useState('')
  const [isSavingMemory, setIsSavingMemory] = useState(false)
  const [isThinking, setIsThinking] = useState(false)
  const [isRestoring, setIsRestoring] = useState(restoreConversation)
  const [restoreError, setRestoreError] = useState('')

  // Restore the persisted transcript only when this conversation survived a reload.
  useEffect(() => {
    if (!restoreConversation) return
    const controller = new AbortController()

    // Fetch and display the owned conversation snapshot from the backend.
    const restore = async () => {
      try {
        const snapshot = await getConversationSnapshot(
          userId,
          conversationId,
          controller.signal,
        )
        setMessages(restoredMessages(snapshot))
        setRestoreError('')
      } catch (error) {
        if (!controller.signal.aborted) {
          setRestoreError(
            error instanceof Error
              ? error.message
              : 'Unable to restore this conversation.',
          )
        }
      } finally {
        if (!controller.signal.aborted) setIsRestoring(false)
      }
    }

    void restore()
    return () => controller.abort()
  }, [conversationId, restoreConversation, userId])

  // Append a complete user or assistant message to the transcript.
  const handleNewMessage = (role: 'user' | 'assistant', content: string) => {
    setMessages(prev => [...prev, { role, content }])
  }

  // Append streamed assistant text to the latest response.
  const handleStreamUpdate = (content: string) => {
    setMessages(prev => {
      const lastMsg = prev[prev.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        const newMsgs = [...prev]
        newMsgs[newMsgs.length - 1] = { ...lastMsg, content: lastMsg.content + content }
        return newMsgs
      }
      return [...prev, { role: 'assistant', content }]
    })
  }

  // Display a memory proposal for explicit user approval.
  const handleMemoryProposal = (proposal: MemoryProposal) => {
    setMemoryProposal(proposal)
    setMemoryNotice('')
    setMemoryError('')
  }

  // Mark the latest assistant response as actively generating a diagram.
  const handleArtifactStarted = (artifactId: string) => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          artifactId,
          artifactStatus: 'generating',
          artifactError: undefined,
          artifactActivity: 'Generating diagram...',
        }
      }
      return next
    })
  }

  // Attach a completed diagram to the latest matching assistant response.
  const handleArtifactReady = (artifact: VisualArtifact) => {
    setMessages(prev => {
      const next = [...prev]
      const index = artifactMessageIndex(next, artifact.id)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          artifact,
          artifactStatus: undefined,
          artifactError: undefined,
        }
      }
      return next
    })
  }

  // Expose one diagram-generation failure on its matching assistant response.
  const handleArtifactError = (artifactId: string, message: string) => {
    setMessages(prev => {
      const next = [...prev]
      const index = artifactMessageIndex(next, artifactId)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          artifactStatus: 'failed',
          artifactError: message,
        }
      }
      return next
    })
  }

  // Add an assistant placeholder while a local visual request is running.
  const handleVisualStarted = (mode: 'generate' | 'analyze') => {
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: mode === 'generate' ? 'Creating your image locally.' : 'Inspecting your image with Gemma.',
      artifactStatus: 'generating',
      artifactActivity: mode === 'generate' ? 'Generating image...' : 'Analyzing image...',
    }])
  }

  // Attach a completed generated or uploaded image to its running placeholder.
  // Mark the pending assistant turn as searching so the interface can say so.
  const handleSearchStarted = (minimized: boolean) => {
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant') {
          next[index] = { ...next[index], isSearching: true, searchMinimized: minimized }
          return next
        }
      }
      return [...next, { role: 'assistant', content: '', isSearching: true, searchMinimized: minimized }]
    })
  }

  // Report that a search was withheld because the query carried private data.
  const handleSearchBlocked = (categories: string[]) => {
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant') {
          next[index] = { ...next[index], isSearching: false, searchBlocked: categories }
          return next
        }
      }
      return [...next, { role: 'assistant', content: '', searchBlocked: categories }]
    })
  }

  // Replace the searching indicator with the sources actually consulted.
  const handleSearchSources = (sources: SearchSource[]) => {
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant') {
          next[index] = { ...next[index], isSearching: false, searchSources: sources }
          return next
        }
      }
      return next
    })
  }

  // Show a running MCP tool on the assistant response that owns the turn.
  const handleToolStarted = (activity: ToolActivity) => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          toolActivities: [...(next[index].toolActivities || []), activity],
        }
      }
      return next
    })
  }

  // Replace one running tool with its visible terminal outcome.
  const handleToolFinished = (activity: ToolActivity) => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index < 0) return next
      const current = next[index].toolActivities || []
      const match = current.findIndex(item => (
        item.serverId === activity.serverId && item.toolName === activity.toolName
      ))
      const toolActivities = [...current]
      if (match >= 0) toolActivities[match] = activity
      else toolActivities.push(activity)
      next[index] = { ...next[index], toolActivities }
      return next
    })
  }

  // Attach pixel-matched images to the assistant turn that requested them.
  const handleImageMatches = (artifacts: ImageArtifact[]) => {
    if (artifacts.length === 0) return
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant') {
          next[index] = { ...next[index], imageMatches: artifacts }
          return next
        }
      }
      return [...next, { role: 'assistant', content: '', imageMatches: artifacts }]
    })
  }

  const handleVisualReady = (artifact: ImageArtifact) => {
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant' && next[index].artifactStatus === 'generating') {
          next[index] = {
            ...next[index],
            artifact,
            artifactId: artifact.id,
            artifactStatus: undefined,
            artifactError: undefined,
            artifactActivity: undefined,
          }
          break
        }
      }
      return next
    })
  }

  // Expose a visual request failure and clear its running state.
  const handleVisualError = (message: string) => {
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant' && next[index].artifactStatus === 'generating') {
          next[index] = {
            ...next[index],
            artifactStatus: 'failed',
            artifactError: message,
            artifactActivity: undefined,
          }
          break
        }
      }
      return next
    })
  }

  // Remove a deleted image from the visible transcript without deleting its text.
  const handleVisualDeleted = (artifactId: string) => {
    setMessages(prev => prev.map(message => message.artifact?.id === artifactId
      ? { ...message, artifact: undefined, artifactId: undefined, content: 'Image deleted.' }
      : message))
  }

  // Save the visible memory proposal after the user approves it.
  const approveMemoryProposal = async () => {
    if (!memoryProposal || isSavingMemory) return
    setIsSavingMemory(true)
    setMemoryError('')
    try {
      if (memoryProposal.kind === 'preferred_name') {
        await approvePreferredName(userId, memoryProposal)
      } else if (memoryProposal.kind === 'response_style') {
        await approveResponseStyle(userId, memoryProposal)
      } else if (memoryProposal.kind === 'entity') {
        await approveEntity(userId, memoryProposal)
      } else if (memoryProposal.kind === 'procedure') {
        await approveProcedure(userId, memoryProposal)
      } else {
        await approveKnowledge(userId, memoryProposal)
      }
      setMemoryNotice(
        `Saved ${proposalType(memoryProposal)}: ${proposalValue(memoryProposal)}`,
      )
      setMemoryProposal(null)
    } catch (error) {
      setMemoryError(
        error instanceof Error ? error.message : 'Unable to save memory.',
      )
    } finally {
      setIsSavingMemory(false)
    }
  }

  // Dismiss the visible memory proposal without saving it.
  const rejectMemoryProposal = () => {
    const type = memoryProposal ? proposalType(memoryProposal) : ''
    setMemoryNotice(type ? `${type[0].toUpperCase()}${type.slice(1)} was not saved.` : '')
    setMemoryError('')
    setMemoryProposal(null)
  }

  const hasMessages = messages.length > 0

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[#f5f5f7]">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isRestoring ? (
          <div className="flex min-h-full items-center justify-center px-5">
            <p role="status" className="animate-pulse text-sm text-[#6e6e73]">
              Restoring conversation...
            </p>
          </div>
        ) : hasMessages ? (
          <div className="mx-auto w-full max-w-[820px] px-5 py-8 md:px-8 md:py-12">
            <MessageList
              messages={messages}
              isThinking={isThinking}
              onArtifactDeleted={handleVisualDeleted}
            />
          </div>
        ) : (
          <div className="mx-auto flex min-h-full w-full max-w-[860px] flex-col items-center justify-center px-5 pb-36 pt-10 text-center md:px-8">
            <div className="anios-orb mb-7 flex h-16 w-16 items-center justify-center rounded-[22px] text-white md:h-[72px] md:w-[72px]">
              <Sparkles size={28} strokeWidth={1.7} />
            </div>
            <p className="mb-2 text-sm font-medium text-[#0071e3]">Private, local assistance</p>
            <h2 className="max-w-2xl text-balance text-[34px] font-semibold leading-[1.08] tracking-[-0.045em] text-[#1d1d1f] md:text-[52px]">
              What can I help you find?
            </h2>
            <p className="mt-4 max-w-xl text-pretty text-[15px] leading-6 text-[#6e6e73] md:text-[17px]">
              Ask a question, explore an idea, or continue something you were working on.
            </p>
          </div>
        )}
      </div>
      {restoreError && (
        <p role="alert" className="mx-auto mb-3 w-full max-w-[756px] px-5 text-sm text-[#c9342f]">
          Unable to restore this conversation. {restoreError}
        </p>
      )}
      {memoryProposal && (
        <section
          aria-label={proposalLabel(memoryProposal)}
          className="mx-auto mb-4 w-[calc(100%_-_2.5rem)] max-w-[756px] rounded-2xl border border-[#0071e3]/20 bg-white p-4 shadow-[0_8px_30px_rgba(0,0,0,0.06)]"
        >
          <p className="text-[15px] text-[#1d1d1f]">
            Save <strong>{proposalValue(memoryProposal)}</strong> as {proposalType(memoryProposal)} memory?
          </p>
          <p className="mt-1 text-sm text-[#6e6e73]">Nothing is saved until you approve.</p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => void approveMemoryProposal()}
              disabled={isSavingMemory}
              className="rounded-full bg-[#0071e3] px-4 py-2 text-sm font-medium text-white hover:bg-[#0077ed] disabled:bg-[#d2d2d7]"
            >Approve {proposalType(memoryProposal)}</button>
            <button
              onClick={rejectMemoryProposal}
              disabled={isSavingMemory}
              className="rounded-full border border-black/10 bg-white px-4 py-2 text-sm font-medium text-[#1d1d1f] hover:bg-[#f5f5f7] disabled:text-[#86868b]"
            >Not now</button>
          </div>
        </section>
      )}
      {memoryNotice && <p role="status" className="mx-auto mb-3 w-full max-w-[756px] px-5 text-sm text-[#248a3d]">{memoryNotice}</p>}
      {memoryError && <p role="alert" className="mx-auto mb-3 w-full max-w-[756px] px-5 text-sm text-[#c9342f]">{memoryError}</p>}
      <div className={hasMessages
        ? 'flex-none border-t border-black/[0.05] bg-[#f5f5f7]/90 px-5 pb-5 pt-4 backdrop-blur-xl md:px-8 md:pb-6'
        : 'pointer-events-none absolute inset-x-0 top-[calc(50%_+_125px)] px-5 md:px-8'
      }>
        <div className={`pointer-events-auto mx-auto w-full ${hasMessages ? 'max-w-[756px]' : 'max-w-[720px]'}`}>
          <Composer
            userId={userId}
            conversationId={conversationId}
            onSendMessage={handleNewMessage}
            onStreamUpdate={handleStreamUpdate}
            onThinkingChange={setIsThinking}
            onMemoryProposal={handleMemoryProposal}
            onArtifactStarted={handleArtifactStarted}
            onArtifactReady={handleArtifactReady}
            onArtifactError={handleArtifactError}
            onVisualStarted={handleVisualStarted}
            onVisualReady={handleVisualReady}
            onVisualError={handleVisualError}
            onImageMatches={handleImageMatches}
            onSearchStarted={handleSearchStarted}
            onSearchBlocked={handleSearchBlocked}
            onSearchSources={handleSearchSources}
            onToolStarted={handleToolStarted}
            onToolFinished={handleToolFinished}
          />
          {hasMessages && (
            <p className="mt-2 text-center text-[11px] text-[#86868b]">AniOS can make mistakes. Check important information.</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatWindow
