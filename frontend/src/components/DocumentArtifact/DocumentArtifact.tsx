import { useEffect, useState } from 'react'

import { getArtifactImage, type DocumentArtifact as DocumentArtifactRecord } from '../../services/api'

interface DocumentArtifactProps {
  artifact: DocumentArtifactRecord
}

// The file's name as it should download: the title with the suffix its type demands.
function fileName(artifact: DocumentArtifactRecord): string {
  const stem = (artifact.title || 'document').replace(/[^A-Za-z0-9 _.-]+/g, '').trim() || 'document'
  const suffix = artifact.mime_type === 'application/pdf' ? '.pdf' : '.docx'
  return `${stem}${suffix}`
}

// A written document as a card with the file to open or save. The bytes come
// through the same authenticated artifact boundary a picture uses; the browser
// URL for them is released when the card goes away.
export function DocumentArtifact({ artifact }: DocumentArtifactProps) {
  const [fileUrl, setFileUrl] = useState('')
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    const load = async () => {
      try {
        const blob = await getArtifactImage(artifact.user_id, artifact.id, controller.signal)
        objectUrl = URL.createObjectURL(blob)
        setFileUrl(objectUrl)
        setLoadError('')
      } catch (error) {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : 'Unable to load the document.')
        }
      }
    }
    void load()
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [artifact.id, artifact.user_id])

  const label = artifact.mime_type === 'application/pdf' ? 'PDF' : 'Word document'
  const size = artifact.byte_size ? `${Math.max(1, Math.round(artifact.byte_size / 1024))} KB` : ''
  return (
    <section
      className="mt-4 flex items-center gap-3 rounded-2xl border border-[#e5e5ea] bg-white px-4 py-3"
      aria-label={`${label}: ${artifact.title || 'document'}`}
    >
      <span aria-hidden="true" className="text-2xl">
        {artifact.mime_type === 'application/pdf' ? '📄' : '📝'}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[#1d1d1f]">{fileName(artifact)}</p>
        <p className="text-xs text-[#6e6e73]">
          {label}
          {size ? ` · ${size}` : ''}
        </p>
        {loadError && (
          <p role="alert" className="mt-1 text-xs text-[#c9342f]">
            {loadError}
          </p>
        )}
      </div>
      {fileUrl && (
        <a
          href={fileUrl}
          download={fileName(artifact)}
          className="rounded-full bg-[#1d1d1f] px-3 py-1.5 text-xs font-medium text-white"
        >
          Save
        </a>
      )}
    </section>
  )
}
