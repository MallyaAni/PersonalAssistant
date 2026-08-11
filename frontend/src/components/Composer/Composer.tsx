import React, { useRef, useState } from 'react'
import { ArrowUp, Loader2, Paperclip, X } from 'lucide-react'
import {
  analyzeImage,
  generateImage,
  ingestDocument,
  refineImage,
  streamChat,
  type AgentActivity,
  type ImageArtifact,
  type MemoryProposal,
  type SearchSource,
  type ToolActivity,
  type VisualArtifact,
} from '../../services/api'
import { shouldEditImage } from '../../services/imageIntent'
import { submitOnEnter } from '../../utils/submitOnEnter'

type ComposerAction = 'chat' | 'generate' | 'analyze' | 'ingest';

// Documents are read client-side and capped to the knowledge endpoint's limit.
const MAX_DOCUMENT_CHARS = 200_000

// Detect questions about an existing image before creation verbs can reroute them.
const asksAboutExistingImage = (prompt: string): boolean => {
  const normalized = prompt.trim().toLowerCase()
  const isQuestion = normalized.endsWith('?')
    || /^(what|which|who|where|when|why|how|is|are|was|were|did|does|do|can|could|would|will)\b/.test(normalized)
  const referencesExistingVisual = /\b(this|that|the|last|previous|existing|create|created|generate|generated|make|made)\b/.test(normalized)
    && /\b(image|picture|photo|artwork|illustration|car|vehicle|it)\b/.test(normalized)
  return isQuestion && referencesExistingVisual
}

// Detect an explicit request to create a new image without treating history questions as creation.
const requestsImageCreation = (prompt: string): boolean => {
  if (asksAboutExistingImage(prompt)) return false
  const normalized = prompt.trim().toLowerCase()
  return /\b(create|generate|make|design)\b.{0,60}\b(image|picture|photo|artwork|illustration)\b/.test(normalized)
    || /\b(draw|paint|sketch|render)\b/.test(normalized)
}

const isImageFile = (file: File): boolean =>
  ['image/png', 'image/jpeg', 'image/webp'].includes(file.type)
  || /\.(png|jpe?g|webp)$/i.test(file.name)

const isTextDocument = (file: File): boolean =>
  file.type.startsWith('text/')
  || /\.(txt|md|markdown|csv|json|log|ya?ml)$/i.test(file.name)

// Say which of the two failures happened, because the fix differs.
//
// This read "Unable to send message. Please try again." for both, and a user
// hit it while DeepMatter was being restarted underneath her. Trying again was
// exactly the wrong advice — nothing she typed was going anywhere until the
// machine came back — and "unable to send message" gave no hint that the
// server, rather than her message, was the problem. She retried for two
// minutes and then reported the agent as broken.
//
// The browser reports an unreachable server as a TypeError from fetch itself,
// with no response to read, which is what separates the two cases here.
const describeSendFailure = (error: unknown): string => {
  if (error instanceof TypeError) {
    return (
      'DeepMatter did not respond, so nothing was sent. It may be restarting — ' +
      'your message is still in the box, so you can send it again in a moment.'
    )
  }
  // Anything else came back *from* DeepMatter, so it can say what it objected to.
  return error instanceof Error && error.message
    ? error.message
    : 'That message could not be sent.'
}

interface ComposerProps {
  userId: string;
  conversationId: string;
  onSendMessage: (role: 'user' | 'assistant', content: string) => void;
  onStreamUpdate: (content: string) => void;
  onThinkingChange: (isThinking: boolean) => void;
  onMemoryProposal: (proposal: MemoryProposal) => void;
  onArtifactStarted: (artifactId: string) => void;
  onArtifactReady: (artifact: VisualArtifact) => void;
  onArtifactError: (artifactId: string, message: string) => void;
  onVisualStarted: (mode: 'generate' | 'analyze') => void;
  onVisualReady: (artifact: ImageArtifact) => void;
  onVisualError: (message: string) => void;
  onImageMatches: (artifacts: ImageArtifact[]) => void;
  // The image an edit typed here applies to, and where its revision goes.
  editableImage: ImageArtifact | null;
  onImageRefined: (artifact: ImageArtifact) => void;
  onSearchStarted: (minimized: boolean) => void;
  onSearchBlocked: (categories: string[]) => void;
  onSearchSources: (sources: SearchSource[]) => void;
  onToolStarted: (activity: ToolActivity) => void;
  onToolFinished: (activity: ToolActivity) => void;
  onAgentStarted: (activity: AgentActivity) => void;
  onAgentFinished: (activity: AgentActivity) => void;
}

