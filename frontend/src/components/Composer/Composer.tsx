import React, { useEffect, useRef, useState } from 'react'
import { ArrowUp, Image as ImageIcon, Loader2, Paperclip, X } from 'lucide-react'
import {
  analyzeImage,
  getArtifact,
  getArtifactImage,
  ingestDocument, uploadDocument,
  refineImage,
  streamChat,
  type ActionActivity,
  type AgentActivity,
  type ImageArtifact,
  type MemoryProposal,
  type SearchSource,
  type ToolActivity,
  type VisualArtifact,
} from '../../services/api'
import { submitOnEnter } from '../../utils/submitOnEnter'

type ComposerAction = 'chat' | 'analyze' | 'ingest' | 'parse'

// Documents are read client-side and capped to the knowledge endpoint's limit.
const MAX_DOCUMENT_CHARS = 200_000

// What ChatRequest.query accepts. Pasting past it used to reach the server,
// fail validation, and come back as an unexplained error, so the same message
// was simply sent again. Checked here so the limit is visible while typing
// rather than discovered by a round trip; the server still enforces it, this
// only stops the pointless request.
const MAX_QUERY_CHARS = 10_000

// A long paste belongs in the knowledge base, where the cap is twenty times
// higher and the text stays referenceable, so the message says so.
const tooLongMessage = (length: number) =>
  `That message is ${length.toLocaleString()} characters and the limit is `
  + `${MAX_QUERY_CHARS.toLocaleString()}. Shorten it, or attach it as a `
  + `text document and I will index it so we can talk about it.`

const isImageFile = (file: File): boolean =>
  ['image/png', 'image/jpeg', 'image/webp'].includes(file.type)
  || /\.(png|jpe?g|webp)$/i.test(file.name)

const isTextDocument = (file: File): boolean =>
  file.type.startsWith('text/')
