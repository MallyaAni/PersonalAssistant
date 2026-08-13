import { expect, test, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const TEST_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2O9sAAAAASUVORK5CYII=',
  'base64',
)
const LIVE_TEST_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAFElEQVR4nGPkDzjBgA0wYRWlkwQAre0BMyym/B0AAAAASUVORK5CYII=',
  'base64',
)

// Build one ready binary artifact record for deterministic browser tests.
function imageArtifactRecord(
  kind: 'generated_image' | 'uploaded_image',
  id: string,
  conversationId: string,
  metadata: Record<string, unknown> = {},
) {
  return {
    id,
    user_id: 'ani.mallya',
    conversation_id: conversationId,
    trace_id: 'visual-browser-trace',
    kind,
    status: 'ready',
    title: kind === 'generated_image' ? 'Generated image' : 'Uploaded image',
    source_format: null,
    source: null,
    mime_type: 'image/png',
    content_available: true,
    byte_size: TEST_PNG.length,
    sha256: 'a'.repeat(64),
    width: 2048,
    height: 2048,
    provider: kind === 'generated_image' ? 'comfyui' : 'user_upload',
    model: kind === 'generated_image' ? 'deterministic-image-model' : null,
    error_code: null,
    metadata,
  }
}

function observeBlockingBrowserErrors(page: Page) {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []

  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', error => pageErrors.push(error.message))

  return { consoleErrors, pageErrors }
}

// Return the composer controls by accessible name so attachment buttons cannot match.
function chatControls(page: Page) {
  const textarea = page.getByLabel('Message DeepMatter')
  const sendButton = page.getByRole('button', { name: 'Send message' })
  return { textarea, sendButton }
}

// Attach one file through the unified composer's real file-chooser interaction.
async function attachComposerFile(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
) {
  const chooserPromise = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Attach a file' }).click()
  await (await chooserPromise).setFiles(file)
}

function latestAssistantAnswer(page: Page) {
  return page.getByLabel('DeepMatter answer').last()
}

// Pull the artifact_ready payload out of a real chat SSE response. Generation
// and editing now arrive this way instead of as a standalone REST response,
// since the main model decides them inside the same streamed chat call.
async function artifactReadyFromChatStream(
  response: Awaited<ReturnType<Page['waitForResponse']>>,
): Promise<Record<string, unknown>> {
  const text = await response.text()
  const match = text.match(/event: artifact_ready\r?\ndata: (.+)\r?\n/)
  if (!match) throw new Error('Chat stream did not contain an artifact_ready event')
  return JSON.parse(match[1]) as Record<string, unknown>
}

// Build one deterministic SSE response with an optional memory proposal.
function chatEventStream(
  traceId: string,
  conversationId: string,
  response: string,
  preferredName?: string,
  responseStyle?: 'concise' | 'detailed',
  structuredProposal?: Record<string, unknown>,
) {
  const frames = [
    'event: start',
    `data: ${JSON.stringify({ trace_id: traceId, conversation_id: conversationId })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: response })}`,
    '',
  ]
  if (preferredName) {
    frames.push(
      'event: memory_proposal',
      `data: ${JSON.stringify({
        kind: 'preferred_name',
        value: preferredName,
        conversation_id: conversationId,
        trace_id: traceId,
      })}`,
      '',
    )
  } else if (responseStyle) {
    frames.push(
      'event: memory_proposal',
      `data: ${JSON.stringify({
        kind: 'response_style',
        value: responseStyle,
        conversation_id: conversationId,
        trace_id: traceId,
      })}`,
      '',
    )
  } else if (structuredProposal) {
    frames.push(
      'event: memory_proposal',
      `data: ${JSON.stringify({
        ...structuredProposal,
        conversation_id: conversationId,
        trace_id: traceId,
      })}`,
      '',
    )
  }
  frames.push(
    'event: done',
    'data: {}',
    '',
    '',
  )
  return frames.join('\n')
}

// Build one deterministic chat response containing several approval proposals.
function multiProposalEventStream(
  traceId: string,
  conversationId: string,
  response: string,
  proposals: Array<Record<string, unknown>>,
) {
  const frames = [
    'event: start',
    `data: ${JSON.stringify({ trace_id: traceId, conversation_id: conversationId })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: response })}`,
    '',
  ]
  for (const proposal of proposals) {
    frames.push(
      'event: memory_proposal',
      `data: ${JSON.stringify({
        ...proposal,
        conversation_id: conversationId,
        trace_id: traceId,
      })}`,
      '',
    )
  }
  frames.push('event: done', 'data: {}', '', '')
  return frames.join('\n')
}

// Build one deterministic MCP lifecycle followed by a completed chat answer.
function toolEventStream(
  conversationId: string,
  status: 'succeeded' | 'refused' | 'failed',
) {
  return [
    'event: start',
    `data: ${JSON.stringify({ trace_id: 'tool-trace', conversation_id: conversationId })}`,
    '',
    'event: tool_started',
    `data: ${JSON.stringify({ server_id: 'weather', tool_name: 'current_weather' })}`,
    '',
    'event: tool_finished',
    `data: ${JSON.stringify({
      server_id: 'weather',
      tool_name: 'current_weather',
      status,
      message: status === 'succeeded'
        ? 'Tool completed.'
        : 'Tool call was withheld by DeepMatter privacy or approval controls.',
    })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: status === 'succeeded' ? 'Raleigh is 72 F.' : 'I answered locally.' })}`,
    '',
    'event: done',
    'data: {}',
    '',
    '',
  ].join('\n')
}

// Build one durable specialist-agent handoff followed by a completed chat turn.
function agentEventStream(conversationId: string) {
  return [
    'event: start',
    `data: ${JSON.stringify({ trace_id: 'agent-trace', conversation_id: conversationId })}`,
    '',
    'event: agent_started',
    `data: ${JSON.stringify({
      agent_id: 'presentation_agent',
      agent_name: 'PresentationAgent',
      model: 'qualified/presentation-model',
    })}`,
    '',
    'event: agent_finished',
    `data: ${JSON.stringify({
      agent_id: 'presentation_agent',
      agent_name: 'PresentationAgent',
      model: 'qualified/presentation-model',
      job_id: '44444444-4444-4444-8444-444444444444',
      status: 'queued',
      message: 'Presentation job queued in the background.',
    })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: 'Your presentation is running in the background.' })}`,
    '',
    'event: done',
    'data: {}',
    '',
    '',
  ].join('\n')
}

// Build one completed internet-tool stream with attributable Google sources.
function searchEventStream(conversationId: string) {
  return [
    'event: start',
    `data: ${JSON.stringify({ trace_id: 'search-trace', conversation_id: conversationId })}`,
    '',
    'event: search_started',
    `data: ${JSON.stringify({ query: 'latest Python release' })}`,
    '',
    'event: tool_started',
    `data: ${JSON.stringify({ server_id: 'internet', tool_name: 'search_web' })}`,
    '',
    'event: tool_finished',
    `data: ${JSON.stringify({
      server_id: 'internet',
      tool_name: 'search_web',
      status: 'succeeded',
      message: 'Tool completed.',
    })}`,
    '',
    'event: search_results',
    `data: ${JSON.stringify({
      sources: [{
        title: 'Python releases',
        url: 'https://docs.python.org/3/whatsnew/',
        snippet: 'Current Python release notes.',
        provider: 'google',
      }],
    })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: 'Python release research completed.' })}`,
    '',
    'event: done',
    'data: {}',
    '',
    '',
  ].join('\n')
}

// Build one deterministic diagram artifact lifecycle for browser acceptance tests.
function diagramEventStream(
  traceId: string,
  conversationId: string,
  artifactId: string,
  outcome: 'ready' | 'failed',
) {
  const frames = [
    'event: start',
    `data: ${JSON.stringify({ trace_id: traceId, conversation_id: conversationId })}`,
    '',
    'event: artifact_started',
    `data: ${JSON.stringify({ id: artifactId, kind: 'diagram', status: 'pending' })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({
      content: outcome === 'ready'
        ? 'Created an editable diagram: Browser validation flow.'
        : "I couldn't create that diagram. Please revise the request and try again.",
    })}`,
    '',
  ]
  if (outcome === 'ready') {
    frames.push(
      'event: artifact_ready',
      `data: ${JSON.stringify({
        id: artifactId,
        user_id: 'ani.mallya',
        conversation_id: conversationId,
        trace_id: traceId,
        kind: 'diagram',
        status: 'ready',
        title: 'Browser validation flow',
        source_format: 'mermaid',
        source: 'flowchart TD\n  Start --> Validate\n  Validate --> Complete',
        mime_type: 'image/svg+xml',
        provider: 'deterministic-test',
        model: null,
        error_code: null,
        metadata: { diagram_type: 'flowchart' },
      })}`,
      '',
    )
  } else {
    frames.push(
      'event: artifact_error',
      `data: ${JSON.stringify({ id: artifactId, message: 'Unable to create the diagram.' })}`,
      '',
    )
  }
  frames.push('event: done', 'data: {}', '', '')
  return frames.join('\n')
}

// Build one deterministic image generate/edit artifact lifecycle. Generation and
// editing now run inside the chat stream -- the main model decides them, so the
// browser never calls /images/generate or /images/refine directly anymore.
function imageActionEventStream(
  traceId: string,
  conversationId: string,
  artifactId: string,
  action: 'generate' | 'edit',
  outcome: 'ready' | 'failed',
  metadata: Record<string, unknown> = {},
) {
  const readyText = action === 'edit'
    ? "Here's the edited image."
    : "Here's the image you asked for."
  const failedText = action === 'edit'
    ? "I couldn't edit that image. Please try again."
    : "I couldn't generate that image. Please try again."
  const frames = [
    'event: start',
    `data: ${JSON.stringify({ trace_id: traceId, conversation_id: conversationId })}`,
    '',
    'event: artifact_started',
    `data: ${JSON.stringify({ id: artifactId, kind: 'generated_image', status: 'pending' })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: outcome === 'ready' ? readyText : failedText })}`,
    '',
  ]
  if (outcome === 'ready') {
    frames.push(
      'event: artifact_ready',
      `data: ${JSON.stringify(
        imageArtifactRecord('generated_image', artifactId, conversationId, metadata),
      )}`,
      '',
    )
  } else {
    frames.push(
      'event: artifact_error',
      `data: ${JSON.stringify({
        id: artifactId,
        message: action === 'edit'
          ? 'Unable to edit the image.'
          : 'Unable to generate the image.',
      })}`,
      '',
    )
  }
  frames.push('event: done', 'data: {}', '', '')
  return frames.join('\n')
}

// Build one deterministic chat response that recalls an owned image by meaning.
function imageMatchEventStream(
  traceId: string,
  conversationId: string,
  response: string,
  artifact: Record<string, unknown>,
) {
  return [
    'event: start',
    `data: ${JSON.stringify({ trace_id: traceId, conversation_id: conversationId })}`,
    '',
    'event: delta',
    `data: ${JSON.stringify({ content: response })}`,
    '',
    'event: image_matches',
    `data: ${JSON.stringify({ artifacts: [artifact] })}`,
    '',
    'event: done',
    'data: {}',
    '',
    '',
  ].join('\n')
}

// Give deterministic tests one server-derived identity and empty owned history.
test.beforeEach(async ({ page }, testInfo) => {
  if (testInfo.title.includes('@live')) return
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: 'ani.mallya',
      expires_at: '2026-08-09T00:00:00Z',
      is_admin: false,
    }),
  }))
  await page.route('http://localhost:8000/api/v1/conversations/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversations: [] }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/discovery/ani.mallya/subscription', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ subscription: null, egress_enabled: false }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/discovery/ani.mallya/runs?limit=5', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ runs: [] }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/discovery/ani.mallya/search-usage', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        today: { used: 0, limit: 10, remaining: 10 },
        month: { used: 0, limit: 1000, remaining: 1000 },
      }),
    }),
  )
})

// Verify login is the only initial view and logout removes private workspace state.
test('requires invite credentials before showing the private workspace', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let authenticated = false
  await page.unroute('http://localhost:8000/api/v1/auth/session')
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: authenticated ? 200 : 401,
    contentType: 'application/json',
    body: JSON.stringify(authenticated
      ? { authentication_required: true, user_id: 'friend.user', expires_at: '2026-08-09T00:00:00Z' }
      : { detail: 'Authentication required' }),
  }))
  await page.route('http://localhost:8000/api/v1/auth/login', async route => {
    const body = route.request().postDataJSON() as { username: string; password: string }
    if (body.username !== 'friend.user' || body.password !== 'correct test password') {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid username or password' }),
      })
      return
    }
    authenticated = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Set-Cookie': 'anios_session=browser-test; Path=/; HttpOnly; SameSite=Lax' },
      body: JSON.stringify({
        authentication_required: true,
        user_id: 'friend.user',
        expires_at: '2026-08-09T00:00:00Z',
      }),
    })
  })
  await page.route('http://localhost:8000/api/v1/auth/logout', async route => {
    authenticated = false
    await route.fulfill({ status: 204 })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in to DeepMatter' })).toBeVisible()
  await expect(page.getByLabel('Message DeepMatter')).not.toBeVisible()
  await page.getByLabel('Username').fill('friend.user')
  await page.getByLabel('Password').fill('wrong test password')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid username or password')

  await page.getByLabel('Password').fill('correct test password')
  await page.getByRole('button', { name: 'Continue' }).click()
  // Rendered twice by design — the mobile drawer and the desktop header —
  // so this asserts on one of them rather than on the page.
  await expect(
    page.getByRole('main').getByText('Signed in as friend.user'),
  ).toBeVisible()
  await expect(page.getByLabel('Message DeepMatter')).toBeVisible()
  // Two sign-out controls exist on purpose: a labelled row in the mobile
  // drawer and an icon button in the desktop header. This is the desktop
  // viewport, so it clicks the icon.
  await page.getByLabel('Sign out').click()
  await expect(page.getByRole('heading', { name: 'Sign in to DeepMatter' })).toBeVisible()
  await expect(page.getByLabel('Message DeepMatter')).not.toBeVisible()
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors.length).toBeGreaterThan(0)
  expect(errors.consoleErrors.every(message => message.includes('401 (Unauthorized)'))).toBe(true)
})

// Verify invited profile creation validates secrets and enters the owned workspace.
test('records an access request instead of creating an account outright', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let requestPayload: Record<string, unknown> | null = null
  await page.unroute('http://localhost:8000/api/v1/auth/session')
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Authentication required' }),
  }))
  await page.route('http://localhost:8000/api/v1/auth/request-access', async route => {
    requestPayload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ request_token: 'pending-token', status: 'pending' }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Request an account' }).click()
  await expect(page.getByRole('heading', { name: 'Create your profile' })).toBeVisible()
  await page.getByLabel('Username').fill('new.friend')
  await page.getByLabel('Password', { exact: true }).fill('a sufficiently long password')
  await page.getByLabel('Confirm password').fill('a different long password')
  await page.getByRole('button', { name: 'Request access' }).click()
  await expect(page.getByRole('alert')).toContainText('Passwords do not match')

  await page.getByLabel('Confirm password').fill('a sufficiently long password')
  await page.getByLabel('Your name').fill('New Friend')
  await page.getByRole('button', { name: 'Request access' }).click()

  // Signing up does not sign you in. The owner has to approve the request
  // before the account exists at all, and the screen has to say so rather than
  // implying a workspace is waiting.
  await expect(page.getByRole('heading', { name: 'Request sent' })).toBeVisible()
  await expect(page.getByLabel('Message DeepMatter')).not.toBeVisible()
  expect(requestPayload).toEqual({
    display_name: 'New Friend',
    username: 'new.friend',
    password: 'a sufficiently long password',
    reason: null,
  })
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors.every(message => message.includes('401 (Unauthorized)'))).toBe(true)
})

