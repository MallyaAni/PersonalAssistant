import { expect, test, type Page } from '@playwright/test'

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

function chatEventStream(
  traceId: string,
  conversationId: string,
  response: string,
  preferredName?: string,
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
  }
  frames.push(
    'event: done',
    'data: {}',
    '',
    '',
  )
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
  await expect(textarea).toHaveValue('')
  await expect(sendButton).toBeDisabled()
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
          schema_version: 1,
          exported_at: '2026-07-16T00:00:00Z',
          user_id: 'ani.mallya',
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
    await expect(latestAssistantAnswer(page)).toBeVisible()
    await expect(textarea).toBeDisabled()
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
