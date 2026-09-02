// Development keeps its explicit API port; production uses the gateway origin.
const API_BASE_URL = import.meta.env.VITE_API_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')

// Send browser credentials on every API request and surface expired sessions.
const authenticatedFetch = async (
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> => {
  const response = await globalThis.fetch(input, {
    ...init,
    credentials: 'include',
  })
  if (response.status === 401) {
    window.dispatchEvent(new Event('anios:unauthorized'))
  }
  return response
}

export interface AuthSession {
  authentication_required: boolean;
  user_id: string;
  expires_at: string | null;
  // Decides what the workspace offers. The server never trusts this: every
  // operator route re-derives the answer from the database.
  is_admin: boolean;
}

// Load the server-derived identity or report that an interactive login is needed.
export async function getAuthSession(): Promise<AuthSession | null> {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/auth/session`)
  if (response.status === 401) return null
  if (!response.ok) throw new Error('Unable to check your DeepMatter session.')
  return response.json()
}

// Exchange a username and password for an HttpOnly server session.
export async function login(username: string, password: string): Promise<AuthSession> {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  return response.json()
}

// Create one invited profile and accept its server-owned browser session.
export async function register(
  username: string,
  password: string,
  inviteCode: string,
): Promise<AuthSession> {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, invite_code: inviteCode }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  return response.json()
}

// Revoke the active browser session without deleting any user-owned data.
export async function logout(): Promise<void> {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/auth/logout`, {
    method: 'POST',
  })
  if (!response.ok && response.status !== 401) {
    throw new Error('Unable to sign out. Please try again.')
  }
}

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
    | 'action'
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

// A document the assistant wrote (a PDF or a Word file), kept in the same
// store as a picture and fetched through the same owned-artifact boundary.
export interface DocumentArtifact extends ArtifactBase {
  kind: 'document';
  source_format: null;
  source: null;
  mime_type:
    | 'application/pdf'
    | 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  content_available: true;
  byte_size: number;
  sha256: string;
}

export type VisualArtifact = DiagramArtifact | ImageArtifact | DocumentArtifact;

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

// What the turn decided to do, announced before the reply starts: the
// capability's name, the one detail worth showing, and a playful waiting
// line to show while it runs.
export interface ActionActivity {
  label: string;
  detail: string;
  waiting: string;
}

export interface AutomationSkill {
  id: string;
  name: string;
  instruction: string;
  source: 'user' | 'pack';
  use_count: number;
  last_used_at: string | null;
}

export interface AutomationTask {
  id: string;
  instruction: string;
  cadence: string;
  schedule: string;
  next_run: string;
  timezone: string;
  channel: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
}

export interface Automations {
  skills: AutomationSkill[];
  tasks: AutomationTask[];
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

export interface DiscoveryInterestProposal {
  kind: 'discovery_interest';
  label: string;
  conversation_id: string;
  trace_id: string;
}

export interface DiscoveryInterestsProposal {
  kind: 'discovery_interests';
  labels: string[];
  conversation_id: string;
  trace_id: string;
}

export interface DiscoveryLocalityProposal {
  kind: 'discovery_locality';
  label: string;
  region: string | null;
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

export interface SemanticFactProposal {
  kind: 'semantic_fact';
  content: string;
  conversation_id: string;
  trace_id: string;
}

export type MemoryProposal =
  | PreferredNameProposal
  | ResponseStyleProposal
  | DiscoveryInterestProposal
  | DiscoveryInterestsProposal
  | DiscoveryLocalityProposal
  | EntityProposal
  | ProcedureProposal
  | KnowledgeProposal
  | EpisodicProposal
  | SemanticFactProposal;

export type ChatStreamUpdate =
  | { type: 'start'; content: string }
  | { type: 'content'; content: string }
  | { type: 'memory_proposal'; proposal: MemoryProposal }
  | { type: 'artifact_started'; artifactId: string; kind: string }
  | { type: 'artifact_ready'; artifact: VisualArtifact }
  | { type: 'image_matches'; artifacts: ImageArtifact[] }
  | { type: 'search_started'; minimized: boolean }
  | { type: 'search_blocked'; categories: string[] }
  | { type: 'search_sources'; sources: SearchSource[] }
  | { type: 'tool_started'; activity: ToolActivity }
  | { type: 'tool_finished'; activity: ToolActivity }
  | { type: 'agent_started'; activity: AgentActivity }
  | { type: 'agent_finished'; activity: AgentActivity }
  | { type: 'action'; activity: ActionActivity }
  | { type: 'artifact_error'; artifactId: string; message: string }

// Send one authenticated JSON request and accept intentional empty responses.
async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
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
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/presentations/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
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
  // 0-based index the new slide takes; null appends to the end.
  position?: number | null,
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides`,
    {
      method: 'POST',
      body: JSON.stringify({
        base_revision_id: baseRevisionId,
        brief,
        position: position ?? null,
      }),
    },
  )
}

// Reorder a deck as a linked revision. The full order is sent, so the server
// can refuse anything that is not a permutation of the existing slides.
export function reorderPresentationSlides(
  userId: string,
  presentationId: string,
  baseRevisionId: string,
  slideIds: string[],
) {
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides/order`,
    {
      method: 'PUT',
      body: JSON.stringify({ base_revision_id: baseRevisionId, slide_ids: slideIds }),
    },
  )
}

