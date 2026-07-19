import { useEffect, useId, useState } from 'react'
import { Download } from 'lucide-react'

import type { DiagramArtifact as DiagramArtifactRecord } from '../../services/api'

let mermaidInitialized = false

interface DiagramArtifactProps {
  artifact: DiagramArtifactRecord;
}

// Convert a diagram title into a stable local download filename.
const artifactFilename = (title: string) => {
  const normalized = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return normalized || 'anios-diagram'
}

// Download generated text without sending artifact contents to another service.
const downloadText = (contents: string, mimeType: string, filename: string) => {
  const url = URL.createObjectURL(new Blob([contents], { type: mimeType }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

// Load and initialize the heavy diagram engine only when a diagram is displayed.
const loadMermaid = async () => {
  const { default: mermaid } = await import('mermaid')
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      flowchart: { htmlLabels: false, useMaxWidth: true },
    })
    mermaidInitialized = true
  }
  return mermaid
}

// Render one validated Mermaid artifact and keep its editable source available.
const DiagramArtifact = ({ artifact }: DiagramArtifactProps) => {
  const renderId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const [svg, setSvg] = useState('')
  const [renderError, setRenderError] = useState('')

  // Render source again whenever the streamed artifact changes.
  useEffect(() => {
    let cancelled = false

    // Convert Mermaid source into strict-rendered SVG markup for this artifact card.
    const renderSource = async () => {
      try {
        const mermaid = await loadMermaid()
        const result = await mermaid.render(
          `anios-diagram-${renderId}`,
          artifact.source,
        )
        if (!cancelled) {
          setSvg(result.svg)
          setRenderError('')
        }
      } catch {
        if (!cancelled) {
          setSvg('')
          setRenderError('Unable to render this diagram.')
        }
      }
    }

    void renderSource()

    // Ignore an asynchronous render after this artifact card unmounts.
    function cancelRender() {
      cancelled = true
    }

    return cancelRender
  }, [artifact.source, renderId])

  return (
    <section
      aria-label={`Diagram: ${artifact.title}`}
      className="mt-5 overflow-hidden rounded-2xl border border-black/[0.08] bg-[#f9f9fb]"
    >
      <header className="border-b border-black/[0.07] px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-[#1d1d1f]">{artifact.title}</p>
            <p className="mt-0.5 text-xs text-[#86868b]">Editable Mermaid diagram</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => downloadText(
                artifact.source,
                'text/plain;charset=utf-8',
                `${artifactFilename(artifact.title)}.mmd`,
              )}
              className="flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-medium text-[#1d1d1f] hover:bg-[#f5f5f7]"
            >
              <Download size={13} /> Mermaid
            </button>
            <button
              type="button"
              disabled={!svg}
              onClick={() => downloadText(
                svg,
                'image/svg+xml;charset=utf-8',
                `${artifactFilename(artifact.title)}.svg`,
              )}
              className="flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-medium text-[#1d1d1f] hover:bg-[#f5f5f7] disabled:text-[#86868b]"
            >
              <Download size={13} /> SVG
            </button>
          </div>
        </div>
      </header>
      <div className="overflow-x-auto bg-white p-4">
        {renderError ? (
          <p role="alert" className="text-sm text-[#c9342f]">{renderError}</p>
        ) : svg ? (
          <div
            aria-label="Rendered Mermaid diagram"
            className="min-w-[420px] [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : (
          <p role="status" className="animate-pulse text-sm text-[#6e6e73]">
            Rendering diagram...
          </p>
        )}
      </div>
      <details className="border-t border-black/[0.07] px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-[#0066cc]">
          View Mermaid source
        </summary>
        <pre className="mt-3 max-h-64 overflow-auto whitespace-pre rounded-xl bg-[#1d1d1f] p-4 text-xs leading-5 text-white">
          {artifact.source}
        </pre>
      </details>
    </section>
  )
}

export default DiagramArtifact
