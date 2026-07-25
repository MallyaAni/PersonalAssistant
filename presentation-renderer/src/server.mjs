import http from 'node:http'
import { renderPresentation } from './render.mjs'
import { validateWithLibreOffice } from './office-validation.mjs'
import packageMetadata from '../package.json' with { type: 'json' }

const PORT = Number(process.env.PORT || 8002)
const MAX_REQUEST_BYTES = Number(process.env.MAX_REQUEST_BYTES || 60 * 1024 * 1024)
const REQUIRE_OFFICE_VALIDATION = process.env.REQUIRE_OFFICE_VALIDATION === 'true'
let renderQueue = Promise.resolve()

// Serialize export work so concurrent LibreOffice calls never share a profile.
const enqueueRender = operation => {
  const result = renderQueue.then(operation)
  renderQueue = result.catch(() => undefined)
  return result
}

// Return a JSON response without leaking provider or stack details.
const sendJson = (response, status, payload) => {
  const body = Buffer.from(JSON.stringify(payload))
  response.writeHead(status, {
    'content-type': 'application/json',
    'content-length': body.length,
  })
  response.end(body)
}

// Read and parse one bounded JSON request body.
const readJson = async request => {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > MAX_REQUEST_BYTES) throw new Error('Request exceeds renderer limit')
    chunks.push(chunk)
  }
  const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!payload || typeof payload !== 'object' || !payload.specification) {
    throw new Error('Presentation specification is required')
  }
  return payload
}

// Handle health and render requests for the stateless compiler.
const handleRequest = async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    sendJson(response, 200, {
      status: 'ok',
      renderer: 'pptxgenjs',
      version: packageMetadata.dependencies.pptxgenjs,
    })
    return
  }
  if (request.method !== 'POST' || request.url !== '/v1/render') {
    sendJson(response, 404, { error: 'not_found' })
    return
  }
  try {
    const payload = await readJson(request)
    const content = await enqueueRender(async () => {
      const rendered = await renderPresentation(
        payload.specification,
        payload.images,
      )
      if (REQUIRE_OFFICE_VALIDATION) {
        await validateWithLibreOffice(rendered)
      }
      return rendered
    })
    response.writeHead(200, {
      'content-type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'content-length': content.length,
      'x-presentation-slide-count': String(payload.specification.slides.length),
      'x-presentation-renderer-version': packageMetadata.dependencies.pptxgenjs,
      'x-presentation-office-validation': REQUIRE_OFFICE_VALIDATION
        ? 'passed'
        : 'skipped',
    })
    response.end(content)
  } catch {
    sendJson(response, 422, { error: 'presentation_render_failed' })
  }
}

// Start the isolated compiler when this module is launched as a service.
const main = () => {
  const server = http.createServer((request, response) => {
    void handleRequest(request, response)
  })
  server.listen(PORT, '0.0.0.0')
}

main()