// Exercise live browser registration and semantic isolation through the gateway.
test('@live invited profiles keep semantic context private across logout', async ({ page }) => {
  test.setTimeout(120_000)
  const firstUser = process.env.ANIOS_E2E_REGISTER_USER_A
  const firstPassword = process.env.ANIOS_E2E_REGISTER_PASSWORD_A
  const firstInvite = process.env.ANIOS_E2E_REGISTER_INVITE_A
  const secondUser = process.env.ANIOS_E2E_REGISTER_USER_B
  const secondPassword = process.env.ANIOS_E2E_REGISTER_PASSWORD_B
  const secondInvite = process.env.ANIOS_E2E_REGISTER_INVITE_B
  test.skip(
    !firstUser || !firstPassword || !firstInvite
      || !secondUser || !secondPassword || !secondInvite,
    'Set both ANIOS_E2E_REGISTER user/password/invite triples for live acceptance.',
  )
  const errors = observeBlockingBrowserErrors(page)
  const firstMarker = `private-blue-orchid-${Date.now()}`

  // Register one invited profile through the visible browser form.
  const registerProfile = async (username: string, password: string, invite: string) => {
    await page.getByRole('button', { name: 'Create an invited profile' }).click()
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByLabel('Confirm password').fill(password)
    await page.getByLabel('Invitation code').fill(invite)
    await page.getByRole('button', { name: 'Create profile' }).click()
    await expect(page.getByText(`Signed in as ${username}`)).toBeVisible()
  }

  await page.goto('/')
  await registerProfile(firstUser!, firstPassword!, firstInvite!)
  const firstWrite = await page.evaluate(async ({ user, marker }) => {
    const response = await fetch(`/api/v1/memory/${encodeURIComponent(user)}/semantic`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: marker, metadata: { source: 'live-browser' } }),
    })
    return response.status
  }, { user: firstUser!, marker: firstMarker })
  expect(firstWrite).toBe(201)
  await page.getByRole('button', { name: 'Sign out' }).click()

  await registerProfile(secondUser!, secondPassword!, secondInvite!)
  const secondView = await page.evaluate(async ({ first, second, marker }) => {
    const cross = await fetch(`/api/v1/memory/${encodeURIComponent(first)}`, {
      credentials: 'include',
    })
    const own = await fetch(`/api/v1/memory/${encodeURIComponent(second)}`, {
      credentials: 'include',
    })
    const ownSearch = await fetch(
      `/api/v1/memory/${encodeURIComponent(second)}/search?query=${encodeURIComponent(marker)}`,
      { credentials: 'include' },
    )
    return {
      crossStatus: cross.status,
      ownStatus: own.status,
      own: await own.json(),
      ownSearchStatus: ownSearch.status,
      ownSearch: await ownSearch.json(),
    }
  }, { first: firstUser!, second: secondUser!, marker: firstMarker })
  expect(secondView.crossStatus).toBe(403)
  expect(secondView.ownStatus).toBe(200)
  expect(secondView.own.semantic).toEqual([])
  expect(secondView.ownSearchStatus).toBe(200)
  expect(secondView.ownSearch.memories).toEqual([])
  await page.getByRole('button', { name: 'Sign out' }).click()

  await page.getByLabel('Username').fill(firstUser!)
  await page.getByLabel('Password').fill(firstPassword!)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByText(`Signed in as ${firstUser}`)).toBeVisible()
  const firstView = await page.evaluate(async ({ user, marker }) => {
    const response = await fetch(`/api/v1/memory/${encodeURIComponent(user)}`, {
      credentials: 'include',
    })
    const search = await fetch(
      `/api/v1/memory/${encodeURIComponent(user)}/search?query=${encodeURIComponent(marker)}`,
      { credentials: 'include' },
    )
    return {
      status: response.status,
      body: await response.json(),
      searchStatus: search.status,
      searchBody: await search.json(),
    }
  }, { user: firstUser!, marker: firstMarker })
  expect(firstView.status).toBe(200)
  expect(firstView.body.semantic.map((item: { content: string }) => item.content)).toContain(firstMarker)
  expect(firstView.searchStatus).toBe(200)
  expect(firstView.searchBody.memories.map((item: { content: string }) => item.content)).toContain(firstMarker)
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors.every(message => (
    message.includes('401 (Unauthorized)') || message.includes('403 (Forbidden)')
  ))).toBe(true)
})

// Exercise real password sessions, chat persistence, and cross-user denial in Chromium.
test('@live password login keeps one conversation private from another account', async ({ page }) => {
  test.setTimeout(180_000)
  const firstUser = process.env.ANIOS_E2E_AUTH_USER
  const firstLogin = process.env.ANIOS_E2E_AUTH_LOGIN ?? firstUser
  const firstPassword = process.env.ANIOS_E2E_AUTH_PASSWORD
  const secondUser = process.env.ANIOS_E2E_AUTH_OTHER_USER
  const secondLogin = process.env.ANIOS_E2E_AUTH_OTHER_LOGIN ?? secondUser
  const secondPassword = process.env.ANIOS_E2E_AUTH_OTHER_PASSWORD
  const browserApiOrigin = process.env.ANIOS_E2E_BROWSER_API_ORIGIN
    ?? 'http://localhost:8000'
  test.skip(
    !firstUser || !firstPassword || !secondUser || !secondPassword,
    'Set both ANIOS_E2E_AUTH user/password pairs for live authentication acceptance.',
  )
  const errors = observeBlockingBrowserErrors(page)
  const uniqueMessage = `AUTH_ISOLATION_${Date.now()}`

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in to DeepMatter' })).toBeVisible()
  await page.getByLabel('Username').fill(firstLogin!)
  await page.getByLabel('Password').fill(firstPassword!)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByText(`Signed in as ${firstUser}`)).toBeVisible()

  const { textarea, sendButton } = chatControls(page)
  const requestPromise = page.waitForRequest(`${browserApiOrigin}/api/v1/chat`)
  const responsePromise = page.waitForResponse(`${browserApiOrigin}/api/v1/chat`)
  await textarea.fill(`${uniqueMessage}. Reply briefly that authentication isolation works.`)
  await sendButton.click()
  const request = await requestPromise
  const payload = request.postDataJSON() as { user_id: string; conversation_id: string }
  const response = await responsePromise
  expect(payload.user_id).toBe(firstUser)
  expect(response.status()).toBe(200)
  expect(await response.finished()).toBeNull()
  await expect(textarea).toBeEnabled({ timeout: 120_000 })
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(latestAssistantAnswer(page)).not.toBeEmpty()

  const ownSnapshot = await page.evaluate(async ({ user, conversation }) => {
    const result = await fetch(
      `${origin}/api/v1/conversations/${encodeURIComponent(user)}/${conversation}`,
      { credentials: 'include' },
    )
    return { status: result.status, body: await result.json() }
  }, { origin: browserApiOrigin, user: firstUser!, conversation: payload.conversation_id })
  expect(ownSnapshot.status).toBe(200)
  expect(ownSnapshot.body.turns.some((turn: { query: string }) => turn.query.includes(uniqueMessage))).toBe(true)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByLabel('Username').fill(secondLogin!)
  await page.getByLabel('Password').fill(secondPassword!)
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByText(`Signed in as ${secondUser}`)).toBeVisible()

  const isolation = await page.evaluate(async ({ first, second, conversation }) => {
    const cross = await fetch(
      `${origin}/api/v1/conversations/${encodeURIComponent(first)}/${conversation}`,
      { credentials: 'include' },
    )
    const own = await fetch(
      `${origin}/api/v1/conversations/${encodeURIComponent(second)}/${conversation}`,
      { credentials: 'include' },
    )
    return {
      crossStatus: cross.status,
      ownStatus: own.status,
      ownBody: await own.json(),
    }
  }, {
    origin: browserApiOrigin,
    first: firstUser!,
    second: secondUser!,
    conversation: payload.conversation_id,
  })
  expect(isolation.crossStatus).toBe(403)
  expect(isolation.ownStatus).toBe(200)
  expect(isolation.ownBody.turns).toEqual([])
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors.every(message => (
    message.includes('401 (Unauthorized)') || message.includes('403 (Forbidden)')
  ))).toBe(true)
})

test('renders a responsive search-first chat shell', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'What can I help you find?' })).toBeVisible()
  const composer = page.getByLabel('Message DeepMatter')
  await expect(composer).toBeVisible()
  await composer.fill('Native font check')
  const fonts = await composer.evaluate(element => {
    const composerStyle = getComputedStyle(element)
    const shellStyle = getComputedStyle(element.parentElement!)
    return {
      root: getComputedStyle(document.documentElement).fontFamily,
      composer: composerStyle.fontFamily,
      composerBackground: composerStyle.backgroundColor,
      composerOutline: composerStyle.outlineStyle,
      shellBackground: shellStyle.backgroundColor,
      shellBorder: shellStyle.borderColor,
      shellShadow: shellStyle.boxShadow,
    }
  })
  expect(fonts.composer).toBe(fonts.root)
  expect(fonts.composer).toContain('system-ui')
  expect(fonts.composerBackground).toBe('rgba(0, 0, 0, 0)')
  expect(fonts.composerOutline).toBe('none')
  expect(fonts.shellBackground).toBe('rgb(255, 255, 255)')
  expect(fonts.shellBorder).not.toContain('0, 113, 227')
  expect(fonts.shellShadow).not.toContain('0, 113, 227')
  await expect(page.getByRole('button', { name: 'Show Sidebar' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Conversations' })).not.toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  await page.getByRole('button', { name: 'Show Sidebar' }).click()
  await expect(page.getByRole('button', { name: 'Conversations' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Keep the active account and logout action explicit on a phone, where the
// compact header otherwise makes it easy to configure Scout under the wrong user.
// Count how many of a locator's matches are actually on screen. Playwright's
// own visibility rules, rather than offsetParent, which reports null for a
// fixed-position element and would call the mobile drawer invisible.
const countVisible = async (locator: import('@playwright/test').Locator) => {
  const total = await locator.count()
  let visible = 0
  for (let index = 0; index < total; index += 1) {
    if (await locator.nth(index).isVisible()) visible += 1
  }
  return visible
}

// Exactly one way to sign out, and one statement of who is signed in.
//
// The sidebar rendered account controls and the header rendered its own, gated
// on different breakpoints: the header on sm, the sidebar's on nothing at all.
// Since the sidebar opens by default from 768px, every desktop window showed
// two sign-out buttons and two identity lines. One test per width, because each
// needs a fresh mount: the sidebar decides whether it is a drawer once, at
// mount, from the width it sees then.
for (const width of [1440, 1024, 820, 768]) {
  test(`offers one identity and one sign-out at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'DeepMatter' })).toBeVisible()

    // The sidebar's copy is display:none from md, so it leaves the
    // accessibility tree entirely rather than merely sitting off screen.
    await expect(page.getByRole('button', { name: 'Sign out' })).toHaveCount(1)
    await expect(countVisible(page.getByText(/^Signed in as /))).resolves.toBe(1)
  })
}

for (const width of [700, 640, 500, 390]) {
  test(`keeps identity and sign-out in the drawer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'DeepMatter' })).toBeVisible()

    // Below md the header shows neither; the menu button is the way in.
    await expect(countVisible(page.getByRole('button', { name: 'Sign out' }))).resolves.toBe(0)
    await page.getByRole('button', { name: 'Show Sidebar' }).click()

    const drawer = page.getByRole('region', { name: 'Account controls' })
    await expect(drawer.getByRole('button', { name: 'Sign out' })).toBeVisible()
    await expect(drawer.getByText(/^Signed in as /)).toBeVisible()
    await expect(countVisible(page.getByRole('button', { name: 'Sign out' }))).resolves.toBe(1)
  })
}

test('shows mobile account identity and logout in the navigation drawer', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('http://localhost:8000/api/v1/auth/logout', route => route.fulfill({
    status: 204,
  }))

  await page.goto('/')
  await page.getByRole('button', { name: 'Show Sidebar' }).click()

  const accountControls = page.getByRole('region', { name: 'Account controls' })
  await expect(accountControls.getByText('Signed in as ani.mallya')).toBeVisible()
  await accountControls.getByRole('button', { name: 'Sign out' }).click()

  await expect(page.getByRole('heading', { name: 'Sign in to DeepMatter' })).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('ignores client-stored user spoofing and scopes conversations by authenticated user', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const legacyConversation = '11111111-1111-4111-8111-111111111111'
  const customConversation = '22222222-2222-4222-8222-222222222222'
  const requests: Array<{ user_id: string; conversation_id: string }> = []

  await page.addInitScript(({ conversation }) => {
    localStorage.setItem('anios_user_id', 'attacker.user')
    localStorage.setItem('anios_conversation_id', conversation)
    localStorage.setItem('anios_conversation_id:attacker.user', '22222222-2222-4222-8222-222222222222')
  }, { conversation: legacyConversation })
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    requests.push({
      user_id: payload.user_id,
      conversation_id: payload.conversation_id,
    })
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('migration-trace', payload.conversation_id, 'ok'),
    })
  })

  // Keep transcript restoration inside the authenticated deterministic boundary.
  await page.route(
    'http://localhost:8000/api/v1/conversations/ani.mallya/*',
    async route => {
      const conversationId = route.request().url().split('/').pop()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          conversation_id: conversationId,
          turns: [],
          artifacts: [],
        }),
      })
    },
  )

  await page.goto('/')
  const stored = await page.evaluate(() => ({
    userId: localStorage.getItem('anios_user_id'),
    conversationId: localStorage.getItem('anios_conversation_id:ani.mallya'),
  }))
  expect(stored.userId).toBe('attacker.user')
  expect(stored.conversationId).toBe(legacyConversation)

  let controls = chatControls(page)
  await controls.textarea.fill('verify migrated default')
  await controls.sendButton.click()
  await expect(controls.textarea).toBeEnabled()
  expect(requests[0]).toEqual({
    user_id: 'ani.mallya',
    conversation_id: stored.conversationId,
  })

  await page.evaluate(({ conversation }) => {
    localStorage.setItem('anios_user_id', 'custom_user')
    localStorage.setItem('anios_conversation_id:custom_user', conversation)
  }, { conversation: customConversation })
  await page.reload()

  controls = chatControls(page)
  await controls.textarea.fill('verify custom user')
  await controls.sendButton.click()
  await expect(controls.textarea).toBeEnabled()
  expect(requests[1]).toEqual({
    user_id: 'ani.mallya',
    conversation_id: legacyConversation,
  })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('renders a completed deterministic chat stream and clears loading state', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const uniqueMessage = `E2E_SUCCESS_${Date.now()}`
  let requestPayload: unknown
  let releaseResponse: () => void = () => undefined
  const responseGate = new Promise<void>(resolve => {
    releaseResponse = resolve
  })
  let requestObserved: () => void = () => undefined
  const requestSeen = new Promise<void>(resolve => {
    requestObserved = resolve
  })

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    requestPayload = route.request().postDataJSON()
    requestObserved()
    await responseGate
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'deterministic-trace',
        (requestPayload as { conversation_id: string }).conversation_id,
        'deterministic browser ok',
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  const responsePromise = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat',
  )

  await textarea.fill(uniqueMessage)
  await sendButton.click()
  await requestSeen
  await expect(textarea).toBeDisabled()
  await expect(sendButton).toBeDisabled()
  await expect(page.getByText('Thinking...', { exact: true })).toBeVisible()

  releaseResponse()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  expect(await response.finished()).toBeNull()

  await expect(page.getByRole('paragraph').filter({ hasText: uniqueMessage })).toBeVisible()
  const answer = latestAssistantAnswer(page)
  await expect(answer.getByText('deterministic browser ok', { exact: true })).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(answer.getByText('deterministic-trace', { exact: true })).not.toBeVisible()
  await answer.getByLabel('Show response metadata').click()
  await expect(answer.getByText('deterministic-trace', { exact: true })).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(sendButton).toBeDisabled()
  expect(requestPayload).toMatchObject({
    user_id: 'ani.mallya',
    query: uniqueMessage,
    metadata: {},
  })
  expect((requestPayload as { conversation_id: string }).conversation_id).toMatch(
    /^[0-9a-f-]{36}$/,
  )
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify successful MCP use remains visible after the answer finishes.
test('shows the MCP tool used for a completed chat answer', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let requestPayload: { conversation_id: string } | undefined
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    requestPayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: toolEventStream(requestPayload!.conversation_id, 'succeeded'),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Use the weather tool for Raleigh')
  await sendButton.click()

  const answer = latestAssistantAnswer(page)
  await expect(answer.getByText('Used current_weather via weather')).toBeVisible()
  await expect(answer.getByText('Raleigh is 72 F.')).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify specialist delegation and its exact model remain visible after queuing.
test('shows a background PresentationAgent handoff in chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON() as { conversation_id: string }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: agentEventStream(payload.conversation_id),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Create a presentation about horses with 6 slides')
  await sendButton.click()

  const answer = latestAssistantAnswer(page)
  await expect(
    answer.getByText(
      'PresentationAgent · qualified/presentation-model queued in the background',
    ),
  ).toBeVisible()
  await expect(
    answer.getByText('Your presentation is running in the background.'),
  ).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify the UI attributes grounded sources and clears the internet tool lifecycle.
test('shows Google source attribution for an internet MCP response', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON() as { conversation_id: string }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: searchEventStream(payload.conversation_id),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Search online for the latest Python release')
  await sendButton.click()

  const answer = latestAssistantAnswer(page)
  await expect(answer.getByText('Used search_web via internet')).toBeVisible()
  const sources = answer.getByLabel('Web sources used')
  await expect(sources).toBeVisible()
  await expect(sources.getByText('Google · docs.python.org', { exact: true })).toBeVisible()
  await expect(sources.getByRole('link', { name: 'Python releases' })).toHaveAttribute(
    'href',
    'https://docs.python.org/3/whatsnew/',
  )
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a refused MCP call is visible and does not leave chat loading.
test('shows an MCP refusal while the local answer still completes', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: toolEventStream(payload.conversation_id, 'refused'),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Send private data through a tool')
  await sendButton.click()

  const answer = latestAssistantAnswer(page)
  await expect(answer.getByText(/withheld by DeepMatter privacy/)).toBeVisible()
  await expect(answer.getByText('I answered locally.')).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify assistant CommonMark becomes semantic headings, emphasis, and lists.
test('renders assistant markdown without interpreting raw HTML', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const streamedChunks = [
    '### 1. The Immediate Tactical Opportunity\n\nYou are playing as **',
    'Black** and should consider *Queen to ',
    'h6*.\n\n* **Move:** **Queen to h6 (Qh6)**\n',
    '* **Why:** It creates immediate pressure.\n\n',
    '<img src="invalid" onerror="window.markdownInjected = true">',
  ]

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    const frames = [
      'event: start',
      `data: ${JSON.stringify({
        trace_id: 'markdown-trace',
        conversation_id: payload.conversation_id,
      })}`,
      '',
    ]
    for (const content of streamedChunks) {
      frames.push('event: delta', `data: ${JSON.stringify({ content })}`, '')
    }
    frames.push('event: done', 'data: {}', '', '')
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: frames.join('\n'),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Analyze this board')
  await sendButton.click()

  const answer = latestAssistantAnswer(page)
  await expect(answer.getByRole('heading', {
    level: 3,
    name: '1. The Immediate Tactical Opportunity',
  })).toBeVisible()
  await expect(answer.getByText('Black', { exact: true })).toHaveJSProperty('tagName', 'STRONG')
  await expect(answer.getByText('Queen to h6', { exact: true })).toHaveJSProperty('tagName', 'EM')
  await expect(answer.getByRole('listitem')).toHaveCount(2)
  await expect(answer.locator('img')).toHaveCount(0)
  expect(await page.evaluate(() => 'markdownInjected' in window)).toBe(false)
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a streamed diagram renders, retains editable source, and survives tab navigation.
test('renders a completed diagram artifact and preserves it across tab navigation', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const uniqueMessage = `Create a flowchart for E2E_DIAGRAM_${Date.now()}`
  const artifactId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  let requestPayload: Record<string, unknown> = {}

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    requestPayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: diagramEventStream(
        'diagram-browser-trace',
        String(requestPayload.conversation_id),
        artifactId,
        'ready',
      ),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: 'ani.mallya', preferences: {} },
        episodic: [],
        semantic: [],
        facts: [],
      }),
    }),
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  const responsePromise = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat',
  )
  await textarea.fill(uniqueMessage)
  await sendButton.click()

  const response = await responsePromise
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  expect(await response.finished()).toBeNull()
  const diagram = page.getByLabel('Diagram: Browser validation flow')
  await expect(diagram).toBeVisible()
  await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()
  await diagram.getByText('View Mermaid source', { exact: true }).click()
  await expect(diagram.getByText('Start --> Validate', { exact: false })).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(sendButton).toBeDisabled()
  expect(requestPayload).toMatchObject({
    user_id: 'ani.mallya',
    query: uniqueMessage,
    metadata: {},
  })

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await page.getByRole('button', { name: 'Conversations', exact: true }).click()
  await expect(diagram).toBeVisible()
  await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a persisted diagram and transcript are restored after a full reload.
