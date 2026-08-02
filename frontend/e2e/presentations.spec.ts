import { expect, test, type Page, type Route } from '@playwright/test'

// Give deterministic presentation tests the authenticated primary identity.
test.beforeEach(async ({ page }, testInfo) => {
  if (testInfo.title.includes('@live')) return
  await page.route('http://localhost:8000/api/v1/auth/session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      authentication_required: true,
      user_id: 'ani.mallya',
      expires_at: '2026-08-09T00:00:00Z',
    }),
  }))
})

// Capture browser exceptions and console errors that block the acceptance path.
const observeBlockingBrowserErrors = (page: Page) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  return { consoleErrors, pageErrors }
}

// Build one native editable two-slide deck for deterministic browser rendering.
const deckSpec = (revised = false) => ({
  schema_version: 1,
  title: 'Browser presentation',
  subtitle: 'Editable acceptance',
  theme: {
    font_face: 'Aptos',
    background_color: 'F5F5F7',
    primary_color: '0071E3',
    text_color: '1D1D1F',
    muted_color: '6E6E73',
  },
  slides: [
    {
      slide_id: 'slide-a',
      title: 'Opening',
      purpose: 'Introduce',
      background_color: null,
      notes: 'Opening notes',
      elements: [{
        element_id: 'title-a',
        type: 'text',
        text: 'Editable opening',
        x: 1,
        y: 1,
        w: 6,
        h: 1,
        font_size: 36,
        bold: true,
        color: null,
        align: 'left',
        valign: 'top',
        bullet: false,
      }],
    },
    {
      slide_id: 'slide-b',
      title: revised ? 'Revised evidence' : 'Evidence',
      purpose: 'Show data',
      background_color: null,
      notes: revised ? 'Revised notes' : 'Evidence notes',
      elements: [{
        element_id: 'chart-b',
        type: 'chart',
        chart_type: 'column',
        categories: ['Chat', 'Memory'],
        series: [{ name: 'Readiness', values: revised ? [95, 90] : [90, 85] }],
        show_legend: false,
        show_title: true,
        title: revised ? 'Updated readiness' : 'Readiness',
        x: 1,
        y: 1.2,
        w: 7,
        h: 4.5,
      }],
    },
  ],
})

// Add one declared and optionally completed visual to a progress draft.
const progressDeckSpec = (withImage = false) => {
  const specification = structuredClone(deckSpec())
  return {
    ...specification,
    slides: specification.slides.map((slide, index) => (
      index === 1
        ? {
            ...slide,
            visual_prompt: 'A decisive evidence photograph',
            visual_priority: 3,
            elements: withImage
              ? [
                  ...slide.elements,
                  {
                    element_id: 'progress-image',
                    type: 'image',
                    artifact_id: '44444444-4444-4444-8444-444444444444',
                    alt_text: 'A decisive evidence photograph',
                    x: 8.45,
                    y: 1.65,
                    w: 4.15,
                    h: 4.65,
                  },
                ]
              : slide.elements,
          }
        : slide
    )),
  }
}

// Build one ready presentation record with linked revision history.
const presentationRecord = (revised = false) => {
  const currentId = revised
    ? '22222222-2222-4222-8222-222222222222'
    : '11111111-1111-4111-8111-111111111111'
  const currentNumber = revised ? 2 : 1
  const revisions = [
    {
      id: currentId,
      presentation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      parent_revision_id: revised
        ? '11111111-1111-4111-8111-111111111111'
        : null,
      revision_number: currentNumber,
      status: 'ready',
      target_slide_id: revised ? 'slide-b' : null,
      change_summary: revised ? 'Make the evidence clearer' : 'Initial presentation',
      provider: 'lm_studio',
      model: 'google/gemma-4-12b',
      renderer: 'pptxgenjs',
      renderer_version: '4.0.1',
      content_available: true,
      byte_size: 42_000,
      sha256: 'a'.repeat(64),
      error_code: null,
      created_at: '2026-07-24T00:00:00Z',
      completed_at: '2026-07-24T00:00:01Z',
    },
  ]
  if (revised) {
    revisions.push({
      ...revisions[0],
      id: '11111111-1111-4111-8111-111111111111',
      parent_revision_id: null,
      revision_number: 1,
      target_slide_id: null,
      change_summary: 'Initial presentation',
    })
  }
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    user_id: 'ani.mallya',
    conversation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    trace_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    title: 'Browser presentation',
    current_revision_id: currentId,
    current_revision: {
      ...revisions[0],
      specification: deckSpec(revised),
    },
    revisions,
    created_at: '2026-07-24T00:00:00Z',
    updated_at: '2026-07-24T00:00:01Z',
  }
}