// Remove one slide from a deck as a linked revision.
export function deletePresentationSlide(
  userId: string,
  presentationId: string,
  slideId: string,
  baseRevisionId: string,
) {
  const query = new URLSearchParams({ base_revision_id: baseRevisionId })
  return apiRequest<PresentationRecord>(
    `/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/slides/${encodeURIComponent(slideId)}?${query}`,
    { method: 'DELETE' },
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
  return authenticatedFetch(
    `${API_BASE_URL}/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}`,
    {
      method: 'DELETE',
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
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/v1/presentations/${encodeURIComponent(userId)}/${encodeURIComponent(presentationId)}/revisions/${encodeURIComponent(revisionId)}/content`,
    {},
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

// Upload a document file (PDF, Word, PowerPoint) to be parsed by Docling on
// the server and stored as knowledge, so ordinary turns can answer from it
// with a citation. Multipart, like the image upload: the bytes go up, the
// server proves the type and does the reading.
export async function uploadDocument(
  userId: string,
  file: File,
  note: string,
  conversationId: string,
) {
  const form = new FormData()
  form.set('document', file)
  form.set('note', note)
  form.set('source_conversation_id', conversationId)
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/v1/memory/${encodeURIComponent(userId)}/agent/knowledge/document`,
    { method: 'POST', body: form },
  )
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(apiErrorMessage(detail, response.status))
  }
  return await response.json() as { id?: string; title?: string; pages?: number; chunk_count?: number; queued?: boolean; job_id?: string }
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
//
// Returns the server's routing decision alongside the stored upload: an edit
// cannot be started until the artifact exists, so the same call that creates it
// reports whether one was asked for.
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
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/vision/analyze`, {
    method: 'POST',
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
  // The server answers as soon as the picture has been looked at, and reasons
  // about it afterwards, so a slow reply cannot outlive a phone's patience.
  return {
    artifact,
    editRequested: result.intent === 'edit',
    reasoningPending: result.reasoning_pending === true,
  }
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
  // A re-observation written only to keep an edited image semantically
  // findable was never shown to the user as an answer to anything - only a
  // genuine legacy flat analysis (from the browser's default upload question,
  // or a row written before this flag existed) falls back to display.
  if (artifact.metadata.analysis_user_facing === false) {
    return []
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
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/v1/artifacts/${encodeURIComponent(userId)}/${encodeURIComponent(artifactId)}/content`,
    { signal },
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

// Fetch one owned artifact's current record.
//
// The upload reply is sent before the reasoning pass finishes, so this is how
// the better answer is collected once it lands.
export async function getArtifact(userId: string, artifactId: string, signal?: AbortSignal) {
  const raw = await apiRequest<Record<string, unknown>>(
    `/api/v1/artifacts/${encodeURIComponent(userId)}/${encodeURIComponent(artifactId)}`,
    { signal },
  )
  return parseVisualArtifact(raw)
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

// Turn one API error body into something worth showing a person.
//
// A rejected request answers with FastAPI's validation detail, which is a list
// of per-field objects rather than a string - so a `typeof detail === 'string'`
// check fell through to "Server responded with 422" and the reason was
// discarded on the way past. A message over the length limit therefore failed
// with nothing to act on, and the same message was simply sent again.
export function describeApiError(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const stated = detail
      .map(item => {
        const entry = item as { loc?: unknown[]; msg?: unknown }
        const message = typeof entry?.msg === 'string' ? entry.msg : ''
        // The leading "body" is an implementation detail of where the value
        // travelled, not something the reader needs.
        const field = Array.isArray(entry?.loc)
          ? entry.loc.filter(part => part !== 'body').join('.')
          : ''
        if (!message) return ''
        return field ? `${field}: ${message}` : message
      })
      .filter(Boolean)
    if (stated.length) return stated.join('; ')
  }
  return `Server responded with ${status}`
}

// Submit a chat message and yield typed server-sent stream updates.
export async function* streamChat(
  userId: string,
  conversationId: string,
  query: string,
  activeImageArtifactId?: string,
  signal?: AbortSignal,
) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      user_id: userId,
      conversation_id: conversationId,
      active_image_artifact_id: activeImageArtifactId || null,
      query: query,
      metadata: {}
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(describeApiError(errorData, response.status));
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
      // A frame of nothing but comments is the server holding the connection
      // open through a long silence - generating a picture takes minutes, and
      // an idle proxied request gets closed long before that. It carries no
      // event, so there is nothing here to act on.
      if (isCommentOnlyFrame(frame)) continue
      const event = parseChatEvent(frame)
      // An event name this build does not know. A newer backend is allowed
      // to say more than an older browser understands.
      if (event === null) continue

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
          ![
            'preferred_name',
            'response_style',
            'discovery_interest',
            'discovery_interests',
            'discovery_locality',
            'entity',
            'procedure',
            'knowledge',
            'episodic',
            'semantic_fact',
          ]
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
        } else if (kind === 'discovery_interest') {
          const { label } = event.data
          if (typeof label !== 'string' || !label.trim()) {
            throw new Error('Interest memory proposal is invalid')
          }
          proposal = {
            kind,
            label,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        } else if (kind === 'discovery_interests') {
          const { labels } = event.data
          if (
            !Array.isArray(labels)
            || labels.length === 0
            || labels.length > 8
            || labels.some(label => typeof label !== 'string' || !label.trim())
          ) {
            throw new Error('Interest-list memory proposal is invalid')
          }
          proposal = {
            kind,
            labels: labels as string[],
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
        } else if (kind === 'discovery_locality') {
          const { label, region } = event.data
          if (
            typeof label !== 'string' ||
            !label.trim() ||
            (region !== null && typeof region !== 'string')
          ) {
            throw new Error('Locality memory proposal is invalid')
          }
          proposal = {
            kind,
            label,
            region,
            conversation_id: proposalConversationId,
            trace_id: proposalTraceId,
          }
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
        } else if (kind === 'episodic' || kind === 'semantic_fact') {
          const { content } = event.data
          if (typeof content !== 'string' || !content.trim()) {
            throw new Error('Text memory proposal is invalid')
          }
          proposal = {
            kind,
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
        // Any artifact kind may open a card: a picture shown again arrives
        // with its own kind (uploaded, edited) and is ready a moment later.
        if (typeof id !== 'string' || typeof kind !== 'string' || !kind || status !== 'pending') {
          throw new Error('Artifact start event is invalid')
        }
        yield {
          type: 'artifact_started',
          artifactId: id,
          kind,
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
      } else if (event.event === 'action') {
        const { label, detail, waiting } = event.data
        if (typeof label !== 'string' || !label) {
          throw new Error('Action event is invalid')
        }
        yield {
          type: 'action',
          activity: {
            label,
            detail: typeof detail === 'string' ? detail : '',
            waiting: typeof waiting === 'string' ? waiting : '',
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

// True when every line in the frame is an SSE comment or blank, which is what
// a keepalive looks like. Anything carrying a field is a real event and must
// still be validated rather than skipped.
function isCommentOnlyFrame(frame: string): boolean {
  const lines = frame.split(/\r?\n/).filter(line => line.trim())
  return lines.length > 0 && lines.every(line => line.startsWith(':'))
}


// Parse one server-sent event frame into a typed chat event, or null for an
// event name this build does not know.
//
// Skipping rather than throwing is the whole point. This used to throw, which
// killed the entire stream mid-reply: one frame the browser had never heard of
// and the answer stopped, with a generic error where the text should be. The
// backend and the frontend are separate deploys - the gateway is a one-shot
// static build - so a new event name is always live on one side before the
// other, and a stream that dies on the unfamiliar cannot survive that.
//
// Everything past the name is still validated. An event that IS known and
// malformed still throws, because that is a real defect rather than a version
// skew.
function parseChatEvent(frame: string): ChatEvent | null {
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
    'action',
    'done',
    'error',
  ].includes(eventName)) {
    return null
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

export interface AgentFact {
  label: string;
  value: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  role: string;
  status: 'idle' | 'working' | 'scheduled' | 'needs_setup' | 'disabled';
  detail: string;
  trigger: string;
  last_active_at: string | null;
  facts: AgentFact[];
  opens_view: string | null;
}

// Read the live state of every specialized agent. Each field is derived from
// the tables the agent itself writes, so this cannot report a state it is not in.
export const getAgents = async (userId: string): Promise<AgentSummary[]> => {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/v1/agents/${encodeURIComponent(userId)}`,
  );
  if (!response.ok) {
    throw new Error('Could not load agents.');
  }
  const payload = await response.json();
  return Array.isArray(payload.agents) ? payload.agents : [];
};

export interface DiscoveryInterest {
  id: string;
  label: string;
  strength: number;
  provenance: string;
}

export interface DiscoveryLocality {
  id: string;
  label: string;
  region: string | null;
  radius_km: number;
  timezone: string;
  is_primary: boolean;
  is_travel_active: boolean;
  // When being away lapses on its own; null means open-ended.
  travel_expires_at?: string | null;
}

export interface DiscoverySource {
  id: string;
  kind: string;
  url: string;
  label: string | null;
  enabled: boolean;
  last_error: string | null;
}

export interface FeedCandidate {
  kind: string;
  url: string;
  title: string;
  event_count: number;
  sample_titles: string[];
}

export interface InterestProposal {
  label: string;
  evidence: string;
  source: string;
}

const discoveryBase = (userId: string) =>
  `${API_BASE_URL}/api/v1/discovery/${encodeURIComponent(userId)}`;

// Surface the server's own reason when it gave one. A generic message forces the
// user to ask someone why something failed, when the backend already said.
const readJson = async (response: Response, message: string) => {
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      detail = '';
    }
    throw new Error(detail || message);
  }
  return response.json();
};

export const getDiscoveryProfile = async (
  userId: string,
): Promise<{ interests: DiscoveryInterest[]; localities: DiscoveryLocality[] }> => {
  const payload = await readJson(
    await authenticatedFetch(discoveryBase(userId)),
    'Could not load the discovery profile.',
  );
  return { interests: payload.interests ?? [], localities: payload.localities ?? [] };
};

// Ask the local model which real places a part-typed name might be.
//
// Suggestions only: the fields stay free text, and an empty list is a normal
// answer rather than an error, so the form works exactly the same when the
// model is unreachable.
export const suggestDiscoveryLocality = async (
  userId: string,
  query: string,
  signal?: AbortSignal,
): Promise<Array<{ label: string; region: string }>> => {
  const response = await authenticatedFetch(
    `${discoveryBase(userId)}/locality/suggest?q=${encodeURIComponent(query)}`,
    { signal },
  )
  if (!response.ok) return []
  const body = (await response.json()) as {
    suggestions?: Array<{ label?: unknown; region?: unknown }>
  }
  return (body.suggestions ?? [])
    .filter(item => typeof item.label === 'string' && typeof item.region === 'string')
    .map(item => ({ label: String(item.label), region: String(item.region) }))
}

export const putDiscoveryLocality = async (
  userId: string,
  body: { label: string; region?: string | null; timezone?: string; is_primary?: boolean },
): Promise<DiscoveryLocality> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/localities`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_primary: true, ...body }),
    }),
    'Could not save that place.',
  );

export const putDiscoveryInterest = async (
  userId: string,
  label: string,
  strength = 2,
): Promise<DiscoveryInterest> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/interests`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, strength }),
    }),
    'Could not save that interest.',
  );

export const deleteDiscoveryInterest = async (
  userId: string,
  interestId: string,
): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/interests/${interestId}`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 404) {
    throw new Error('Could not remove that interest.');
  }
};

export const getDiscoverySources = async (userId: string): Promise<DiscoverySource[]> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/sources`),
    'Could not load feeds.',
  );
  return payload.sources ?? [];
};

export const putDiscoverySource = async (
  userId: string,
  body: { kind: string; url: string; label?: string | null },
): Promise<DiscoverySource> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/sources`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'Could not add that feed.',
  );

export const deleteDiscoverySource = async (
  userId: string,
  sourceId: string,
): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/sources/${sourceId}`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 404) {
    throw new Error('Could not remove that feed.');
  }
};

export const suggestDiscoverySources = async (
  userId: string,
): Promise<FeedCandidate[]> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/sources/suggest`),
    'Could not suggest feeds.',
  );
  return payload.candidates ?? [];
};

