import React from 'react'
import MessageList from '../MessageList/MessageList'
import Composer from '../Composer/Composer'

import { useState } from 'react'

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const ChatWindow: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'System initialized. Ready to begin AniOS development.' }
  ])

  const handleNewMessage = (role: 'user' | 'assistant', content: string) => {
    setMessages(prev => [...prev, { role, content }])
  }

  const handleStreamUpdate = (content: string) => {
    setMessages(prev => {
      const lastMsg = prev[prev.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        const newMsgs = [...prev]
        newMsgs[newMsgs.length - 1] = { ...lastMsg, content }
        return newMsgs
      }
      return [...prev, { role: 'assistant', content }]
    })
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-4 space-y-4">
      <div className="flex-1 overflow-y-auto bg-slate-900/50 rounded-lg p-4 border border-slate-800 shadow-inner">
        <MessageList messages={messages} />
      </div>
      <div className="pt-4">
        <Composer onSendMessage={handleNewMessage} onStreamUpdate={handleStreamUpdate} />
      </div>
    </div>
  )
}

export default ChatWindow
