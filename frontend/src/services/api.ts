const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const AUTH_TOKEN = import.meta.env.VITE_AUTH_TOKEN || '';

const authHeaders = (): Record<string, string> => (
  AUTH_TOKEN ? { Authorization: `Bearer ${AUTH_TOKEN}` } : {}
)

export interface MemoryItem {
  id: string;
  user_id: string;
  content: string;
  extra_data: Record<string, unknown>;
}

export interface MemorySnapshot {
  profile: {
    id?: string;
    user_id: string;
    name?: string | null;
    preferences: Record<string, unknown>;
  };
  episodic: MemoryItem[];
  semantic: MemoryItem[];
  facts: Array<Record<string, unknown>>;
}

interface ChatEvent {
  event: 'start' | 'delta' | 'memory_proposal' | 'done' | 'error';
  data: Record<string, unknown>;
}

export interface PreferredNameProposal {
  kind: 'preferred_name';
  value: string;
  conversation_id: string;
  trace_id: string;
}

export type ChatStreamUpdate =
  | { type: 'start'; content: string }
  | { type: 'content'; content: string }
  | { type: 'memory_proposal'; proposal: PreferredNameProposal }

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `Server responded with ${response.status}`)
  }
  return response.json()
}

export function getMemorySnapshot(userId: string, signal?: AbortSignal) {
  return apiRequest<MemorySnapshot>(
    `/api/v1/memory/${encodeURIComponent(userId)}`,
    { signal },
  )
}

export function saveProfile(
  userId: string,
  name: string,
  responseStyle: string,
) {
  return apiRequest(`/api/v1/memory/${encodeURIComponent(userId)}/profile`, {
    method: 'PUT',
    body: JSON.stringify({
      name: name || null,
      preferences: responseStyle ? { response_style: responseStyle } : {},
    }),
  })
}

export function approvePreferredName(
  userId: string,
  proposal: PreferredNameProposal,
) {
  return apiRequest<{ profile: MemorySnapshot['profile']; fact: Record<string, unknown> }>(
    `/api/v1/memory/${encodeURIComponent(userId)}/profile/preferred-name`,
    {
      method: 'POST',
      body: JSON.stringify({
        name: proposal.value,
        source_conversation_id: proposal.conversation_id,
        source_trace_id: proposal.trace_id,
      }),
    },
  )
}

export function clearPreferredName(userId: string) {
  return apiRequest<MemorySnapshot['profile']>(
    `/api/v1/memory/${encodeURIComponent(userId)}/profile/preferred-name`,
    { method: 'DELETE' },
  )
}

export function createMemory(
  userId: string,
  memoryType: 'episodic' | 'semantic',
  content: string,
) {
  return apiRequest<MemoryItem>(
    `/api/v1/memory/${encodeURIComponent(userId)}/${memoryType}`,
    {
      method: 'POST',
      body: JSON.stringify({ content, metadata: { source: 'ui' } }),
    },
  )
}

export function deleteMemory(
  userId: string,
  memoryType: 'episodic' | 'semantic',
  memoryId: string,
) {
  return apiRequest(
    `/api/v1/memory/${encodeURIComponent(userId)}/${memoryType}/${memoryId}`,
    { method: 'DELETE' },
  )
}

export function updateMemory(
  userId: string,
  memoryType: 'episodic' | 'semantic',
  memoryId: string,
  content: string,
) {
  return apiRequest<MemoryItem>(
    `/api/v1/memory/${encodeURIComponent(userId)}/${memoryType}/${memoryId}`,
    {
      method: 'PUT',
      body: JSON.stringify({ content, metadata: { source: 'ui_correction' } }),
    },
  )
}

export function exportMemory(userId: string) {
  return apiRequest<{
    schema_version: number;
    exported_at: string;
    user_id: string;
    memory: MemorySnapshot;
    conversations: Array<Record<string, unknown>>;
  }>(`/api/v1/memory/${encodeURIComponent(userId)}/export`)
}

export function deleteAllMemory(userId: string) {
  return apiRequest(`/api/v1/memory/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

export async function* streamChat(userId: string, conversationId: string, query: string) {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ 
      user_id: userId, 
      conversation_id: conversationId,
      query: query,
      metadata: {} 
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      typeof errorData.detail === 'string'
        ? errorData.detail
        : `Server responded with ${response.status}`,
    );
  }

  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('Server did not return a chat event stream')
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("Failed to get reader from response");

  const decoder = new TextDecoder();
  let buffer = ''
  let sawStart = false
  let sawDone = false

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true })

    while (true) {
      const separator = buffer.match(/\r?\n\r?\n/)
      if (!separator || separator.index === undefined) break
      const frame = buffer.slice(0, separator.index)
      buffer = buffer.slice(separator.index + separator[0].length)
      const event = parseChatEvent(frame)

      if (event.event === 'start') {
        const traceId = event.data.trace_id
        const streamConversationId = event.data.conversation_id
        if (typeof traceId !== 'string' || typeof streamConversationId !== 'string') {
          throw new Error('Chat start event is missing identifiers')
        }
        sawStart = true
        yield {
          type: 'start',
          content: `Trace: ${traceId}\nConversation: ${streamConversationId}\nResponse: `,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'delta') {
        if (!sawStart || typeof event.data.content !== 'string') {
          throw new Error('Chat delta event is invalid')
        }
        yield {
          type: 'content',
          content: event.data.content,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'memory_proposal') {
        const kind = event.data.kind
        const value = event.data.value
        const proposalConversationId = event.data.conversation_id
        const proposalTraceId = event.data.trace_id
        if (
          kind !== 'preferred_name' ||
          typeof value !== 'string' ||
          !value.trim() ||
          typeof proposalConversationId !== 'string' ||
          typeof proposalTraceId !== 'string'
        ) {
          throw new Error('Preferred-name memory proposal is invalid')
        }
        yield {
          type: 'memory_proposal',
          proposal: {
            kind,
            value,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          },
        } satisfies ChatStreamUpdate
      } else if (event.event === 'error') {
        throw new Error(
          typeof event.data.message === 'string'
            ? event.data.message
            : 'Chat stream failed',
        )
      } else if (event.event === 'done') {
        sawDone = true
      }
    }
  }

  buffer += decoder.decode()
  if (buffer.trim()) throw new Error('Chat stream ended with an incomplete event')
  if (!sawStart) throw new Error('Chat stream did not start')
  if (!sawDone) throw new Error('Chat stream ended before completion')
}

function parseChatEvent(frame: string): ChatEvent {
  let eventName = ''
  const dataLines: string[] = []

  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }

  if (!['start', 'delta', 'memory_proposal', 'done', 'error'].includes(eventName)) {
    throw new Error('Chat stream contained an unknown event')
  }

  let data: unknown
  try {
    data = JSON.parse(dataLines.join('\n'))
  } catch {
    throw new Error('Chat stream contained invalid event data')
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Chat stream event data must be an object')
  }

  return {
    event: eventName as ChatEvent['event'],
    data: data as Record<string, unknown>,
  }
}