test('restores a completed diagram artifact after a full browser reload', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const userId = 'reload_diagram_user'
  const conversationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  const artifactId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
  const traceId = 'reload-diagram-trace'
  const query = 'Create the reload validation flowchart'
  let persisted = false

  await page.unroute('http://localhost:8000/api/v1/auth/session')
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: userId,
      expires_at: '2026-08-09T00:00:00Z',
    }),
  }))
  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem(`anios_conversation_id:${user}`, conversation)
  }, { user: userId, conversation: conversationId })
  await page.route(`http://localhost:8000/api/v1/conversations/${userId}/${conversationId}`, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        conversation_id: conversationId,
        turns: persisted ? [{
          id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
          conversation_id: conversationId,
          user_id: userId,
          query,
          response: 'Created an editable diagram: Reload validation flow.',
          metadata: { artifact_ids: [artifactId], artifact_status: 'ready' },
        }] : [],
        artifacts: persisted ? [{
          id: artifactId,
          user_id: userId,
          conversation_id: conversationId,
          trace_id: traceId,
          kind: 'diagram',
          status: 'ready',
          title: 'Reload validation flow',
          source_format: 'mermaid',
          source: 'flowchart TD\n  ReloadStart --> ReloadComplete',
          mime_type: 'image/svg+xml',
          provider: 'deterministic-test',
          model: null,
          error_code: null,
          metadata: { diagram_type: 'flowchart' },
        }] : [],
      }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    persisted = true
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: diagramEventStream(
        traceId,
        conversationId,
        artifactId,
        'ready',
      ).replaceAll('ani.mallya', userId),
    })
  })

  await page.goto('/')
  await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill(query)
  await sendButton.click()
  await expect(page.getByLabel('Diagram: Browser validation flow')).toBeVisible()

  await page.reload()
  await expect(page.getByText(query, { exact: true })).toBeVisible()
  const restored = page.getByLabel('Diagram: Reload validation flow')
  await expect(restored).toBeVisible()
  await expect(restored.getByLabel('Rendered Mermaid diagram')).toBeVisible()
  await restored.getByText('View Mermaid source', { exact: true }).click()
  await expect(restored.locator('pre')).toContainText('ReloadStart --> ReloadComplete')
  await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
  await expect(page.getByRole('alert')).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify owned diagram history supports Mermaid/SVG download and deletion.
test('manages visual artifact history and local exports', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
  let deleted = false
  await page.route('http://localhost:8000/api/v1/artifacts/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(deleted ? [] : [{
        id: artifactId,
        user_id: 'ani.mallya',
        conversation_id: 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa',
        trace_id: 'artifact-history-trace',
        kind: 'diagram',
        status: 'ready',
        title: 'Artifact history flow',
        source_format: 'mermaid',
        source: 'flowchart TD\n  HistoryStart --> HistoryComplete',
        mime_type: 'image/svg+xml',
        provider: 'deterministic-test',
        model: null,
        error_code: null,
        metadata: { diagram_type: 'flowchart' },
      }]),
    }),
  )
  await page.route(`http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}`, route => {
    deleted = true
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'deleted', id: artifactId }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Visual artifacts' }).click()
  const diagram = page.getByLabel('Diagram: Artifact history flow')
  await expect(diagram).toBeVisible()
  await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()

  const mermaidDownload = page.waitForEvent('download')
  await diagram.getByRole('button', { name: 'Mermaid' }).click()
  expect((await mermaidDownload).suggestedFilename()).toBe('artifact-history-flow.mmd')

  const svgDownload = page.waitForEvent('download')
  await diagram.getByRole('button', { name: 'SVG' }).click()
  expect((await svgDownload).suggestedFilename()).toBe('artifact-history-flow.svg')

  await page.getByRole('button', { name: 'Delete Artifact history flow' }).click()
  await expect(diagram).not.toBeVisible()
  await expect(page.getByText('No visual artifacts yet.', { exact: false })).toBeVisible()
  expect(deleted).toBe(true)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify artifact history load failures are visible instead of appearing empty.
test('shows a visible visual artifact history failure', async ({ page }) => {
  await page.route('http://localhost:8000/api/v1/artifacts/ani.mallya', route =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Artifact history is unavailable.' }),
    }),
  )
  await page.goto('/')
  await page.getByRole('button', { name: 'Visual artifacts' }).click()
  await expect(page.getByRole('alert')).toContainText('Artifact history is unavailable.')
  await expect(page.getByText('No visual artifacts yet.', { exact: false })).toBeVisible()
})

// Verify diagram-generation failures are visible and do not leave chat loading.
test('shows a diagram artifact failure and clears loading state', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const uniqueMessage = `Create a failed flowchart E2E_DIAGRAM_FAILURE_${Date.now()}`

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: diagramEventStream(
        'diagram-failure-trace',
        payload.conversation_id,
        'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'failed',
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill(uniqueMessage)
  await sendButton.click()

  await expect(page.getByRole('alert').filter({ hasText: 'Unable to create the diagram.' })).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(sendButton).toBeDisabled()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('disables message and manual-memory actions until they have content', async ({ page }) => {
  await page.route('http://localhost:8000/api/v1/memory/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: 'ani.mallya', preferences: {} },
        episodic: [],
        semantic: [],
        facts: [],
      }),
    }),
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await expect(sendButton).toBeDisabled()
  await textarea.fill('ready')
  await expect(sendButton).toBeEnabled()
  await textarea.fill('   ')
  await expect(sendButton).toBeDisabled()

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await expect(page.getByLabel('Event or experience')).not.toBeVisible()
  await page.getByText('Advanced: add memory manually').click()
  const episodicInput = page.getByLabel('Event or experience')
  const semanticInput = page.getByLabel('Fact or preference')
  const addEpisodic = page.getByRole('button', { name: 'Add event or experience' })
  const addSemantic = page.getByRole('button', { name: 'Add fact or preference' })
  await expect(addEpisodic).toBeDisabled()
  await expect(addSemantic).toBeDisabled()
  await episodicInput.fill('an event')
  await semanticInput.fill('a durable fact')
  await expect(addEpisodic).toBeEnabled()
  await expect(addSemantic).toBeEnabled()
})

test('shows every agent memory form with live user-scoped counts', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const requested: string[] = []
  let exportRequests = 0
  await page.route('http://localhost:8000/api/v1/memory/ani.mallya/agent', async route => {
    requested.push('agent')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        semantic_cache: 2,
        working: 3,
        procedures: 4,
        entities: 5,
        entity_relations: 6,
        knowledge_documents: 7,
        knowledge_chunks: 8,
        summaries: 9,
      }),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/ani.mallya/tools', async route => {
    requested.push('tools')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ descriptors: [{ id: 'one' }], preferences: [], outcomes: [] }),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/ani.mallya', async route => {
    requested.push('personal')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: 'ani.mallya', name: 'Ani', preferences: {} },
        episodic: [{ id: 'episode', user_id: 'ani.mallya', content: 'event', extra_data: {} }],
        semantic: [{ id: 'fact', user_id: 'ani.mallya', content: 'fact', extra_data: {} }],
        facts: [{ id: 'profile-fact' }],
      }),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/ani.mallya/export', async route => {
    exportRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema_version: 2,
        exported_at: '2026-07-23T12:00:00Z',
        user_id: 'ani.mallya',
        agent_memory: {
          semantic_cache: [{
            id: 'cache-1',
            intent: 'Find calendar availability',
            selected_tool: 'calendar.search',
            embedding: [0.1, 0.2],
          }],
        },
        memory: {
          profile: { user_id: 'ani.mallya', name: 'Ani', preferences: {} },
          episodic: [],
          semantic: [],
          facts: [],
        },
        conversations: [],
      }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Memory', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Agent memory map' })).toBeVisible()
  for (const label of [
    'LLM context window',
    'Session based',
    'Semantic cache',
    'Procedural / workflow',
    'Toolbox',
    'Entity memory',
    'Knowledge base',
    'Persona',
    'Semantic',
    'Episodic',
    'Summaries',
    'Conversational',
  ]) {
    await expect(page.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('3 active items', { exact: true })).toBeVisible()
  await expect(page.getByText('7 documents, 8 chunks', { exact: true })).toBeVisible()
  await expect(page.getByText('9 conversation digests', { exact: true })).toBeVisible()
  expect([...new Set(requested)].sort()).toEqual(['agent', 'personal', 'tools'])
  expect(exportRequests).toBe(0)

  await page.getByRole('button', { name: 'View Semantic cache details' }).click()
  const details = page.getByRole('region', { name: 'Semantic cache details' })
  await expect(details).toBeVisible()
  await expect(details.getByText('Find calendar availability', { exact: true })).toBeVisible()
  await expect(details.getByText('calendar.search', { exact: true })).toBeVisible()
  await expect(details.getByText('Embedding', { exact: true })).not.toBeVisible()
  expect(exportRequests).toBe(1)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('renders a visible error and clears loading state when chat fails', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const uniqueMessage = `E2E_FAILURE_${Date.now()}`
  let rejectRequest: () => void = () => undefined
  const rejectionGate = new Promise<void>(resolve => {
    rejectRequest = resolve
  })

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    await rejectionGate
    await route.abort('connectionrefused')
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill(uniqueMessage)
  await sendButton.click()

  await expect(page.getByText('Thinking...', { exact: true })).toBeVisible()
  rejectRequest()
  await expect(
    page.getByText('DeepMatter did not respond, so nothing was sent.', { exact: false }),
  ).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('paragraph').filter({ hasText: uniqueMessage })).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue(uniqueMessage)
  await expect(sendButton).toBeEnabled()
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors.some(error => error.includes('ERR_CONNECTION_REFUSED'))).toBe(true)
  expect(
    errors.consoleErrors.filter(error => !error.includes('ERR_CONNECTION_REFUSED')),
  ).toEqual([])
})

// The backend auto-saves a classified proposal before the reply streams, with
// no approval round-trip - the frontend never calls a write endpoint for one.
// It only has to show what was already written.
test('shows an auto-saved preferred-name proposal from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('proposal-trace', payload.conversation_id, 'ok', 'Approved Name'),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('My name is Approved Name.')
  await sendButton.click()
  await expect(page.getByText('Saved Approved Name as preferred name memory.')).toBeVisible()
  await expect(page.getByRole('button', { name: /approve/i })).toHaveCount(0)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('shows an auto-saved response-style proposal from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'style-proposal-trace',
        payload.conversation_id,
        'ok',
        undefined,
        'concise',
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Please be concise.')
  await sendButton.click()
  await expect(page.getByText('Saved concise as response style memory.')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A typed place must be able to say which Arlington it means.
//
// The form had one box and sent only `label`, so typing could not set a region
// at all: "Arlington" was stored region-less, which is the ambiguity the web
// source warns about, and "Arlington, Virginia" was stored as a town with that
// entire string as its name. Only "Use my location" ever set a region, which is
// why a denied permission left the user worse off than granting it.
// Picking a suggestion fills both halves, so nobody has to know the format.
test('completes a part-typed place and fills the region with it', async ({ page }) => {
  const asked: string[] = []
  const saved: Array<Record<string, unknown>> = []
  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ user_id: 'ani.mallya', agents: [{
      id: 'discovery', name: 'Scout', role: 'Finds things happening near you.',
      status: 'idle', detail: 'Ready.', trigger: 'On request',
      last_active_at: null, facts: [],
    }] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ user_id: 'ani.mallya', interests: [], localities: [] }) }))
  for (const path of ['sources', 'schedule', 'known']) {
    await page.route(`**/api/v1/discovery/ani.mallya/${path}`, route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ sources: [], schedule: null, locality: null, known: [] }) }))
  }
  await page.route('**/api/v1/discovery/ani.mallya/locality/suggest**', route => {
    asked.push(new URL(route.request().url()).searchParams.get('q') ?? '')
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ suggestions: [
        { label: 'Arlington', region: 'Texas' },
        { label: 'Arlington', region: 'Virginia' },
      ] }),
    })
  })
  await page.route('**/api/v1/discovery/ani.mallya/localities', async route => {
    saved.push(route.request().postDataJSON() as Record<string, unknown>)
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id: 'l1', label: 'Arlington', region: 'Virginia',
        radius_km: 25, timezone: 'America/New_York', is_primary: true,
        is_travel_active: false }) })
  })

  await page.goto('/')
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()
  await page.getByLabel('Town or city').fill('Arlingt')

  // Both namesakes are offered, which is the point of suggesting at all.
  const virginia = page.getByRole('button', { name: /Arlington, Virginia/ })
  await expect(virginia).toBeVisible()
  await expect(page.getByRole('button', { name: /Arlington, Texas/ })).toBeVisible()

  await virginia.click()
  // Picking one supplies the half nobody knew the format for.
  await expect(page.getByLabel('Town or city')).toHaveValue('Arlington')
  await expect(page.getByLabel('State or country')).toHaveValue('Virginia')

  await page.getByRole('button', { name: 'Save' }).first().click()
  await expect.poll(() => saved.length).toBeGreaterThan(0)
  expect(saved[0]).toMatchObject({ label: 'Arlington', region: 'Virginia' })
  // Debounced, not per keystroke.
  expect(asked.length).toBeLessThanOrEqual(2)
})