// Build one terminal failed deck that has metadata but no completed slides.
const failedPresentationRecord = (includeRevision = true) => {
  const revision = {
    id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    presentation_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    parent_revision_id: null,
    revision_number: 1,
    status: 'failed',
    target_slide_id: null,
    change_summary: 'Initial presentation',
    provider: 'lm_studio',
    model: 'google/gemma-4-12b',
    renderer: null,
    renderer_version: null,
    content_available: false,
    byte_size: null,
    sha256: null,
    error_code: 'generation_failed',
    created_at: '2026-07-24T00:00:00Z',
    completed_at: '2026-07-24T00:00:01Z',
    specification: null,
  }
  return {
    id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    user_id: 'ani.mallya',
    conversation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    trace_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    title: 'Untitled presentation',
    current_revision_id: null,
    current_revision: null,
    revisions: includeRevision ? [revision] : [],
    created_at: '2026-07-24T00:00:00Z',
    updated_at: '2026-07-24T00:00:01Z',
  }
}

// Build one reconnectable background-job response at a requested lifecycle state.
const presentationJob = (
  status: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled',
  draft: ReturnType<typeof deckSpec> | null = null,
) => ({
  id: '99999999-9999-4999-8999-999999999999',
  presentation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  revision_id: '11111111-1111-4111-8111-111111111111',
  user_id: 'ani.mallya',
  status,
  expected_slide_count: 2,
  auto_image_max: 2,
  attempt_count: status === 'queued' ? 0 : 1,
  cancel_requested: false,
  error_code: status === 'failed' ? 'generation_failed' : null,
  draft_specification: draft,
  presentation: status === 'ready' ? presentationRecord() : null,
  created_at: '2026-07-26T00:00:00Z',
  started_at: status === 'queued' ? null : '2026-07-26T00:00:01Z',
  updated_at: '2026-07-26T00:00:02Z',
  completed_at: status === 'ready' ? '2026-07-26T00:00:03Z' : null,
})

// Add one ready local-image revision to the deterministic selected slide.
const imagePresentationRecord = () => {
  const base = presentationRecord(true)
  const imageRevision = {
    ...base.revisions[0],
    id: '33333333-3333-4333-8333-333333333333',
    parent_revision_id: base.current_revision_id,
    revision_number: 3,
    change_summary: 'Generated a local image for Revised evidence',
  }
  const specification = structuredClone(base.current_revision.specification)
  specification.slides[1].elements.push({
    element_id: 'slide-b-image',
    type: 'image',
    artifact_id: '44444444-4444-4444-8444-444444444444',
    alt_text: 'A horse beside an editable chart',
    x: 8.45,
    y: 1.65,
    w: 4.15,
    h: 4.65,
  })
  return {
    ...base,
    current_revision_id: imageRevision.id,
    current_revision: {
      ...imageRevision,
      specification,
    },
    revisions: [imageRevision, ...base.revisions],
  }
}

// Add a source-conditioned FLUX child as the next selected-slide revision.
const refinedImagePresentationRecord = () => {
  const base = imagePresentationRecord()
  const refinementRevision = {
    ...base.revisions[0],
    id: '55555555-5555-4555-8555-555555555555',
    parent_revision_id: base.current_revision_id,
    revision_number: 4,
    change_summary: 'Refined the local image for Revised evidence: Make only the horse chestnut brown',
  }
  const specification = structuredClone(base.current_revision.specification)
  const image = specification.slides[1].elements.find(
    element => element.type === 'image',
  )
  if (image?.type === 'image') {
    image.artifact_id = '66666666-6666-4666-8666-666666666666'
    image.alt_text = 'A horse beside an editable chart. Refined: Make only the horse chestnut brown'
  }
  return {
    ...base,
    current_revision_id: refinementRevision.id,
    current_revision: {
      ...refinementRevision,
      specification,
    },
    revisions: [refinementRevision, ...base.revisions],
  }
}