export const suggestDiscoveryInterests = async (
  userId: string,
): Promise<InterestProposal[]> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/interests/suggest`),
    'Could not suggest interests.',
  );
  return payload.proposals ?? [];
};

// Name the town containing a coordinate. The backend rounds the coordinate to
// roughly a kilometre before its single outbound lookup and stores nothing
// numeric, so the precise fix the browser produced never leaves this machine.
export const resolveDiscoveryLocality = async (
  userId: string,
  latitude: number,
  longitude: number,
): Promise<{
  label: string;
  region: string | null;
  country: string | null;
  country_code: string | null;
  display: string;
  stored_region: string | null;
}> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/locality/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude, longitude }),
    }),
    'Could not work out where that is.',
  );

export interface DiscoveryFind {
  title: string;
  starts_at: string | null;
  place?: string | null;
  url?: string | null;
  summary?: string | null;
  // Identity of the happening itself, sent back when the user says they already
  // know it so the dismissal records that event and not its title text.
  item_digest?: string | null;
  calendar_path?: string | null;
}

export interface SweepResult {
  message: string | null;
  committed: boolean;
  selected: DiscoveryFind[];
  candidate_count: number;
  novel_count: number;
  // How many finds were dropped as already known. Shown because a dismissal the
  // user did not intend is otherwise invisible.
  hidden_count?: number;
  requests_spent: number;
}

export interface DiscoveryRun {
  id: string;
  status: string;
  scheduled_for: string;
  completed_at: string | null;
  delivered: boolean;
  error_code: string | null;
  found: DiscoveryFind[];
  // Surfaced for being unlike anything this account has been shown, rather than
  // for matching an interest. A separate list all the way to the interface, so
  // an unusual find is never mistaken for something that matched.
  notable?: DiscoveryFind[];
}

// Read what Scout actually found on each sweep. Every run already stored its
// digest; nothing could read it back, so a scheduled sweep's recommendations
// were reachable only through a delivery that is still switched off.
export const getDiscoveryRuns = async (
  userId: string,
  limit = 10,
): Promise<DiscoveryRun[]> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/runs?limit=${limit}`),
    'Could not load what Scout found.',
  )
  return payload.runs
}

