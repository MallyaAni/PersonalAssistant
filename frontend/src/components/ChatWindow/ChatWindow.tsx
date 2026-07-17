import React from 'react'
import { Sparkles } from 'lucide-react'
import MessageList from '../MessageList/MessageList'
import Composer from '../Composer/Composer'
import {
  approvePreferredName,
  type PreferredNameProposal,
} from '../../services/api'

import { useState } from 'react'

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const ChatWindow: React.FC<{ userId: string; conversationId: string }> = ({ userId, conversationId }) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [memoryProposal, setMemoryProposal] = useState<PreferredNameProposal | null>(null)
  const [memoryNotice, setMemoryNotice] = useState('')
  const [memoryError, setMemoryError] = useState('')
  const [isSavingMemory, setIsSavingMemory] = useState(false)
  const [isThinking, setIsThinking] = useState(false)

  const handleNewMessage = (role: 'user' | 'assistant', content: string) => {
    setMessages(prev => [...prev, { role, content }])
  }

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

  const handleMemoryProposal = (proposal: PreferredNameProposal) => {
    setMemoryProposal(proposal)
    setMemoryNotice('')
    setMemoryError('')
  }

  const approveMemoryProposal = async () => {
    if (!memoryProposal || isSavingMemory) return
    setIsSavingMemory(true)
    setMemoryError('')
    try {
      await approvePreferredName(userId, memoryProposal)
      setMemoryNotice(`Saved preferred name: ${memoryProposal.value}`)
      setMemoryProposal(null)
    } catch (error) {
      setMemoryError(
        error instanceof Error ? error.message : 'Unable to save preferred name.',
      )
    } finally {
      setIsSavingMemory(false)
    }
  }

  const rejectMemoryProposal = () => {
    setMemoryNotice('Preferred name was not saved.')
    setMemoryError('')
    setMemoryProposal(null)
  }

  const hasMessages = messages.length > 0

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[#f5f5f7]">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {hasMessages ? (
          <div className="mx-auto w-full max-w-[820px] px-5 py-8 md:px-8 md:py-12">
            <MessageList messages={messages} isThinking={isThinking} />
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
      {memoryProposal && (
        <section
          aria-label="Preferred name memory proposal"
          className="mx-auto mb-4 w-[calc(100%_-_2.5rem)] max-w-[756px] rounded-2xl border border-[#0071e3]/20 bg-white p-4 shadow-[0_8px_30px_rgba(0,0,0,0.06)]"
        >
          <p className="text-[15px] text-[#1d1d1f]">Save <strong>{memoryProposal.value}</strong> as your preferred name?</p>
          <p className="mt-1 text-sm text-[#6e6e73]">Nothing is saved until you approve.</p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => void approveMemoryProposal()}
              disabled={isSavingMemory}
              className="rounded-full bg-[#0071e3] px-4 py-2 text-sm font-medium text-white hover:bg-[#0077ed] disabled:bg-[#d2d2d7]"
            >Approve preferred name</button>
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
