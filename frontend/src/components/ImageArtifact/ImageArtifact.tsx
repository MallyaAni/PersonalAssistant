import { useEffect, useState } from 'react'
import { Download, RefreshCw, Trash2 } from 'lucide-react'

import {
  deleteArtifact,
  getArtifactImage,
  type ImageArtifact as ImageArtifactRecord,
} from '../../services/api'

interface ImageArtifactProps {
  artifact: ImageArtifactRecord;
  onDeleted?: (artifactId: string) => void;
  onRetry?: () => void;
}

// Download one already loaded private image without another provider request.
const downloadImage = (url: string, artifact: ImageArtifactRecord) => {
  const extension = artifact.mime_type.split('/')[1].replace('jpeg', 'jpg')
  const link = document.createElement('a')
  link.href = url
  link.download = `anios-${artifact.kind}-${artifact.id}.${extension}`
  link.click()
}

// Render, download, retry, and delete one owned generated or uploaded image.
const ImageArtifact = ({ artifact, onDeleted, onRetry }: ImageArtifactProps) => {
  const [imageUrl, setImageUrl] = useState('')
  const [loadError, setLoadError] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const analysis = typeof artifact.metadata.analysis === 'string'
    ? artifact.metadata.analysis
    : ''

  // Fetch private image bytes and release their browser URL after use.
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''

    // Load the owned image through the authenticated artifact boundary.
    const loadImage = async () => {
      try {
        const blob = await getArtifactImage(
          artifact.user_id,
          artifact.id,
          controller.signal,
        )
        objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
        setLoadError('')
      } catch (error) {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : 'Unable to load image.')
        }
      }
    }

    void loadImage()

    // Cancel loading and release the temporary browser object URL.
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [artifact.id, artifact.user_id])

  // Delete the owned binary and remove its card after confirmation from the API.
  const removeImage = async () => {
    if (isDeleting) return
    setIsDeleting(true)
    setDeleteError('')
    try {
      await deleteArtifact(artifact.user_id, artifact.id)
      onDeleted?.(artifact.id)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Unable to delete image.')
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <section
      aria-label={`Image: ${artifact.title}`}
      className="mt-5 overflow-hidden rounded-2xl border border-black/[0.08] bg-[#f9f9fb]"
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-black/[0.07] px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-[#1d1d1f]">{artifact.title}</p>
          <p className="mt-0.5 text-xs text-[#86868b]">
            {artifact.kind === 'generated_image' ? 'Locally generated image' : 'Uploaded image analysis'}
            {' · '}{artifact.width}×{artifact.height}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-medium hover:bg-[#f5f5f7]"
            >
              <RefreshCw size={13} /> Retry
            </button>
          )}
          <button
            type="button"
            disabled={!imageUrl}
            onClick={() => downloadImage(imageUrl, artifact)}
            className="flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-medium hover:bg-[#f5f5f7] disabled:text-[#86868b]"
          >
            <Download size={13} /> Download
          </button>
          <button
            type="button"
            disabled={isDeleting}
            onClick={() => void removeImage()}
            className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-[#c9342f] hover:bg-[#fff1f0] disabled:text-[#86868b]"
          >
            <Trash2 size={13} /> {isDeleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </header>
      <div className="bg-white p-4">
        {loadError ? (
          <p role="alert" className="text-sm text-[#c9342f]">{loadError}</p>
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt={artifact.kind === 'generated_image' ? 'Generated visual result' : 'Uploaded visual'}
            className="mx-auto max-h-[620px] w-auto max-w-full rounded-xl object-contain"
          />
        ) : (
          <p role="status" className="animate-pulse text-sm text-[#6e6e73]">Loading image…</p>
        )}
        {analysis && (
          <div className="mt-4 rounded-xl bg-[#f5f5f7] p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[#86868b]">Gemma analysis</p>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#333336]">{analysis}</p>
          </div>
        )}
        {deleteError && <p role="alert" className="mt-3 text-sm text-[#c9342f]">{deleteError}</p>}
      </div>
    </section>
  )
}

export default ImageArtifact