// `commit: false` is a rehearsal — the whole pipeline runs and nothing is
// recorded, so the same configuration can be tried repeatedly. A real sweep
// marks what it found as seen, which correctly makes a second run empty and
// therefore useless for judging quality.
export const runDiscoverySweep = async (
  userId: string,
  commit = true,
): Promise<SweepResult> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/sweep?commit=${commit}`, {
      method: 'POST',
    }),
    'Could not run a sweep.',
  );

export interface DigestPreview {
  message: string | null;
  would_send: boolean;
  recipients: { id: string; channel: string; label: string | null }[];
  egress_enabled: boolean;
  calendar_links_reachable: boolean;
  event_count: number;
}

// Show exactly what a delivery would send, without sending it. Verifying an
// outbound feature by triggering it cannot be undone.
export const previewDiscoveryDigest = async (
  userId: string,
): Promise<DigestPreview> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/digest/preview`),
    'Could not build a preview.',
  );

export interface DiscoverySchedule {
  cadence: 'daily' | 'weekly';
  hour: number;
  // Minutes past the hour. Older schedules have none stored and read as 0,
  // which is exactly where they used to fire.
  minute?: number;
  weekday: number;
  timezone: string;
  enabled: boolean;
  next_run_at: string;
}

// Without a schedule the worker polls forever and finds nothing due, so the
// loop only ever runs when someone presses a button.
export const getDiscoverySchedule = async (
  userId: string,
): Promise<DiscoverySchedule | null> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/schedule`),
    'Could not load the schedule.',
  );
  return payload.schedule ?? null;
};

export const putDiscoverySchedule = async (
  userId: string,
  body: {
    cadence: 'daily' | 'weekly';
    hour: number;
    minute?: number;
    weekday: number;
    timezone: string;
  },
): Promise<DiscoverySchedule> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/schedule`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'Could not save the schedule.',
  );