// Render the chat input and stream submitted messages.
const Composer: React.FC<ComposerProps> = ({
  userId,
  conversationId,
  onSendMessage,
  onStreamUpdate,
  onThinkingChange,
  onMemoryProposal,
  onArtifactStarted,
  onArtifactReady,
  onArtifactError,
  onVisualStarted,
  onVisualReady,
  onVisualError,
  onImageMatches,
  editableImage,
  onImageRefined,
  onSearchStarted,
  onSearchBlocked,
  onSearchSources,
  onToolStarted,
  onToolFinished,
  onAgentStarted,
  onAgentFinished,
}) => {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [attachedFile, setAttachedFile] = useState<File | null>(null)
  const [visualInFlight, setVisualInFlight] = useState(false)
  const [visualError, setVisualError] = useState('')
  const requestController = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const canSend = !isSending && (Boolean(input.trim()) || attachedFile !== null)

  // Decide what a send should do: an attachment routes by file type, otherwise
  // an explicit "draw me..." becomes generation and everything else is chat.
  const resolveAction = (file: File | null, prompt: string): ComposerAction | 'unsupported' => {
    if (file) {
      if (isImageFile(file)) return 'analyze'
      if (isTextDocument(file)) return 'ingest'
      return 'unsupported'
    }
    return requestsImageCreation(prompt) ? 'generate' : 'chat'
  }

  // Read a text document and index it into memory so it can be recalled later.
  const ingestAttachedDocument = async (file: File, note: string) => {
    onSendMessage('user', note ? `${note}\n\n📎 ${file.name}` : `📎 ${file.name}`)
    const content = (await file.text()).trim()
    if (!content) {
      onSendMessage('assistant', `"${file.name}" looks empty, so nothing was saved.`)
      return
    }
    await ingestDocument(userId, file.name, content.slice(0, MAX_DOCUMENT_CHARS), conversationId)
    onSendMessage(
      'assistant',
      `Added **${file.name}** to your knowledge — I can reference it in our conversation now.`,
    )
  }

  // Submit the active chat, generation, analysis, or document-ingest request.
  const handleSend = async () => {
    const prompt = input.trim()
    const file = attachedFile
    if ((!prompt && !file) || isSending) return

    const action = resolveAction(file, prompt)
    if (action === 'unsupported') {
      setVisualError('Attach an image (PNG, JPEG, WebP) or a text document for now.')
      return
    }

    setIsSending(true)
    setVisualError('')
    // Empty the composer as soon as the send is accepted. The transcript owns
    // the submitted text from here, so leaving a copy in the box while the
    // response streams reads as if nothing was sent. The catch restores it so a
    // failed send is never lost and Retry still has something to resend.
    setInput('')
    setAttachedFile(null)

    try {
      if (action === 'ingest') {
        await ingestAttachedDocument(file as File, prompt)
        return
      }

      if (action === 'analyze') {
        const question = prompt || 'Describe this image, including any text you can read.'
        onSendMessage('user', prompt || `📎 ${(file as File).name}`)
        onThinkingChange(false)
        onVisualStarted('analyze')
        setVisualInFlight(true)
        const controller = new AbortController()
        requestController.current = controller
        const artifact = await analyzeImage(
          userId,
          conversationId,
          question,
          file as File,
          controller.signal,
        )
        onVisualReady(artifact)
        return
      }

      onSendMessage('user', prompt)

      // An edit typed here, rather than into the image card's follow-up box.
      //
      // Without this the same words became an ordinary chat turn: the model has
      // no image tool, so it answered that it could not edit images, which is
      // indistinguishable from the feature being broken. Only explicitly
      // edit-shaped text is taken, so ordinary conversation that happens to
      // follow an image still reaches the model.
      if (editableImage && shouldEditImage(prompt)) {
        onThinkingChange(false)
        onVisualStarted('generate')
        setVisualInFlight(true)
        const revision = await refineImage(
          userId,
          editableImage.id,
          prompt,
          conversationId,
        )
        onImageRefined(revision)
        return
      }

      if (action === 'generate') {
        onThinkingChange(false)
        onVisualStarted('generate')
        setVisualInFlight(true)
        const controller = new AbortController()
        requestController.current = controller
        const artifact = await generateImage(userId, conversationId, prompt, controller.signal)
        onVisualReady(artifact)
        return
      }

      onThinkingChange(true)
      for await (const update of streamChat(userId, conversationId, prompt)) {
        if (update.type === 'start') onStreamUpdate(update.content)
        else if (update.type === 'content') {
          onThinkingChange(false)
          onStreamUpdate(update.content)
        }
        else if (update.type === 'memory_proposal') {
          onMemoryProposal(update.proposal)
        } else if (update.type === 'artifact_started') {
          onArtifactStarted(update.artifactId)
        } else if (update.type === 'artifact_ready') {
          onThinkingChange(false)
          onArtifactReady(update.artifact)
        } else if (update.type === 'image_matches') {
          onImageMatches(update.artifacts)
        } else if (update.type === 'search_started') {
          onSearchStarted(update.minimized)
        } else if (update.type === 'search_blocked') {
          onSearchBlocked(update.categories)
        } else if (update.type === 'search_sources') {
          onSearchSources(update.sources)
        } else if (update.type === 'tool_started') {
          onToolStarted(update.activity)
        } else if (update.type === 'tool_finished') {
          onToolFinished(update.activity)
        } else if (update.type === 'agent_started') {
          onAgentStarted(update.activity)
        } else if (update.type === 'agent_finished') {
          onThinkingChange(false)
          onAgentFinished(update.activity)
        } else {
          onThinkingChange(false)
          onArtifactError(update.artifactId, update.message)
        }
      }
    } catch (err) {
      onThinkingChange(false)
      // Give the text back so the send can be retried rather than retyped.
      setInput(prompt)
      setAttachedFile(file)
      if (action === 'chat') {
        console.warn('Chat request failed:', err)
        onStreamUpdate(describeSendFailure(err))
      } else if (action === 'ingest') {
        const message = err instanceof Error ? err.message : 'Unable to save the document.'
        setVisualError(message)
      } else {
        const message = err instanceof DOMException && err.name === 'AbortError'
          ? 'Visual request cancelled.'
          : err instanceof Error ? err.message : 'Unable to complete the visual request.'
        setVisualError(message)
        onVisualError(message)
      }
    } finally {
      requestController.current = null
      setVisualInFlight(false)
      onThinkingChange(false)
      setIsSending(false)
    }
  }

  // Cancel the active browser request and let the backend perform terminal cleanup.
  const cancelVisualRequest = () => {
    requestController.current?.abort()
  }

  // Send on Enter while preserving Shift+Enter for new lines.
  const handleKeyDown = submitOnEnter(handleSend, !canSend)

  return (
    <div>
      {attachedFile && (
        <div className="mb-2 flex items-center gap-2 px-2">
          <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs text-[#1d1d1f]">
            <Paperclip size={13} className="flex-none text-[#6e6e73]" />
            <span className="min-w-0 truncate">{attachedFile.name}</span>
            <button
              type="button"
              aria-label="Remove attachment"
              onClick={() => setAttachedFile(null)}
              disabled={isSending}
              className="flex-none rounded-full p-0.5 text-[#6e6e73] hover:bg-[#e8e8ed]"
            >
              <X size={13} />
            </button>
          </span>
        </div>
      )}
      <div className="composer-shell flex items-end gap-2 rounded-[28px] border border-black/[0.08] bg-white p-2 pl-2 focus-within:border-black/[0.16] focus-within:shadow-[0_2px_8px_rgba(0,0,0,0.05),0_14px_44px_rgba(0,0,0,0.1)]">
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp,text/plain,text/markdown,text/csv,.md,.markdown,.txt,.csv,.json,.log,.yml,.yaml"
          className="sr-only"
          onChange={event => {
            setAttachedFile(event.target.files?.[0] ?? null)
            setVisualError('')
            event.target.value = ''
          }}
          disabled={isSending}
        />
        <button
          type="button"
          aria-label="Attach a file"
          onClick={() => fileInput.current?.click()}
          disabled={isSending}
          className="flex h-11 w-11 flex-none items-center justify-center rounded-full text-[#6e6e73] hover:bg-[#f5f5f7] disabled:opacity-40"
        >
          <Paperclip size={19} />
        </button>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message DeepMatter — attach a file, or say &ldquo;draw me&hellip;&rdquo;"
          aria-label="Message DeepMatter"
          className="min-h-[44px] max-h-40 flex-1 resize-none bg-transparent py-3 text-[16px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#86868b]"
          rows={1}
          disabled={isSending}
        />
        {visualInFlight && (
          <button type="button" aria-label="Cancel visual request" onClick={cancelVisualRequest} className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-[#f5f5f7] text-[#6e6e73] hover:bg-[#e8e8ed]">
            <X size={18} />
          </button>
        )}
        <button
          type="button"
          aria-label="Send message"
          onClick={handleSend}
          disabled={!canSend}
          className={`flex h-11 w-11 flex-none items-center justify-center rounded-full text-white ${canSend ? 'bg-[#0071e3] hover:bg-[#0077ed]' : 'bg-[#d2d2d7]'}`}
        >
          {isSending ? <Loader2 className="animate-spin" size={19} /> : <ArrowUp size={20} strokeWidth={2.4} />}
        </button>
      </div>
      {visualError && (
        <div className="mt-2 flex items-center justify-between gap-3 px-2 text-sm">
          <p role="alert" className="text-[#c9342f]">{visualError}</p>
          <button type="button" onClick={() => void handleSend()} disabled={!canSend} className="flex-none rounded-full px-3 py-1.5 text-xs font-medium text-[#0066cc] hover:bg-white">
            Retry
          </button>
        </div>
      )}
    </div>
  )
}

export default Composer
