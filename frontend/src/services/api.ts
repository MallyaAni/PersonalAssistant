const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const AUTH_TOKEN = import.meta.env.VITE_AUTH_TOKEN || '';

// Build the optional authorization header for API requests.
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

export interface AgentMemorySnapshot {
  semantic_cache: number;
  working: number;
  procedures: number;
  entities: number;
  entity_relations: number;
  knowledge_documents: number;
  knowledge_chunks: number;
  summaries: number;
}

export interface ToolMemorySnapshot {
  descriptors: Array<Record<string, unknown>>;
  preferences: Array<Record<string, unknown>>;
  outcomes: Array<Record<string, unknown>>;
}

export interface MemoryExport {
  schema_version: number;
  exported_at: string;
  user_id: string;
  agent_memory: Record<string, Array<Record<string, unknown>>>;
  memory: MemorySnapshot;
  conversations: Array<Record<string, unknown>>;
}

interface ChatEvent {
  event:
    | 'start'
    | 'delta'
    | 'memory_proposal'
    | 'artifact_started'
    | 'artifact_ready'
    | 'image_matches'
    | 'search_started'
    | 'search_results'
    | 'search_blocked'
    | 'tool_started'
    | 'tool_finished'
    | 'agent_started'
    | 'agent_finished'
    | 'artifact_error'
    | 'done'
    | 'error';
  data: Record<string, unknown>;
}

interface ArtifactBase {
  id: string;
  user_id: string;
  conversation_id: string;
  trace_id: string;
  status: 'ready';
  title: string;
  provider: string;
  model: string | null;
  error_code: null;
  metadata: Record<string, unknown>;
}

export interface DiagramArtifact extends ArtifactBase {
  kind: 'diagram';
  source_format: 'mermaid';
  source: string;
  mime_type: 'image/svg+xml';
  metadata: { diagram_type: string };
}

export interface SearchSource {
  title: string;
  url: string;
  snippet: string;
  provider?: string;
}

export interface ToolActivity {
  serverId: string;
  toolName: string;
  status: 'running' | 'succeeded' | 'refused' | 'failed';
  message?: string;
}

export interface ImageArtifact extends ArtifactBase {
  kind: 'generated_image' | 'uploaded_image';
  source_format: null;
  source: null;
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp';
  content_available: true;
  byte_size: number;
  sha256: string;
  width: number;
  height: number;
}

export type VisualArtifact = DiagramArtifact | ImageArtifact;

export interface PresentationTheme {
  font_face: string;
  background_color: string;
  primary_color: string;
  text_color: string;
  muted_color: string;
}