export const deleteDiscoverySchedule = async (userId: string): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/schedule`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 404) {
    throw new Error('Could not turn off the schedule.');
  }
};

// Record that the user already knows this, in the place they currently are.
// Scoped deliberately: knowing every trail at home says nothing about a town
// they have never visited.
export const markDiscoveryKnown = async (
  userId: string,
  label: string,
  itemDigest?: string | null,
): Promise<{ label: string; locality: string | null; known_here: number }> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/known`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // The happening's identity when the sweep supplied one. Without it the
      // record falls back to the title, which is how a page called "Trails"
      // once became a suppression key broad enough to hide other counties'
      // listings the user had never seen.
      body: JSON.stringify({ label, item_digest: itemDigest ?? null }),
    }),
    'Could not record that.',
  );

// Make one saved destination Scout's active travel locality.
// Tell Scout where the user is now. This never changes where they live, which
// is why it is a separate call from saving a place: reporting a location used
// to write the home locality and the memory fact behind it.
export const putDiscoveryCurrentPlace = async (
  userId: string,
  body: { label: string; region?: string | null; timezone?: string },
): Promise<{
  locality: DiscoveryLocality
  away: boolean
  home: DiscoveryLocality | null
}> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/current-place`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'Could not update where you are.',
  )

export const putDiscoveryTravelMode = async (
  userId: string,
  localityId: string,
): Promise<DiscoveryLocality> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/travel`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locality_id: localityId }),
    }),
    'Could not start travel mode.',
  );
  return payload.active_locality;
};

