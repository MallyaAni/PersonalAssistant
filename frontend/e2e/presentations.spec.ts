import { expect, test, type Page, type Route } from '@playwright/test'

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

// Encode one deterministic presentation event as an SSE frame.
const presentationEvent = (event: string, data: unknown) => (
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
)

// Verify create, select, revise, persist-visible, and download interactions.
test('creates and revises an editable presentation in the browser', async ({ page }) => {
  const errors = observeBlockingBrowserErrors(page)
  let created = false
  let revised = false
  let imaged = false
  const requests: Array<{ method: string; url: string; body: unknown }> = []

  await page.route('**/api/v1/presentations**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const body = request.postDataJSON() as unknown
    requests.push({ method: request.method(), url: url.pathname, body })

    if (request.method() === 'POST' && url.pathname === '/api/v1/presentations/stream') {
      await new Promise(resolve => setTimeout(resolve, 100))
      created = true
      const ready = presentationRecord()
      const firstSlide = {
        ...deckSpec(),
        slides: deckSpec().slides.slice(0, 1),
      }
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          presentationEvent('started', {
            presentation_id: ready.id,
            revision_id: ready.current_revision_id,
            trace_id: ready.trace_id,
          }),
          presentationEvent('draft', {
            specification: firstSlide,
            expected_slide_count: 2,
          }),
          presentationEvent('draft', {
            specification: deckSpec(),
            expected_slide_count: 2,
          }),
          presentationEvent('ready', { presentation: ready }),
          presentationEvent('done', {}),
        ].join(''),
      })
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
      imaged = true
      await fulfillJson(route, imagePresentationRecord(), 201)
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
        created ? [imaged ? imagePresentationRecord() : presentationRecord(revised)] : [],
      )
      return
    }
    if (request.method() === 'GET') {
      await fulfillJson(route, imaged ? imagePresentationRecord() : presentationRecord(revised))
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
  await expect(page.getByText('Generating locally…')).toBeVisible()
  await expect(page.getByText('Local image added in revision 3.')).toBeVisible()
  await expect(page.getByRole('img', {
    name: 'A horse beside an editable chart',
  }).first()).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download editable PowerPoint' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('browser-presentation-r2.pptx')

  expect(requests.some(request => request.method === 'POST'
    && request.url === '/api/v1/presentations/stream')).toBe(true)
  const revisionRequest = requests.find(request => request.url.endsWith('/slides/slide-b/revisions'))
  expect(revisionRequest?.body).toMatchObject({
    base_revision_id: '11111111-1111-4111-8111-111111111111',
    feedback: 'Make the evidence clearer',
  })
  const imageRequest = requests.find(request => request.url.endsWith('/slides/slide-b/image'))
  expect(imageRequest?.body).toMatchObject({
    base_revision_id: '22222222-2222-4222-8222-222222222222',
    prompt: 'A horse beside an editable chart',
  })
  expect(errors).toEqual({ consoleErrors: [], pageErrors: [] })
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