interface PresentationElementBase {
  element_id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PresentationTextElement extends PresentationElementBase {
  type: 'text';
  text: string;
  font_size: number;
  bold: boolean;
  color: string | null;
  align: 'left' | 'center' | 'right';
  valign: 'top' | 'mid' | 'bottom';
  bullet: boolean;
}

export interface PresentationShapeElement extends PresentationElementBase {
  type: 'shape';
  shape: 'rect' | 'roundRect' | 'ellipse' | 'line';
  fill_color: string;
  line_color: string;
  line_width: number;
}

export interface PresentationChartElement extends PresentationElementBase {
  type: 'chart';
  chart_type: 'bar' | 'column' | 'line' | 'pie';
  categories: string[];
  series: Array<{ name: string; values: number[] }>;
  show_legend: boolean;
  show_title: boolean;
  title: string | null;
}

export interface PresentationTableElement extends PresentationElementBase {
  type: 'table';
  headers: string[];
  rows: string[][];
  font_size: number;
}

export interface PresentationImageElement extends PresentationElementBase {
  type: 'image';
  artifact_id: string;
  alt_text: string;
}

export type PresentationElement =
  | PresentationTextElement
  | PresentationShapeElement
  | PresentationChartElement
  | PresentationTableElement
  | PresentationImageElement;

export interface PresentationSlide {
  slide_id: string;
  title: string;
  purpose: string;
  visual_prompt: string | null;
  visual_priority: number;
  background_color: string | null;
  notes: string;
  elements: PresentationElement[];
}

export interface PresentationDeckSpec {
  schema_version: 1;
  title: string;
  subtitle: string | null;
  theme: PresentationTheme;
  slides: PresentationSlide[];
}

export interface PresentationRevision {
  id: string;
  presentation_id: string;
  parent_revision_id: string | null;
  revision_number: number;
  status: 'pending' | 'ready' | 'failed';
  target_slide_id: string | null;
  change_summary: string;
  provider: string;
  model: string | null;
  renderer: string | null;
  renderer_version: string | null;
  content_available: boolean;
  byte_size: number | null;
  sha256: string | null;
  error_code: string | null;
  specification?: PresentationDeckSpec | null;
}

export interface PresentationRecord {
  id: string;
  user_id: string;
  conversation_id: string;
  trace_id: string;
  title: string;
  current_revision_id: string | null;
  current_revision: PresentationRevision | null;
  revisions: PresentationRevision[];
  created_at: string;
  updated_at: string;
}

export interface AgentActivity {
  agentId: string;
  agentName: string;
  model?: string;
  jobId?: string;
  status: 'running' | 'queued' | 'failed';
  message?: string;
}

export interface PresentationJob {
  id: string;
  presentation_id: string;
  revision_id: string;
  user_id: string;
  status: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled';
  expected_slide_count: number | null;
  auto_image_max: number;
  attempt_count: number;
  cancel_requested: boolean;
  error_code: string | null;
  draft_specification: PresentationDeckSpec | null;
  presentation: PresentationRecord | null;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  completed_at: string | null;
}

interface PresentationEvent {
  event: 'started' | 'draft' | 'ready' | 'error' | 'done';
  data: Record<string, unknown>;
}

export type PresentationCreationUpdate =
  | {
    type: 'started';
    presentationId: string;
    revisionId: string;
    traceId: string;
  }
  | {
    type: 'draft';
    specification: PresentationDeckSpec;
    expectedSlideCount: number;
  }
  | { type: 'ready'; presentation: PresentationRecord };

export interface ConversationTurn {
  id: string;
  conversation_id: string;
  user_id: string;
  query: string;
  response: string;
  metadata: Record<string, unknown>;
}

export interface ConversationSnapshot {
  conversation_id: string;
  turns: ConversationTurn[];
  artifacts: Array<Record<string, unknown> | VisualArtifact>;
}

export interface PreferredNameProposal {
  kind: 'preferred_name';
  value: string;
  conversation_id: string;
  trace_id: string;
}

export interface ResponseStyleProposal {
  kind: 'response_style';
  value: 'concise' | 'detailed';
  conversation_id: string;
  trace_id: string;
}

export interface EntityProposal {
  kind: 'entity';
  entity_type: string;
  canonical_name: string;
  attributes: Record<string, unknown>;
  conversation_id: string;
  trace_id: string;
}

export interface ProcedureProposal {
  kind: 'procedure';
  name: string;
  description: string;
  steps: Array<Record<string, unknown>>;
  conversation_id: string;
  trace_id: string;
}

export interface KnowledgeProposal {
  kind: 'knowledge';
  title: string;
  content: string;
  conversation_id: string;
  trace_id: string;
}

export interface EpisodicProposal {
  kind: 'episodic';
  content: string;
  conversation_id: string;
  trace_id: string;
}

export type MemoryProposal =
  | PreferredNameProposal
  | ResponseStyleProposal
  | EntityProposal
  | ProcedureProposal
  | KnowledgeProposal
  | EpisodicProposal;

export type ChatStreamUpdate =
  | { type: 'start'; content: string }
  | { type: 'content'; content: string }
  | { type: 'memory_proposal'; proposal: MemoryProposal }
  | { type: 'artifact_started'; artifactId: string }
  | { type: 'artifact_ready'; artifact: VisualArtifact }
  | { type: 'image_matches'; artifacts: ImageArtifact[] }
  | { type: 'search_started'; minimized: boolean }
  | { type: 'search_blocked'; categories: string[] }
  | { type: 'search_sources'; sources: SearchSource[] }
  | { type: 'tool_started'; activity: ToolActivity }
  | { type: 'tool_finished'; activity: ToolActivity }
  | { type: 'agent_started'; activity: AgentActivity }
  | { type: 'agent_finished'; activity: AgentActivity }
  | { type: 'artifact_error'; artifactId: string; message: string }

// Send one authenticated JSON request and accept intentional empty responses.
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
    throw new Error(apiErrorMessage(detail, response.status))
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

// List recent presentations owned by one user.
export function getPresentations(userId: string, signal?: AbortSignal) {
  return apiRequest<PresentationRecord[]>(
    `/api/v1/presentations/${encodeURIComponent(userId)}`,
    { signal },
  )
}

// Load one owned presentation with its active specification and lineage.
export function getPresentation(
  userId: string,
  presentationId: string,
  signal?: AbortSignal,
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}`,
    { signal },
  )
}

// Queue one editable presentation and return its durable job handle.
export function createPresentation(
  userId: string,
  conversationId: string,
  prompt: string,
) {
  return apiRequest<PresentationJob>('/api/v1/presentations', {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      conversation_id: conversationId,
      prompt,
    }),
  })
}

// Read reconnectable progress for one durable presentation job.
export function getPresentationJob(
  userId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  return apiRequest<PresentationJob>(
    `/api/v1/presentations/jobs/${encodeURIComponent(userId)}/${encodeURIComponent(jobId)}`,
    { signal },
  )
}

// Request cooperative cancellation for one queued or running deck.
export function cancelPresentationJob(userId: string, jobId: string) {
  return apiRequest<void>(
    `/api/v1/presentations/jobs/${encodeURIComponent(userId)}/${encodeURIComponent(jobId)}`,
    { method: 'DELETE' },
  )
}

// Stream application-compiled slide previews before the final PPTX is promoted.
export async function* streamPresentationCreation(
  userId: string,
  conversationId: string,
  prompt: string,
): AsyncGenerator<PresentationCreationUpdate> {
  const response = await fetch(`${API_BASE_URL}/api/v1/presentations/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({
      user_id: userId,
      conversation_id: conversationId,
      prompt,
    }),
  })
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawStarted = false
  let sawDone = false

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let boundary = buffer.search(/\r?\n\r?\n/)
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      const delimiter = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0] || '\n\n'
      buffer = buffer.slice(boundary + delimiter.length)
      const event = parsePresentationEvent(frame)
      if (event.event === 'started') {
        const { presentation_id, revision_id, trace_id } = event.data
        if (
          typeof presentation_id !== 'string'
          || typeof revision_id !== 'string'
          || typeof trace_id !== 'string'
        ) throw new Error('Presentation start event is invalid')
        sawStarted = true
        yield {
          type: 'started',
          presentationId: presentation_id,
          revisionId: revision_id,
          traceId: trace_id,
        }
      } else if (event.event === 'draft') {
        const { specification, expected_slide_count } = event.data
        if (
          !specification
          || typeof specification !== 'object'
          || Array.isArray(specification)
          || typeof expected_slide_count !== 'number'
        ) throw new Error('Presentation draft event is invalid')
        yield {
          type: 'draft',
          specification: specification as unknown as PresentationDeckSpec,
          expectedSlideCount: expected_slide_count,
        }
      } else if (event.event === 'ready') {
        const presentation = event.data.presentation
        if (!presentation || typeof presentation !== 'object' || Array.isArray(presentation)) {
          throw new Error('Ready presentation event is invalid')
        }
        yield {
          type: 'ready',
          presentation: presentation as unknown as PresentationRecord,
        }
      } else if (event.event === 'error') {
        throw new Error(
          typeof event.data.message === 'string'
            ? event.data.message
            : 'Unable to create the presentation.',
        )
      } else {
        sawDone = true
      }
      boundary = buffer.search(/\r?\n\r?\n/)
    }
    if (done) break
  }
  if (buffer.trim()) throw new Error('Presentation stream ended with an incomplete event')
  if (!sawStarted) throw new Error('Presentation stream did not start')
  if (!sawDone) throw new Error('Presentation stream ended before completion')
}

