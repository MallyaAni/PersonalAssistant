import React, { useEffect, useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
import MessageList from '../MessageList/MessageList'
import Composer from '../Composer/Composer'
import {
  getConversationSnapshot,
  readAnalysisThread,
  type AgentActivity,
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
  agentActivities?: AgentActivity[];
}

interface ChatWindowProps {
  userId: string;
  conversationId: string;
  restoreConversation: boolean;
}

// Return the primary value shown for one proposal.
const proposalValue = (proposal: MemoryProposal) => {
  if (proposal.kind === 'preferred_name' || proposal.kind === 'response_style') {
    return proposal.value
  }
  if (proposal.kind === 'discovery_interest') return proposal.label
  if (proposal.kind === 'discovery_interests') return proposal.labels.join(', ')
  if (proposal.kind === 'discovery_locality') {
    return proposal.region ? `${proposal.label}, ${proposal.region}` : proposal.label
  }
  if (proposal.kind === 'entity') return proposal.canonical_name
  if (proposal.kind === 'procedure') return proposal.name
  if (proposal.kind === 'episodic' || proposal.kind === 'semantic_fact') {
    return proposal.content
  }
  return proposal.title
}

// Return a plain-language name for one durable memory form.
const proposalType = (proposal: MemoryProposal) => ({
  preferred_name: 'preferred name',
  response_style: 'response style',
  discovery_interest: 'interest',
  discovery_interests: 'Scout interests',
  discovery_locality: 'home locality',
  entity: 'person or organization',
  procedure: 'reusable workflow',
  knowledge: 'reference knowledge',
  episodic: 'experience or event',
  semantic_fact: 'fact',
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

// Render the chat transcript, recently auto-saved memory, and the composer.
const ChatWindow: React.FC<ChatWindowProps> = ({
  userId,
  conversationId,
  restoreConversation,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  // Everything the backend auto-saved for the reply just given, so the
  // interface can show what was written - not a queue awaiting approval,
  // since nothing here is pending. Cleared on the next question rather than
  // accumulated for the whole conversation.
  const [memoryProposals, setMemoryProposals] = useState<MemoryProposal[]>([])
  const [isThinking, setIsThinking] = useState(false)
  const [isRestoring, setIsRestoring] = useState(restoreConversation)
  const [restoreError, setRestoreError] = useState('')
  // Undefined follows the newest visible image, a string is an explicit choice,
  // and null records that the user deliberately cleared image context.
  const [selectedImageId, setSelectedImageId] = useState<string | null | undefined>(undefined)

  // Start each conversation with its own newest-image context policy.
  useEffect(() => {
    setSelectedImageId(undefined)
  }, [conversationId, userId])

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
    // A save notice belongs to the reply that just finished; the next
    // question starts a clean slate rather than accumulating every save
    // notice from the whole conversation on screen.
    if (role === 'user') {
      setMemoryProposals([])
    }
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

  // Record one memory record the backend already auto-saved, for display.
  const handleMemoryProposal = (proposal: MemoryProposal) => {
    setMemoryProposals(current => [...current, proposal])
  }

  // Mark the latest assistant response as actively generating its artifact --
  // a diagram, or a picture the model chose to create or edit mid-chat.
  const handleArtifactStarted = (artifactId: string, kind: 'diagram' | 'generated_image') => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          artifactId,
          artifactStatus: 'generating',
          artifactError: undefined,
          artifactActivity: kind === 'diagram' ? 'Generating diagram...' : 'Generating image...',
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

  // Add an assistant placeholder while an uploaded image is being analyzed.
  // Generation, editing, and diagrams all run through the chat stream instead
  // and get their placeholder from handleArtifactStarted below.
  const handleVisualStarted = (_mode: 'analyze') => {
    setMessages(prev => [...prev, {
      role: 'assistant',
      // Deliberately unnamed. This said "with Qwen" and stayed correct only
      // by accident: image analysis runs on VISION_MODEL, a separate role
      // from MAIN_LLM_MODEL, so moving the conversational model to DeepSeek
      // left this true while looking stale. Naming a model here couples user
      // copy to a value nobody updates together with docker-compose.yml.
      content: 'Inspecting your image.',
      artifactStatus: 'generating',
      artifactActivity: 'Analyzing image...',
    }])
  }

  // Swap in the reasoned answer once it arrives, without adding a turn.
  //
  // The upload already rendered the vision model's answer; this replaces that
  // same message's artifact so its analysis thread re-reads with the better
  // one. A new message here would show the user two answers to one question.
  const handleVisualReasoned = (artifact: ImageArtifact) => {
    const thread = readAnalysisThread(artifact)
    const latestAnswer = thread[thread.length - 1]?.answer
    setMessages(prev => prev.map(message => (
      message.artifactId === artifact.id
        ? { ...message, artifact, content: latestAnswer || message.content }
        : message
    )))
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

  // Show a running specialist agent on the assistant response that owns the turn.
  const handleAgentStarted = (activity: AgentActivity) => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index >= 0) {
        next[index] = {
          ...next[index],
          agentActivities: [...(next[index].agentActivities || []), activity],
        }
      }
      return next
    })
  }

  // Replace one running specialist with its durable queued or failed outcome.
  const handleAgentFinished = (activity: AgentActivity) => {
    setMessages(prev => {
      const next = [...prev]
      const index = latestAssistantIndex(next)
      if (index < 0) return next
      const current = next[index].agentActivities || []
      const match = current.findIndex(item => item.agentId === activity.agentId)
      const agentActivities = [...current]
      if (match >= 0) agentActivities[match] = activity
      else agentActivities.push(activity)
      next[index] = { ...next[index], agentActivities }
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
    const thread = readAnalysisThread(artifact)
    const latestAnswer = thread[thread.length - 1]?.answer
    setSelectedImageId(artifact.id)
    setMessages(prev => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant' && next[index].artifactStatus === 'generating') {
          next[index] = {
            ...next[index],
            content: artifact.kind === 'generated_image'
              ? 'Image ready.'
              : latestAnswer || 'I analyzed the image, but no answer was returned.',
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

  // Replace the parent revision and retire the completed image-generation placeholder.
  const handleImageRefined = (artifact: ImageArtifact) => {
    const parentId = String(artifact.metadata?.parent_artifact_id ?? '')
    if (!parentId) return
    setSelectedImageId(current => current === parentId ? artifact.id : current)
    setMessages(prev => {
      const next = prev.map(message => {
        const replacesPrimary = message.artifact?.id === parentId
        const hasMatchedParent = message.imageMatches?.some(match => match.id === parentId) ?? false
        if (!replacesPrimary && !hasMatchedParent) return message
        return {
          ...message,
          content: replacesPrimary ? 'Image updated.' : message.content,
          artifact: replacesPrimary ? artifact : message.artifact,
          artifactId: replacesPrimary ? artifact.id : message.artifactId,
          imageMatches: hasMatchedParent
            ? message.imageMatches?.map(match => (match.id === parentId ? artifact : match))
            : message.imageMatches,
        }
      })
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (
          next[index].artifactStatus === 'generating'
          && next[index].artifactActivity === 'Generating image...'
        ) {
          next.splice(index, 1)
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
  //
  // Clearing to `undefined`, not `null`, when the deleted image was the active
  // one. `null` means the user deliberately detached image context and should
  // stick; a deletion is not that choice, and leaving it `null` silently
  // disabled auto-following the newest visible image for the rest of the
  // conversation - so an edit request typed later, with no explanation, found
  // nothing to apply to.
  const handleVisualDeleted = (artifactId: string) => {
    setSelectedImageId(current => current === artifactId ? undefined : current)
    setMessages(prev => prev.map(message => message.artifact?.id === artifactId
      ? { ...message, artifact: undefined, artifactId: undefined, content: 'Image deleted.' }
      : message))
  }

  // The image an edit typed into the composer should apply to: the most recent
  // one in view. Without this, an edit request typed there becomes an ordinary
  // chat turn and the model answers that it cannot edit images — which reads as
  // the feature being broken rather than as it being in the wrong box.
  const newestVisibleImage = useMemo<ImageArtifact | null>(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index]
      // A diagram is also an artifact and is not editable this way, so the kind
      // is checked rather than assumed from position.
      const artifact = message.artifact
      if (
        artifact
        && (artifact.kind === 'generated_image' || artifact.kind === 'uploaded_image')
      ) {
        return artifact as ImageArtifact
      }
      const matched = message.imageMatches?.[0]
      if (matched) return matched
    }
    return null
  }, [messages])

  // Resolve an explicit image choice, otherwise visibly follow the newest image.
  const editableImage = useMemo<ImageArtifact | null>(() => {
    if (selectedImageId === null) return null
    if (selectedImageId === undefined) return newestVisibleImage
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index]
      if (message.artifact?.id === selectedImageId) {
        return message.artifact as ImageArtifact
      }
      const matched = message.imageMatches?.find(item => item.id === selectedImageId)
      if (matched) return matched
    }
    return null
  }, [messages, newestVisibleImage, selectedImageId])

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
              activeImageId={editableImage?.id}
              onImageSelect={artifact => setSelectedImageId(artifact.id)}
            />
          </div>
        ) : (
          <div className="mx-auto flex min-h-full w-full max-w-[860px] flex-col items-center justify-center px-5 pb-36 pt-10 text-center md:px-8">
            <div className="anios-orb mb-7 flex h-16 w-16 items-center justify-center rounded-[22px] text-white md:h-[72px] md:w-[72px]">
              <Sparkles size={28} strokeWidth={1.7} />
            </div>
            <p className="mb-2 text-sm font-medium text-[#0071e3]">Private intelligence</p>
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
      {memoryProposals.length > 0 && (
        <section
          role="status"
          aria-label="Saved to memory"
          className="mx-auto mb-4 w-[calc(100%_-_2.5rem)] max-w-[756px] rounded-2xl border border-[#0071e3]/20 bg-white p-4 shadow-[0_8px_30px_rgba(0,0,0,0.06)]"
        >
          <ul className="space-y-1">
            {/* One turn shares one trace, so kind and trace together are not
                unique the moment a message yields two facts of the same kind. */}
            {memoryProposals.map((proposal, index) => (
              <li key={`${proposal.trace_id}-${proposal.kind}-${index}`} className="text-[15px] text-[#1d1d1f]">
                Saved <strong>{proposalValue(proposal)}</strong> as {proposalType(proposal)} memory.
              </li>
            ))}
          </ul>
        </section>
      )}
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
            onVisualReasoned={handleVisualReasoned}
            onVisualError={handleVisualError}
            onImageMatches={handleImageMatches}
            editableImage={editableImage}
            onClearEditableImage={() => setSelectedImageId(null)}
            onImageRefined={handleImageRefined}
            onSearchStarted={handleSearchStarted}
            onSearchBlocked={handleSearchBlocked}
            onSearchSources={handleSearchSources}
            onToolStarted={handleToolStarted}
            onToolFinished={handleToolFinished}
            onAgentStarted={handleAgentStarted}
            onAgentFinished={handleAgentFinished}
          />
          {hasMessages && (
            <p className="mt-2 text-center text-[11px] text-[#86868b]">DeepMatter can make mistakes. Check important information.</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatWindow
