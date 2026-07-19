import React, { useRef, useState } from 'react'
import { ArrowUp, ImagePlus, Loader2, MessageCircle, ScanSearch, X } from 'lucide-react'
import {
  analyzeImage,
  generateImage,
  streamChat,
  type ImageArtifact,
  type MemoryProposal,
  type VisualArtifact,
} from '../../services/api'

type ComposerMode = 'chat' | 'generate' | 'analyze';

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
}) => {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [mode, setMode] = useState<ComposerMode>('chat')
  const [selectedImage, setSelectedImage] = useState<File | null>(null)
  const [visualError, setVisualError] = useState('')
  const requestController = useRef<AbortController | null>(null)
  const canSend = Boolean(input.trim()) && !isSending && (mode !== 'analyze' || selectedImage !== null)

  // Submit the active chat, image-generation, or image-analysis request.
  const handleSend = async () => {
    const prompt = input.trim()
    if (!prompt || isSending || (mode === 'analyze' && !selectedImage)) return
    setIsSending(true)
    setVisualError('')
    onSendMessage('user', input)

    try {
      if (mode !== 'chat') {
        onThinkingChange(false)
        onVisualStarted(mode)
        const controller = new AbortController()
        requestController.current = controller
        const artifact = mode === 'generate'
          ? await generateImage(userId, conversationId, prompt, controller.signal)
          : await analyzeImage(
              userId,
              conversationId,
              prompt,
              selectedImage as File,
              controller.signal,
            )
        onVisualReady(artifact)
        setInput('')
        setSelectedImage(null)
        return
      }

      onThinkingChange(true)
      for await (const update of streamChat(userId, conversationId, input)) {
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
        } else {
          onThinkingChange(false)
          onArtifactError(update.artifactId, update.message)
        }
      }
      setInput('')
    } catch (err) {
      onThinkingChange(false)
      if (mode === 'chat') {
        console.warn('Chat request failed:', err)
        onStreamUpdate('Unable to send message. Please try again.')
      } else {
        const message = err instanceof DOMException && err.name === 'AbortError'
          ? 'Visual request cancelled.'
          : err instanceof Error ? err.message : 'Unable to complete the visual request.'
        setVisualError(message)
        onVisualError(message)
      }
    } finally {
      requestController.current = null
      onThinkingChange(false)
      setIsSending(false)
    }
  }

  // Cancel the active browser request and let the backend perform terminal cleanup.
  const cancelVisualRequest = () => {
    requestController.current?.abort()
  }

  // Change composer behavior while clearing errors from the previous mode.
  const chooseMode = (nextMode: ComposerMode) => {
    if (isSending) return
    setMode(nextMode)
    setVisualError('')
  }

  // Send on Enter while preserving Shift+Enter for new lines.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // If Enter is pressed without Shift, trigger send and prevent newline
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div>
      <div role="group" aria-label="Composer mode" className="mb-2 flex flex-wrap gap-1.5 px-2">
        <button type="button" onClick={() => chooseMode('chat')} disabled={isSending} aria-pressed={mode === 'chat'} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${mode === 'chat' ? 'bg-[#1d1d1f] text-white' : 'bg-white text-[#6e6e73] hover:bg-[#e8e8ed]'}`}>
          <MessageCircle size={13} /> Chat
        </button>
        <button type="button" onClick={() => chooseMode('generate')} disabled={isSending} aria-pressed={mode === 'generate'} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${mode === 'generate' ? 'bg-[#1d1d1f] text-white' : 'bg-white text-[#6e6e73] hover:bg-[#e8e8ed]'}`}>
          <ImagePlus size={13} /> Create image
        </button>
        <button type="button" onClick={() => chooseMode('analyze')} disabled={isSending} aria-pressed={mode === 'analyze'} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${mode === 'analyze' ? 'bg-[#1d1d1f] text-white' : 'bg-white text-[#6e6e73] hover:bg-[#e8e8ed]'}`}>
          <ScanSearch size={13} /> Analyze image
        </button>
      </div>
      {mode === 'analyze' && (
        <div className="mb-2 flex items-center gap-2 px-2 text-xs">
          <label className="cursor-pointer rounded-full border border-black/10 bg-white px-3 py-1.5 font-medium text-[#0066cc] hover:bg-[#f5f5f7]">
            Choose image
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              onChange={event => setSelectedImage(event.target.files?.[0] ?? null)}
              disabled={isSending}
            />
          </label>
          <span className="min-w-0 truncate text-[#6e6e73]">
            {selectedImage?.name || 'PNG, JPEG, or WebP'}
          </span>
        </div>
      )}
      <div className="composer-shell flex items-end gap-2 rounded-[28px] border border-black/[0.08] bg-white p-2 pl-5 focus-within:border-black/[0.16] focus-within:shadow-[0_2px_8px_rgba(0,0,0,0.05),0_14px_44px_rgba(0,0,0,0.1)]">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={mode === 'chat' ? 'Ask AniOS anything...' : mode === 'generate' ? 'Describe the image to create...' : 'What should AniOS inspect?'}
          aria-label="Message AniOS"
          className="min-h-[44px] max-h-40 flex-1 resize-none bg-transparent py-3 text-[16px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#86868b]"
          rows={1}
          disabled={isSending}
        />
        {isSending && mode !== 'chat' && (
          <button type="button" aria-label="Cancel visual request" onClick={cancelVisualRequest} className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-[#f5f5f7] text-[#6e6e73] hover:bg-[#e8e8ed]">
            <X size={18} />
          </button>
        )}
        <button
          type="button"
          aria-label={mode === 'chat' ? 'Send message' : mode === 'generate' ? 'Generate image' : 'Analyze image'}
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
            Retry visual request
          </button>
        </div>
      )}
    </div>
  )
}

export default Composer