// Parse one bounded presentation SSE frame without interpreting arbitrary fields.
function parsePresentationEvent(frame: string): PresentationEvent {
  let eventName = ''
  const dataLines: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!['started', 'draft', 'ready', 'error', 'done'].includes(eventName)) {
    throw new Error('Presentation stream contained an unknown event')
  }
  let data: unknown
  try {
    data = JSON.parse(dataLines.join('\n'))
  } catch {
    throw new Error('Presentation stream contained invalid event data')
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Presentation stream event data must be an object')
  }
  return {
    event: eventName as PresentationEvent['event'],
    data: data as Record<string, unknown>,
  }
}

// Apply feedback to one selected slide against a known base revision.
export function revisePresentationSlide(
  userId: string,
  presentationId: string,
  slideId: string,
  baseRevisionId: string,
  feedback: string,
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides/${encodeURIComponent(slideId)}/revisions`,
    {
      method: 'POST',
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        feedback,
      }),
    },
  )
}

// Add one slide to an existing deck. Distinct from revising a slide: every
// existing slide is carried through untouched.
export function addPresentationSlide(
  userId: string,
  presentationId: string,
  baseRevisionId: string,
  brief: string,
  afterSlideId?: string | null,
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides`,
    {
      method: 'POST',
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        brief,
        after_slide_id: afterSlideId ?? null,
      }),
    },
  )
}

