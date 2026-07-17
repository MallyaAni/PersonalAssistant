import React from 'react'
import MessageBubble from '../MessageBubble/MessageBubble'

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface MessageListProps {
  messages: Message[];
  isThinking: boolean;
}

const MessageList: React.FC<MessageListProps> = ({ messages, isThinking }) => {
  const lastMessageIsAssistant = messages[messages.length - 1]?.role === 'assistant'

  return (
    <div className="space-y-7">
      {messages.map((msg, idx) => (
        <MessageBubble
          key={idx}
          role={msg.role}
          content={msg.content}
          isThinking={isThinking && lastMessageIsAssistant && idx === messages.length - 1}
        />
      ))}
      {isThinking && !lastMessageIsAssistant && (
        <MessageBubble role="assistant" content="" isThinking />
      )}
    </div>
  )
}

export default MessageList