// Return Scout to the user's approved home locality.
export const deleteDiscoveryTravelMode = async (userId: string): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/travel`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Could not stop travel mode.');
};

export interface DiscoveryKnownItem {
  id: string;
  label: string;
  created_at: string | null;
}

// Load the things hidden around the user's current primary locality.
export const getDiscoveryKnown = async (
  userId: string,
): Promise<{ locality: string | null; known: DiscoveryKnownItem[] }> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/known`),
    'Could not load hidden discoveries.',
  );

// Undo one owned dismissal so similar discoveries can appear again.
export const deleteDiscoveryKnown = async (
  userId: string,
  itemId: string,
): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/known/${encodeURIComponent(itemId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(response.status === 404 ? 'That dismissal no longer exists.' : 'Could not undo that dismissal.');
  }
};

export interface AdminInvite {
  id: string;
  status: 'open' | 'used' | 'expired';
  expires_at: string;
  created_at: string | null;
  consumed_at: string | null;
  consumed_by: string | null;
  requested_by: string | null;
  requested_username: string | null;
  requested_contact: string | null;
  requested_reason: string | null;
  requested_at: string | null;
}

export interface AdminAccount {
  user_id: string;
  username: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  last_seen_at: string | null;
  search_monthly_limit: number | null;
  search_daily_limit: number | null;
}

export interface SearchUsageWindow {
  used: number;
  limit: number;
  remaining: number;
}

export interface SearchUsage {
  today: SearchUsageWindow;
  month: SearchUsageWindow;
}

// What this account has left of the shared metered search allowance. Shown to
// the person spending it: a limit nobody can see is indistinguishable from the
// feature quietly not working.
export const getSearchUsage = async (userId: string): Promise<SearchUsage> =>
  readJson(
    await authenticatedFetch(
      `${API_BASE_URL}/api/v1/discovery/${encodeURIComponent(userId)}/search-usage`,
    ),
    'Could not load your search usage.',
  );

export interface SearchDefaults {
  guest_daily: number;
  guest_monthly: number;
  operator_daily: number;
  operator_monthly: number;
}

