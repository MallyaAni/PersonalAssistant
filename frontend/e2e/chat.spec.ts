import { expect, test, type Page } from '@playwright/test'

const TEST_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2O9sAAAAASUVORK5CYII=',
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

function chatControls(page: Page) {
  const textarea = page.getByLabel('Message AniOS')
  const sendButton = textarea.locator('..').locator('button')
  return { textarea, sendButton }
}

function latestAssistantAnswer(page: Page) {
  return page.getByLabel('AniOS answer').last()
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

test('renders a responsive search-first chat shell', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'What can I help you find?' })).toBeVisible()
  const composer = page.getByLabel('Message AniOS')
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

test('migrates only the legacy default user and rotates its conversation', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const legacyConversation = '11111111-1111-4111-8111-111111111111'
  const customConversation = '22222222-2222-4222-8222-222222222222'
  const requests: Array<{ user_id: string; conversation_id: string }> = []

  await page.addInitScript(({ conversation }) => {
    if (sessionStorage.getItem('legacy_default_seeded')) return
    sessionStorage.setItem('legacy_default_seeded', 'true')
    localStorage.setItem('anios_user_id', 'dev_user_001')
    localStorage.setItem('anios_conversation_id', conversation)
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

  await page.goto('/')
  let stored = await page.evaluate(() => ({
    userId: localStorage.getItem('anios_user_id'),
    conversationId: localStorage.getItem('anios_conversation_id'),
  }))
  expect(stored.userId).toBe('ani.mallya')
  expect(stored.conversationId).not.toBe(legacyConversation)

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
    localStorage.setItem('anios_conversation_id', conversation)
  }, { conversation: customConversation })
  await page.reload()
  stored = await page.evaluate(() => ({
    userId: localStorage.getItem('anios_user_id'),
    conversationId: localStorage.getItem('anios_conversation_id'),
  }))
  expect(stored).toEqual({
    userId: 'custom_user',
    conversationId: customConversation,
  })

  controls = chatControls(page)
  await controls.textarea.fill('verify custom user')
  await controls.sendButton.click()
  await expect(controls.textarea).toBeEnabled()
  expect(requests[1]).toEqual({
    user_id: 'custom_user',
    conversation_id: customConversation,
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

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
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
  await expect(page.getByText('Unable to send message. Please try again.', { exact: true })).toBeVisible()
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

test('requires explicit approval before saving a preferred-name proposal', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const proposedNames = ['Rejected Name', 'Approved Name']
  const approvals: Array<{
    name: string;
    source_conversation_id: string;
    source_trace_id: string;
  }> = []
  let chatCount = 0

  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    const preferredName = proposedNames[chatCount++]
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream('proposal-trace', payload.conversation_id, 'ok', preferredName),
    })
  })
  await page.route(
    'http://localhost:8000/api/v1/memory/*/profile/preferred-name',
    async route => {
      approvals.push(route.request().postDataJSON())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 'ani.mallya',
          profile: {
            user_id: 'ani.mallya',
            name: approvals.at(-1)!.name,
            preferences: {},
          },
          fact: {},
        }),
      })
    },
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('My name is Rejected Name.')
  await sendButton.click()
  await expect(page.getByLabel('Preferred name memory proposal')).toContainText('Rejected Name')
  expect(approvals).toEqual([])
  await page.getByRole('button', { name: 'Not now' }).click()
  await expect(page.getByText('Preferred name was not saved.')).toBeVisible()
  expect(approvals).toEqual([])

  await textarea.fill('My name is Approved Name.')
  await sendButton.click()
  await expect(page.getByLabel('Preferred name memory proposal')).toContainText('Approved Name')
  await page.getByRole('button', { name: 'Approve preferred name' }).click()
  await expect(page.getByText('Saved preferred name: Approved Name')).toBeVisible()
  expect(approvals).toEqual([{
    name: 'Approved Name',
    source_conversation_id: expect.any(String),
    source_trace_id: 'proposal-trace',
  }])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('requires approval before saving a response-style proposal', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const approvals: Array<Record<string, unknown>> = []

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
  await page.route('http://localhost:8000/api/v1/memory/*/facts', async route => {
    approvals.push(route.request().postDataJSON())
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ fact: {}, deduplicated: false }),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Please be concise.')
  await sendButton.click()
  await expect(page.getByLabel('Response style memory proposal')).toContainText('concise')
  expect(approvals).toEqual([])
  await page.getByRole('button', { name: 'Approve response style' }).click()
  await expect(page.getByText('Saved response style: concise')).toBeVisible()
  expect(approvals).toEqual([{
    fact_type: 'profile',
    fact_key: 'response_style',
    value: 'concise',
    purpose: 'personalization',
    source_conversation_id: expect.any(String),
    source_trace_id: 'style-proposal-trace',
    metadata: { source: 'chat_approval' },
  }])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

test('keeps a preferred-name proposal actionable when approval fails', async ({ page }) => {
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        'proposal-error-trace',
        payload.conversation_id,
        'ok',
        'Retry Name',
      ),
    })
  })
  await page.route(
    'http://localhost:8000/api/v1/memory/*/profile/preferred-name',
    route => route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Unable to save approved memory.' }),
    }),
  )

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('My name is Retry Name.')
  await sendButton.click()
  await page.getByRole('button', { name: 'Approve preferred name' }).click()

  await expect(page.getByRole('alert')).toHaveText('Unable to save approved memory.')
  await expect(page.getByLabel('Preferred name memory proposal')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve preferred name' })).toBeEnabled()
  await expect(textarea).toBeEnabled()
  await expect(sendButton).toBeDisabled()
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

test('isolates chat state and conversation identity when the active user changes', async ({ page }) => {
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
  await page.getByLabel('Active user ID').fill('different_user')
  await expect(page.getByRole('button', { name: 'Switch user' })).toBeEnabled()
  await page.getByRole('button', { name: 'Switch user' }).click()
  await expect(page.getByLabel('Active user ID')).toHaveValue('different_user')
  await page.getByRole('button', { name: 'Conversations' }).click()
  await expect(page.getByText('message for first user', { exact: true })).not.toBeVisible()

  await textarea.fill('message for second user')
  await sendButton.click()
  await expect(textarea).toBeEnabled()

  expect(requests).toHaveLength(2)
  expect(requests[0].user_id).toBe('ani.mallya')
  expect(requests[1].user_id).toBe('different_user')
  expect(requests[1].conversation_id).not.toBe(requests[0].conversation_id)
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

// Verify entity, workflow, and knowledge chat proposals never write before approval.
test('reviews structured durable memory proposals before saving', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const writes: Array<{ url: string; method: string; body: Record<string, unknown> }> = []
  const proposals = [
    {
      kind: 'entity',
      entity_type: 'person',
      canonical_name: 'Rejected Avery',
      attributes: { relationship: 'dentist' },
    },
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
  await page.route('http://localhost:8000/api/v1/memory/*/agent/**', async route => {
    writes.push({
      url: route.request().url(),
      method: route.request().method(),
      body: route.request().postDataJSON(),
    })
    await route.fulfill({
      status: route.request().method() === 'POST' ? 201 : 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: crypto.randomUUID(), chunks: [] }),
    })
  })

  await page.goto('/')
  const { textarea, sendButton } = chatControls(page)
  await textarea.fill('Reject entity proposal')
  await sendButton.click()
  await expect(page.getByLabel('Entity memory proposal')).toContainText('Rejected Avery')
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'Not now' }).click()
  expect(writes).toEqual([])

  for (const expectation of [
    ['Approve entity', 'Entity memory proposal', 'Approve person or organization'],
    ['Approve procedure', 'Procedure memory proposal', 'Approve reusable workflow'],
    ['Approve knowledge', 'Knowledge memory proposal', 'Approve reference knowledge'],
  ]) {
    await textarea.fill(expectation[0])
    await sendButton.click()
    await expect(page.getByLabel(expectation[1])).toBeVisible()
    await page.getByRole('button', { name: expectation[2] }).click()
  }

  expect(writes).toHaveLength(3)
  expect(writes.map(write => write.method)).toEqual(['PUT', 'POST', 'POST'])
  expect(writes[0].body).toMatchObject({
    canonical_name: 'Approved Avery',
    source_conversation_id: expect.any(String),
    source_trace_id: 'structured-proposal-trace',
  })
  expect(writes[1].body).toMatchObject({
    name: 'Morning launch',
    source_conversation_id: expect.any(String),
    source_trace_id: 'structured-proposal-trace',
  })
  expect(writes[2].body).toMatchObject({
    title: 'Studio reference',
    source_conversation_id: expect.any(String),
    source_trace_id: 'structured-proposal-trace',
  })
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

// Verify ordinary live chat still renders a real response through the configured model.
test('@live renders a real Gemma response through AniOS', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_gemma_${stamp}`
  const token = `LIVE_GEMMA_${stamp}`
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
    await expect(latestAssistantAnswer(page)).toBeVisible({ timeout: 120_000 })
    expect(await response.finished()).toBeNull()

    await expect(latestAssistantAnswer(page).getByText(token, { exact: false })).toBeVisible({ timeout: 120_000 })
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
    await expect(latestAssistantAnswer(page).getByText(token, { exact: false })).toBeVisible()
    expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
  } finally {
    await page.request.delete(`http://localhost:8000/api/v1/memory/${userId}`)
  }
})