// A document the server parses (Docling) rather than one the browser can read
// as text: PDF, Word, PowerPoint - by declared type or, failing that, suffix.
const isParsedDocument = (file: File): boolean =>
  ['application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  ].includes(file.type)
  || /\.(pdf|docx|pptx)$/i.test(file.name)
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
  onArtifactStarted: (artifactId: string, kind: string) => void;
  onArtifactReady: (artifact: VisualArtifact) => void;
  onArtifactError: (artifactId: string, message: string) => void;
  onVisualStarted: (mode: 'analyze') => void;
  onVisualReady: (artifact: ImageArtifact) => void;
  onVisualReasoned: (artifact: ImageArtifact) => void;
  onVisualError: (message: string) => void;
  onImageMatches: (artifacts: ImageArtifact[]) => void;
  // The image an edit typed here applies to, and where its revision goes.
  editableImage: ImageArtifact | null;
  onClearEditableImage: () => void;
  onImageRefined: (artifact: ImageArtifact) => void;
  onSearchStarted: (minimized: boolean) => void;
  onSearchBlocked: (categories: string[]) => void;
  onSearchSources: (sources: SearchSource[]) => void;
  onToolStarted: (activity: ToolActivity) => void;
  onToolFinished: (activity: ToolActivity) => void;
  onAgentStarted: (activity: AgentActivity) => void;
  onAgentFinished: (activity: AgentActivity) => void;
  onAction: (activity: ActionActivity) => void;
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
  onVisualReasoned,
  onVisualError,
  onImageMatches,
  editableImage,
  onClearEditableImage,
  onImageRefined,
  onSearchStarted,
  onSearchBlocked,
  onSearchSources,
  onToolStarted,
  onToolFinished,
  onAgentStarted,
  onAgentFinished,
  onAction,
}) => {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [attachedFile, setAttachedFile] = useState<File | null>(null)
  const [visualInFlight, setVisualInFlight] = useState(false)
  const [chatInFlight, setChatInFlight] = useState(false)
  const [visualError, setVisualError] = useState('')
  const [activeImageUrl, setActiveImageUrl] = useState('')
  const requestController = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const canSend = !isSending && (Boolean(input.trim()) || attachedFile !== null)

  // Load a private thumbnail for the image currently targeted by the main composer.
  useEffect(() => {
    if (!editableImage) {
      setActiveImageUrl('')
      return
    }
    const controller = new AbortController()
    let objectUrl = ''

    // Resolve the selected image through its authenticated binary endpoint.
    const loadThumbnail = async () => {
      try {
        const blob = await getArtifactImage(
          editableImage.user_id,
          editableImage.id,
          controller.signal,
        )
        objectUrl = URL.createObjectURL(blob)
        setActiveImageUrl(objectUrl)
      } catch {
        if (!controller.signal.aborted) setActiveImageUrl('')
      }
    }

    void loadThumbnail()
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [editableImage])

  // Decide what a send should do: an attachment routes by file type; with no
  // attachment it is always an ordinary chat turn. Whether that turn wants a
  // new picture, a search, a diagram, or a specialist is not a client-side
  // guess -- it is the main model's own decision, made with full context, on
  // the server.
  const resolveAction = (file: File | null, prompt: string): ComposerAction | 'unsupported' => {
    if (file) {
      if (isImageFile(file)) return 'analyze'
      if (isTextDocument(file)) return 'ingest'
      if (isParsedDocument(file)) return 'parse'
      return 'unsupported'
    }
    return 'chat'
  }

  // Send a PDF, Word or PowerPoint file to be parsed on the server (Docling)
  // and stored as knowledge, then say so the way the text path does.
  const uploadAttachedDocument = async (file: File, note: string) => {
    onSendMessage('user', note ? `${note}\n\n📎 ${file.name}` : `📎 ${file.name}`)
    try {
      const stored = await uploadDocument(userId, file, note, conversationId)
      const pages = typeof stored.pages === 'number' && stored.pages > 1 ? ` (${stored.pages} pages)` : ''
      onSendMessage(
        'assistant',
        `Added **${file.name}**${pages} to your knowledge — I can reference it in our conversation now.`,
      )
    } catch (error) {
      onSendMessage('assistant', error instanceof Error ? error.message : `I couldn't read ${file.name}.`)
    }
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

  // Collect the reasoned answer the server writes after the upload replies.
  //
  // Bounded rather than open-ended: reasoning that never lands leaves the
  // vision model's answer standing, which is a complete answer already. Errors
  // are swallowed for the same reason -- there is nothing to tell the user,
  // because nothing was lost.
  const pollForReasonedAnswer = async (artifactId: string) => {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 2_000))
      try {
        const artifact = await getArtifact(userId, artifactId)
        if (artifact.kind !== 'uploaded_image' && artifact.kind !== 'generated_image') return
        const metadata = artifact.metadata as Record<string, unknown> | undefined
        if (metadata?.analysis_reasoned === true) {
          onVisualReasoned(artifact)
          return
        }
      } catch {
        return
      }
    }
  }

  // Submit the active chat, generation, analysis, or document-ingest request.
  const handleSend = async () => {
    const prompt = input.trim()
    const file = attachedFile
    if ((!prompt && !file) || isSending) return

    if (prompt.length > MAX_QUERY_CHARS) {
      setVisualError(tooLongMessage(prompt.length))
      return
    }

    const action = resolveAction(file, prompt)
    if (action === 'unsupported') {
      setVisualError('Attach an image (PNG, JPEG, WebP), a PDF, a Word or PowerPoint file, or a text document.')
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
      if (action === 'parse') {
        await uploadAttachedDocument(file as File, prompt)
        return
      }

      if (action === 'analyze') {
        // Attaching a picture and asking for an edit in the same message is the
        // obvious way to ask, and it used to describe the image instead: an
        // attachment routed to analysis whatever the words said. Worse, the
        // instruction was put to the vision model as a question, which answered
        // that it cannot edit images — and that refusal was then indexed as the
        // picture's description.
        //
        // The server reads the words and says which it was, so the upload and
        // the decision about it are one round trip.
        onSendMessage('user', prompt || `📎 ${(file as File).name}`)
        onThinkingChange(false)
        onVisualStarted('analyze')
        setVisualInFlight(true)
        const controller = new AbortController()
        requestController.current = controller
        const { artifact, editRequested, reasoningPending } = await analyzeImage(
          userId,
          conversationId,
          prompt || 'Describe this image, including any text you can read.',
          file as File,
          controller.signal,
        )
        onVisualReady(artifact)
        // The reasoned answer lands after this reply, so collect it separately
        // rather than holding the upload open for it -- that wait is what a
        // locked phone drops, reporting a failure for work that succeeded.
        if (reasoningPending) void pollForReasonedAnswer(artifact.id)
        // The upload has to be stored before it can be edited, so the edit runs
        // against the artifact the analysis just created.
        if (editRequested) {
          const revision = await refineImage(
            userId,
            artifact.id,
            prompt,
            conversationId,
          )
          onImageRefined(revision)
        }
        return
      }

      onSendMessage('user', prompt)

      // Whether this turn wants live search, a new or edited picture, a
      // diagram, or a specialist -- or is just ordinary conversation -- is
      // now the main model's own decision, made from full understanding of
      // the request rather than a client-side guess at intent. It reaches
      // that decision through the same streamed chat call every message
      // takes, so the image currently in view is passed along as context for
      // the "edit" option, and whichever action the model chooses (search,
      // a new image, an edit, a diagram, or a delegated specialist) arrives
      // back as ordinary chat stream events.

      onThinkingChange(true)
      // The model may decide this turn is a slow generation or edit before the
      // browser ever knows, so every chat send -- not only the old
      // client-triggered visual ones -- needs to stay cancellable.
      const chatController = new AbortController()
      requestController.current = chatController
      setChatInFlight(true)
      for await (const update of streamChat(
        userId,
        conversationId,
        prompt,
        editableImage?.id,
        chatController.signal,
      )) {
        if (update.type === 'start') onStreamUpdate(update.content)
        else if (update.type === 'content') {
          onThinkingChange(false)
          onStreamUpdate(update.content)
        }
        else if (update.type === 'memory_proposal') {
          onMemoryProposal(update.proposal)
        } else if (update.type === 'artifact_started') {
          onArtifactStarted(update.artifactId, update.kind)
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
        } else if (update.type === 'action') {
          onAction(update.activity)
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
        if (err instanceof DOMException && err.name === 'AbortError') {
          onStreamUpdate('Request cancelled.')
        } else {
          console.warn('Chat request failed:', err)
          onStreamUpdate(describeSendFailure(err))
        }
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
      setChatInFlight(false)
      onThinkingChange(false)
      setIsSending(false)
    }
  }

  // Cancel the active browser request and let the backend perform terminal cleanup.
  const cancelActiveRequest = () => {
    requestController.current?.abort()
  }

  // Send on Enter while preserving Shift+Enter for new lines.
  const handleKeyDown = submitOnEnter(handleSend, !canSend)

  return (
    <div>
      {editableImage && (
        <div className="mb-2 flex items-center gap-2 px-2">
          <span
            aria-label={`Using image in chat: ${editableImage.title}`}
            className="inline-flex max-w-full items-center gap-2 rounded-2xl border border-[#0071e3]/20 bg-[#f0f7ff] px-2 py-1.5 text-xs text-[#1d1d1f]"
          >
            {activeImageUrl ? (
              <img
                src={activeImageUrl}
                alt=""
                className="h-8 w-8 flex-none rounded-lg object-cover"
              />
            ) : (
              <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-[#eaf4ff] text-[#0071e3]">
                <ImageIcon size={15} />
              </span>
            )}
            <span className="min-w-0">
              <span className="block font-medium text-[#0066cc]">Using this image</span>
              <span className="block max-w-48 truncate text-[#6e6e73]">{editableImage.title}</span>
            </span>
            <button
              type="button"
              aria-label="Stop using selected image"
              onClick={onClearEditableImage}
              disabled={isSending}
              className="flex-none rounded-full p-1 text-[#6e6e73] hover:bg-[#e8f2ff] disabled:opacity-40"
            >
              <X size={14} />
            </button>
          </span>
        </div>
      )}
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
        {/* Extensions are listed alongside the MIME types on purpose: Windows
            resolves a .jpg's type from the registry, which can say image/jpg or
            image/pjpeg rather than image/jpeg, and a MIME-only accept list then
            hides the user's own photographs in the file dialog. */}
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/pjpeg,image/webp,.jpg,.jpeg,.png,.webp,text/plain,text/markdown,text/csv,.md,.markdown,.txt,.csv,.json,.log,.yml,.yaml"
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
        {(visualInFlight || chatInFlight) && (
          <button type="button" aria-label="Cancel request" onClick={cancelActiveRequest} className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-[#f5f5f7] text-[#6e6e73] hover:bg-[#e8e8ed]">
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