// Generate one local image and attach it as a new selected-slide revision.
export function generatePresentationSlideImage(
  userId: string,
  presentationId: string,
  slideId: string,
  baseRevisionId: string,
  prompt?: string,
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides/${encodeURIComponent(slideId)}/image`,
    {
      method: 'POST',
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        prompt: prompt?.trim() || null,
      }),
    },
  )
}

// Delete one owned presentation and all of its linked revisions.
export function deletePresentation(userId: string, presentationId: string) {
  return fetch(
    `${API_BASE_URL}/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}`,
    {
      method: 'DELETE',
      headers: authHeaders(),
    },
  ).then(response => {
    if (!response.ok) throw new Error(`Server responded with ${response.status}`)
  })
}

// Download one ready revision and preserve the backend-provided filename.
export async function downloadPresentation(
  userId: string,
  presentationId: string,
  revisionId: string,
) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/revisions/${encodeURIComponent(revisionId)}/content`,
    { headers: authHeaders() },
  )
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  const disposition = response.headers.get('content-disposition') || ''
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] || 'presentation.pptx'
  return { blob: await response.blob(), filename }
}

// Extract one safe message from FastAPI string or structured error details.
function apiErrorMessage(detail: unknown, status: number): string {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) {
    return `Server responded with ${status}`
  }
  const value = (detail as Record<string, unknown>).detail
  if (typeof value === 'string' && value) return value
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const message = (value as Record<string, unknown>).message
    if (typeof message === 'string' && message) return message
  }
  return `Server responded with ${status}`
}

// Load personal memory for one user.
export function getMemorySnapshot(userId: string, signal?: AbortSignal) {
  return apiRequest<MemorySnapshot>(
    `/api/v1/memory/${encodeURIComponent(userId)}`,
    { signal },
  )
}

// Load counts for every agent-memory store owned by one user.
export function getAgentMemorySnapshot(userId: string, signal?: AbortSignal) {
  return apiRequest<AgentMemorySnapshot>(
    `/api/v1/memory/${encodeURIComponent(userId)}/agent`,
    { signal },
  )
}

// Load tool descriptors, preferences, and outcomes for one user.
export function getToolMemorySnapshot(userId: string, signal?: AbortSignal) {
  return apiRequest<ToolMemorySnapshot>(
    `/api/v1/memory/${encodeURIComponent(userId)}/tools`,
    { signal },
  )
}

// Save the user's editable profile and response-style preference.
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

// Approve a preferred-name proposal produced during chat.
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

// Approve a response-style proposal produced during chat.
export function approveResponseStyle(
  userId: string,
  proposal: ResponseStyleProposal,
) {
  return apiRequest<{ fact: Record<string, unknown>; deduplicated: boolean }>(
    `/api/v1/memory/${encodeURIComponent(userId)}/facts`,
    {
      method: 'POST',
      body: JSON.stringify({
        fact_type: 'profile',
        fact_key: 'response_style',
        value: proposal.value,
        purpose: 'personalization',
        source_conversation_id: proposal.conversation_id,
        source_trace_id: proposal.trace_id,
        metadata: { source: 'chat_approval' },
      }),
    },
  )
}

// Approve an entity proposal produced during chat.
export function approveEntity(userId: string, proposal: EntityProposal) {
  return apiRequest(
    `/api/v1/memory/${encodeURIComponent(userId)}/agent/entities`,
    {
      method: 'PUT',
      body: JSON.stringify({
        entity_type: proposal.entity_type,
        canonical_name: proposal.canonical_name,
        attributes: proposal.attributes,
        source_conversation_id: proposal.conversation_id,
        source_trace_id: proposal.trace_id,
      }),
    },
  )
}

// Approve a reusable procedure proposal produced during chat.
export function approveProcedure(userId: string, proposal: ProcedureProposal) {
  return apiRequest(
    `/api/v1/memory/${encodeURIComponent(userId)}/agent/procedures`,
    {
      method: 'POST',
      body: JSON.stringify({
        name: proposal.name,
        description: proposal.description,
        steps: proposal.steps,
        source_conversation_id: proposal.conversation_id,
        source_trace_id: proposal.trace_id,
        metadata: { source: 'chat_approval' },
      }),
    },
  )
}

// Approve a proactively proposed episodic memory produced during chat.
export function approveEpisodic(userId: string, proposal: EpisodicProposal) {
  return apiRequest<MemoryItem>(
    `/api/v1/memory/${encodeURIComponent(userId)}/episodic`,
    {
      method: 'POST',
      body: JSON.stringify({
        content: proposal.content,
        purpose: 'chat_approval',
        metadata: {
          source: 'chat_approval',
          source_conversation_id: proposal.conversation_id,
          source_trace_id: proposal.trace_id,
        },
      }),
    },
  )
}

