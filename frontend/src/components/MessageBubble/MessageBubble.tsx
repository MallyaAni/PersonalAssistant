import React from 'react'
import { MoreHorizontal, Search, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import DiagramArtifact from '../DiagramArtifact/DiagramArtifact'
import ImageArtifact from '../ImageArtifact/ImageArtifact'
import type {
  ImageArtifact as ImageArtifactRecord,
  SearchSource,
  VisualArtifact,
} from '../../services/api'

interface MessageProps {
  role: 'user' | 'assistant';
  content: string;
  isThinking?: boolean;
  artifact?: VisualArtifact;
  artifactStatus?: 'generating' | 'failed';
  artifactError?: string;
  artifactActivity?: string;
  imageMatches?: ImageArtifactRecord[];
  isSearching?: boolean;
  searchSources?: SearchSource[];
  onArtifactDeleted?: (artifactId: string) => void;
}

// Separate trace metadata from the visible assistant answer.
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

// Present a source by its site rather than its full URL, the way a search
// result does, falling back to the raw value when it is not a parsable URL.
const displayDomain = (url: string): string => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

// Render one user or assistant message with its optional visual artifact.
const MessageBubble: React.FC<MessageProps> = ({
  role,
  content,
  isThinking = false,
  artifact,
  artifactStatus,
  artifactError,
  artifactActivity,
  imageMatches,
  isSearching,
  searchSources,
  onArtifactDeleted,
}) => {
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
      {isUser || isThinking ? (
        <p
          role={isThinking ? 'status' : undefined}
          aria-live={isThinking ? 'polite' : undefined}
          className={`whitespace-pre-wrap ${isUser ? 'text-[22px] font-semibold leading-[1.28] tracking-[-0.025em] text-[#1d1d1f] md:text-[28px]' : 'text-[16px] leading-7 text-[#333336] md:text-[17px]'} ${isThinking ? 'animate-pulse text-[#6e6e73]' : ''}`}
        >
          {visibleContent}
        </p>
      ) : (
        <div className="assistant-markdown text-[16px] leading-7 text-[#333336] md:text-[17px]">
          <ReactMarkdown>{visibleContent}</ReactMarkdown>
        </div>
      )}
      {!isUser && !isSearching && searchSources && searchSources.length > 0 && (
        <p className="mb-3 flex items-center gap-1.5 text-xs font-medium text-[#6e6e73]">
          <Search size={12} /> Answered using web search
        </p>
      )}
      {!isUser && isSearching && (
        <p role="status" aria-live="polite" className="mb-3 flex items-center gap-1.5 text-sm text-[#6e6e73]">
          <Search size={13} className="animate-pulse" /> Searching the web...
        </p>
      )}
      {!isUser && artifactStatus === 'generating' && (
        <p role="status" className="mt-4 animate-pulse text-sm text-[#6e6e73]">
          {artifactActivity || 'Creating visual artifact...'}
        </p>
      )}
      {!isUser && artifactStatus === 'failed' && (
        <p role="alert" className="mt-4 text-sm text-[#c9342f]">
          {artifactError || 'Unable to create the visual artifact.'}
        </p>
      )}
      {!isUser && artifact?.kind === 'diagram' && <DiagramArtifact artifact={artifact} />}
      {!isUser && artifact && artifact.kind !== 'diagram' && (
        <ImageArtifact artifact={artifact} onDeleted={onArtifactDeleted} />
      )}
      {!isUser && searchSources && searchSources.length > 0 && (
        <section className="mt-5" aria-label="Web sources used">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-[#86868b]">
            {searchSources.length} web {searchSources.length === 1 ? 'result' : 'results'}
          </p>
          <ol className="mt-3 space-y-4">
            {searchSources.map((source, index) => (
              <li key={`${source.url}-${index}`}>
                <p className="truncate text-xs text-[#6e6e73]" title={source.url}>
                  {displayDomain(source.url)}
                </p>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="mt-0.5 block text-[15px] leading-6 text-[#1a0dab] hover:underline dark:text-[#8ab4f8]"
                >
                  {source.title}
                </a>
                {source.snippet && (
                  <p className="source-snippet mt-0.5 text-sm leading-6 text-[#4d5156]">
                    {source.snippet}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {!isUser && imageMatches && imageMatches.length > 0 && (
        <section className="mt-4 space-y-3" aria-label="Matching images">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-[#86868b]">
            {imageMatches.length === 1
              ? '1 matching image from your library'
              : `${imageMatches.length} matching images from your library`}
          </p>
          {imageMatches.map(match => (
            <ImageArtifact
              key={match.id}
              artifact={match}
              onDeleted={onArtifactDeleted}
            />
          ))}
        </section>
      )}
    </article>
  )
}

export default MessageBubble
