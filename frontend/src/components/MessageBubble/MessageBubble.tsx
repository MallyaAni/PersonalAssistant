import React from 'react'
import { MoreHorizontal, Search, Sparkles } from 'lucide-react'

interface MessageProps {
  role: 'user' | 'assistant';
  content: string;
  isThinking?: boolean;
}

const parseAssistantEnvelope = (content: string) => {
  const match = content.match(
    /^Trace: ([^\n]+)\nConversation: ([^\n]+)\nResponse: ?([\s\S]*)$/,
  )
  if (!match) return null
  return {
    traceId: match[1],
    conversationId: match[2],
    answer: match[3],
  }
}

const MessageBubble: React.FC<MessageProps> = ({ role, content, isThinking = false }) => {
  const isUser = role === 'user';
  const envelope = isUser ? null : parseAssistantEnvelope(content)
  const visibleContent = isThinking ? 'Thinking...' : (envelope?.answer ?? content)
  
  return (
    <article aria-label={isUser ? 'Your question' : (isThinking ? 'AniOS is thinking' : 'AniOS answer')} className={isUser ? 'border-b border-black/[0.07] pb-7' : 'rounded-[26px] border border-black/[0.06] bg-white p-5 shadow-[0_12px_40px_rgba(0,0,0,0.055)] md:p-7'}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className={`flex h-7 w-7 items-center justify-center rounded-lg ${isUser ? 'bg-[#e8f2ff] text-[#0071e3]' : 'anios-wordmark text-white'}`}>
            {isUser ? <Search size={14} strokeWidth={2.2} /> : <Sparkles size={14} strokeWidth={1.8} />}
          </span>
          <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#86868b]">
            {isUser ? 'Your question' : 'AniOS answer'}
          </span>
        </div>
        {envelope && (
          <details className="metadata-disclosure relative flex-none text-xs text-[#6e6e73]">
            <summary
              aria-label="Show response metadata"
              title="Response metadata"
              className="flex h-8 w-8 cursor-pointer select-none items-center justify-center rounded-full border border-black/[0.07] bg-[#f5f5f7] text-[#6e6e73] hover:bg-[#e8e8ed]"
            >
              <MoreHorizontal size={17} />
            </summary>
            <div className="absolute right-0 top-10 z-20 w-[min(280px,calc(100vw-3rem))] rounded-2xl border border-black/[0.08] bg-white p-4 shadow-[0_16px_50px_rgba(0,0,0,0.14)]">
              <p className="mb-3 text-sm font-semibold text-[#1d1d1f]">Response metadata</p>
              <dl className="grid gap-2 break-all">
                <dt className="font-medium text-[#86868b]">Trace ID</dt>
                <dd>{envelope.traceId}</dd>
                <dt className="mt-1 font-medium text-[#86868b]">Conversation ID</dt>
                <dd>{envelope.conversationId}</dd>
              </dl>
            </div>
          </details>
        )}
      </div>
      <p
        role={isThinking ? 'status' : undefined}
        aria-live={isThinking ? 'polite' : undefined}
        className={`whitespace-pre-wrap ${isUser ? 'text-[22px] font-semibold leading-[1.28] tracking-[-0.025em] text-[#1d1d1f] md:text-[28px]' : 'text-[16px] leading-7 text-[#333336] md:text-[17px]'} ${isThinking ? 'animate-pulse text-[#6e6e73]' : ''}`}
      >
        {visibleContent}
      </p>
    </article>
  )
}

export default MessageBubble
