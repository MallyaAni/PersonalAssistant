import React from 'react'
import MessageBubble from '../MessageBubble/MessageBubble'
import type { VisualArtifact } from '../../services/api'

interface Message {
  role: 'user' | 'assistant';
  content: string;
  artifact?: VisualArtifact;
  artifactStatus?: 'generating' | 'failed';
  artifactError?: string;
  artifactActivity?: string;
}

interface MessageListProps {
  messages: Message[];
  isThinking: boolean;
  onArtifactDeleted?: (artifactId: string) => void;
}

// Render the ordered transcript and route owned artifact actions upward.
const MessageList: React.FC<MessageListProps> = ({
  messages,
  isThinking,
  onArtifactDeleted,
}) => {
  const lastMessageIsAssistant = messages[messages.length - 1]?.role === 'assistant'

  return (
    <div className="space-y-7">
      {messages.map((msg, idx) => (
        <MessageBubble
          key={idx}
          role={msg.role}
          content={msg.content}
          isThinking={isThinking && lastMessageIsAssistant && idx === messages.length - 1}
          artifact={msg.artifact}
          artifactStatus={msg.artifactStatus}
          artifactError={msg.artifactError}
          artifactActivity={msg.artifactActivity}
          onArtifactDeleted={onArtifactDeleted}
        />
      ))}
      {isThinking && !lastMessageIsAssistant && (
        <MessageBubble role="assistant" content="" isThinking />
      )}
    </div>
  )
}

export default MessageList