for (const width of [1280, 390]) {
  test(`saves a typed town and its region as separate fields at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  const saved: Array<Record<string, unknown>> = []
  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ user_id: 'ani.mallya', agents: [{
      id: 'discovery', name: 'Scout', role: 'Finds things happening near you.',
      status: 'idle', detail: 'Ready.', trigger: 'On request',
      last_active_at: null, facts: [],
    }] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ user_id: 'ani.mallya', interests: [], localities: [] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/sources', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ sources: [] }) }))
  await page.route('**/api/v1/discovery/ani.mallya/schedule', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ schedule: null }) }))
  await page.route('**/api/v1/discovery/ani.mallya/known', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ locality: null, known: [] }) }))
  await page.route('**/api/v1/discovery/ani.mallya/localities', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    saved.push(body)
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id: 'loc-1', label: body.label, region: body.region, radius_km: 25,
        timezone: 'America/New_York', is_primary: true, is_travel_active: false,
      }),
    })
  })

  await page.goto('/')
  if (width < 768) await page.getByRole('button', { name: 'Show Sidebar' }).click()
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()

  // Both inputs have to be usable, not merely present: a phone is where the
  // location button is most likely to be refused and typing is the fallback.
  for (const label of ['Town or city', 'State or country']) {
    const box = await page.getByLabel(label).boundingBox()
    expect(box, `${label} at ${width}px`).not.toBeNull()
    expect(box!.width, `${label} width at ${width}px`).toBeGreaterThan(90)
    expect(box!.x + box!.width, `${label} right edge at ${width}px`).toBeLessThanOrEqual(width)
    expect(box!.height, `${label} tap height at ${width}px`).toBeGreaterThanOrEqual(36)
  }

  await page.getByLabel('Town or city').fill('Arlington')
  // With no region the form says why that is a problem, before anything saves.
  await expect(page.getByText(/add a state or country/i)).toBeVisible()

  await page.getByLabel('State or country').fill('Virginia')
  await expect(page.getByText('Arlington, Virginia').first()).toBeVisible()
  await page.getByRole('button', { name: 'Save' }).first().click()

  await expect.poll(() => saved.length).toBeGreaterThan(0)
  expect(saved[0]).toMatchObject({ label: 'Arlington', region: 'Virginia' })
  })
}

// Verify chat auto-saves locality and interest proposals with no approval step.
test('shows auto-saved home locality and interest proposals from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let chatCount = 0

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    const proposal = chatCount++ === 0
      ? { kind: 'discovery_locality', label: 'Arlington', region: 'Virginia' }
      : { kind: 'discovery_interest', label: 'hiking' }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'discovery-proposal-trace',
        payload.conversation_id,
        'ok',
        undefined,
        undefined,
        proposal,
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('I live in Arlington, Virginia.')
  await sendButton.click()
  await expect(page.getByText('Saved Arlington, Virginia as home locality memory.')).toBeVisible()

  await textarea.fill('I am interested in hiking.')
  await sendButton.click()
  await expect(page.getByText('Saved hiking as interest memory.')).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Every semantically extracted interest is auto-saved in one write.
test('shows an auto-saved semantic interest list for Scout from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'semantic-interest-trace',
        payload.conversation_id,
        'Those sound like great interests.',
        undefined,
        undefined,
        {
          kind: 'discovery_interests',
          labels: ['basketball', 'soccer', 'baseball', 'hiking'],
        },
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('My interests are basketball, soccer, baseball, hiking')
  await sendButton.click()

  await expect(
    page.getByText('Saved basketball, soccer, baseball, hiking as Scout interests memory.'),
  ).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A saved-memory notice belongs to the reply that produced it, not to the
// whole conversation. The next question starts a clean slate immediately -
// there is no grace period, because nothing here is awaiting an answer.
test('clears the saved-memory notice on the next question', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let turn = 0

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    turn += 1
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: multiProposalEventStream(
        `turn-${turn}-trace`,
        payload.conversation_id,
        'Noted.',
        turn === 1 ? [{ kind: 'preferred_name', value: 'Jen' }] : [],
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('hi my name is Jen')
  await sendButton.click()
  await expect(page.getByText('Saved Jen as preferred name memory.')).toBeVisible()

  await textarea.fill('and something else')
  await sendButton.click()
  await expect(page.getByText('Saved Jen as preferred name memory.')).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Both facts from one introduction are auto-saved and both are shown.
test('shows every auto-saved memory from one chat turn', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: multiProposalEventStream(
        'multi-profile-trace',
        payload.conversation_id,
        'Nice to meet you, Jen.',
        [
          { kind: 'preferred_name', value: 'Jen' },
          {
            kind: 'discovery_interests',
            labels: ['acting', 'theater', 'networking events'],
          },
        ],
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('hi my name is Jen and i like acting, theater, networking events')
  await sendButton.click()

  await expect(page.getByText('Saved Jen as preferred name memory.')).toBeVisible()
  await expect(
    page.getByText('Saved acting, theater, networking events as Scout interests memory.'),
  ).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Parse and display a semantically selected general fact without dropping the stream.
test('shows an auto-saved semantic fact proposal from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'semantic-fact-trace',
        payload.conversation_id,
        'I noted that.',
        undefined,
        undefined,
        { kind: 'semantic_fact', content: 'My dog is called Biscuit.' },
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Please keep track of what my dog is called.')
  await sendButton.click()
  await expect(
    page.getByText('Saved My dog is called Biscuit. as fact memory.'),
  ).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('reuses a conversation ID and rotates it only for a new conversation', async ({ page }) => {
  const conversationIds: string[] = []
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    conversationIds.push(route.request().postDataJSON().conversation_id)
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('test', conversationIds.at(-1)!, 'ok'),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  for (const message of ['first message', 'second message']) {
    await textarea.fill(message)
    await sendButton.click()
    await expect(textarea).toBeEnabled()
  }
  expect(conversationIds).toHaveLength(2)
  expect(conversationIds[0]).toBe(conversationIds[1])

  await page.getByRole('button', { name: 'New conversation' }).click()
  await expect(page.getByText('first message', { exact: true })).not.toBeVisible()
  await expect(page.getByText('second message', { exact: true })).not.toBeVisible()
  await textarea.fill('third message')
  await sendButton.click()
  await expect(textarea).toBeEnabled()
  expect(conversationIds[2]).not.toBe(conversationIds[0])
})

test('keeps the visible transcript when navigating to memory and back', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const userMessage = `navigation message ${Date.now()}`
  const assistantMessage = `navigation response ${Date.now()}`

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'navigation-trace',
        payload.conversation_id,
        assistantMessage,
      ),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: 'ani.mallya', preferences: {} },
        episodic: [],
        semantic: [],
        facts: [],
      }),
    }),
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill(userMessage)
  await sendButton.click()
  await expect(textarea).toBeEnabled()
  await expect(page.getByText(userMessage, { exact: true })).toBeVisible()
  await expect(page.getByText(assistantMessage, { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Personal Memory' })).toBeVisible()
  await page.getByRole('button', { name: 'Conversations' }).click()

  await expect(page.getByText(userMessage, { exact: true })).toBeVisible()
  await expect(page.getByText(assistantMessage, { exact: false })).toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('opens a fresh chat when starting a conversation from memory', async ({ page }) => {
  const userMessage = `conversation to replace ${Date.now()}`

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('new-conversation-trace', payload.conversation_id, 'ok'),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: 'ani.mallya', preferences: {} },
        episodic: [],
        semantic: [],
        facts: [],
      }),
    }),
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill(userMessage)
  await sendButton.click()
  await expect(textarea).toBeEnabled()

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Personal Memory' })).toBeVisible()
  await page.getByRole('button', { name: 'New conversation' }).click()

  await expect(textarea).toBeVisible()
  await expect(page.getByText(userMessage, { exact: true })).not.toBeVisible()
})

test('does not let browser state switch the authenticated account', async ({ page }) => {
  const requests: Array<{ user_id: string; conversation_id: string; query: string }> = []
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    requests.push(payload)
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('test', payload.conversation_id, 'ok'),
    })
  })
  await page.route('http://localhost:8000/api/v1/memory/**', async route => {
    const userId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile: { user_id: userId, preferences: {} },
        episodic: [],
        semantic: [],
        facts: [],
      }),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('message for first user')
  await sendButton.click()
  await expect(textarea).toBeEnabled()

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await expect(page.getByLabel('Active user ID')).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Switch user' })).not.toBeVisible()
  await page.evaluate(() => localStorage.setItem('anios_user_id', 'different_user'))
  await page.getByRole('button', { name: 'Conversations' }).click()
  await expect(page.getByText('message for first user', { exact: true })).toBeVisible()

  await textarea.fill('second message after tampering')
  await sendButton.click()
  await expect(textarea).toBeEnabled()

  expect(requests).toHaveLength(2)
  expect(requests[0].user_id).toBe('ani.mallya')
  expect(requests[1].user_id).toBe('ani.mallya')
  expect(requests[1].conversation_id).toBe(requests[0].conversation_id)
})

test('manages persisted personal memory through the browser', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const snapshot = {
    profile: { user_id: 'ani.mallya', preferences: {} as Record<string, unknown> },
    episodic: [] as Array<Record<string, unknown>>,
    semantic: [] as Array<Record<string, unknown>>,
    facts: [] as Array<Record<string, unknown>>,
  }

  await page.route('http://localhost:8000/api/v1/memory/**', async route => {
    const request = route.request()
    if (request.method() === 'GET' && request.url().endsWith('/export')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 2,
          exported_at: '2026-07-16T00:00:00Z',
          user_id: 'ani.mallya',
          agent_memory: {},
          memory: snapshot,
          conversations: [],
        }),
      })
      return
    }
    if (request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(snapshot) })
      return
    }
    if (request.method() === 'PUT' && request.url().endsWith('/profile')) {
      const body = request.postDataJSON()
      snapshot.profile = { user_id: 'ani.mallya', ...body }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(snapshot.profile) })
      return
    }
    if (request.method() === 'PUT' && request.url().includes('/semantic/')) {
      const body = request.postDataJSON()
      const memory = snapshot.semantic[0]
      memory.content = body.content
      memory.extra_data = body.metadata
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(memory) })
      return
    }
    if (request.method() === 'POST' && request.url().endsWith('/semantic')) {
      const body = request.postDataJSON()
      const memory = {
        id: '33333333-3333-4333-8333-333333333333',
        user_id: 'ani.mallya',
        content: body.content,
        extra_data: body.metadata,
      }
      snapshot.semantic.push(memory)
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(memory) })
      return
    }
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Personal Memory' })).toBeVisible()

  await page.getByLabel('Profile name').fill('Ani Browser User')
  await page.getByLabel('Response style').fill('concise')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByLabel('Profile name')).toHaveValue('Ani Browser User')

  const memoryText = `Browser memory ${Date.now()}`
  await page.getByText('Advanced: add memory manually').click()
  await page.getByLabel('Fact or preference').fill(memoryText)
  await page.getByRole('button', { name: 'Add fact or preference' }).click()
  await expect(page.getByText(memoryText, { exact: true })).toBeVisible()
  await expect(page.getByLabel('Fact or preference')).toHaveValue('')
  const correctedText = `${memoryText} corrected`
  await page.getByRole('button', { name: 'Edit semantic record' }).click()
  await page.getByLabel('Correct semantic record').fill(correctedText)
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText(correctedText, { exact: true })).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export personal memory' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('anios-memory-ani.mallya.json')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify entity, workflow, and knowledge chat proposals are auto-saved and shown.
test('shows auto-saved entity, procedure, and knowledge proposals from chat', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const proposals = [
    {
      kind: 'entity',
      entity_type: 'person',
      canonical_name: 'Approved Avery',
      attributes: { relationship: 'dentist' },
    },
    {
      kind: 'procedure',
      name: 'Morning launch',
      description: 'User-approved workflow: Morning launch',
      steps: [
        { order: 1, instruction: 'Open dashboard' },
        { order: 2, instruction: 'Review alerts' },
      ],
    },
    {
      kind: 'knowledge',
      title: 'Studio reference',
      content: 'The studio marker is violet seven.',
    },
  ]
  let proposalIndex = 0

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'structured-proposal-trace',
        payload.conversation_id,
        'ok',
        undefined,
        undefined,
        proposals[proposalIndex++],
      ),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)

  for (const expectation of [
    'Saved Approved Avery as person or organization memory.',
    'Saved Morning launch as reusable workflow memory.',
    'Saved Studio reference as reference knowledge memory.',
  ]) {
    await textarea.fill('Remember this')
    await sendButton.click()
    await expect(page.getByText(expectation)).toBeVisible()
  }

  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify the configured local model produces a persisted diagram in the real browser path.
test('@live creates and renders a real diagram artifact', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_diagram_${stamp}`
  const startLabel = `LiveStart${stamp}`
  const endLabel = `LiveComplete${stamp}`
  const query = `Create a flowchart showing ${startLabel} to ValidateArtifact to ${endLabel}.`
  const apiUrl = process.env.ANIOS_API_URL ?? 'http://localhost:8000'
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  try {
    await page.goto('/')
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(
      response => response.url() === `${apiUrl}/api/v1/chat`,
    )
    await textarea.fill(query)
    await sendButton.click()
    await expect(textarea).toBeDisabled()

    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()
    const diagram = page.locator('section[aria-label^="Diagram:"]').last()
    await expect(diagram).toBeVisible({ timeout: 120_000 })
    await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible({ timeout: 120_000 })
    await diagram.getByText('View Mermaid source', { exact: true }).click()
    await expect(diagram.locator('pre')).toContainText(startLabel)
    await expect(diagram.locator('pre')).toContainText(endLabel)
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')
    await expect(sendButton).toBeDisabled()

    const conversationId = await page.evaluate(() =>
      localStorage.getItem('anios_conversation_id'),
    )
    expect(conversationId).toMatch(/^[0-9a-f-]{36}$/)
    const artifactsResponse = await page.request.get(
      `${apiUrl}/api/v1/artifacts/${userId}/conversations/${conversationId}`,
    )
    expect(artifactsResponse.status()).toBe(200)
    const artifacts = await artifactsResponse.json()
    expect(artifacts).toEqual([
      expect.objectContaining({
        user_id: userId,
        conversation_id: conversationId,
        kind: 'diagram',
        status: 'ready',
        source_format: 'mermaid',
      }),
    ])

    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    await page.getByRole('button', { name: 'Conversations', exact: true }).click()
    await expect(diagram).toBeVisible()
    await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()

    const restoreResponse = page.waitForResponse(response =>
      response.url() ===
        `${apiUrl}/api/v1/conversations/${userId}/${conversationId}` &&
      response.request().method() === 'GET',
    )
    await page.reload()
    expect((await restoreResponse).status()).toBe(200)
    await expect(page.getByText(query, { exact: true })).toBeVisible()
    await expect(diagram).toBeVisible()
    await expect(diagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()
    await diagram.getByText('View Mermaid source', { exact: true }).click()
    await expect(diagram.locator('pre')).toContainText(startLabel)
    await expect(diagram.locator('pre')).toContainText(endLabel)
    await expect(page.getByRole('alert')).not.toBeVisible()

    const historyResponse = page.waitForResponse(response =>
      response.url() === `${apiUrl}/api/v1/artifacts/${userId}` &&
      response.request().method() === 'GET',
    )
    await page.getByRole('button', { name: 'Visual artifacts' }).click()
    expect((await historyResponse).status()).toBe(200)
    const historyDiagram = page.locator('section[aria-label^="Diagram:"]').last()
    await expect(historyDiagram.getByLabel('Rendered Mermaid diagram')).toBeVisible()

    const mermaidDownload = page.waitForEvent('download')
    await historyDiagram.getByRole('button', { name: 'Mermaid' }).click()
    expect((await mermaidDownload).suggestedFilename()).toMatch(/\.mmd$/)
    const svgDownload = page.waitForEvent('download')
    await historyDiagram.getByRole('button', { name: 'SVG' }).click()
    expect((await svgDownload).suggestedFilename()).toMatch(/\.svg$/)

    const deleteResponse = page.waitForResponse(response =>
      response.url() === `${apiUrl}/api/v1/artifacts/${userId}/${artifacts[0].id}` &&
      response.request().method() === 'DELETE',
    )
    await page.getByRole('button', { name: /^Delete / }).click()
    expect((await deleteResponse).status()).toBe(200)
    await expect(page.getByText('No visual artifacts yet.', { exact: false })).toBeVisible()
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    const conversationId = await page.evaluate(() =>
      localStorage.getItem('anios_conversation_id'),
    ).catch(() => null)
    if (conversationId) {
      const response = await page.request.get(
        `${apiUrl}/api/v1/artifacts/${userId}/conversations/${conversationId}`,
      )
      if (response.ok()) {
        for (const artifact of await response.json()) {
          await page.request.delete(
            `${apiUrl}/api/v1/artifacts/${userId}/${artifact.id}`,
          )
        }
      }
    }
    await page.request.delete(`${apiUrl}/api/v1/memory/${userId}`)
  }
})

// Verify ordinary live chat renders and restores a real response from the configured provider.
test('@live renders a real configured-provider response through DeepMatter', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(240_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_provider_${stamp}`
  const token = `LIVE_PROVIDER_${stamp}`
  const query = `Reply with exactly: ${token}`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  try {
    await page.goto('/')
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
    )

    await textarea.fill(query)
    await sendButton.click()
    await expect(textarea).toBeDisabled()

    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    const answer = latestAssistantAnswer(page)
    await expect(answer).toBeVisible({ timeout: 180_000 })
    expect(await response.finished()).toBeNull()

    const renderedAnswer = (await answer.locator('.assistant-markdown').innerText()).trim()
    expect(renderedAnswer.length).toBeGreaterThan(0)
    expect(renderedAnswer).not.toBe('Thinking...')
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')
    await expect(sendButton).toBeDisabled()

    const memoryResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}`) &&
      response.request().method() === 'GET',
    )
    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    expect((await memoryResponsePromise).status()).toBe(200)
    await expect(page.getByRole('alert')).not.toBeVisible()
    await page.getByRole('button', { name: 'Conversations' }).click()
    await expect(page.getByText(query, { exact: true })).toBeVisible()
    await expect(latestAssistantAnswer(page).locator('.assistant-markdown')).toHaveText(renderedAnswer)
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

// Verify live chat delegates a deck durably while ordinary conversation continues.
test('@live delegates a presentation subagent without blocking chat', async ({ page }) => {
  test.setTimeout(120_000)
  test.skip(
    process.env.ANIOS_E2E_LIVE !== '1',
    'Set ANIOS_E2E_LIVE=1 to exercise the live presentation worker.',
  )
  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  const presentationResponse = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat',
  )
  await textarea.fill(
    `Create a presentation about supervisor validation ${stamp} with exactly 2 slides.`,
  )
  await sendButton.click()

  const response = await presentationResponse
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  expect(await response.finished()).toBeNull()
  const answer = latestAssistantAnswer(page)
  await expect(
    answer.getByText(/PresentationAgent · .+ queued in the background/),
  ).toBeVisible()
  const answerText = await answer.textContent()
  const jobId = answerText?.match(
    /follow job\s+([0-9a-f]{8}-[0-9a-f-]{27,})/i,
  )?.[1]
  expect(jobId).toBeTruthy()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()

  await textarea.fill(`Reply with exactly: parallel chat ${stamp}`)
  await sendButton.click()
  await expect(
    latestAssistantAnswer(page).getByText(`parallel chat ${stamp}`, { exact: true }),
  ).toBeVisible({ timeout: 60_000 })
  await expect(textarea).toBeEnabled()

  let job: Record<string, unknown> | undefined
  await expect.poll(async () => {
    const result = await page.request.get(
      `http://localhost:8000/api/v1/presentations/jobs/ani.mallya/${jobId}`,
    )
    expect(result.ok()).toBeTruthy()
    job = await result.json()
    return job?.status
  }, { timeout: 90_000 }).toBe('ready')
  const presentation = job?.presentation as {
    current_revision?: { specification?: { slides?: unknown[] } }
  }
  expect(presentation.current_revision?.specification?.slides).toHaveLength(2)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify the configured model selects a live tool and exposes its full lifecycle.
test('@live uses the configured model for an MCP tool in chat', async ({ page }) => {
  test.setTimeout(120_000)
  test.skip(process.env.RUN_LIVE_TOOL_TESTS !== '1', 'requires configured live MCP servers')
  const errors = observeBlockingBrowserErrors(page)
  const apiUrl = 'http://localhost:8000'
  const userId = process.env.ANIOS_LIVE_TOOL_USER || 'live_tool_browser_user'
  const conversationId = '78787878-7878-4878-8878-787878787878'
  const query = `Invoke local_utility/current_time with no arguments and report its returned UTC JSON. Browser marker ${Date.now()}`

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await page.evaluate(() => {
      const trackedWindow = window as Window & {
        sawMcpToolRunning?: boolean;
        sawInternetToolRunning?: boolean;
      }
      trackedWindow.sawMcpToolRunning = false
      trackedWindow.sawInternetToolRunning = false
      const observer = new MutationObserver(() => {
        if (document.body.innerText.includes('Using current_time via local_utility...')) {
          trackedWindow.sawMcpToolRunning = true
        }
        if (document.body.innerText.includes('Using search_web via internet...')) {
          trackedWindow.sawInternetToolRunning = true
        }
      })
      observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    })
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(response => (
      response.url() === `${apiUrl}/api/v1/chat` &&
      response.request().method() === 'POST'
    ))
    await textarea.fill(query)
    await sendButton.click()

    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()

    const answer = latestAssistantAnswer(page)
    await expect(answer.getByText('Used current_time via local_utility')).toBeVisible()
    await expect(answer).toContainText('UTC')
    expect(await page.evaluate(() => (
      window as Window & { sawMcpToolRunning?: boolean }
    ).sawMcpToolRunning)).toBe(true)
    await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')

    const internetResponsePromise = page.waitForResponse(response => (
      response.url() === `${apiUrl}/api/v1/chat` &&
      response.request().method() === 'POST'
    ))
    const internetQuery = `Search online for the latest stable Python release and cite the source. Browser search marker ${Date.now()}`
    await textarea.fill(internetQuery)
    await sendButton.click()
    const internetResponse = await internetResponsePromise
    expect(internetResponse.status()).toBe(200)
    expect(await internetResponse.finished()).toBeNull()

    const internetAnswer = latestAssistantAnswer(page)
    await expect(internetAnswer.getByText('Used search_web via internet')).toBeVisible()
    const sources = internetAnswer.getByLabel('Web sources used')
    await expect(sources).toBeVisible()
    await expect(sources.getByText(/^(Google|tavily) · /).first()).toBeVisible()
    expect(await page.evaluate(() => (
      window as Window & { sawInternetToolRunning?: boolean }
    ).sawInternetToolRunning)).toBe(true)
    await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`${apiUrl}/api/v1/memory/${userId}`)
  }
})

