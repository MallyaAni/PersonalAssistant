import React from 'react'
import MessageBubble from '../MessageBubble/MessageBubble'

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const MessageList: React.FC<{ messages: Message[] }> = ({ messages }) => {
  return (
    <div className="space-y-4">
      {messages.map((msg, idx) => (
        <MessageBubble key={idx} role={msg.role} content={msg.content} />
      ))}
    </div>
  )
}

export default MessageList