import React, { useState } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'
import { streamChat, type PreferredNameProposal } from '../../services/api'

interface ComposerProps {
  userId: string;
  conversationId: string;
  onSendMessage: (role: 'user' | 'assistant', content: string) => void;
  onStreamUpdate: (content: string) => void;
  onThinkingChange: (isThinking: boolean) => void;
  onMemoryProposal: (proposal: PreferredNameProposal) => void;
}

const Composer: React.FC<ComposerProps> = ({
  userId,
  conversationId,
  onSendMessage,
  onStreamUpdate,
  onThinkingChange,
  onMemoryProposal,
}) => {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const canSend = Boolean(input.trim()) && !isSending
  
  const handleSend = async () => {
    if (!input.trim() || isSending) return
    setIsSending(true)
    onThinkingChange(true)
    
    onSendMessage('user', input)

    try {
      for await (const update of streamChat(userId, conversationId, input)) {
        if (update.type === 'start') onStreamUpdate(update.content)
        else if (update.type === 'content') {
          onThinkingChange(false)
          onStreamUpdate(update.content)
        }
        else onMemoryProposal(update.proposal)
      }
    } catch (err) {
      console.warn('Chat request failed:', err)
      onThinkingChange(false)
      onStreamUpdate('Unable to send message. Please try again.')
    } finally {
      onThinkingChange(false)
      setInput('')
      setIsSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // If Enter is pressed without Shift, trigger send and prevent newline
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="composer-shell flex items-end gap-2 rounded-[28px] border border-black/[0.08] bg-white p-2 pl-5 focus-within:border-black/[0.16] focus-within:shadow-[0_2px_8px_rgba(0,0,0,0.05),0_14px_44px_rgba(0,0,0,0.1)]">
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask AniOS anything..."
        aria-label="Message AniOS"
        className="min-h-[44px] max-h-40 flex-1 resize-none bg-transparent py-3 text-[16px] leading-5 text-[#1d1d1f] outline-none placeholder:text-[#86868b]"
        rows={1}
        disabled={isSending}
      />
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
  )
}

export default Composer