// Verify the live browser completes a provider-attributed internet MCP search.
test('@live uses the hybrid internet MCP in chat', async ({ page }) => {
  test.setTimeout(150_000)
  test.skip(process.env.RUN_LIVE_TOOL_TESTS !== '1', 'requires configured live MCP search')
  const errors = observeBlockingBrowserErrors(page)
  const apiUrl = 'http://localhost:8000'
  const userId = process.env.ANIOS_LIVE_TOOL_USER || 'live_search_browser_user'
  const conversationId = '79797979-7979-4979-8979-797979797979'
  const marker = `browser-search-${Math.random().toString(36).slice(2, 10)}`
  const query = `Search online for the latest stable Python release and cite the source. Validation ${marker}`

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await page.evaluate(() => {
      const trackedWindow = window as Window & { sawInternetToolRunning?: boolean }
      trackedWindow.sawInternetToolRunning = false
      const observer = new MutationObserver(() => {
        if (document.body.innerText.includes('Using search_web via internet...')) {
          trackedWindow.sawInternetToolRunning = true
        }
      })
      observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    })
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(response => (
      response.url() === `${apiUrl}/api/v1/chat` &&
      response.request().method() === 'POST'
    ))
    await textarea.fill(query)
    await sendButton.click()

    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()
    const stream = await response.text()
    expect(stream).toContain('event: search_started')
    expect(stream).toContain('event: tool_started')
    expect(stream).toContain('event: search_results')
    expect(stream).toContain('event: done')

    const answer = latestAssistantAnswer(page)
    await expect(answer.getByText('Used search_web via internet')).toBeVisible()
    const sources = answer.getByLabel('Web sources used')
    await expect(sources).toBeVisible()
    await expect(sources.getByText(/^(Google|tavily) · /).first()).toBeVisible()
    expect(await page.evaluate(() => (
      window as Window & { sawInternetToolRunning?: boolean }
    ).sawInternetToolRunning)).toBe(true)
    await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`${apiUrl}/api/v1/memory/${userId}`)
  }
})

// Verify image generation renders, survives navigation and reload, and deletes cleanly.
test('generates, restores, and deletes an owned image artifact', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '12121212-1212-4212-8212-121212121212'
  const prompt = 'Create an image of a deterministic cobalt origami whale'
  let conversationId = ''
  let artifact: ReturnType<typeof imageArtifactRecord> | null = null

  // Generation now runs inside the chat stream: the main model decides to
  // create the picture and the browser learns about it through the same
  // artifact_started/artifact_ready events a diagram uses.
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    conversationId = String(payload.conversation_id)
    artifact = imageArtifactRecord('generated_image', artifactId, conversationId, {
      seed: 42,
      steps: 28,
    })
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageActionEventStream(
        'generate-browser-trace',
        conversationId,
        artifactId,
        'generate',
        'ready',
        { seed: 42, steps: 28 },
      ),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route('http://localhost:8000/api/v1/artifacts/ani.mallya', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(artifact ? [artifact] : []),
    }),
  )
  await page.route('http://localhost:8000/api/v1/conversations/ani.mallya/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversation_id: conversationId, turns: [], artifacts: artifact ? [artifact] : [] }),
    }),
  )
  let deleted = false
  await page.route(`http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}`, route => {
    deleted = true
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'deleted', id: artifactId }),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(prompt)
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await responsePromise).status()).toBe(200)

  const imageCard = page.getByLabel('Image: Generated image')
  await expect(imageCard).toBeVisible()
  await expect(imageCard.getByAltText('Generated visual result')).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')

  await page.getByRole('button', { name: 'Visual artifacts' }).click()
  await expect(page.getByLabel('Image: Generated image').filter({ visible: true })).toBeVisible()
  await page.getByRole('button', { name: 'Conversations' }).click()
  await expect(imageCard).toBeVisible()

  await page.reload()
  await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
  const restored = page.getByLabel('Image: Generated image')
  await expect(restored).toBeVisible()
  await expect(restored.getByAltText('Generated visual result')).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await restored.getByRole('button', { name: 'Download' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(`anios-generated_image-${artifactId}.png`)
  await restored.getByRole('button', { name: 'Delete' }).click()
  await expect(restored).not.toBeVisible()
  expect(deleted).toBe(true)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// A recalled image is shown every time it is relevant, but compactly - the
// full 620px card with its download/retry/delete toolbar is reserved for an
// image just created or uploaded, not for a passing reference to one already
// in the library. Expanding it reveals the same full card and controls.
test('shows a recalled image as a compact thumbnail that expands on click', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '34343434-3434-4434-8434-343434343434'
  let conversationId = ''

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    conversationId = String(payload.conversation_id)
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageMatchEventStream(
        'recall-trace',
        conversationId,
        'Based on the photo, that jacket pairs well with dark jeans.',
        imageArtifactRecord('uploaded_image', artifactId, conversationId),
      ),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill('does that jacket go with dark jeans?')
  await page.getByRole('button', { name: 'Send message' }).click()

  const collapsed = page.getByRole('button', { name: 'Expand image: Uploaded image' })
  await expect(collapsed).toBeVisible()
  await expect(page.getByLabel('Image: Uploaded image', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Download' })).not.toBeVisible()

  await collapsed.click()
  const expandedCard = page.getByLabel('Image: Uploaded image', { exact: true })
  await expect(expandedCard).toBeVisible()
  await expect(expandedCard.getByRole('button', { name: 'Download' })).toBeVisible()
  await expect(expandedCard.getByRole('button', { name: 'Delete' })).toBeVisible()

  await expandedCard.getByRole('button', { name: 'Collapse' }).click()
  await expect(collapsed).toBeVisible()
  await expect(page.getByLabel('Image: Uploaded image', { exact: true })).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a historical image question uses chat without regenerating.
test('routes an image followup question to chat without regenerating', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '24242424-2424-4242-8242-242424242424'
  const prompt = 'Create an image of a cobalt sports car'
  const question = 'what car did we create an image of?'
  const answer = 'We created an image of a cobalt sports car.'
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []

  // Both turns go through the same chat endpoint now; the second body's own
  // fields prove the followup reused the image as context instead of the
  // main model choosing to generate a second one.
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(payload)
    conversationId = conversationId || String(payload.conversation_id)
    if (chatBodies.length === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream(
          'generate-browser-trace',
          conversationId,
          artifactId,
          'generate',
          'ready',
          { generation_prompt: prompt },
        ),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('followup-trace', conversationId, answer),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(prompt)
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Image: Generated image')).toBeVisible()

  await textarea.fill(question)
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await responsePromise).status()).toBe(200)

  expect(chatBodies).toHaveLength(2)
  expect(chatBodies[1]).toMatchObject({
    user_id: 'ani.mallya',
    query: question,
    active_image_artifact_id: artifactId,
  })
  await expect(latestAssistantAnswer(page).getByText(answer, { exact: true })).toBeVisible()
  await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify image-card selection disambiguates multiple images in the main composer.
test('selects and clears image context when several images are visible', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactIds = [
    '25252525-2525-4252-8252-252525252525',
    '26262626-2626-4262-8262-262626262626',
  ]
  let generationIndex = 0
  const chatBodies: Record<string, unknown>[] = []

  for (const artifactId of artifactIds) {
    await page.route(
      `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
      route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
    )
  }
  // The first two turns are the model choosing to generate a picture; every
  // turn after that is an ordinary answer using whichever image is selected.
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    const conversationId = String(body.conversation_id)
    if (generationIndex < artifactIds.length) {
      const artifactId = artifactIds[generationIndex]
      generationIndex += 1
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream(
          'generate-browser-trace',
          conversationId,
          artifactId,
          'generate',
          'ready',
          { generation_prompt: String(body.query) },
        ),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('selection-trace', conversationId, 'Selected image answer.'),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  for (const prompt of ['Create an image of a blue coupe', 'Create an image of a red roadster']) {
    await textarea.fill(prompt)
    await page.getByRole('button', { name: 'Send message' }).click()
    await expect(textarea).toBeEnabled()
  }

  const cards = page.getByLabel('Image: Generated image')
  await expect(cards).toHaveCount(2)
  await expect(cards.nth(1).getByRole('button', { name: 'Using in chat' })).toBeVisible()
  await cards.nth(0).getByRole('button', { name: 'Ask or edit' }).click()
  await expect(cards.nth(0).getByRole('button', { name: 'Using in chat' })).toBeVisible()

  await textarea.fill('What is distinctive about this one?')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(textarea).toBeEnabled()
  expect(chatBodies[2]).toMatchObject({ active_image_artifact_id: artifactIds[0] })

  await page.getByRole('button', { name: 'Stop using selected image' }).click()
  await expect(page.getByLabel(/Using image in chat:/)).toHaveCount(0)
  await textarea.fill('Now answer without a selected image.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(textarea).toBeEnabled()
  expect(chatBodies[3]).toMatchObject({ active_image_artifact_id: null })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a generated-image question uses the selected image in the main chat.
test('asks about a selected generated image from the main composer', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '78787878-7878-4878-8878-787878787878'
  const prompt = 'Create an image of a deterministic cobalt origami whale'
  const question = 'What is in this image?'
  const answer = 'The image shows a single cobalt origami whale.'
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []

  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route('http://localhost:8000/api/v1/conversations/ani.mallya/**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversation_id: conversationId, turns: [], artifacts: [] }),
    }),
  )
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    conversationId = conversationId || String(body.conversation_id)
    if (chatBodies.length === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream(
          'generate-browser-trace',
          conversationId,
          artifactId,
          'generate',
          'ready',
          { seed: 42, steps: 28 },
        ),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('selected-image-trace', conversationId, answer),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(prompt)
  await page.getByRole('button', { name: 'Send message' }).click()

  const imageCard = page.getByLabel('Image: Generated image')
  await expect(imageCard).toBeVisible()
  await expect(imageCard.getByAltText('Generated visual result')).toBeVisible()

  await expect(page.getByLabel(`Using image in chat: Generated image`)).toBeVisible()
  await textarea.fill(question)
  const chatResponse = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await chatResponse).status()).toBe(200)

  expect(chatBodies[1]).toMatchObject({ query: question, active_image_artifact_id: artifactId })
  await expect(latestAssistantAnswer(page).getByText(answer, { exact: true })).toBeVisible()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Deleting the active image must not disable auto-following the newest
// visible image for the rest of the conversation. It used to: the delete
// handler cleared the selection to `null`, the same value a deliberate
// "clear image context" click uses, so every later picture was silently
// skipped and an edit request typed afterward found nothing to apply to
// with no explanation. This proves a second, later image still becomes
// active on its own after the first one is deleted.
test('keeps auto-following the newest image after deleting the active one', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const firstId = '91919191-9191-4191-8191-919191919191'
  const secondId = '92929292-9292-4292-8292-929292929292'
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []
  let deletedId = ''

  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${firstId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${secondId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route(`http://localhost:8000/api/v1/artifacts/ani.mallya/${firstId}`, route => {
    deletedId = firstId
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'deleted', id: firstId }),
    })
  })
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    conversationId = conversationId || String(body.conversation_id)
    if (chatBodies.length === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream('gen-1-trace', conversationId, firstId, 'generate', 'ready'),
      })
      return
    }
    if (chatBodies.length === 2) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream('gen-2-trace', conversationId, secondId, 'generate', 'ready'),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('followup-trace', conversationId, 'Sure, here is what I see.'),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')

  await textarea.fill('Create an image of a red bicycle')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Image: Generated image')).toBeVisible()

  await page.getByLabel('Image: Generated image').getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByLabel('Image: Generated image')).not.toBeVisible()
  expect(deletedId).toBe(firstId)

  await textarea.fill('Create an image of a blue bicycle')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Image: Generated image')).toBeVisible()

  await textarea.fill('what do you think of it?')
  const followupResponse = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await followupResponse).status()).toBe(200)

  expect(chatBodies[2]).toMatchObject({ active_image_artifact_id: secondId })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a polite question-shaped edit command creates a linked image revision.