// Verify image generation renders, survives navigation and reload, and deletes cleanly.
test('generates, restores, and deletes an owned image artifact', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '12121212-1212-4212-8212-121212121212'
  const prompt = 'Create deterministic cobalt origami whale'
  let conversationId = ''
  let artifact: ReturnType<typeof imageArtifactRecord> | null = null
  let releaseGeneration = () => {}
  const generationGate = new Promise<void>(resolve => { releaseGeneration = resolve })

  await page.route('http://localhost:8000/api/v1/images/generate', async route => {
    const payload = route.request().postDataJSON()
    conversationId = String(payload.conversation_id)
    artifact = imageArtifactRecord('generated_image', artifactId, conversationId, {
      seed: 42,
      steps: 28,
    })
    await generationGate
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(artifact),
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
  await page.getByRole('button', { name: 'Create image', exact: true }).click()
  const textarea = page.getByLabel('Message AniOS')
  await textarea.fill(prompt)
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/images/generate')
  await page.getByRole('button', { name: 'Generate image' }).click()
  await expect(page.getByText('Generating image...', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel visual request' })).toBeVisible()
  releaseGeneration()
  expect((await responsePromise).status()).toBe(201)

  const imageCard = page.getByLabel('Image: Generated image')
  await expect(imageCard).toBeVisible()
  await expect(imageCard.getByAltText('Generated visual result')).toBeVisible()
  await expect(page.getByText('Generating image...', { exact: true })).not.toBeVisible()
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

// Verify an uploaded image reaches the VLM and displays its grounded analysis.
test('uploads and analyzes an image with visible progress and result', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '34343434-3434-4434-8434-343434343434'
  const analysis = 'A cobalt origami whale floating above a white platform.'
  let multipartBody = ''
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

  await page.goto('/')
  await page.getByRole('button', { name: 'Analyze image', exact: true }).click()
  await page.getByLabel('Choose image').setInputFiles({
    name: 'cobalt-whale.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  })
  const textarea = page.getByLabel('Message AniOS')
  await textarea.fill('Describe the subject and color.')
  const responsePromise = page.waitForResponse('http://localhost:8000/api/v1/vision/analyze')
  await page.getByRole('button', { name: 'Analyze image' }).last().click()
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
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a provider failure is visible and the unchanged request can be retried.
test('shows an image failure, clears loading, and retries successfully', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  const artifactId = '78787878-7878-4878-8878-787878787878'
  let attempts = 0

  await page.route('http://localhost:8000/api/v1/images/generate', async route => {
    attempts += 1
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Unable to generate the image.' }),
      })
      return
    }
    const payload = route.request().postDataJSON()
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(imageArtifactRecord(
        'generated_image',
        artifactId,
        String(payload.conversation_id),
      )),
    })
  })
  await page.route(
    `http://localhost:8000/api/v1/artifacts/ani.mallya/${artifactId}/content`,
    route => route.fulfill({ status: 200, contentType: 'image/png', body: TEST_PNG }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Create image', exact: true }).click()
  const textarea = page.getByLabel('Message AniOS')
  await textarea.fill('Retry this deterministic image')
  await page.getByRole('button', { name: 'Generate image' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to generate the image.' }).first()).toBeVisible()
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('Retry this deterministic image')
  await page.getByRole('button', { name: 'Retry visual request' }).click()
  await expect(page.getByLabel('Image: Generated image')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry visual request' })).not.toBeVisible()
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
  await page.getByRole('button', { name: 'Analyze image', exact: true }).click()
  await page.getByLabel('Choose image').setInputFiles({
    name: 'invalid-contract.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  })
  const textarea = page.getByLabel('Message AniOS')
  for (const scenario of scenarios) {
    status = scenario.status
    detail = scenario.detail
    await textarea.fill(`Validate visible HTTP ${scenario.status}`)
    await page.getByRole('button', { name: 'Analyze image' }).last().click()
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

// Verify real ComfyUI generation and Gemma vision analysis through the current UI.
test('@live visual generation and analysis complete through the browser', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = observeBlockingBrowserErrors(page)
  const userId = `live_visual_${Date.now()}`
  const conversationId = '90909090-9090-4090-8090-909090909090'
  const generationPrompt = `A sapphire ceramic seahorse beside a copper sphere LIVE_UI_${Date.now()}`
  const analysisPrompt = 'Identify the animal, dominant colors, and the object beneath it.'
  const createdIds: string[] = []

  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  try {
    await page.goto('/')
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    await page.getByRole('button', { name: 'Create image', exact: true }).click()
    const textarea = page.getByLabel('Message AniOS')
    await textarea.fill(generationPrompt)
    const generationResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/images/generate',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Generate image' }).click()
    await expect(page.getByText('Generating image...', { exact: true })).toBeVisible()
    const generationResponse = await generationResponsePromise
    expect(generationResponse.status()).toBe(201)
    const generated = await generationResponse.json() as Record<string, unknown>
    createdIds.push(String(generated.id))
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

    await page.getByRole('button', { name: 'Visual artifacts' }).click()
    await expect(page.getByLabel('Image: Generated image').filter({ visible: true })).toBeVisible()
    await page.getByRole('button', { name: 'Conversations' }).click()
    await page.reload()
    await expect(page.getByText('Restoring conversation...')).not.toBeVisible()
    await expect(page.getByLabel('Image: Generated image').getByAltText('Generated visual result')).toBeVisible()

    await page.getByRole('button', { name: 'Analyze image', exact: true }).click()
    await page.getByLabel('Choose image').setInputFiles('E:\\AI\\anios-direct-ui.png')
    await textarea.fill(analysisPrompt)
    const analysisResponsePromise = page.waitForResponse(
      response => response.url() === 'http://localhost:8000/api/v1/vision/analyze',
      { timeout: 120_000 },
    )
    await page.getByRole('button', { name: 'Analyze image' }).last().click()
    await expect(page.getByText('Analyzing image...', { exact: true })).toBeVisible()
    const analysisResponse = await analysisResponsePromise
    expect(analysisResponse.status()).toBe(201)
    const analysisResult = await analysisResponse.json() as Record<string, unknown>
    const analyzed = analysisResult.artifact as Record<string, unknown>
    createdIds.push(String(analyzed.id))
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
    await expect(analyzedCard.getByText(String(metadata.analysis), { exact: true })).toBeVisible()
    await expect(page.getByText('Analyzing image...', { exact: true })).not.toBeVisible()
    await expect(textarea).toBeEnabled()

    await generatedCard.getByRole('button', { name: 'Delete' }).click()
    await analyzedCard.getByRole('button', { name: 'Delete' }).click()
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
    await page.getByRole('button', { name: 'Create image', exact: true }).click()
    const textarea = page.getByLabel('Message AniOS')
    await textarea.fill(`Cancellation probe cobalt glass compass ${Date.now()}`)
    const requestPromise = page.waitForRequest(
      request => request.url() === 'http://localhost:8000/api/v1/images/generate',
    )
    await page.getByRole('button', { name: 'Generate image' }).click()
    await requestPromise
    await expect.poll(async () => {
      const response = await page.request.get(`http://localhost:8000/api/v1/artifacts/${userId}`)
      const artifacts = await response.json() as Array<Record<string, unknown>>
      return artifacts[0]?.status
    }).toBe('pending')

    await page.getByRole('button', { name: 'Cancel visual request' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'Visual request cancelled.' }).first()).toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Cancel visual request' })).not.toBeVisible()
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

// Verify live structured proposals reject safely, persist on approval, and recall.
test('@live reviews and recalls entity procedure and knowledge memory', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(360_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `capture_live_${stamp}`
  const rejectedEntity = `RejectedPerson${stamp}`
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

  try {
    await page.goto('/')
    await sendAndWait(`Remember that ${rejectedEntity} is my dentist.`)
    await expect(page.getByLabel('Entity memory proposal')).toContainText(rejectedEntity)
    let snapshot = await page.request.get(
      `http://localhost:8000/api/v1/memory/${userId}/agent`,
    )
    expect((await snapshot.json()).entities).toBe(0)
    await page.getByRole('button', { name: 'Not now' }).click()
    snapshot = await page.request.get(
      `http://localhost:8000/api/v1/memory/${userId}/agent`,
    )
    expect((await snapshot.json()).entities).toBe(0)

    await sendAndWait(`Remember that ${entity} is my dentist.`)
    const entityApproval = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/agent/entities`) &&
      response.request().method() === 'PUT',
    )
    await page.getByRole('button', { name: 'Approve person or organization' }).click()
    expect((await entityApproval).status()).toBe(200)

    await sendAndWait(
      `Remember this workflow: Morning ${stamp}. Steps: ` +
      `open ${procedureCode}; verify ${procedureCode}.`,
    )
    const procedureApproval = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/agent/procedures`) &&
      response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Approve reusable workflow' }).click()
    expect((await procedureApproval).status()).toBe(201)

    await sendAndWait(
      `Remember this reference: Studio ${stamp} | ` +
      `The reference code is ${knowledgeCode}.`,
    )
    const knowledgeApproval = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/agent/knowledge`) &&
      response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Approve reference knowledge' }).click()
    expect((await knowledgeApproval).status()).toBe(201)

    snapshot = await page.request.get(
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

test('@live approves a response-style proposal through chat', async ({ page }) => {
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
    await expect(page.getByLabel('Response style memory proposal')).toContainText(
      'concise',
      { timeout: 120_000 },
    )
    const approvalResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/facts`) &&
      response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Approve response style' }).click()
    expect((await approvalResponse).status()).toBe(201)
    await expect(page.getByText('Saved response style: concise')).toBeVisible()

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

test('@live approves, corrects, recalls, rejects, and deletes a preferred name', async ({ page }) => {
  test.skip(process.env.ANIOS_E2E_LIVE !== '1', 'Set ANIOS_E2E_LIVE=1 to contact the configured live provider')
  test.setTimeout(240_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `pname_live_${stamp}`
  const otherUser = `pname_other_${stamp}`
  const rejectedName = `Rejected${stamp}`
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
    await sendAndWait(`My name is ${rejectedName}.`)
    await expect(page.getByLabel('Preferred name memory proposal')).toContainText(rejectedName)
    const beforeReject = await page.request.get(`http://localhost:8000/api/v1/memory/${userId}`)
    expect((await beforeReject.json()).profile.name).toBeUndefined()
    await page.getByRole('button', { name: 'Not now' }).click()
    const afterReject = await page.request.get(`http://localhost:8000/api/v1/memory/${userId}`)
    expect((await afterReject.json()).profile.name).toBeUndefined()

    await sendAndWait(`My name is ${approvedName}.`)
    const approvalResponse = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/memory/${userId}/profile/preferred-name`) &&
      response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Approve preferred name' }).click()
    expect((await approvalResponse).status()).toBe(200)
    await expect(page.getByText(`Saved preferred name: ${approvedName}`)).toBeVisible()
    const otherSnapshot = await page.request.get(`http://localhost:8000/api/v1/memory/${otherUser}`)
    expect((await otherSnapshot.json()).profile.name).toBeUndefined()

    await page.getByRole('button', { name: 'New conversation' }).click()
    await sendAndWait('What is my preferred name? Reply with only the name.')
    await expect(latestAssistantAnswer(page).getByText(approvedName, { exact: false })).toBeVisible({ timeout: 120_000 })

    await sendAndWait(`My preferred name is ${correctedName}.`)
    await expect(page.getByLabel('Preferred name memory proposal')).toContainText(correctedName)
    await page.getByRole('button', { name: 'Approve preferred name' }).click()
    await expect(page.getByText(`Saved preferred name: ${correctedName}`)).toBeVisible()

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
