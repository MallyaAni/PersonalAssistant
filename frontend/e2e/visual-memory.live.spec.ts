import { expect, test } from '@playwright/test'

const token = process.env.LIVE_AUTH_TOKEN || ''
const conversationId = process.env.LIVE_CONVERSATION_ID || ''
const artifactId = process.env.LIVE_IMAGE_ARTIFACT_ID || ''
const frontendUrl = process.env.ANIOS_FRONTEND_URL || 'http://127.0.0.1:5173'

// Verify ordinary chat carries the visible owned image and answers from it.
test('@live active uploaded image grounds a style question', async ({ page }) => {
  test.skip(!token || !conversationId || !artifactId, 'Live owned-image inputs required')
  test.setTimeout(240_000)

  const consoleErrors: string[] = []
  const failedRequests: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('requestfailed', request => failedRequests.push(request.url()))

  // Send the temporary test token only to AniOS APIs, never third-party assets.
  await page.route('**/api/**', async route => {
    await route.continue({
      headers: {
        ...route.request().headers(),
        Authorization: `Bearer ${token}`,
      },
    })
  })

  await page.goto(frontendUrl)
  await page.evaluate(({ id }) => {
    localStorage.setItem('anios_conversation_id:ani.mallya', id)
  }, { id: conversationId })
  await page.reload()
  await expect(page.getByRole('region', { name: /Image:/ }).first()).toBeVisible()
  // Navigation intentionally aborts the first page's in-flight restoration.
  failedRequests.length = 0

  const chatRequest = page.waitForRequest(request => (
    request.url().endsWith('/api/v1/chat') && request.method() === 'POST'
  ))
  const chatResponse = page.waitForResponse(response => (
    response.url().endsWith('/api/v1/chat') && response.status() === 200
  ))
  await page.getByLabel('Message DeepMatter').fill('what do you think of my style?')
  await page.getByLabel('Send message').click()

  const request = await chatRequest
  const body = request.postDataJSON()
  expect(body.active_image_artifact_id).toBe(artifactId)
  await (await chatResponse).finished()
  await expect(page.getByLabel('Message DeepMatter')).toBeEnabled({ timeout: 180_000 })
  const answer = page.locator('.assistant-markdown').last()
  await expect(answer).toContainText(/style|outfit|jacket|hat/i, { timeout: 180_000 })
  await expect(answer).not.toContainText(/I (?:do not|don't) have any information/i)
  await expect(page.getByText(/I (?:do not|don't) have any information/i)).toHaveCount(0)
  expect(consoleErrors).toEqual([])
  expect(failedRequests).toEqual([])
})
