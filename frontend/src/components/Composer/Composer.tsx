import React, { useState } from 'react'
import { Send } from 'lucide-react'
import { streamChat } from '../../services/api'

interface ComposerProps {
  onSendMessage: (role: 'user' | 'assistant', content: string) => void;
  onStreamUpdate: (content: string) => void;
}

const Composer: React.FC<ComposerProps> = ({ onSendMessage, onStreamUpdate }) => {
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  
  const handleSend = async () => {
    if (!input.trim() || isSending) return
    setIsSending(true)
    
    onSendMessage('user', input)

    try {
      for await (const chunk of streamChat("dev_user_001", input)) {
        onStreamUpdate(chunk)
      }
    } catch (err) {
      console.warn("Chat request failed:", err)
      onStreamUpdate('Unable to send message. Please try again.')
    } finally {
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
    <div className="flex gap-2 items-center bg-slate-900 p-2 rounded-lg border border-slate-800">
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type a message to AniOS..."
        className="flex-1 bg-transparent outline-none resize-none p-2"
        rows={3}
        disabled={isSending}
      />
      <button 
        onClick={handleSend}
        disabled={isSending}
        className={`p-2 ${isSending ? 'bg-gray-600' : 'bg-blue-600 hover:bg-blue-700'} rounded text-white transition-colors`}
      >
        {isSending ? <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Send size={20} />}
      </button>
    </div>
  )
}

export default Composer