//
// Both whether this is an edit at all, and the edit itself, are the main
// model's own decisions now (edit_image in MainActionSelector), made in one
// native tool call alongside every other option -- not a client-side guess
// followed by a direct REST call. The browser only sees the chat stream, so
// this test proves what used to be silent is now a visible reply: the
// original stays, and the edited revision arrives as its own answer instead
// of overwriting it without a trace.
test('routes can-you image edits to refinement instead of vision Q&A', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const originalId = '81818181-8181-4181-8181-818181818181'
  const revisionId = '82828282-8282-4282-8282-828282828282'
  const prompt = 'Create an image of a blue sports car'
  const feedback = 'can you make this car red?'
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []

  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${originalId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${revisionId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    conversationId = conversationId || String(body.conversation_id)
    if (chatBodies.length === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream(
          'generate-browser-trace',
          conversationId,
          originalId,
          'generate',
          'ready',
          { generation_prompt: prompt },
        ),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageActionEventStream(
        'edit-browser-trace',
        conversationId,
        revisionId,
        'edit',
        'ready',
        {
          generation_prompt: prompt,
          parent_artifact_id: originalId,
          refinement_feedback: feedback,
        },
      ),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(prompt)
  await page.getByRole('button', { name: 'Send message' }).click()

  const originalCard = page.getByLabel('Image: Generated image').first()
  await expect(originalCard.getByRole('button', { name: 'Using in chat' })).toBeVisible()
  await textarea.fill(feedback)
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await responsePromise).status()).toBe(200)

  // The original is untouched and the edit arrives as a second, visible card.
  await expect(page.getByLabel('Image: Generated image')).toHaveCount(2)
  await expect(page.getByText("Here's the edited image.", { exact: true })).toBeVisible()
  await expect(textarea).toBeEnabled()
  expect(chatBodies[1]).toMatchObject({
    user_id: 'ani.mallya',
    conversation_id: conversationId,
    query: feedback,
    active_image_artifact_id: originalId,
  })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// An edit re-observes the result's pixels so it stays semantically findable,
// which populates the same metadata.analysis field the upload flow uses to
// show a "Describe this image" card - but nobody asked a question here, and
// showing it anyway is exactly the leak reported live: "can you edit this to
// a straw hat?" edited the picture cleanly, then also surfaced an unwanted
// image description underneath it.
test('does not surface the post-edit re-observation as an answer nobody asked for', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const originalId = '91919191-9191-4191-8191-919191919191'
  const revisionId = '92929292-9292-4292-8292-929292929292'
  const prompt = 'Create an image of a man wearing a black cowboy hat'
  const feedback = 'can you edit this to a straw hat?'
  const reindexedAnalysis = 'A man wearing a wide-brimmed straw hat on a pier.'
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []

  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${originalId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${revisionId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    conversationId = conversationId || String(body.conversation_id)
    if (chatBodies.length === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: imageActionEventStream(
          'generate-browser-trace',
          conversationId,
          originalId,
          'generate',
          'ready',
          { generation_prompt: prompt },
        ),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageActionEventStream(
        'edit-browser-trace',
        conversationId,
        revisionId,
        'edit',
        'ready',
        {
          generation_prompt: prompt,
          parent_artifact_id: originalId,
          refinement_feedback: feedback,
          analysis_status: 'ready',
          analysis: reindexedAnalysis,
          analysis_model: 'google/gemma-4-12b',
          analysis_user_facing: false,
        },
      ),
    })
  })

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(prompt)
  await page.getByRole('button', { name: 'Send message' }).click()

  const originalCard = page.getByLabel('Image: Generated image').first()
  await expect(originalCard.getByRole('button', { name: 'Using in chat' })).toBeVisible()
  await textarea.fill(feedback)
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/chat')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await responsePromise).status()).toBe(200)

  await expect(page.getByText("Here's the edited image.", { exact: true })).toBeVisible()
  await expect(page.getByLabel('Image: Generated image')).toHaveCount(2)
  await expect(page.getByText(reindexedAnalysis)).not.toBeVisible()
  await expect(page.getByText('Describe this image.', { exact: true })).not.toBeVisible()
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify an uploaded image reaches the VLM and can become a linked FLUX revision.
test('uploads, analyzes, and source-refines an image with visible results', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '34343434-3434-4434-8434-343434343434'
  const refinedId = '45454545-4545-4454-8454-454545454545'
  const analysis = 'A cobalt origami whale floating above a white platform.'
  const feedback = 'Make only the whale violet'
  let multipartBody = ''
  let conversationId = ''
  const chatBodies: Record<string, unknown>[] = []
  let releaseAnalysis = () => {}
  const analysisGate = new Promise<void>(resolve => { releaseAnalysis = resolve })

  await page.route('http://localhost:8000/api/v1/vision/analyze', async route => {
    multipartBody = route.request().postDataBuffer()?.toString('utf8') || ''
    const conversationMatch = multipartBody.match(/name="conversation_id"\r\n\r\n([^\r]+)/)
    const artifact = imageArtifactRecord(
      'uploaded_image',
      artifactId,
      conversationMatch?.[1] || '56565656-5656-4656-8656-565656565656',
      { analysis_status: 'ready', analysis, analysis_model: 'google/gemma-4-12b' },
    )
    await analysisGate
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ artifact, analysis, model: 'google/gemma-4-12b' }),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${refinedId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )
  // The followup edit now runs through the same chat stream every message
  // takes; the main model chose edit_image, not a client-side guess.
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    chatBodies.push(body)
    conversationId = conversationId || String(body.conversation_id)
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageActionEventStream(
        'edit-browser-trace',
        conversationId,
        refinedId,
        'edit',
        'ready',
        {
          parent_artifact_id: artifactId,
          refinement_feedback: feedback,
          edit_mode: 'source_conditioned',
        },
      ),
    })
  })

  await page.goto('/')
  await attachComposerFile(page, {
    name: 'cobalt-whale.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  })
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill('Describe the subject and color.')
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/vision/analyze')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Analyzing image...', { exact: true })).toBeVisible()
  releaseAnalysis()
  expect((await responsePromise).status()).toBe(201)

  const imageCard = page.getByLabel('Image: Uploaded image')
  await expect(imageCard.getByAltText('Uploaded visual')).toBeVisible()
  await expect(imageCard.getByText(analysis, { exact: true })).toBeVisible()
  expect(multipartBody).toContain('name="user_id"')
  expect(multipartBody).toContain('ani.mallya')
  expect(multipartBody).toContain('name="prompt"')
  expect(multipartBody).toContain('Describe the subject and color.')
  expect(multipartBody).toContain('filename="cobalt-whale.png"')
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(page.getByText('Analyzing image...', { exact: true })).not.toBeVisible()
  await expect(imageCard.getByRole('button', { name: 'Using in chat' })).toBeVisible()
  await textarea.fill(feedback)
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Image: Generated image')).toHaveCount(1)
  await expect(page.getByLabel('Image: Generated image').getByAltText(
    'Generated visual result',
  )).toBeVisible()
  await expect(page.getByText("Here's the edited image.", { exact: true })).toBeVisible()
  expect(chatBodies[0]).toMatchObject({
    user_id: 'ani.mallya',
    conversation_id: expect.any(String),
    query: feedback,
    active_image_artifact_id: artifactId,
  })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify attaching a picture and asking for an edit in one message edits it.
//
// The obvious way to ask, and it described the picture instead: an attachment
// routed to analysis whatever the words said, and the edit request was put to
// the vision model, which answered that it cannot edit images. The server now
// reads the words and says which it was, on the same call that stores the
// upload — so the edit can run against an artifact that exists.
test('edits an uploaded image when the same message asks for an edit', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '63636363-6363-4636-8636-636363636363'
  const refinedId = '64646464-6464-4646-8646-646464646464'
  const instruction = 'give me a straw hat'
  const analysis = 'A person standing outdoors on a bright day.'
  let analyzedPrompt = ''
  let refinementBody: Record<string, unknown> = {}

  await page.route('http://localhost:8000/api/v1/vision/analyze', async route => {
    const body = route.request().postDataBuffer()?.toString('utf8') || ''
    analyzedPrompt = body.match(/name="prompt"\r\n\r\n([^\r]+)/)?.[1] || ''
    const conversationId = body.match(/name="conversation_id"\r\n\r\n([^\r]+)/)?.[1] || ''
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        artifact: imageArtifactRecord('uploaded_image', artifactId, conversationId, {
          analysis_status: 'ready',
          analysis,
          analysis_model: 'google/gemma-4-12b',
        }),
        analysis,
        model: 'google/gemma-4-12b',
        // The server's reading of the words that came with the upload.
        intent: 'edit',
      }),
    })
  })
  for (const id of [artifactId, refinedId]) {
    await page.route(
      `http://localhost:8000/api/v1/artifacts/ani.mallya/${id}/content`,
      route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
    )
  }
  await page.route(
    `http://localhost:8000/api/v1/images/${artifactId}/refine`,
    async route => {
      refinementBody = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(imageArtifactRecord(
          'generated_image',
          refinedId,
          String(refinementBody.conversation_id),
          {
            parent_artifact_id: artifactId,
            refinement_feedback: instruction,
            edit_mode: 'source_conditioned',
          },
        )),
      })
    },
  )

  await page.goto('/')
  await attachComposerFile(page, {
    name: 'me.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  })
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill(instruction)
  await page.getByRole('button', { name: 'Send message' }).click()

  // The edited picture arrives after the instruction is sent from the main composer.
  await expect(page.getByLabel('Image: Generated image')).toHaveCount(1)
  await expect(page.getByLabel('Image: Generated image').getByAltText(
    'Generated visual result',
  )).toBeVisible()
  expect(refinementBody).toMatchObject({ user_id: 'ani.mallya', feedback: instruction })
  // Forwarded verbatim: the server classifies these words, and substitutes a
  // neutral question before the vision model sees them. Doing that swap here
  // instead would leave the server classifying text nobody typed.
  expect(analyzedPrompt).toBe(instruction)
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a provider failure is visible and the unchanged request can be retried.
// Generation failures now surface through the ordinary chat-failure path
// (the text is restored to the composer for a manual resend) rather than the
// dedicated visual-error banner with its own Retry button, since generation
// is no longer a separate client-triggered request the composer can retry on
// the user's behalf.
test('shows an image failure, clears loading, and can be resent', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '78787878-7878-4878-8878-787878787878'
  let attempts = 0

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    attempts += 1
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Unable to generate the image.' }),
      })
      return
    }
    const payload = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: imageActionEventStream(
        'retry-browser-trace',
        String(payload.conversation_id),
        artifactId,
        'generate',
        'ready',
      ),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )

  await page.goto('/')
  const textarea = page.getByLabel('Message DeepMatter')
  await textarea.fill('Create an image for deterministic retry')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Unable to generate the image.', { exact: true })).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('Create an image for deterministic retry')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('Image: Generated image')).toBeVisible()
  expect(attempts).toBe(2)
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors).toEqual([
    'Failed to load resource: the server responded with a status of 503 (Service Unavailable)',
  ])
})

// Verify upload limit, validation, and VLM failures remain visible and retryable.
test('shows every documented image-analysis failure contract', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let status = 413
  let detail: string | Record<string, unknown> = 'Uploaded image is too large.'
  const scenarios = [
    { status: 413, detail: 'Uploaded image is too large.', message: 'Uploaded image is too large.' },
    { status: 422, detail: 'Uploaded image is invalid or unsupported.', message: 'Uploaded image is invalid or unsupported.' },
    {
      status: 502,
      detail: { message: 'Unable to analyze the uploaded image.', artifact_id: '90909090-1111-4111-8111-909090909090' },
      message: 'Unable to analyze the uploaded image.',
    },
  ]

  await page.route('http://localhost:8000/api/v1/vision/analyze', route =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify({ detail }),
    }),
  )

  await page.goto('/')
  await attachComposerFile(page, {
    name: 'invalid-contract.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  })
  const textarea = page.getByLabel('Message DeepMatter')
  for (const scenario of scenarios) {
    status = scenario.status
    detail = scenario.detail
    await textarea.fill(`Validate visible HTTP ${scenario.status}`)
    await page.getByRole('button', { name: 'Send message' }).click()
    await expect(page.getByRole('alert').filter({ hasText: scenario.message }).first()).toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue(`Validate visible HTTP ${scenario.status}`)
    await expect(page.getByText('Analyzing image...', { exact: true })).not.toBeVisible()
  }
  expect(errors.pageErrors).toEqual([])
  expect(errors.consoleErrors).toHaveLength(3)
  expect(errors.consoleErrors.join('\n')).toContain('413')
  expect(errors.consoleErrors.join('\n')).toContain('422')
  expect(errors.consoleErrors.join('\n')).toContain('502')
})

// Verify real ComfyUI generation plus generated/uploaded source edits in the UI.
test('@live visual generation and analysis complete through the browser', async ({ page }) => {
  test.setTimeout(240_000)
  const errors = observeBlockingBrowserErrors(page)
  const userId = `live_visual_${Date.now()}`
  const conversationId = '90909090-9090-4090-8090-909090909090'
  const generationPrompt = `Create an image of a sapphire ceramic seahorse beside a copper sphere LIVE_UI_${Date.now()}`
  const analysisPrompt = 'Identify the animal, dominant colors, and the object beneath it.'
  const createdIds: string[] = []

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    const textarea = page.getByLabel('Message DeepMatter')
    await textarea.fill(generationPrompt)
    const generationResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    await expect(page.getByText('Generating image...', { exact: true })).toBeVisible()
    const generationResponse = await generationResponsePromise
    expect(generationResponse.status()).toBe(200)
    const generated = await artifactReadyFromChatStream(generationResponse)
    const generatedId = String(generated.id)
    createdIds.push(generatedId)
    expect(generated).toMatchObject({
      user_id: userId,
      conversation_id: conversationId,
      kind: 'generated_image',
      status: 'ready',
      content_available: true,
      provider: 'comfyui',
    })
    const generatedCard = page.getByLabel('Image: Generated image')
    await expect(generatedCard.getByAltText('Generated visual result')).toBeVisible()
    await expect(page.getByText('Generating image...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')

    const refinementFeedback = 'change only the copper sphere to polished gold'
    await expect(generatedCard.getByRole('button', { name: 'Using in chat' })).toBeVisible()
    await textarea.fill(refinementFeedback)
    const refinementResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    const refinementResponse = await refinementResponsePromise
    expect(refinementResponse.status()).toBe(200)
    const revision = await artifactReadyFromChatStream(refinementResponse)
    const revisionId = String(revision.id)
    createdIds.push(revisionId)
    expect(revision).toMatchObject({
      user_id: userId,
      conversation_id: conversationId,
      kind: 'generated_image',
      status: 'ready',
      content_available: true,
      provider: 'comfyui',
      model: 'flux-2-klein-4b-fp8.safetensors',
      metadata: {
        parent_artifact_id: generatedId,
        refinement_feedback: refinementFeedback,
        edit_mode: 'source_conditioned',
        steps: 4,
      },
    })
    expect(await refinementResponse.finished()).toBeNull()
    await expect(page.getByLabel(/^Image: /)).toHaveCount(1)
    const revisedCard = page.getByLabel('Image: Edited image')
    await expect(revisedCard.getByAltText('Generated visual result')).toBeVisible()
    await expect(textarea).toBeEnabled()
    await revisedCard.screenshot({ path: 'test-results/live-flux-refinement.png' })

    await page.getByRole('button', { name: 'Visual artifacts' }).click()
    await expect(page.getByLabel('Image: Edited image').filter({ visible: true })).toBeVisible()
    await page.getByRole('button', { name: 'Conversations' }).click()
    await page.reload()
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    await expect(page.getByLabel('Image: Edited image').getByAltText('Generated visual result')).toBeVisible()

    const generatedContent = await page.request.get(
      `http://localhost:8000/api/v1/artifacts/${userId}/${revisionId}/content`,
    )
    expect(generatedContent.status()).toBe(200)
    await attachComposerFile(page, {
      name: 'generated-live-image.png',
      mimeType: 'image/png',
      buffer: await generatedContent.body(),
    })
    await textarea.fill(analysisPrompt)
    const analysisResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/vision/analyze',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    await expect(page.getByText('Analyzing image...', { exact: true })).toBeVisible()
    const analysisResponse = await analysisResponsePromise
    expect(analysisResponse.status()).toBe(201)
    const analysisResult = await analysisResponse.json() as Record<string, unknown>
    const analyzed = analysisResult.artifact as Record<string, unknown>
    const analyzedId = String(analyzed.id)
    createdIds.push(analyzedId)
    const metadata = analyzed.metadata as Record<string, unknown>
    expect(analyzed).toMatchObject({
      user_id: userId,
      conversation_id: conversationId,
      kind: 'uploaded_image',
      status: 'ready',
      content_available: true,
    })
    expect(metadata.analysis_status).toBe('ready')
    expect(typeof metadata.analysis).toBe('string')
    expect(String(metadata.analysis).length).toBeGreaterThan(20)
    const analyzedCard = page.getByLabel('Image: Uploaded image')
    await expect(analyzedCard.getByAltText('Uploaded visual')).toBeVisible()
    const renderedAnalysis = analyzedCard.locator('.assistant-markdown')
    await expect(renderedAnalysis).toBeVisible()
    expect((await renderedAnalysis.innerText()).trim().length).toBeGreaterThan(20)
    await expect(page.getByText('Analyzing image...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()

    const uploadFeedback = 'make only the background a soft warm gray'
    await expect(analyzedCard.getByRole('button', { name: 'Using in chat' })).toBeVisible()
    await textarea.fill(uploadFeedback)
    const uploadRefinementResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    const uploadRefinementResponse = await uploadRefinementResponsePromise
    expect(uploadRefinementResponse.status()).toBe(200)
    const uploadRevision = await artifactReadyFromChatStream(uploadRefinementResponse)
    const uploadRevisionId = String(uploadRevision.id)
    createdIds.push(uploadRevisionId)
    expect(uploadRevision).toMatchObject({
      user_id: userId,
      conversation_id: conversationId,
      kind: 'generated_image',
      status: 'ready',
      provider: 'comfyui',
      model: 'flux-2-klein-4b-fp8.safetensors',
      metadata: {
        parent_artifact_id: analyzedId,
        refinement_feedback: uploadFeedback,
        edit_mode: 'source_conditioned',
        steps: 4,
      },
    })
    await expect(page.getByLabel('Image: Uploaded image')).toHaveCount(0)
    const uploadedRevisionCard = page.getByLabel('Image: Edited image').last()
    await expect(uploadedRevisionCard.getByAltText('Generated visual result')).toBeVisible()

    await page.reload()
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    await expect(page.getByLabel('Image: Edited image')).toHaveCount(2)
    await expect(page.getByLabel('Image: Generated image').getByAltText(
      'Generated visual result',
    )).toBeVisible()
    await expect(page.getByLabel('Image: Uploaded image').getByAltText(
      'Uploaded visual',
    )).toBeVisible()

    await page.getByLabel('Image: Edited image').first().getByRole('button', { name: 'Delete' }).click()
    await page.getByLabel('Image: Edited image').last().getByRole('button', { name: 'Delete' }).click()
    const uploadedParentDelete = await page.request.delete(
      `http://localhost:8000/api/v1/artifacts/${userId}/${analyzedId}`,
    )
    expect(uploadedParentDelete.status()).toBe(200)
    const originalDelete = await page.request.delete(
      `http://localhost:8000/api/v1/artifacts/${userId}/${generatedId}`,
    )
    expect(originalDelete.status()).toBe(200)
    const remainingResponse = await page.request.get(
      `http://localhost:8000/api/v1/artifacts/${userId}`,
    )
    expect(remainingResponse.status()).toBe(200)
    expect(await remainingResponse.json()).toEqual([])
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
    if (response.ok()) {
      const remaining = await response.json() as Array<Record<string, unknown>>
      for (const artifact of remaining) {
        await page.request.delete(
          `http://localhost:8000/api/v1/artifacts/${userId}/${String(artifact.id)}`,
        )
      }
    }
  }
})

// Verify natural image intent, followups, web search, and memory drilldown live.
test('@live image conversation routes through generation, chat, search, and memory details', async ({ page }) => {
  test.setTimeout(240_000)
  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_image_chat_${stamp}`
  const conversationId = '75757575-7575-4575-8575-757575757575'
  const generationPrompt = `create an image of a cobalt blue sports car on a coastal road LIVE_IMAGE_CHAT_${stamp}`
  const failedRequiredResponses: string[] = []

  page.on('response', response => {
    if (
      response.url().startsWith('http://localhost:8000/api/v1/')
      && response.status() >= 400
    ) {
      failedRequiredResponses.push(`${response.status()} ${response.url()}`)
    }
  })
  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    const textarea = page.getByLabel('Message DeepMatter')
    await textarea.fill(generationPrompt)
    const generationResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    const generationResponse = await generationResponsePromise
    expect(generationResponse.status()).toBe(200)
    const generated = await artifactReadyFromChatStream(generationResponse)
    expect((generated.metadata as Record<string, unknown>).generation_prompt)
      .toBe(generationPrompt)
    await expect(page.getByLabel('Image: Generated image')).toBeVisible()
    await expect(page.getByText('Generating image...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()

    await textarea.fill('what car did we create an image of?')
    const followupResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    const followupResponse = await followupResponsePromise
    expect(followupResponse.status()).toBe(200)
    expect(await followupResponse.finished()).toBeNull()
    // The followup answered from context rather than creating a second
    // picture -- the only image card still on screen is the original.
    await expect(page.getByLabel('Image: Generated image')).toHaveCount(1)
    await expect(latestAssistantAnswer(page)).toContainText(/cobalt blue sports car/i)
    await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')

    await textarea.fill('can you search the internet for that car to get its model?')
    const searchResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    const searchResponse = await searchResponsePromise
    expect(searchResponse.status()).toBe(200)
    expect(await searchResponse.finished()).toBeNull()
    const searchStream = await searchResponse.text()
    expect(searchStream).toContain('event: search_results')
    expect(searchStream).toContain('event: done')
    const searchAnswer = latestAssistantAnswer(page)
    await expect(searchAnswer.getByText('Used search_web via internet')).toBeVisible()
    if (!searchStream.includes('"sources": []')) {
      await expect(searchAnswer.getByLabel('Web sources used')).toBeVisible()
    }
    await expect(page.getByText('Thinking...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveValue('')

    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    const exportResponsePromise = page.waitForResponse(
      response => response.url().endsWith(`/api/v1/memory/${userId}/export`),
    )
    await page.getByRole('button', { name: 'View Semantic cache details' }).click()
    expect((await exportResponsePromise).status()).toBe(200)
    const details = page.getByRole('region', { name: 'Semantic cache details' })
    await expect(details).toBeVisible()
    await expect(details.getByText('Loading details...', { exact: true })).not.toBeVisible()

    await expect(page.getByLabel('Image: Generated image')).toHaveCount(1)
    expect(failedRequiredResponses).toEqual([])
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
    if (response.ok()) {
      const artifacts = await response.json() as Array<Record<string, unknown>>
      for (const artifact of artifacts) {
        await page.request.delete(
          `http://localhost:8000/api/v1/artifacts/${userId}/${String(artifact.id)}`,
        )
      }
    }
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

// Verify cancelling a live browser request interrupts its provider job and terminalizes state.
test('@live cancelled image generation becomes a terminal failed artifact', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = observeBlockingBrowserErrors(page)
  const userId = `live_cancel_${Date.now()}`
  const conversationId = '81818181-8181-4181-8181-818181818181'

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    const textarea = page.getByLabel('Message DeepMatter')
    await textarea.fill(`Create an image of a cancellation probe cobalt glass compass ${Date.now()}`)
    const requestPromise = page.waitForRequest(
      request => request.url() === 'http://localhost:8000/api/v1/chat',
    )
    await page.getByRole('button', { name: 'Send message' }).click()
    await requestPromise
    await expect.poll(async () => {
      const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
      const artifacts = await response.json() as Array<Record<string, unknown>>
      return artifacts[0]?.status
    }).toBe('pending')

    await page.getByRole('button', { name: 'Cancel request' }).click()
    await expect(page.getByText('Request cancelled.', { exact: true }).first()).toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Cancel request' })).not.toBeVisible()
    await expect.poll(async () => {
      const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
      const artifacts = await response.json() as Array<Record<string, unknown>>
      return { status: artifacts[0]?.status, error_code: artifacts[0]?.error_code }
    }, { timeout: 15_000 }).toEqual({ status: 'failed', error_code: 'cancelled' })
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
    if (response.ok()) {
      const artifacts = await response.json() as Array<Record<string, unknown>>
      for (const artifact of artifacts) {
        await page.request.delete(
          `http://localhost:8000/api/v1/artifacts/${userId}/${String(artifact.id)}`,
        )
      }
    }
  }
})