// Fulfill one JSON route with the supplied status and body.
const fulfillJson = (
  route: Route,
  body: unknown,
  status = 200,
) => route.fulfill({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

// Build one complete deterministic chat stream for cross-tab concurrency.
const chatEventStream = (conversationId: string, response: string) => [
  'event: start',
  `data: ${JSON.stringify({
    trace_id: '77777777-7777-4777-8777-777777777777',
    conversation_id: conversationId,
  })}`,
  '',
  'event: delta',
  `data: ${JSON.stringify({ content: response })}`,
  '',
  'event: done',
  'data: {}',
  '',
  '',
].join('\n')

// Verify a failed empty deck explains its state and can be deleted in the browser.
test('deletes a failed presentation without completed slides', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let deleted = false

  await page.route('**/api/v1/presentations**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (
      request.method() === 'DELETE'
      && url.pathname.endsWith('/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')
    ) {
      deleted = true
      await route.fulfill({ status: 204 })
      return
    }
    if (
      request.method() === 'GET'
      && url.pathname === '/api/v1/presentations/ani.mallya'
    ) {
      await fulfillJson(route, deleted ? [] : [failedPresentationRecord()])
      return
    }
    if (
      request.method() === 'GET'
      && url.pathname.endsWith('/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')
    ) {
      await fulfillJson(route, failedPresentationRecord())
      return
    }
    await fulfillJson(route, {}, 404)
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByText('Failed · no completed slides')).toBeVisible()
  await expect(page.getByText(
    'This presentation failed before any slides were completed.',
  )).toBeVisible()
  await expect(page.getByRole('button', {
    name: 'Delete presentation: Untitled presentation',
  })).toBeVisible()

  page.once('dialog', dialog => dialog.accept())
  const deletion = page.waitForResponse(response => (
    response.request().method() === 'DELETE'
    && response.url().endsWith('/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee')
  ))
  await page.getByRole('button', {
    name: 'Delete all 1 failed presentations',
  }).click()
  expect((await deletion).status()).toBe(204)
  await expect(page.getByText('No presentations yet.')).toBeVisible()
  expect(deleted).toBe(true)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify create, select, revise, persist-visible, and download interactions.
test('creates and revises an editable presentation in the browser', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let created = false
  let revised = false
  let imageOperations = 0
  let jobPolls = 0
  const requests: Array<{ method: string; url: string; body: unknown }> = []

  await page.route('**/api/v1/presentations**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const body = request.postDataJSON() as unknown
    requests.push({ method: request.method(), url: url.pathname, body })

    if (request.method() === 'POST' && url.pathname === '/api/v1/presentations') {
      created = true
      await fulfillJson(route, presentationJob('queued'), 202)
      return
    }
    if (request.method() === 'GET' && url.pathname.includes('/presentations/jobs/')) {
      jobPolls += 1
      if (jobPolls === 1) {
        await new Promise(resolve => setTimeout(resolve, 250))
        await fulfillJson(route, presentationJob('running', {
          ...deckSpec(),
          slides: deckSpec().slides.slice(0, 1),
        }))
      } else if (jobPolls === 2) {
        await fulfillJson(route, presentationJob('running', progressDeckSpec()))
      } else if (jobPolls === 3) {
        await fulfillJson(
          route,
          presentationJob('running', progressDeckSpec(true)),
        )
      } else {
        await fulfillJson(route, presentationJob('ready', deckSpec()))
      }
      return
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/slides/slide-b/revisions')) {
      await new Promise(resolve => setTimeout(resolve, 100))
      revised = true
      await fulfillJson(route, presentationRecord(true))
      return
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/slides/slide-b/image')) {
      await new Promise(resolve => setTimeout(resolve, 100))
      imageOperations += 1
      await fulfillJson(
        route,
        imageOperations > 1
          ? refinedImagePresentationRecord()
          : imagePresentationRecord(),
        201,
      )
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/content')) {
      await route.fulfill({
        status: 200,
        headers: {
          'content-type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          'content-disposition': 'attachment; filename="browser-presentation-r2.pptx"',
          'access-control-expose-headers': 'Content-Disposition',
        },
        body: Buffer.from('PK mock editable presentation'),
      })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/presentations/ani.mallya') {
      await fulfillJson(
        route,
        created
          ? [imageOperations > 1
              ? refinedImagePresentationRecord()
              : imageOperations === 1
                ? imagePresentationRecord()
                : presentationRecord(revised)]
          : [],
      )
      return
    }
    if (request.method() === 'GET') {
      await fulfillJson(
        route,
        imageOperations > 1
          ? refinedImagePresentationRecord()
          : imageOperations === 1
            ? imagePresentationRecord()
            : presentationRecord(revised),
      )
      return
    }
    await fulfillJson(route, {}, 404)
  })
  await page.route('**/api/v1/artifacts/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=',
        'base64',
      ),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByRole('heading', { name: 'Presentations' })).toBeVisible()
  await expect(page.getByText('No presentations yet.')).toBeVisible()

  await page.getByLabel('Create a new deck').fill(
    'Create a two-slide editable browser acceptance presentation.',
  )
  await page.getByRole('button', { name: 'Create presentation' }).click()
  await expect(page.getByText('Using PresentationAgent…')).toBeVisible()
  const progress = page.getByRole('progressbar', {
    name: 'Presentation completion',
  })
  await expect(progress).toHaveAttribute('aria-valuenow', '8')
  await expect(progress).toHaveAttribute(
    'aria-valuetext',
    'Planning the deck outline',
  )
  await expect(progress).toHaveAttribute('aria-valuenow', '37')
  await expect(progress).toHaveAttribute(
    'aria-valuetext',
    'Planning slide 2 of 2',
  )
  await expect(progress).toHaveAttribute('aria-valuenow', '65')
  await expect(progress).toHaveAttribute(
    'aria-valuetext',
    'Generating visual 1 of 1',
  )
  await expect(progress).toHaveAttribute('aria-valuenow', '92')
  await expect(progress).toHaveAttribute(
    'aria-valuetext',
    'Rendering and validating the editable PowerPoint',
  )
  await expect(page.getByText('Browser presentation', { exact: true }).first()).toBeVisible()
  await expect(page.getByLabel('Slide preview: Opening').first()).toBeVisible()

  await page.getByRole('button', { name: 'Select slide 2: Evidence' }).click()
  await page.getByRole('textbox', { name: 'Slide feedback' }).fill(
    'Make the evidence clearer',
  )
  await page.getByRole('button', { name: 'Apply slide feedback' }).click()
  await expect(page.getByText('PresentationAgent is revising…')).toBeVisible()
  await expect(page.getByText('Slide revised as revision 2.')).toBeVisible()
  await expect(page.getByText('Revised evidence', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('Revision 2', { exact: true }).first()).toBeVisible()
  const followup = page.getByRole('region', {
    name: 'Follow-up conversation for Revised evidence',
  })
  await expect(followup.getByText('Make the evidence clearer', { exact: true })).toBeVisible()
  await expect(followup.getByText(
    'Applied in revision 2. This slide changed; all other slides were preserved.',
    { exact: true },
  )).toBeVisible()
  await page.getByRole('button', { name: 'Select slide 1: Opening' }).click()
  await expect(page.getByRole('region', {
    name: 'Follow-up conversation for Opening',
  }).getByText('No suggestions for this slide yet.')).toBeVisible()
  await page.getByRole('button', { name: 'Select slide 2: Revised evidence' }).click()

  await page.getByRole('textbox', { name: 'Slide image prompt' }).fill(
    'A horse beside an editable chart',
  )
  await page.getByRole('button', { name: 'Generate slide image' }).click()
  await expect(page.getByText('Generating with HiDream…')).toBeVisible()
  await expect(page.getByText('Local image added in revision 3.')).toBeVisible()
  await expect(page.getByRole('img', {
    name: 'A horse beside an editable chart',
  }).first()).toBeVisible()

  await page.getByRole('textbox', { name: 'Slide image prompt' }).fill(
    'Make only the horse chestnut brown',
  )
  await page.getByRole('button', { name: 'Refine slide image' }).click()
  await expect(page.getByText('Refining with FLUX…')).toBeVisible()
  await expect(page.getByText('Slide image refined with FLUX in revision 4.')).toBeVisible()
  await expect(page.getByRole('img', {
    name: 'A horse beside an editable chart. Refined: Make only the horse chestnut brown',
  }).first()).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download editable PowerPoint' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('browser-presentation-r2.pptx')

  expect(requests.some(request => request.method === 'POST'
    && request.url === '/api/v1/presentations')).toBe(true)
  const revisionRequest = requests.find(request => request.url.endsWith('/slides/slide-b/revisions'))
  expect(revisionRequest?.body).toMatchObject({
    base_revision_id: '11111111-1111-4111-8111-111111111111',
    feedback: 'Make the evidence clearer',
  })
  const imageRequests = requests.filter(request => request.url.endsWith('/slides/slide-b/image'))
  expect(imageRequests[0]?.body).toMatchObject({
    base_revision_id: '22222222-2222-4222-8222-222222222222',
    prompt: 'A horse beside an editable chart',
  })
  expect(imageRequests[1]?.body).toMatchObject({
    base_revision_id: '33333333-3333-4333-8333-333333333333',
    prompt: 'Make only the horse chestnut brown',
  })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify a durable deck continues while Conversations completes another turn.
test('keeps chat responsive while a presentation job runs in the background', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let queuedAt = 0
  let chatRequests = 0
  let jobRequests = 0

  await page.route('**/api/v1/presentations**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'POST' && url.pathname === '/api/v1/presentations') {
      queuedAt = Date.now()
      await fulfillJson(route, presentationJob('queued'), 202)
      return
    }
    if (request.method() === 'GET' && url.pathname.includes('/presentations/jobs/')) {
      jobRequests += 1
      const elapsed = Date.now() - queuedAt
      await fulfillJson(
        route,
        elapsed >= 1_800
          ? presentationJob('ready', deckSpec())
          : presentationJob('running', {
            ...deckSpec(),
            slides: deckSpec().slides.slice(0, 1),
          }),
      )
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/presentations/ani.mallya') {
      await fulfillJson(
        route,
        queuedAt > 0 && Date.now() - queuedAt >= 1_800
          ? [presentationRecord()]
          : [],
      )
      return
    }
    if (request.method() === 'GET') {
      await fulfillJson(route, presentationRecord())
      return
    }
    await fulfillJson(route, {}, 404)
  })
  await page.route('http://localhost:8000/api/v1/chat', async route => {
    chatRequests += 1
    const payload = route.request().postDataJSON() as { conversation_id: string }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatEventStream(
        payload.conversation_id,
        'CHAT_COMPLETED_WHILE_DECK_RUNNING',
      ),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await page.getByLabel('Create a new deck').fill(
    'Create a two-slide background presentation.',
  )
  await page.getByRole('button', { name: 'Create presentation' }).click()
  await expect(page.getByText('Using PresentationAgent…')).toBeVisible()
  await expect(page.getByText(
    'PresentationAgent is working in the background. You can continue chatting.',
  )).toBeVisible()

  await page.getByRole('button', { name: 'Conversations' }).click()
  const textarea = page.getByLabel('Message AniOS')
  await textarea.fill('UNIQUE_CHAT_DURING_PRESENTATION')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByLabel('AniOS answer').last()).toContainText(
    'CHAT_COMPLETED_WHILE_DECK_RUNNING',
  )

  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByText(
    'Presentation ready. Every supported slide object is editable in PowerPoint.',
  )).toBeVisible({
    timeout: 5_000,
  })
  await expect(page.getByRole('button', {
    name: 'Download editable PowerPoint',
  })).toBeVisible()
  const storedJob = await page.evaluate(() => (
    localStorage.getItem('anios_presentation_job:ani.mallya')
  ))
  expect(storedJob).toBeNull()
  expect(chatRequests).toBe(1)
  expect(jobRequests).toBeGreaterThan(0)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify live background creation, chat concurrency, and source-refined slide imagery.
test('@live creates a deck in the background without blocking chat', async ({ page }) => {
  test.skip(
    process.env.ANIOS_E2E_LIVE !== '1',
    'Set ANIOS_E2E_LIVE=1 to exercise the live presentation worker.',
  )
  test.setTimeout(540_000)

  const errors = observeBlockingBrowserErrors(page)
  const failedRequests: string[] = []
  page.on('requestfailed', request => {
    const url = new URL(request.url())
    if (
      request.method() === 'POST'
      || url.pathname.includes('/presentations/jobs/')
    ) {
      failedRequests.push(`${request.method()} ${request.url()}`)
    }
  })
  const stamp = Date.now()
  const userId = `live_presentation_bg_${stamp}`
  const conversationId = '46464646-4646-4646-8646-464646464646'
  const marker = `background-reference-${stamp}`
  // Start the live browser with isolated ownership and conversation state.
  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await page.getByLabel('Create a new deck').fill(
    `Create exactly 2 slides about durable agent jobs. Include the exact text ${marker} in the deck and use strong visual storytelling.`,
  )
  const queuedResponse = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/presentations'
      && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Create presentation' }).click()
  const queued = await queuedResponse
  expect(queued.status()).toBe(202)
  const job = await queued.json() as { id: string; presentation_id: string }
  await expect(page.getByText(
    'PresentationAgent is working in the background. You can continue chatting.',
  )).toBeVisible()

  await page.getByRole('button', { name: 'Conversations' }).click()
  const textarea = page.getByLabel('Message AniOS')
  await textarea.fill(
    `Confirm in one sentence that chat remains responsive during deck creation, and include reference ${marker}.`,
  )
  const chatResponse = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/chat'
      && response.request().method() === 'POST',
    { timeout: 120_000 },
  )
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await chatResponse).status()).toBe(200)
  await expect(page.getByLabel('AniOS answer').last()).toContainText(marker, {
    timeout: 120_000,
  })
  await expect(textarea).toBeEnabled()
  await expect(textarea).toHaveValue('')
  await expect(page.getByLabel('AniOS is thinking')).toHaveCount(0)

  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByText(
    'Presentation ready. Every supported slide object is editable in PowerPoint.',
  )).toBeVisible({ timeout: 300_000 })
  await expect(page.getByRole('button', {
    name: 'Download editable PowerPoint',
  })).toBeVisible()

  const terminalResponse = await page.request.get(
    `http://localhost:8000/api/v1/presentations/jobs/${userId}/${job.id}`,
  )
  expect(terminalResponse.status()).toBe(200)
  const terminal = await terminalResponse.json()
  expect(terminal.status).toBe('ready')
  expect(terminal.presentation.current_revision.status).toBe('ready')
  expect(terminal.presentation.current_revision.specification.slides).toHaveLength(2)
  expect(terminal.presentation.current_revision.renderer).toBe(
    'pptxgenjs+libreoffice',
  )
  expect(terminal.presentation.current_revision.content_available).toBe(true)
  expect(failedRequests).toEqual([])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })

  const readySlides = terminal.presentation.current_revision.specification.slides
  const imageSlides = readySlides.filter((slide: {
    elements: Array<{ type: string }>;
  }) => slide.elements.some(element => element.type === 'image'))
  expect(imageSlides.length).toBeGreaterThan(0)
  const imageSlide = imageSlides[0]
  const slideIndex = readySlides.findIndex(
    (slide: { slide_id: string }) => slide.slide_id === imageSlide.slide_id,
  )
  const slideId = String(imageSlide.slide_id)
  const initialImage = imageSlide.elements.find(
    (element: { type: string }) => element.type === 'image',
  )
  const initialArtifactId = String(initialImage.artifact_id)
  await page.getByRole('button', {
    name: `Select slide ${slideIndex + 1}: ${imageSlide.title}`,
  }).click()
  await expect(page.getByRole('img', {
    name: String(initialImage.alt_text),
  }).first()).toBeVisible()
  const selectedPreview = page.getByLabel(
    `Slide preview: ${imageSlide.title}`,
  ).first().locator('img')
  const initialPreviewUrl = await selectedPreview.getAttribute('src')
  await expect(page.getByRole('button', { name: 'Refine slide image' })).toBeVisible()

  const imageFeedback = 'Make only the main subject emerald green'
  await page.getByRole('textbox', { name: 'Slide image prompt' }).fill(imageFeedback)
  const refinementResponsePromise = page.waitForResponse(
    response => response.url().endsWith(`/slides/${slideId}/image`)
      && response.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await page.getByRole('button', { name: 'Refine slide image' }).click()
  await expect(page.getByText('Refining with FLUX…')).toBeVisible()
  const refinementResponse = await refinementResponsePromise
  expect(refinementResponse.status()).toBe(201)
  const refinedPresentation = await refinementResponse.json() as ReturnType<
    typeof presentationRecord
  >
  const refinedImage = refinedPresentation.current_revision.specification.slides[0]
    .elements.find(element => element.type === 'image')
  expect(refinedImage?.type).toBe('image')
  const refinedArtifactId = refinedImage?.type === 'image'
    ? refinedImage.artifact_id
    : ''
  expect(refinedArtifactId).not.toBe(initialArtifactId)
  await expect(page.getByText(
    `Slide image refined with FLUX in revision ${refinedPresentation.current_revision.revision_number}.`,
  )).toBeVisible()
  await expect(selectedPreview).toBeVisible()
  await expect.poll(
    async () => selectedPreview.getAttribute('src'),
  ).not.toBe(initialPreviewUrl)

  const artifactResponse = await page.request.get(
    `http://localhost:8000/api/v1/artifacts/${userId}`,
  )
  expect(artifactResponse.status()).toBe(200)
  const artifacts = await artifactResponse.json() as Array<Record<string, unknown>>
  const initialArtifact = artifacts.find(artifact => artifact.id === initialArtifactId)
  expect(initialArtifact).toMatchObject({
    kind: 'generated_image',
    status: 'ready',
    model: 'hidream_o1_image_dev_fp8_scaled.safetensors',
    metadata: {
      presentation_id: job.presentation_id,
      slide_id: slideId,
      presentation_auto_generated: true,
    },
  })
  const refinedArtifact = artifacts.find(artifact => artifact.id === refinedArtifactId)
  expect(refinedArtifact).toMatchObject({
    kind: 'generated_image',
    status: 'ready',
    model: 'flux-2-klein-4b-fp8.safetensors',
    metadata: {
      parent_artifact_id: initialArtifactId,
      refinement_feedback: imageFeedback,
      edit_mode: 'source_conditioned',
      steps: 4,
    },
  })
  const download = await page.request.get(
    `http://localhost:8000/api/v1/presentations/${userId}/${job.presentation_id}/revisions/${refinedPresentation.current_revision_id}/content`,
  )
  expect(download.status()).toBe(200)
  expect(download.headers()['content-type']).toContain(
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  )
  expect((await download.body()).length).toBeGreaterThan(10_000)

  const cleanup = await page.request.delete(
    `http://localhost:8000/api/v1/presentations/${userId}/${job.presentation_id}`,
  )
  expect(cleanup.status()).toBe(204)
  const automaticArtifactIds = imageSlides.map((slide: {
    elements: Array<{ type: string; artifact_id?: string }>;
  }) => slide.elements.find(element => element.type === 'image')?.artifact_id)
    .filter((artifactId: string | undefined): artifactId is string => Boolean(artifactId))
  for (const artifactId of automaticArtifactIds) {
    expect((await page.request.delete(
      `http://localhost:8000/api/v1/artifacts/${userId}/${artifactId}`,
    )).status()).toBe(200)
  }
  expect((await page.request.delete(
    `http://localhost:8000/api/v1/artifacts/${userId}/${refinedArtifactId}`,
  )).status()).toBe(200)
})