export interface SearchCredits {
  defaults: SearchDefaults;
  monthly_credits: number;
  remaining: number;
  spent: number;
  daily_ceiling: number;
  committed_daily: number;
  overcommitted: boolean;
}

// Ask for an account. Grants nothing on its own — the operator decides, and on
// approval these are the credentials the account is created with.
export const requestAccess = async (
  displayName: string,
  username: string,
  password: string,
  phone: string,
  reason: string,
): Promise<{ request_token: string; status: string }> =>
  readJson(
    await fetch(`${API_BASE_URL}/api/v1/auth/request-access`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: displayName,
        username,
        password,
        // Required. The number is what the iMessage bridge recognises an
        // approved person by, so it is sent as typed and validated server-side
        // - the server owns the rule, and a second copy of it here would be
        // one more thing to keep in step.
        phone,
        reason: reason || null,
      }),
    }),
    'Could not send that request.',
  );

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  turns: number;
  started_at: string;
  last_at: string;
}

// History belongs to the account, so the server lists it. Relying on an id the
// browser happened to keep left every past conversation unreachable from a
// second device or a cleared cache.
export const listConversations = async (
  userId: string,
): Promise<ConversationSummary[]> => {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/v1/conversations/${encodeURIComponent(userId)}`,
  );
  const payload = await readJson(response, 'Could not load your conversations.');
  return payload.conversations ?? [];
};

export const deleteConversation = async (
  userId: string,
  conversationId: string,
): Promise<void> => {
  await readJson(
    await authenticatedFetch(
      `${API_BASE_URL}/api/v1/conversations/${encodeURIComponent(userId)}/${encodeURIComponent(conversationId)}`,
      { method: 'DELETE' },
    ),
    'Could not delete that conversation.',
  );
};

const adminBase = `${API_BASE_URL}/api/v1/admin`;

// Erase the account and everything it owns. Unlike revoking, this cannot be
// undone, so the caller is expected to confirm first.
export const deleteAccount = async (userId: string): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/accounts/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
      credentials: 'include',
    }),
    'Could not delete that account.',
  );
};

export const getSearchCredits = async (): Promise<SearchCredits> =>
  readJson(
    await fetch(`${adminBase}/search-credits`, { credentials: 'include' }),
    'Could not load search credits.',
  );

export const getAdminInvites = async (): Promise<AdminInvite[]> => {
  const payload = await readJson(
    await fetch(`${adminBase}/invites`, { credentials: 'include' }),
    'Could not load invitations.',
  );
  return payload.invites ?? [];
};

// The code comes back exactly once; only its digest is stored, so it cannot be
// recovered afterwards.
export const createAdminInvite = async (
  ttlHours: number,
): Promise<{ code: string; expires_at: string }> =>
  readJson(
    await fetch(`${adminBase}/invites?ttl_hours=${ttlHours}`, {
      method: 'POST',
      credentials: 'include',
    }),
    'Could not create an invitation.',
  );

export const revokeAdminInvite = async (inviteId: string): Promise<void> => {
  const response = await fetch(`${adminBase}/invites/${inviteId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json())?.detail ?? '';
    } catch {
      detail = '';
    }
    throw new Error(detail || 'Could not revoke that invitation.');
  }
};

export const getAdminAccounts = async (): Promise<AdminAccount[]> => {
  const payload = await readJson(
    await fetch(`${adminBase}/accounts`, { credentials: 'include' }),
    'Could not load accounts.',
  );
  return payload.accounts ?? [];
};

export interface AccessRequest {
  id: string;
  display_name: string;
  contact: string | null;
  reason: string | null;
  status: 'pending' | 'approved' | 'denied';
  created_at: string | null;
  username: string | null;
}

export interface AdminSubscription {
  id: string;
  requested_by: string;
  channel: string;
  approved: boolean;
  deliverable: boolean;
  delivery_count: number;
  address: string;
}

export interface GuestSubscription {
  id: string;
  channel: string;
  approved: boolean;
  deliverable: boolean;
  delivery_count: number;
}

export const getAccessRequests = async (): Promise<AccessRequest[]> => {
  const payload = await readJson(
    await fetch(`${adminBase}/access-requests`, { credentials: 'include' }),
    'Could not load access requests.',
  );
  return payload.requests ?? [];
};