// Verify live structured proposals are auto-saved with no approval step, and recall.
test('@live auto-saves and recalls entity, procedure, and knowledge memory', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(360_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `capture_live_${stamp}`
  const entity = `Person${stamp}`
  const procedureCode = `WORKFLOW_${stamp}`
  const knowledgeCode = `REFERENCE_${stamp}`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  // Send one live message and wait for the complete SSE response.
  const sendAndWait = async (message: string) => {
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
    )
    await textarea.fill(message)
    await sendButton.click()
    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()
    await expect(textarea).toBeEnabled({ timeout: 120_000 })
  }
  const savedNotice = () => page.getByRole('status', { name: 'Saved to memory' })

  try {
    await page.goto('/')
    await sendAndWait(`Remember that ${entity} is my dentist.`)
    await expect(savedNotice()).toContainText(entity)

    await sendAndWait(
      `Remember this workflow: Morning ${stamp}. Steps: ` +
      `open ${procedureCode}; verify ${procedureCode}.`,
    )
    await expect(savedNotice()).toContainText(`Morning ${stamp}`)

    await sendAndWait(
      `Remember this reference: Studio ${stamp} | ` +
      `The reference code is ${knowledgeCode}.`,
    )
    await expect(savedNotice()).toContainText(`Studio ${stamp}`)

    const snapshot = await page.request.get(
      `http://localhost:8000/api/v1/memory/${userId}/agent`,
    )
    expect(await snapshot.json()).toMatchObject({
      entities: 1,
      procedures: 1,
      knowledge_documents: 1,
      knowledge_chunks: 1,
    })

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait(
      'Who is my dentist person? Reply with only their remembered name.',
    )
    await expect(latestAssistantAnswer(page)).toContainText(entity, {
      timeout: 120_000,
    })

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait(
      'What are my remembered Morning workflow steps? Reply with the workflow code.',
    )
    await expect(latestAssistantAnswer(page)).toContainText(procedureCode, {
      timeout: 120_000,
    })

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait(
      'According to my remembered Studio reference knowledge, what is the ' +
      'reference code? Reply with only the code.',
    )
    await expect(latestAssistantAnswer(page)).toContainText(knowledgeCode, {
      timeout: 120_000,
    })
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

test('@live recalls a prior turn in the same conversation', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_history_${stamp}`
  const conversationId = crypto.randomUUID()
  const name = `BrowserName${stamp}`
  const requests: Array<{ user_id: string; conversation_id: string; query: string }> = []

  await page.addInitScript(
    ({ user, conversation }) => {
      localStorage.setItem('anios_user_id', user)
      localStorage.setItem('anios_conversation_id', conversation)
    },
    { user: userId, conversation: conversationId },
  )
  page.on('request', request => {
    if (request.url() === 'http://localhost:8000/api/v1/chat') {
      requests.push(request.postDataJSON())
    }
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)

  const firstResponsePromise = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat',
  )
  await textarea.fill(`My name is ${name}.`)
  await sendButton.click()
  const firstResponse = await firstResponsePromise
  expect(firstResponse.status()).toBe(200)
  expect(firstResponse.headers()['content-type']).toContain('text/event-stream')
  expect(await firstResponse.finished()).toBeNull()
  await expect(textarea).toBeEnabled({ timeout: 120_000 })

  const secondResponsePromise = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat',
  )
  await textarea.fill('What name did I tell you? Reply with only the name.')
  await sendButton.click()
  await expect(textarea).toBeDisabled()
  const secondResponse = await secondResponsePromise
  expect(secondResponse.status()).toBe(200)
  expect(secondResponse.headers()['content-type']).toContain('text/event-stream')
  expect(await secondResponse.finished()).toBeNull()

  await expect(latestAssistantAnswer(page).getByText(name, { exact: false })).toBeVisible({ timeout: 120_000 })
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(sendButton).toBeDisabled()
  expect(requests).toHaveLength(2)
  expect(requests.map(request => request.user_id)).toEqual([userId, userId])
  expect(requests.map(request => request.conversation_id)).toEqual([
    conversationId,
    conversationId,
  ])
  expect(requests[1].query).not.toContain(name)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('@live auto-saves a response-style proposal from chat', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const userId = `style_live_${Date.now()}`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  try {
    await page.goto('/')
    const { textarea, sendButton } = chatControls(page)
    await textarea.fill('Please be concise.')
    await sendButton.click()
    await expect(page.getByRole('status', { name: 'Saved to memory' })).toContainText(
      'concise',
      { timeout: 120_000 },
    )

    const snapshot = await page.request.get(
      `http://localhost:8000/api/v1/memory/${userId}`,
    )
    expect(snapshot.status()).toBe(200)
    const memory = await snapshot.json()
    expect(memory.profile.preferences.response_style).toBe('concise')
    expect(memory.facts).toHaveLength(1)
    expect(memory.facts[0]).toMatchObject({
      fact_key: 'response_style',
      value: 'concise',
      approval_state: 'approved',
      version: 1,
    })
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

test('@live auto-saves, corrects, recalls, and deletes a preferred name', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(240_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `pname_live_${stamp}`
  const otherUser = `pname_other_${stamp}`
  const approvedName = `Approved${stamp}`
  const correctedName = `Corrected${stamp}`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  const sendAndWait = async (message: string) => {
    const { textarea, sendButton } = chatControls(page)
    const responsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/chat',
    )
    await textarea.fill(message)
    await sendButton.click()
    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()
    await expect(textarea).toBeEnabled({ timeout: 120_000 })
  }

  try {
    await page.goto('/')
    await sendAndWait(`My name is ${approvedName}.`)
    await expect(page.getByRole('status', { name: 'Saved to memory' })).toContainText(approvedName)
    const snapshot = await page.request.get(`http://localhost:8000/api/v1/memory/${userId}`)
    expect((await snapshot.json()).profile.name).toBe(approvedName)
    const otherSnapshot = await page.request.get(`http://localhost:8000/api/v1/memory/${otherUser}`)
    expect((await otherSnapshot.json()).profile.name).toBeUndefined()

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait('What is my preferred name? Reply with only the name.')
    await expect(latestAssistantAnswer(page).getByText(approvedName, { exact: false })).toBeVisible({ timeout: 120_000 })

    await sendAndWait(`My preferred name is ${correctedName}.`)
    await expect(page.getByRole('status', { name: 'Saved to memory' })).toContainText(correctedName)

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait('What is my preferred name? Reply with only the name.')
    await expect(latestAssistantAnswer(page).getByText(correctedName, { exact: false })).toBeVisible({ timeout: 120_000 })

    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    await expect(page.getByLabel('Profile name')).toHaveValue(correctedName)
    const deleteResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/profile/preferred-name`) &&
      response.request().method() === 'DELETE',
    )
    await page.getByRole('button', { name: 'Delete preferred name' }).click()
    expect((await deleteResponse).status()).toBe(200)
    await expect(page.getByLabel('Profile name')).toHaveValue('')
    const afterDelete = await page.request.get(`http://localhost:8000/api/v1/memory/${userId}`)
    expect((await afterDelete.json()).profile.name).toBeNull()
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
    await page.request.delete(`http://localhost:8000/api/v1/memory/${otherUser}`)
  }
})

test('@live persists, recalls, and deletes personal memory', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const userId = `live_memory_${Date.now()}`
  const token = `MEMORY_${Date.now()}`
  const memory = `The user's personal memory verification code is ${token}.`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  try {
    await page.goto('/')
    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Personal Memory' })).toBeVisible()
    await expect(page.getByLabel('Active user ID')).toHaveValue(userId)

    const createResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/semantic`) &&
      response.request().method() === 'POST',
    )
    await page.getByText('Advanced: add memory manually').click()
    await page.getByLabel('Fact or preference').fill(memory)
    await page.getByRole('button', { name: 'Add fact or preference' }).click()
    expect((await createResponse).status()).toBe(201)
    await expect(page.getByText(memory, { exact: true })).toBeVisible()

    await page.reload()
    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    await expect(page.getByText(memory, { exact: true })).toBeVisible()

    const correctedMemory = `${memory} Corrected through the browser.`
    const correctionResponse = page.waitForResponse(response =>
      response.url().includes(`/api/v1/memory/${userId}/semantic/`) &&
      response.request().method() === 'PUT',
    )
    await page.getByRole('button', { name: 'Edit semantic record' }).click()
    await page.getByLabel('Correct semantic record').fill(correctedMemory)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    expect((await correctionResponse).status()).toBe(200)
    await expect(page.getByText(correctedMemory, { exact: true })).toBeVisible()

    const exportResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/export`) &&
      response.request().method() === 'GET',
    )
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export personal memory' }).click()
    expect((await exportResponse).status()).toBe(200)
    expect((await downloadPromise).suggestedFilename()).toBe(`anios-memory-${userId}.json`)

    await page.getByRole('button', { name: 'Conversations' }).click()
    const { textarea, sendButton } = chatControls(page)
    const chatResponse = page.waitForResponse(response =>
      response.url() === 'http://localhost:8000/api/v1/chat',
    )
    await textarea.fill('What is my personal memory verification code? Reply with only the code.')
    await sendButton.click()
    const response = await chatResponse
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(await response.finished()).toBeNull()
    await expect(page.getByText(token, { exact: false })).toBeVisible({ timeout: 120_000 })
    await expect(textarea).toBeEnabled()
    await expect(sendButton).toBeDisabled()

    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    page.once('dialog', dialog => dialog.accept())
    const deleteResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}`) &&
      response.request().method() === 'DELETE',
    )
    await page.getByRole('button', { name: 'Delete all personal memory' }).click()
    expect((await deleteResponse).status()).toBe(200)
    await expect(page.getByText('No facts or preferences saved.')).toBeVisible()
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

// Verify the browser forget-me action removes an uploaded artifact and its memory.
test('@live delete all personal memory also deletes owned artifacts', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the live application')
  const userId = process.env.ANIOS_E2E_USERNAME ?? ''
  const bearerToken = process.env.ANIOS_E2E_BEARER_TOKEN ?? ''
  const apiUrl = process.env.ANIOS_API_URL ?? 'http://localhost:8000'
  test.skip(!userId || !bearerToken, 'Set ANIOS_E2E_USERNAME and ANIOS_E2E_BEARER_TOKEN')
  test.setTimeout(180_000)
  const errors = observeBlockingBrowserErrors(page)
  const authorization = { Authorization: `Bearer ${bearerToken}` }
  await page.route('**/api/**', async route => {
    await route.continue({
      headers: { ...route.request().headers(), ...authorization },
    })
  })

  try {
    const upload = await page.request.post(`${apiUrl}/api/v1/vision/analyze`, {
      headers: authorization,
      multipart: {
        user_id: userId,
        conversation_id: randomUUID(),
        prompt: 'Describe this deletion-test image briefly.',
        image: {
          name: 'memory-delete-probe.png',
          mimeType: 'image/png',
          buffer: LIVE_TEST_PNG,
        },
      },
    })
    expect(upload.status()).toBe(201)
    expect((await page.request.get(`${apiUrl}/api/v1/artifacts/${userId}`, {
      headers: authorization,
    })).status()).toBe(200)

    await page.goto('/')
    await expect(
      page.getByRole('main').getByText(`Signed in as ${userId}`),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Memory', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Personal Memory' })).toBeVisible()

    page.once('dialog', dialog => dialog.accept())
    const deleteResponse = page.waitForResponse(response => (
      response.url().endsWith(`/api/v1/memory/${userId}`) &&
      response.request().method() === 'DELETE'
    ))
    await page.getByRole('button', { name: 'Delete all personal memory' }).click()
    const deleted = await deleteResponse
    expect(deleted.status()).toBe(200)
    expect((await deleted.json()).deleted.artifacts).toBeGreaterThanOrEqual(1)
    await expect(page.getByText('No facts or preferences saved.')).toBeVisible()

    const artifacts = await page.request.get(`${apiUrl}/api/v1/artifacts/${userId}`, {
      headers: authorization,
    })
    expect(artifacts.status()).toBe(200)
    expect(await artifacts.json()).toEqual([])
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`${apiUrl}/api/v1/memory/${userId}`, {
      headers: authorization,
    })
  }
})

// Enter submits and Shift+Enter starts a new line. Every multi-line box needs
// this wired explicitly, because a browser never submits a form from inside a
// textarea, so it is easy for one box to silently behave unlike its neighbours.
test('Enter sends from the composer and Shift+Enter writes a new line', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const sent: string[] = []
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    sent.push(payload.query)
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('enter-trace', payload.conversation_id, 'received'),
    })
  })

  await page.goto('/')
  const { textarea } = chatControls(page)

  // Shift+Enter must not send; it extends the message.
  await textarea.fill('first line')
  await textarea.press('Shift+Enter')
  await textarea.type('second line')
  expect(await textarea.inputValue()).toContain('\n')
  expect(sent).toHaveLength(0)

  // Plain Enter sends, and the composer empties without a click.
  await textarea.press('Enter')
  await expect(textarea).toHaveValue('')
  await expect(latestAssistantAnswer(page)).toContainText('received')
  expect(sent).toHaveLength(1)
  expect(sent[0]).toContain('first line')

  // An empty composer must not send on Enter.
  await textarea.press('Enter')
  expect(sent).toHaveLength(1)

  expect(errors.consoleErrors).toEqual([])
  expect(errors.pageErrors).toEqual([])
})

// The Agents tab is the control surface for every specialized worker, so it
// must show real state rather than a static list. Deterministic: the registry
// response is stubbed, and the assertions are about what the user can read.
test('the Agents tab reports each agent status and what it is waiting on', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.route('**/api/v1/agents/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: 'test',
        agents: [
          {
            id: 'discovery',
            name: 'Scout',
            role: 'Finds things happening near you.',
            status: 'needs_setup',
            detail: 'Add an interest and a feed before it can find anything.',
            trigger: 'On request',
            last_active_at: null,
            facts: [
              { label: 'Feeds', value: '0' },
              { label: 'Interests', value: '0' },
            ],
          },
          {
            id: 'presentation',
            name: 'Deck',
            role: 'Plans and builds editable presentations.',
            status: 'working',
            detail: 'Building 1 deck now.',
            trigger: 'Delegated from chat',
            last_active_at: new Date().toISOString(),
            facts: [{ label: 'Decks built', value: '3' }],
          },
        ],
      }),
    })
  })

  await page.goto('/')
  await page.getByLabel('Agents').click()

  await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()

  // Scope each assertion to its own card, so a status shown on one agent can never
  // satisfy an assertion about the other.
  const scout = page.locator('article').filter({ hasText: 'Scout' })
  const deck = page.locator('article').filter({ hasText: 'Deck' })

  // An agent that cannot run must say what is missing, not just "idle".
  await expect(scout.getByText('Needs setup')).toBeVisible()
  await expect(
    scout.getByText('Add an interest and a feed before it can find anything.'),
  ).toBeVisible()
  // A never-run agent must not display a fabricated timestamp.
  await expect(scout.getByText('Last active never run')).toBeVisible()

  // A working agent reports what it is doing right now.
  await expect(deck.getByText('Working', { exact: true })).toBeVisible()
  await expect(deck.getByText('Building 1 deck now.')).toBeVisible()
  await expect(deck.getByText('3', { exact: true })).toBeVisible()

  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a familiar-item dismissal can be reviewed and undone from Scout's panel.
test('undoes a dismissed discovery from the Agents tab', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let hidden = [{ id: 'known-1', label: 'Four Mile Run Trail', created_at: null }]

  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      agents: [{
        id: 'discovery',
        name: 'Scout',
        role: 'Finds things happening near you.',
        status: 'idle',
        detail: 'Ready.',
        trigger: 'On request',
        last_active_at: null,
        facts: [],
      }],
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      interests: [{ id: 'interest-1', label: 'hiking', strength: 2, provenance: 'user_explicit' }],
      localities: [{
        id: 'place-1',
        label: 'Arlington',
        region: 'Virginia',
        radius_km: 25,
        timezone: 'America/New_York',
        is_primary: true,
      }],
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/sources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ sources: [] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/schedule', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ schedule: null }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/known', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ locality: 'Arlington', known: hidden }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/known/known-1', route => {
    hidden = []
    return route.fulfill({ status: 204 })
  })

  await page.goto('/')
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()
  await expect(page.getByText('Hidden around Arlington')).toBeVisible()
  await expect(page.getByText('Four Mile Run Trail')).toBeVisible()

  await page.getByRole('button', { name: 'Undo dismissal of Four Mile Run Trail' }).click()

  await expect(page.getByText('Restored Four Mile Run Trail. Similar finds can appear here again.')).toBeVisible()
  await expect(page.getByText('Hidden around Arlington')).not.toBeVisible()
  expect(hidden).toEqual([])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify reporting a location moves Scout without touching home. This used to
// save the home locality, so one press while away rewrote where the user lives
// and the approved memory fact behind it.
test('reports a location without changing where the user lives', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const localities: Array<{
    id: string;
    label: string;
    region: string | null;
    radius_km: number;
    timezone: string;
    is_primary: boolean;
    is_travel_active: boolean;
  }> = [{
    id: 'place-home',
    label: 'Arlington',
    region: 'Virginia',
    radius_km: 25,
    timezone: 'America/New_York',
    is_primary: true,
    is_travel_active: false,
  }]

  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      agents: [{
        id: 'discovery',
        name: 'Scout',
        role: 'Finds things happening near you.',
        status: 'idle',
        detail: 'Ready.',
        trigger: 'On request',
        last_active_at: null,
        facts: [],
      }],
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      interests: [{ id: 'interest-1', label: 'hiking', strength: 2, provenance: 'user_explicit' }],
      localities,
    }),
  }))
  // The browser reports a coordinate; the backend blunts it and names the town.
  // Only the town is ever stored, which is what the resolve step exists for.
  await page.route('**/api/v1/discovery/ani.mallya/locality/resolve', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      label: 'Denver',
      region: 'Colorado',
      country: 'United States',
      country_code: 'us',
      display: 'Denver, Colorado, US',
      stored_region: 'Colorado',
      sent_precision_decimals: 2,
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/current-place', async route => {
    const body = route.request().postDataJSON()
    const home = localities.find(item => item.is_primary)
    // Reporting home ends the trip; anywhere else is simply being away.
    if (home && home.label === body.label) {
      localities.forEach(item => { item.is_travel_active = false })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ locality: home, away: false, home }),
      })
      return
    }
    const destination = {
      id: 'place-travel',
      label: body.label,
      region: body.region ?? null,
      radius_km: 25,
      timezone: body.timezone,
      is_primary: false,
      is_travel_active: true,
      travel_expires_at: '2026-08-17T00:00:00Z',
    }
    localities.push(destination)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ locality: destination, away: true, home }),
    })
  })
  await page.route('**/api/v1/discovery/ani.mallya/travel', async route => {
    if (route.request().method() === 'DELETE') {
      localities.forEach(item => { item.is_travel_active = false })
      await route.fulfill({ status: 204 })
      return
    }
    const body = route.request().postDataJSON()
    localities.forEach(item => { item.is_travel_active = item.id === body.locality_id })
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ active_locality: localities.find(item => item.is_travel_active) }),
    })
  })
  await page.route('**/api/v1/discovery/ani.mallya/sources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ sources: [] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/schedule', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ schedule: null }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/known', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ locality: 'Arlington', known: [] }),
  }))

  await page.context().grantPermissions(['geolocation'])
  await page.context().setGeolocation({ latitude: 39.74, longitude: -104.99 })

  await page.goto('/')
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()
  await page.getByRole('button', { name: 'Use my location' }).click()

  // The chat banner and the Scout status line both say this; assert on the
  // banner rather than on whichever the page happens to render first.
  await expect(
    page.getByText('Looking around Denver, Colorado for now.'),
  ).toBeVisible()
  // The whole point: home is untouched, so the memory fact behind it is too.
  expect(localities[0].is_primary).toBe(true)
  expect(localities[0].label).toBe('Arlington')
  expect(localities[1].is_travel_active).toBe(true)
  // Visiting and moving are indistinguishable from a coordinate, so it asks.
  await expect(page.getByRole('button', { name: 'I moved here' })).toBeVisible()
  await page.getByRole('button', { name: 'Just visiting' }).click()
  expect(localities[0].is_primary).toBe(true)

  await page.getByRole('button', { name: /Back to Arlington/ }).click()
  expect(localities[0].is_primary).toBe(true)
  expect(localities.some(item => item.is_travel_active)).toBe(false)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a user can tune ranking strength and see the persisted value after refresh.
test('changes Scout interest importance from the Agents tab', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const interest = {
    id: 'interest-1',
    label: 'hiking',
    strength: 2,
    provenance: 'user_explicit',
  }
  const writes: Array<{ label: string; strength: number }> = []

  await page.route('**/api/v1/agents/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      agents: [{
        id: 'discovery',
        name: 'Scout',
        role: 'Finds things happening near you.',
        status: 'idle',
        detail: 'Ready.',
        trigger: 'On request',
        last_active_at: null,
        facts: [],
      }],
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'ani.mallya',
      interests: [interest],
      localities: [{
        id: 'place-home',
        label: 'Arlington',
        region: 'Virginia',
        radius_km: 25,
        timezone: 'America/New_York',
        is_primary: true,
        is_travel_active: false,
      }],
    }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/interests', async route => {
    const body = route.request().postDataJSON() as { label: string; strength: number }
    writes.push(body)
    interest.strength = body.strength
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(interest),
    })
  })
  await page.route('**/api/v1/discovery/ani.mallya/sources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ sources: [] }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/schedule', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ schedule: null }),
  }))
  await page.route('**/api/v1/discovery/ani.mallya/known', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ locality: 'Arlington', known: [] }),
  }))

  await page.goto('/')
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()
  const importance = page.getByLabel('Importance of hiking')
  await expect(importance).toHaveValue('2')
  await importance.selectOption('3')

  await expect(page.getByText('hiking importance set to high.')).toBeVisible()
  await expect(importance).toHaveValue('3')
  expect(writes).toEqual([{ label: 'hiking', strength: 3 }])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Exercise the complete Scout profile workflow against the rebuilt API and database.
test('@live manages Scout memory, travel, strength, and dismissal undo', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the live application')
  const errors = observeBlockingBrowserErrors(page)
  const apiUrl = process.env.ANIOS_API_URL ?? 'http://localhost:8000'
  const stamp = Date.now()
  const userId = `live_scout_${stamp}`
  const interestLabel = `urban hiking ${stamp}`
  await page.addInitScript(id => localStorage.setItem('anios_user_id', id), userId)

  try {
    await page.goto('/')
    await page.getByLabel('Agents').click()
    await page.getByRole('button', { name: 'Configure' }).click()

    await page.getByLabel('Town or city').fill('Arlington')
    const homeResponse = page.waitForResponse(response => (
      response.url() === `${apiUrl}/api/v1/discovery/${userId}/localities` &&
      response.request().method() === 'PUT'
    ))
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    expect((await homeResponse).status()).toBe(200)
    await expect(page.getByText(/Saved .* looking around Arlington/)).toBeVisible()

    await page.getByLabel('Add an interest').fill(interestLabel)
    await page.getByLabel('Add an interest').press('Enter')
    const importance = page.getByLabel(`Importance of ${interestLabel}`)
    await expect(importance).toHaveValue('2')
    await importance.selectOption('3')
    await expect(importance).toHaveValue('3')

    await page.getByLabel('Travel destination').fill('Denver')
    await page.getByRole('button', { name: 'Start travel' }).click()
    await expect(page.getByText('Looking around Denver', { exact: true })).toBeVisible()

    const marked = await page.request.post(
      `${apiUrl}/api/v1/discovery/${userId}/known`,
      { data: { label: `River trail ${stamp}` } },
    )
    expect(marked.status()).toBe(200)

    await page.reload()
    await page.getByLabel('Agents').click()
    await page.getByRole('button', { name: 'Configure' }).click()
    await expect(page.getByText('Hidden around Denver')).toBeVisible()
    await page.getByRole('button', { name: `Undo dismissal of River trail ${stamp}` }).click()
    await expect(page.getByText('Hidden around Denver')).not.toBeVisible()

    await page.getByRole('button', { name: 'Return home' }).click()
    await expect(page.getByText('Travel mode off. Scout is back around Arlington.')).toBeVisible()

    const profile = await page.request.get(`${apiUrl}/api/v1/discovery/${userId}`)
    expect(profile.status()).toBe(200)
    const profileBody = await profile.json()
    expect(profileBody.interests).toEqual([
      expect.objectContaining({ label: interestLabel, strength: 3 }),
    ])
    expect(profileBody.localities).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Arlington', is_primary: true, is_travel_active: false }),
      expect.objectContaining({ label: 'Denver', is_primary: false, is_travel_active: false }),
    ]))

    const memory = await page.request.get(`${apiUrl}/api/v1/memory/${userId}`)
    expect(memory.status()).toBe(200)
    const factValues = (await memory.json()).facts.map((fact: { value: string }) => fact.value)
    expect(factValues).toEqual(expect.arrayContaining(['Arlington', interestLabel]))
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`${apiUrl}/api/v1/memory/${userId}`)
  }
})

// Verify semantic chat interests become the signed-in user's visible Scout profile.
test('@live auto-saves semantic Scout interests from authenticated chat', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the live application')
  const username = process.env.ANIOS_E2E_USERNAME ?? ''
  const password = process.env.ANIOS_E2E_PASSWORD ?? ''
  test.skip(!username || !password, 'Set ANIOS_E2E_USERNAME and ANIOS_E2E_PASSWORD')
  test.setTimeout(120_000)
  const apiUrl = process.env.ANIOS_API_URL ?? 'http://localhost:8000'
  const frontendOrigin = new URL(
    process.env.ANIOS_FRONTEND_URL ?? 'http://localhost:5173',
  ).origin
  const labels = ['basketball', 'soccer', 'baseball', 'hiking']

  try {
    await page.goto('/')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByText(`Signed in as ${username}`)).toBeVisible()
    const errors = observeBlockingBrowserErrors(page)

    const cleared = await page.request.delete(`${apiUrl}/api/v1/memory/${username}`, {
      headers: { Origin: frontendOrigin },
    })
    expect(cleared.status()).toBe(200)
    const { textarea, sendButton } = chatControls(page)

    const interestResponse = page.waitForResponse(response => (
      response.url() === `${apiUrl}/api/v1/chat` &&
      response.request().method() === 'POST'
    ))
    await textarea.fill('My interests are basketball, soccer, baseball, hiking')
    await sendButton.click()
    const interestStream = await interestResponse
    expect(interestStream.status()).toBe(200)
    expect(await interestStream.finished()).toBeNull()
    await expect(page.getByRole('status', { name: 'Saved to memory' })).toContainText(
      labels.join(', '),
      { timeout: 30_000 },
    )
    await expect(textarea).toBeEnabled()

    await page.getByLabel('Agents').click()
    await page.getByRole('button', { name: 'Configure' }).click()
    for (const label of labels) {
      await expect(page.getByLabel(`Importance of ${label}`)).toHaveValue('2')
    }

    const profile = await page.request.get(`${apiUrl}/api/v1/discovery/${username}`)
    expect(profile.status()).toBe(200)
    const body = await profile.json()
    expect(body.interests.map((interest: { label: string }) => interest.label).sort())
      .toEqual([...labels].sort())
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`${apiUrl}/api/v1/memory/${username}`, {
      headers: { Origin: frontendOrigin },
    })
  }
})

// Verify Scout's real browser rehearsal uses honest, readable uncertain-date copy.
test('@live renders future-safe Scout wording for the signed-in profile', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the live application')
  const userId = process.env.ANIOS_E2E_USERNAME ?? ''
  const bearerToken = process.env.ANIOS_E2E_BEARER_TOKEN ?? ''
  test.skip(!userId || !bearerToken, 'Set ANIOS_E2E_USERNAME and ANIOS_E2E_BEARER_TOKEN')
  test.setTimeout(120_000)
  const errors = observeBlockingBrowserErrors(page)
  await page.setExtraHTTPHeaders({ Authorization: `Bearer ${bearerToken}` })

  await page.goto('/')
  await expect(page.getByText(`Signed in as ${userId}`)).toBeVisible()
  await page.getByLabel('Agents').click()
  await page.getByRole('button', { name: 'Configure' }).click()
  const sweepResponse = page.waitForResponse(response => (
    response.url().includes(`/api/v1/discovery/${userId}/sweep?commit=false`) &&
    response.request().method() === 'POST'
  ))
  await page.getByRole('button', { name: 'Try it' }).click()
  const rehearsalResponse = await sweepResponse
  expect(rehearsalResponse.status()).toBe(200)
  expect(await rehearsalResponse.finished()).toBeNull()

  const rehearsal = page.getByText('Rehearsal — nothing was saved').locator('..')
  await expect(rehearsal).toContainText(
    /Coming up near you:|I found (this|a few possibilities), but couldn't confirm/,
    { timeout: 90_000 },
  )
  await expect(rehearsal).not.toContainText('Worth a look — no date given')
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