// Verify a real cancelled job has a useful title and can be removed from the UI.
test('@live deletes a cancelled presentation without completed slides', async ({ page }) => {
  test.skip(
    process.env.ANIOS_E2E_LIVE !== '1',
    'Set ANIOS_E2E_LIVE=1 to exercise live failed-deck cleanup.',
  )
  test.setTimeout(60_000)

  const errors = observeBlockingBrowserErrors(page)
  const stamp = Date.now()
  const userId = `live_presentation_delete_${stamp}`
  const conversationId = '57575757-5757-4757-8757-575757575757'
  const prompt = `Disposable presentation cleanup ${stamp}`
  const createResponse = await page.request.post(
    'http://localhost:8000/api/v1/presentations',
    {
      data: {
        user_id: userId,
        conversation_id: conversationId,
        prompt,
      },
    },
  )
  expect(createResponse.status()).toBe(202)
  const job = await createResponse.json() as {
    id: string;
    presentation_id: string;
  }
  const cancellation = await page.request.delete(
    `http://localhost:8000/api/v1/presentations/jobs/${userId}/${job.id}`,
  )
  expect(cancellation.status()).toBe(204)
  await expect.poll(async () => {
    const response = await page.request.get(
      `http://localhost:8000/api/v1/presentations/jobs/${userId}/${job.id}`,
    )
    return (await response.json()).status
  }).toBe('cancelled')

  // Open the presentation library as the isolated owner of the cancelled job.
  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })
  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByText(prompt, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Failed · no completed slides')).toBeVisible()
  await expect(page.getByText(
    'This presentation failed before any slides were completed.',
  )).toBeVisible()

  page.once('dialog', dialog => dialog.accept())
  const deletion = page.waitForResponse(response => (
    response.request().method() === 'DELETE'
    && response.url().endsWith(`/${job.presentation_id}`)
  ))
  await page.getByRole('button', {
    name: 'Delete all 1 failed presentations',
  }).click()
  expect((await deletion).status()).toBe(204)
  await expect(page.getByText('No presentations yet.')).toBeVisible()
  expect((await page.request.get(
    `http://localhost:8000/api/v1/presentations/${userId}/${job.presentation_id}`,
  )).status()).toBe(404)
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})