// Approve a knowledge proposal produced during chat.
export function approveKnowledge(userId: string, proposal: KnowledgeProposal) {
  return apiRequest(
    `/api/v1/memory/${encodeURIComponent(userId)}/agent/knowledge`,
    {
      method: 'POST',
      body: JSON.stringify({
        title: proposal.title,
        content: proposal.content,
        purpose: 'chat_approval',
        source_conversation_id: proposal.conversation_id,
        source_trace_id: proposal.trace_id,
      }),
    },
  )
}

// Ingest an uploaded text document into the user's knowledge store so it is
// chunked, embedded, and recalled by ordinary conversation turns.
export function ingestDocument(
  userId: string,
  title: string,
  content: string,
  conversationId: string,
) {
  return apiRequest<{ id: string; chunk_count?: number }>(
    `/api/v1/memory/${encodeURIComponent(userId)}/agent/knowledge`,
    {
      method: 'POST',
      body: JSON.stringify({
        title,
        content,
        purpose: 'uploaded_document',
        source_conversation_id: conversationId,
      }),
    },
  )
}

// Remove the user's approved preferred name.
export function clearPreferredName(userId: string) {
  return apiRequest<MemorySnapshot['profile']>(
    `/api/v1/memory/${encodeURIComponent(userId)}/profile/preferred-name`,
    { method: 'DELETE' },
  )
}

// Create an episodic or semantic memory for one user.
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

// Delete one episodic or semantic memory.
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

// Correct the content of one episodic or semantic memory.
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

// Export all memory categories for one user.
export function exportMemory(userId: string) {
  return apiRequest<MemoryExport>(`/api/v1/memory/${encodeURIComponent(userId)}/export`)
}

// Delete all memory categories owned by one user.
export function deleteAllMemory(userId: string) {
  return apiRequest(`/api/v1/memory/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

// Load validated ready visual artifacts from the user's recent history.
export async function getReadyArtifacts(userId: string, signal?: AbortSignal) {
  const records = await apiRequest<Array<Record<string, unknown>>>(
    `/api/v1/artifacts/${encodeURIComponent(userId)}`,
    { signal },
  )
  return records
    .filter(record => record.status === 'ready')
    .map(parseVisualArtifact)
}

// Generate one owned image through the configured local image provider.
export async function generateImage(
  userId: string,
  conversationId: string,
  prompt: string,
  signal?: AbortSignal,
) {
  const record = await apiRequest<Record<string, unknown>>('/api/v1/images/generate', {
    method: 'POST',
    signal,
    body: JSON.stringify({
      user_id: userId,
      conversation_id: conversationId,
      prompt,
      width: 2048,
      height: 2048,
    }),
  })
  const artifact = parseVisualArtifact(record)
  if (artifact.kind !== 'generated_image') {
    throw new Error('Image generation returned an unexpected artifact')
  }
  return artifact
}

// Refine a generated or uploaded image, returning a new linked revision.
export async function refineImage(
  userId: string,
  artifactId: string,
  feedback: string,
  conversationId: string,
  signal?: AbortSignal,
) {
  const record = await apiRequest<Record<string, unknown>>(
    `/api/v1/images/${encodeURIComponent(artifactId)}/refine`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify({
        user_id: userId,
        conversation_id: conversationId,
        feedback,
      }),
    },
  )
  const artifact = parseVisualArtifact(record)
  if (artifact.kind !== 'generated_image') {
    throw new Error('Image refinement returned an unexpected artifact')
  }
  return artifact
}

// Upload and analyze one owned image with the configured local vision model.
export async function analyzeImage(
  userId: string,
  conversationId: string,
  prompt: string,
  image: File,
  signal?: AbortSignal,
) {
  const form = new FormData()
  form.set('user_id', userId)
  form.set('conversation_id', conversationId)
  form.set('prompt', prompt)
  form.set('image', image)
  const response = await fetch(`${API_BASE_URL}/api/v1/vision/analyze`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
    signal,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  const result = await response.json() as Record<string, unknown>
  if (!result.artifact || typeof result.artifact !== 'object' || Array.isArray(result.artifact)) {
    throw new Error('Image analysis response is invalid')
  }
  const artifact = parseVisualArtifact(result.artifact as Record<string, unknown>)
  if (artifact.kind !== 'uploaded_image') {
    throw new Error('Image analysis returned an unexpected artifact')
  }
  return artifact
}

// Ask one followup question about an already-owned generated or uploaded image.
export async function askAboutImage(
  userId: string,
  artifactId: string,
  prompt: string,
  signal?: AbortSignal,
) {
  const result = await apiRequest<Record<string, unknown>>(
    `/api/v1/vision/artifacts/${encodeURIComponent(artifactId)}/ask`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify({ user_id: userId, prompt }),
    },
  )
  if (!result.artifact || typeof result.artifact !== 'object' || Array.isArray(result.artifact)) {
    throw new Error('Image question response is invalid')
  }
  const artifact = parseVisualArtifact(result.artifact as Record<string, unknown>)
  if (artifact.kind !== 'generated_image' && artifact.kind !== 'uploaded_image') {
    throw new Error('Image question returned an unexpected artifact')
  }
  return artifact
}

// One persisted question/answer pair from an image's analysis thread.
export interface ImageAnalysisTurn {
  prompt: string;
  answer: string;
  model?: string;
}

// Read the persisted question/answer thread from one image artifact's metadata.
export function readAnalysisThread(artifact: ImageArtifact): ImageAnalysisTurn[] {
  const raw = artifact.metadata.analysis_thread
  if (Array.isArray(raw)) {
    return raw
      .filter((entry): entry is Record<string, unknown> =>
        !!entry && typeof entry === 'object' && !Array.isArray(entry))
      .map(entry => ({
        prompt: typeof entry.prompt === 'string' ? entry.prompt : '',
        answer: typeof entry.answer === 'string' ? entry.answer : '',
        model: typeof entry.model === 'string' ? entry.model : undefined,
      }))
      .filter(entry => entry.answer)
  }
  const legacy = artifact.metadata.analysis
  if (typeof legacy === 'string' && legacy.trim()) {
    return [{ prompt: 'Describe this image.', answer: legacy.trim() }]
  }
  return []
}

// Load private image bytes with the same optional authorization as API requests.
export async function getArtifactImage(
  userId: string,
  artifactId: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/artifacts/${encodeURIComponent(userId)}/${encodeURIComponent(artifactId)}/content`,
    { headers: authHeaders(), signal },
  )
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(response.headers.get('content-type') || '')) {
    throw new Error('Artifact content is not a supported image')
  }
  return response.blob()
}

