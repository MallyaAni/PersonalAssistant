import { useEffect, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'

import { deleteArtifact, getReadyArtifacts, type VisualArtifact } from '../../services/api'
import DiagramArtifact from '../DiagramArtifact/DiagramArtifact'
import ImageArtifact from '../ImageArtifact/ImageArtifact'

interface ArtifactPanelProps {
  userId: string;
}

// Display and manage the active user's persisted ready visual artifacts.
const ArtifactPanel = ({ userId }: ArtifactPanelProps) => {
  const [artifacts, setArtifacts] = useState<VisualArtifact[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  // Load recent artifacts again when the user or refresh request changes.
  useEffect(() => {
    const controller = new AbortController()

    // Fetch owned ready visuals and expose a visible failure when loading fails.
    const load = async () => {
      setIsLoading(true)
      setError('')
      try {
        setArtifacts(await getReadyArtifacts(userId, controller.signal))
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : 'Unable to load artifacts.')
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }

    void load()
    return () => controller.abort()
  }, [refreshKey, userId])

  // Delete one owned artifact and remove it from the visible history.
  const removeArtifact = async (artifactId: string) => {
    setError('')
    try {
      await deleteArtifact(userId, artifactId)
      setArtifacts(current => current.filter(artifact => artifact.id !== artifactId))
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete artifact.')
    }
  }

  // Remove an image after its shared card completes the owned delete request.
  const removeDeletedImage = (artifactId: string) => {
    setArtifacts(current => current.filter(item => item.id !== artifactId))
  }

  return (
    <section className="min-h-0 flex-1 overflow-y-auto bg-[#f5f5f7] px-5 py-8 md:px-8 md:py-12">
      <div className="mx-auto max-w-[980px]">
        <header className="mb-7 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#0071e3]">Owned visual outputs</p>
            <h2 className="mt-1 text-3xl font-semibold tracking-[-0.035em] text-[#1d1d1f]">Visual artifacts</h2>
          </div>
          <button
            type="button"
            aria-label="Refresh visual artifacts"
            onClick={() => setRefreshKey(key => key + 1)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-black/10 bg-white hover:bg-[#f5f5f7]"
          >
            <RefreshCw size={17} />
          </button>
        </header>
        {error && <p role="alert" className="mb-4 text-sm text-[#c9342f]">{error}</p>}
        {isLoading ? (
          <p role="status" className="animate-pulse text-sm text-[#6e6e73]">Loading visual artifacts...</p>
        ) : artifacts.length === 0 ? (
          <div className="rounded-3xl border border-black/[0.06] bg-white p-8 text-center text-sm text-[#6e6e73]">
            No visual artifacts yet. Create a diagram or image, or analyze an upload.
          </div>
        ) : (
          <div className="space-y-6">
            {artifacts.map(artifact => (
              <div key={artifact.id} className="relative">
                {artifact.kind === 'diagram' ? (
                  <>
                    <DiagramArtifact artifact={artifact} />
                    <button
                      type="button"
                      aria-label={`Delete ${artifact.title}`}
                      onClick={() => void removeArtifact(artifact.id)}
                      className="mt-2 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-[#c9342f] hover:bg-[#fff1f0]"
                    >
                      <Trash2 size={13} /> Delete artifact
                    </button>
                  </>
                ) : (
                  <ImageArtifact artifact={artifact} onDeleted={removeDeletedImage} />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

export default ArtifactPanel
