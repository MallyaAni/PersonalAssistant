import React from 'react'

interface MessageProps {
  role: 'user' | 'assistant';
  content: string;
}

const MessageBubble: React.FC<MessageProps> = ({ role, content }) => {
  const isUser = role === 'user';
  
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] p-3 rounded-lg ${
        isUser ? 'bg-blue-600 text-white' : 'bg-slate-800 text-gray%e1'
      } border border-slate-700`}>
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  )
}

export default MessageBubble