// Delete one visual artifact owned by the active user.
export function deleteArtifact(userId: string, artifactId: string) {
  return apiRequest<{ status: 'deleted'; id: string }>(
    `/api/v1/artifacts/${encodeURIComponent(userId)}/${encodeURIComponent(artifactId)}`,
    { method: 'DELETE' },
  )
}

// Load the persisted transcript and artifacts for one owned conversation.
export async function getConversationSnapshot(
  userId: string,
  conversationId: string,
  signal?: AbortSignal,
) {
  const snapshot = await apiRequest<ConversationSnapshot>(
    `/api/v1/conversations/${encodeURIComponent(userId)}/${encodeURIComponent(conversationId)}`,
    { signal },
  )
  return parseConversationSnapshot(snapshot, conversationId)
}

// Submit a chat message and yield typed server-sent stream updates.
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
        const proposalConversationId = event.data.conversation_id
        const proposalTraceId = event.data.trace_id
        if (
          !['preferred_name', 'response_style', 'entity', 'procedure', 'knowledge', 'episodic']
            .includes(String(kind)) ||
          typeof proposalConversationId !== 'string' ||
          typeof proposalTraceId !== 'string'
        ) {
          throw new Error('Memory proposal is invalid')
        }
        let proposal: MemoryProposal
        if (kind === 'preferred_name' || kind === 'response_style') {
          const value = event.data.value
          if (typeof value !== 'string' || !value.trim()) {
            throw new Error('Memory proposal value is invalid')
          }
          if (kind === 'response_style' && !['concise', 'detailed'].includes(value)) {
            throw new Error('Response-style memory proposal is invalid')
          }
          proposal = {
            kind,
            value,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          } as MemoryProposal
        } else if (kind === 'entity') {
          const { entity_type, canonical_name, attributes } = event.data
          if (
            typeof entity_type !== 'string' ||
            typeof canonical_name !== 'string' ||
            !attributes || typeof attributes !== 'object' || Array.isArray(attributes)
          ) throw new Error('Entity memory proposal is invalid')
          proposal = {
            kind,
            entity_type,
            canonical_name,
            attributes: attributes as Record<string, unknown>,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        } else if (kind === 'procedure') {
          const { name, description, steps } = event.data
          if (
            typeof name !== 'string' ||
            typeof description !== 'string' ||
            !Array.isArray(steps) || !steps.length
          ) throw new Error('Procedure memory proposal is invalid')
          proposal = {
            kind,
            name,
            description,
            steps: steps as Array<Record<string, unknown>>,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        } else if (kind === 'episodic') {
          const { content } = event.data
          if (typeof content !== 'string' || !content.trim()) {
            throw new Error('Episodic memory proposal is invalid')
          }
          proposal = {
            kind: 'episodic',
            content,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        } else {
          const { title, content } = event.data
          if (typeof title !== 'string' || typeof content !== 'string') {
            throw new Error('Knowledge memory proposal is invalid')
          }
          proposal = {
            kind: 'knowledge',
            title,
            content,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        }
        yield {
          type: 'memory_proposal',
          proposal,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'artifact_started') {
        const { id, kind, status } = event.data
        if (
          typeof id !== 'string' ||
          kind !== 'diagram' ||
          status !== 'pending'
        ) {
          throw new Error('Artifact start event is invalid')
        }
        yield {
          type: 'artifact_started',
          artifactId: id,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'artifact_ready') {
        yield {
          type: 'artifact_ready',
          artifact: parseVisualArtifact(event.data),
        } satisfies ChatStreamUpdate
      } else if (event.event === 'search_started') {
        const { minimized } = event.data as { minimized?: unknown }
        yield {
          type: 'search_started',
          minimized: minimized === true,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'search_blocked') {
        const { categories } = event.data as { categories?: unknown }
        yield {
          type: 'search_blocked',
          categories: Array.isArray(categories)
            ? categories.filter((c): c is string => typeof c === 'string')
            : [],
        } satisfies ChatStreamUpdate
      } else if (event.event === 'search_results') {
        const { sources } = event.data as { sources?: unknown }
        if (!Array.isArray(sources)) {
          throw new Error('Search results event is invalid')
        }
        // Sources are untrusted third-party strings; keep only well-formed
        // entries and let the renderer escape them.
        const parsed = sources.flatMap(entry => {
          const record = entry as Record<string, unknown>
          if (typeof record?.title !== 'string' || typeof record?.url !== 'string') {
            return []
          }
          return [{
            title: record.title,
            url: record.url,
            snippet: typeof record.snippet === 'string' ? record.snippet : '',
            provider: typeof record.provider === 'string' ? record.provider : undefined,
          }]
        })
        yield { type: 'search_sources', sources: parsed } satisfies ChatStreamUpdate
      } else if (event.event === 'tool_started') {
        const { server_id, tool_name } = event.data
        if (typeof server_id !== 'string' || typeof tool_name !== 'string') {
          throw new Error('Tool start event is invalid')
        }
        yield {
          type: 'tool_started',
          activity: {
            serverId: server_id,
            toolName: tool_name,
            status: 'running',
          },
        } satisfies ChatStreamUpdate
      } else if (event.event === 'tool_finished') {
        const { server_id, tool_name, status, message } = event.data
        if (
          typeof server_id !== 'string' ||
          typeof tool_name !== 'string' ||
          !['succeeded', 'refused', 'failed'].includes(String(status)) ||
          typeof message !== 'string'
        ) {
          throw new Error('Tool finish event is invalid')
        }
        yield {
          type: 'tool_finished',
          activity: {
            serverId: server_id,
            toolName: tool_name,
            status: status as ToolActivity['status'],
            message,
          },
        } satisfies ChatStreamUpdate
      } else if (event.event === 'agent_started') {
        const { agent_id, agent_name, model } = event.data
        if (
          typeof agent_id !== 'string' ||
          typeof agent_name !== 'string' ||
          (model !== null && model !== undefined && typeof model !== 'string')
        ) {
          throw new Error('Agent start event is invalid')
        }
        yield {
          type: 'agent_started',
          activity: {
            agentId: agent_id,
            agentName: agent_name,
            model: typeof model === 'string' ? model : undefined,
            status: 'running',
          },
        } satisfies ChatStreamUpdate
      } else if (event.event === 'agent_finished') {
        const { agent_id, agent_name, model, job_id, status, message } = event.data
        if (
          typeof agent_id !== 'string' ||
          typeof agent_name !== 'string' ||
          !['queued', 'failed'].includes(String(status)) ||
          typeof message !== 'string' ||
          (model !== null && model !== undefined && typeof model !== 'string') ||
          (job_id !== undefined && typeof job_id !== 'string')
        ) {
          throw new Error('Agent finish event is invalid')
        }
        yield {
          type: 'agent_finished',
          activity: {
            agentId: agent_id,
            agentName: agent_name,
            model: typeof model === 'string' ? model : undefined,
            jobId: typeof job_id === 'string' ? job_id : undefined,
            status: status as AgentActivity['status'],
            message,
          },
        } satisfies ChatStreamUpdate
      } else if (event.event === 'image_matches') {
        const { artifacts } = event.data as { artifacts?: unknown }
        if (!Array.isArray(artifacts)) {
          throw new Error('Image match event is invalid')
        }
        // Reuse the shared parser, then keep only binary image kinds; a
        // diagram cannot be embedded and must never appear as a pixel match.
        const matched = artifacts
          .map(record => parseVisualArtifact(record as Record<string, unknown>))
          .filter(
            (artifact): artifact is ImageArtifact =>
              artifact.kind === 'generated_image' ||
              artifact.kind === 'uploaded_image',
          )
        yield {
          type: 'image_matches',
          artifacts: matched,
        } satisfies ChatStreamUpdate
      } else if (event.event === 'artifact_error') {
        const { id, message } = event.data
        if (typeof id !== 'string' || typeof message !== 'string') {
          throw new Error('Artifact error event is invalid')
        }
        yield {
          type: 'artifact_error',
          artifactId: id,
          message,
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

// Parse one server-sent event frame into a typed chat event.
function parseChatEvent(frame: string): ChatEvent {
  let eventName = ''
  const dataLines: string[] = []

  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }

  if (![
    'start',
    'delta',
    'memory_proposal',
    'artifact_started',
    'artifact_ready',
    'artifact_error',
    'image_matches',
    'search_started',
    'search_results',
    'search_blocked',
    'tool_started',
    'tool_finished',
    'agent_started',
    'agent_finished',
    'done',
    'error',
  ].includes(eventName)) {
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

// Validate one ready visual artifact before it reaches React state.
function parseVisualArtifact(data: Record<string, unknown>): VisualArtifact {
  const {
    id,
    user_id,
    conversation_id,
    trace_id,
    kind,
    status,
    title,
    source_format,
    source,
    mime_type,
    provider,
    model,
    error_code,
    metadata,
  } = data
  const validBase = (
    typeof id !== 'string' ||
    typeof user_id !== 'string' ||
    typeof conversation_id !== 'string' ||
    typeof trace_id !== 'string' ||
    status !== 'ready' ||
    typeof title !== 'string' ||
    typeof provider !== 'string' ||
    (model !== null && typeof model !== 'string') ||
    error_code !== null ||
    !metadata ||
    typeof metadata !== 'object' ||
    Array.isArray(metadata)
  )
  if (validBase) {
    throw new Error('Ready artifact event is invalid')
  }
  if (kind === 'diagram') {
    if (
      source_format !== 'mermaid' ||
      typeof source !== 'string' ||
      mime_type !== 'image/svg+xml' ||
      typeof (metadata as Record<string, unknown>).diagram_type !== 'string'
    ) {
      throw new Error('Ready diagram artifact is invalid')
    }
    return data as unknown as DiagramArtifact
  }
  if (kind === 'generated_image' || kind === 'uploaded_image') {
    const { content_available, byte_size, sha256, width, height } = data
    if (
      source_format !== null ||
      source !== null ||
      !['image/png', 'image/jpeg', 'image/webp'].includes(String(mime_type)) ||
      content_available !== true ||
      typeof byte_size !== 'number' || byte_size <= 0 ||
      typeof sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(sha256) ||
      typeof width !== 'number' || width <= 0 ||
      typeof height !== 'number' || height <= 0
    ) {
      throw new Error('Ready image artifact is invalid')
    }
    return data as unknown as ImageArtifact
  }
  throw new Error('Ready artifact kind is invalid')
}

// Validate a restored transcript before it reaches React state.
function parseConversationSnapshot(
  data: ConversationSnapshot,
  expectedConversationId: string,
): ConversationSnapshot {
  if (
    !data ||
    typeof data !== 'object' ||
    data.conversation_id !== expectedConversationId ||
    !Array.isArray(data.turns) ||
    !Array.isArray(data.artifacts)
  ) {
    throw new Error('Conversation snapshot is invalid')
  }
  for (const turn of data.turns) {
    if (
      !turn ||
      typeof turn.id !== 'string' ||
      turn.conversation_id !== expectedConversationId ||
      typeof turn.user_id !== 'string' ||
      typeof turn.query !== 'string' ||
      typeof turn.response !== 'string' ||
      !turn.metadata ||
      typeof turn.metadata !== 'object' ||
      Array.isArray(turn.metadata)
    ) {
      throw new Error('Conversation snapshot contains an invalid turn')
    }
  }
  const artifacts = data.artifacts.map(record => {
    if (
      !record ||
      typeof record !== 'object' ||
      typeof record.id !== 'string' ||
      record.conversation_id !== expectedConversationId ||
      typeof record.trace_id !== 'string' ||
      !['diagram', 'generated_image', 'uploaded_image'].includes(String(record.kind))
    ) {
      throw new Error('Conversation snapshot contains an invalid artifact')
    }
    if (record.status === 'ready') {
      return parseVisualArtifact(record as Record<string, unknown>)
    }
    if (!['pending', 'failed'].includes(String(record.status))) {
      throw new Error('Conversation snapshot contains an invalid artifact status')
    }
    return record
  })
  return { ...data, artifacts }
}