// Verify the browser cancels a real running specialist job at a safe checkpoint.
test('@live cancels an in-flight presentation job', async ({ page }) => {
  test.skip(
    process.env.ANIOS_E2E_LIVE !== '1',
    'Set ANIOS_E2E_LIVE=1 to exercise live worker cancellation.',
  )
  test.setTimeout(180_000)

  const errors = observeBlockingBrowserErrors(page)
  const failedRequests: string[] = []
  const successfulNoContentRequests = new Set<string>()
  // Record no-content responses that Chromium may also report as aborted body reads.
  page.on('response', response => {
    if (response.status() === 204) {
      successfulNoContentRequests.add(
        `${response.request().method()} ${response.url()}`,
      )
    }
  })
  page.on('requestfailed', request => {
    if (
      request.method() === 'POST'
      || request.url().includes('/presentations/jobs/')
    ) {
      failedRequests.push(`${request.method()} ${request.url()}`)
    }
  })
  const stamp = Date.now()
  const userId = `live_presentation_cancel_${stamp}`
  const conversationId = '47474747-4747-4747-8747-474747474747'
  // Start the cancellation browser with isolated ownership and job state.
  await page.addInitScript(({ user, conversation }) => {
    localStorage.setItem('anios_user_id', user)
    localStorage.setItem('anios_conversation_id', conversation)
  }, { user: userId, conversation: conversationId })

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await page.getByLabel('Create a new deck').fill(
    `Create exactly 6 slides about browser cancellation ${Date.now()}.`,
  )
  const queuedResponse = page.waitForResponse(
    response => response.url() === 'http://localhost:8000/api/v1/presentations'
      && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Create presentation' }).click()
  const queued = await queuedResponse
  expect(queued.status()).toBe(202)
  const job = await queued.json() as { id: string; presentation_id: string }
  await expect(page.getByRole('button', {
    name: 'Cancel presentation',
  })).toBeVisible()
  const jobStatusUrl = (
    `http://localhost:8000/api/v1/presentations/jobs/${userId}/${job.id}`
  )
  // Wait until a real worker owns the job before exercising browser cancellation.
  await expect.poll(
    // Read the persisted worker state without changing the browser workflow.
    async () => {
      const response = await page.request.get(jobStatusUrl)
      expect(response.status()).toBe(200)
      return (await response.json() as { status: string }).status
    },
    { timeout: 60_000 },
  ).toBe('running')

  const cancelResponse = page.waitForResponse(
    response => response.url().endsWith(`/jobs/${userId}/${job.id}`)
      && response.request().method() === 'DELETE',
  )
  await page.getByRole('button', { name: 'Cancel presentation' }).click()
  expect((await cancelResponse).status()).toBe(204)
  await expect(page.getByText(
    'Cancellation requested. The worker will stop at the next safe checkpoint.',
  )).toBeVisible()
  await expect(page.getByText(
    'Presentation creation was cancelled.',
  )).toBeVisible({ timeout: 120_000 })

  const terminalResponse = await page.request.get(
    jobStatusUrl,
  )
  expect(terminalResponse.status()).toBe(200)
  const terminal = await terminalResponse.json()
  expect(terminal.status).toBe('cancelled')
  expect(terminal.cancel_requested).toBe(true)
  expect(terminal.error_code).toBe('cancelled')
  expect(terminal.presentation).toBeNull()
  expect(await page.evaluate(() => (
    localStorage.getItem(`anios_presentation_job:${localStorage.getItem('anios_user_id')}`)
  ))).toBeNull()
  const unresolvedFailedRequests: string[] = []
  for (const request of failedRequests) {
    if (!successfulNoContentRequests.has(request)) {
      unresolvedFailedRequests.push(request)
    }
  }
  expect(unresolvedFailedRequests).toEqual([])
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })

  const cleanup = await page.request.delete(
    `http://localhost:8000/api/v1/presentations/${userId}/${job.presentation_id}`,
  )
  expect(cleanup.status()).toBe(204)
})