export const decideAccessRequest = async (
  requestId: string,
  decision: 'approve' | 'deny',
): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/access-requests/${requestId}/${decision}`, {
      method: 'POST',
      credentials: 'include',
    }),
    'Could not record that decision.',
  );
};

export const getAdminSubscriptions = async (): Promise<AdminSubscription[]> => {
  const payload = await readJson(
    await fetch(`${adminBase}/subscriptions`, { credentials: 'include' }),
    'Could not load subscriptions.',
  );
  return payload.subscriptions ?? [];
};

// Permitting this machine to message one address. Shown with the address,
// because approving blind is not a decision.
export const approveSubscription = async (subscriberId: string): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/subscriptions/${subscriberId}/approve`, {
      method: 'POST',
      credentials: 'include',
    }),
    'Could not approve that subscription.',
  );
};

// Refuse a request to be messaged. Approving had no counterpart, so declining
// meant leaving the request in the list — which looks exactly like one nobody
// has got to yet.
export const denySubscription = async (subscriberId: string): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/subscriptions/${subscriberId}/deny`, {
      method: 'POST',
      credentials: 'include',
    }),
    'Could not deny that subscription.',
  );
};

// Both windows are sent on every call because the endpoint writes both. Sending
// only the edited one would silently clear the other.
// Suspend or restore an account. Reversible on purpose: the account and
// everything it owns stay put, so this is "locked out", not "deleted".
export const setAccountActive = async (
  userId: string,
  active: boolean,
): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/accounts/${encodeURIComponent(userId)}/revoke`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active }),
    }),
    'Could not change that account.',
  );
};

export const setAccountSearchLimit = async (
  userId: string,
  monthlyLimit: number | null,
  dailyLimit: number | null,
): Promise<void> => {
  await readJson(
    await fetch(`${adminBase}/accounts/${encodeURIComponent(userId)}/search-limit`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ monthly_limit: monthlyLimit, daily_limit: dailyLimit }),
    }),
    'Could not set that limit.',
  );
};

// A guest asking to receive their own agent's digest. Where it goes is theirs to
// choose; whether this machine messages it is the operator's to approve.
export const requestSubscription = async (
  userId: string,
  channel: string,
  address: string,
): Promise<GuestSubscription> =>
  readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/subscription`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, address }),
    }),
    'Could not subscribe.',
  );

export const getSubscription = async (
  userId: string,
): Promise<GuestSubscription | null> => {
  const payload = await readJson(
    await authenticatedFetch(`${discoveryBase(userId)}/subscription`),
    'Could not load your subscription.',
  );
  return payload.subscription ?? null;
};

export const cancelSubscription = async (userId: string): Promise<void> => {
  const response = await authenticatedFetch(`${discoveryBase(userId)}/subscription`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 404) {
    throw new Error('Could not unsubscribe.');
  }
};

// Everything automated for the active user: skills (taught and shipped) and
// scheduled tasks, as the Automations panel shows them.
export function getAutomations(userId: string, signal?: AbortSignal) {
  return apiRequest<Automations>(
    `/api/v1/automations/${encodeURIComponent(userId)}`,
    { signal },
  )
}

// Forget one skill the user taught. Shipped skills cannot be deleted.
export function deleteSkill(userId: string, skillId: string) {
  return apiRequest<{ status: 'deleted'; id: string }>(
    `/api/v1/automations/${encodeURIComponent(userId)}/skills/${encodeURIComponent(skillId)}`,
    { method: 'DELETE' },
  )
}

// Cancel one scheduled task outright.
export function deleteScheduledTask(userId: string, taskId: string) {
  return apiRequest<{ status: 'deleted'; id: string }>(
    `/api/v1/automations/${encodeURIComponent(userId)}/tasks/${encodeURIComponent(taskId)}`,
    { method: 'DELETE' },
  )
}

// Pause or resume one scheduled task; resuming re-arms its next slot.
export function setScheduledTaskEnabled(userId: string, taskId: string, enabled: boolean) {
  return apiRequest<AutomationTask>(
    `/api/v1/automations/${encodeURIComponent(userId)}/tasks/${encodeURIComponent(taskId)}`,
    { method: 'PATCH', body: JSON.stringify({ enabled }) },
  )
}