// Verify the browser revises a real persisted deck through the configured local model.
test('@live revises and downloads a persisted presentation', async ({ page }) => {
  test.skip(
    process.env.ANIOS_E2E_LIVE !== '1' || !process.env.ANIOS_PRESENTATION_ID,
    'Set ANIOS_E2E_LIVE=1 and ANIOS_PRESENTATION_ID to exercise the live deck.',
  )
  test.setTimeout(240_000)

  const errors = observeBlockingBrowserErrors(page)
  const presentationId = process.env.ANIOS_PRESENTATION_ID as string
  const userId = 'ani.mallya'
  const beforeResponse = await page.request.get(
    `http://localhost:8000/api/v1/presentations/${userId}/${presentationId}`,
  )
  expect(beforeResponse.status()).toBe(200)
  const before = await beforeResponse.json()
  const beforeSpec = before.current_revision.specification
  const selected = beforeSpec.slides[1]
  const marker = `UIREV_${Date.now()}`

  await page.goto('/')
  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByRole('heading', { name: 'Presentations' })).toBeVisible()
  await expect(page.getByText(before.title, { exact: true }).first()).toBeVisible()
  await page.getByRole('button', {
    name: `Select slide 2: ${selected.title}`,
  }).click()
  await page.getByRole('textbox', { name: 'Slide feedback' }).fill(
    `Add the exact text "${marker}" to this slide as a small muted footer. Keep the native editable chart and all current values unchanged.`,
  )

  const revisionResponse = page.waitForResponse(
    response => response.url().includes(`/slides/${selected.slide_id}/revisions`)
      && response.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await page.getByRole('button', { name: 'Apply slide feedback' }).click()
  await expect(page.getByText('PresentationAgent is revising…')).toBeVisible()
  const response = await revisionResponse
  expect(response.status()).toBe(201)
  const revised = await response.json()
  await expect(page.getByText(
    `Slide revised as revision ${revised.current_revision.revision_number}.`,
  )).toBeVisible()
  await expect(page.getByText(marker, { exact: true }).first()).toBeVisible()

  const afterSpec = revised.current_revision.specification
  expect(afterSpec.slides[0]).toEqual(beforeSpec.slides[0])
  expect(afterSpec.slides[2]).toEqual(beforeSpec.slides[2])
  expect(afterSpec.slides[1]).not.toEqual(beforeSpec.slides[1])
  expect(afterSpec.slides[1].elements.some(
    (element: { text?: string }) => element.text === marker,
  )).toBe(true)

  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await page.getByRole('button', { name: 'Presentations' }).click()
  await expect(page.getByText(
    `Revision ${revised.current_revision.revision_number}`,
    { exact: true },
  ).first()).toBeVisible()
  await page.getByRole('button', {
    name: `Select slide 2: ${afterSpec.slides[1].title}`,
  }).click()
  const restoredFollowup = page.getByRole('region', {
    name: `Follow-up conversation for ${afterSpec.slides[1].title}`,
  })
  await expect(restoredFollowup.getByText(marker, { exact: false })).toBeVisible()
  await expect(restoredFollowup.getByText(
    `Applied in revision ${revised.current_revision.revision_number}. This slide changed; all other slides were preserved.`,
    { exact: true },
  )).toBeVisible()

  const downloadResponse = page.waitForResponse(
    response => response.url().endsWith(
      `/revisions/${revised.current_revision_id}/content`,
    ),
  )
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download editable PowerPoint' }).click()
  expect((await downloadResponse).status()).toBe(200)
  expect((await downloadPromise).suggestedFilename()).toContain(
    `r${revised.current_revision.revision_number}.pptx`,
  )
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
})
