import { useEffect, useMemo, useState } from 'react'
import {
  Download,
  FilePlus2,
  ImagePlus,
  Loader2,
  Presentation as PresentationIcon,
  RefreshCw,
  Sparkles,
  Trash2,
} from 'lucide-react'

import {
  cancelPresentationJob,
  createPresentation,
  deletePresentation,
  downloadPresentation,
  generatePresentationSlideImage,
  getArtifactImage,
  getPresentation,
  getPresentationJob,
  getPresentations,
  revisePresentationSlide,
  type PresentationDeckSpec,
  type PresentationElement,
  type PresentationRecord,
  type PresentationSlide,
  type PresentationTheme,
} from '../../services/api'

const SLIDE_WIDTH = 13.333
const SLIDE_HEIGHT = 7.5

// Isolate one user's reconnectable presentation job in browser storage.
const presentationJobStorageKey = (userId: string) => (
  `anios_presentation_job:${userId}`
)

interface PresentationPanelProps {
  userId: string;
  conversationId: string;
}

interface PresentationProgress {
  percent: number;
  label: string;
}

interface SlideCanvasProps {
  slide: PresentationSlide;
  theme: PresentationTheme;
  userId?: string;
  compact?: boolean;
}

// Convert a six-digit PowerPoint color into a browser color.
const cssColor = (value: string | null | undefined, fallback: string) => (
  `#${value || fallback}`
)

// Position one native object proportionally on the widescreen preview canvas.
const elementPosition = (element: PresentationElement) => ({
  left: `${(element.x / SLIDE_WIDTH) * 100}%`,
  top: `${(element.y / SLIDE_HEIGHT) * 100}%`,
  width: `${(element.w / SLIDE_WIDTH) * 100}%`,
  height: `${(element.h / SLIDE_HEIGHT) * 100}%`,
})

// Convert persisted slide and image checkpoints into honest stage-based progress.
const presentationProgress = (
  draft: PresentationDeckSpec | null,
  expectedSlides: number,
  autoImageMax: number,
): PresentationProgress => {
  if (!draft) {
    return { percent: 8, label: 'Planning the deck outline' }
  }
  const completedSlides = draft.slides.length
  const totalSlides = Math.max(expectedSlides, completedSlides, 1)
  if (completedSlides < totalSlides) {
    return {
      percent: Math.min(
        64,
        10 + Math.round((completedSlides / totalSlides) * 54),
      ),
      label: `Planning slide ${completedSlides + 1} of ${totalSlides}`,
    }
  }
  const visualCandidates = draft.slides.filter(
    slide => Boolean(slide.visual_prompt) && slide.visual_priority > 0,
  ).length
  const expectedVisuals = Math.min(
    Math.max(autoImageMax, 0),
    visualCandidates,
  )
  const completedVisuals = draft.slides.reduce(
    (count, slide) => count + (
      slide.elements.some(element => element.type === 'image') ? 1 : 0
    ),
    0,
  )
  if (expectedVisuals > 0 && completedVisuals < expectedVisuals) {
    return {
      percent: 65 + Math.round((completedVisuals / expectedVisuals) * 24),
      label: `Generating visual ${completedVisuals + 1} of ${expectedVisuals}`,
    }
  }
  return {
    percent: 92,
    label: 'Rendering and validating the editable PowerPoint',
  }
}

interface OwnedSlideImageProps {
  userId?: string;
  artifactId: string;
  altText: string;
  position: ReturnType<typeof elementPosition>;
}

// Load one owned image reference into a temporary browser URL for slide previews.
const OwnedSlideImage = ({
  userId,
  artifactId,
  altText,
  position,
}: OwnedSlideImageProps) => {
  const [imageUrl, setImageUrl] = useState('')
  const [loadError, setLoadError] = useState('')

  // Fetch private image bytes and release their temporary URL after this preview.
  useEffect(() => {
    if (!userId) return undefined
    const controller = new AbortController()
    let objectUrl = ''

    // Resolve the user-owned artifact without exposing its storage path.
    const load = async () => {
      try {
        const blob = await getArtifactImage(userId, artifactId, controller.signal)
        objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
        setLoadError('')
      } catch (loadFailure) {
        if (!controller.signal.aborted) {
          setLoadError(
            loadFailure instanceof Error
              ? loadFailure.message
              : 'Unable to load slide image.',
          )
        }
      }
    }

    void load()
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [artifactId, userId])

  if (imageUrl) {
    return (
      <img
        src={imageUrl}
        alt={altText}
        className="absolute object-cover"
        style={position}
      />
    )
  }
  return (
    <div
      className="absolute flex items-center justify-center rounded-[1cqw] bg-black/[0.06] px-[1cqw] text-center text-[1.8cqw] text-[#6e6e73]"
      style={position}
    >
      {loadError || `Image · ${altText}`}
    </div>
  )
}

// Render a compact browser preview from the same canonical DeckSpec as PowerPoint.
const SlideCanvas = ({
  slide,
  theme,
  userId,
  compact = false,
}: SlideCanvasProps) => (
  <div
    aria-label={`Slide preview: ${slide.title}`}
    className="presentation-canvas relative aspect-video w-full overflow-hidden bg-white"
    style={{
      backgroundColor: cssColor(slide.background_color, theme.background_color),
      fontFamily: `${theme.font_face}, -apple-system, BlinkMacSystemFont, sans-serif`,
    }}
  >
    {slide.elements.map(element => {
      const position = elementPosition(element)
      if (element.type === 'text') {
        return (
          <div
            key={element.element_id}
            className="absolute overflow-hidden whitespace-pre-wrap"
            style={{
              ...position,
              color: cssColor(element.color, theme.text_color),
              fontSize: `${element.font_size / 7.2}cqw`,
              fontWeight: element.bold ? 700 : 400,
              textAlign: element.align,
              display: 'flex',
              alignItems: element.valign === 'mid'
                ? 'center'
                : element.valign === 'bottom' ? 'flex-end' : 'flex-start',
              lineHeight: 1.15,
            }}
          >
            {element.bullet ? `• ${element.text}` : element.text}
          </div>
        )
      }
      if (element.type === 'shape') {
        return (
          <div
            key={element.element_id}
            className="absolute"
            style={{
              ...position,
              backgroundColor: element.shape === 'line'
                ? 'transparent'
                : cssColor(element.fill_color, 'FFFFFF'),
              border: `${Math.max(element.line_width, 1)}px solid ${cssColor(element.line_color, 'D2D2D7')}`,
              borderRadius: element.shape === 'ellipse'
                ? '50%'
                : element.shape === 'roundRect' ? '12%' : 0,
            }}
          />
        )
      }
      if (element.type === 'chart') {
        const values = element.series[0]?.values || []
        const maximum = Math.max(...values, 1)
        return (
          <div
            key={element.element_id}
            className="absolute flex flex-col overflow-hidden rounded-[2cqw] border border-black/10 bg-white/90 p-[2cqw]"
            style={position}
          >
            {element.show_title && (
              <p className="truncate text-center text-[2.2cqw] font-semibold">
                {element.title || element.series[0]?.name}
              </p>
            )}
            <div className="mt-[1cqw] flex min-h-0 flex-1 items-end justify-around gap-[1cqw] border-b border-l border-black/20 px-[1cqw]">
              {values.map((value, index) => (
                <div key={`${element.element_id}-${element.categories[index]}`} className="flex h-full min-w-0 flex-1 flex-col justify-end">
                  <div
                    className="w-full rounded-t-[0.6cqw]"
                    style={{
                      height: `${(value / maximum) * 82}%`,
                      backgroundColor: cssColor(theme.primary_color, '0071E3'),
                    }}
                    title={`${element.categories[index]}: ${value}`}
                  />
                  {!compact && (
                    <span className="truncate pt-[0.4cqw] text-center text-[1.4cqw]">
                      {element.categories[index]}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      }
      if (element.type === 'table') {
        return (
          <table
            key={element.element_id}
            className="absolute table-fixed border-collapse overflow-hidden bg-white text-[1.6cqw]"
            style={position}
          >
            <thead>
              <tr>
                {element.headers.map(header => (
                  <th key={header} className="border border-black/15 bg-black/[0.04] px-[0.8cqw] py-[0.5cqw] text-left font-semibold">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {element.rows.map((row, rowIndex) => (
                <tr key={`${element.element_id}-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowIndex}-${cellIndex}`} className="border border-black/15 px-[0.8cqw] py-[0.5cqw]">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )
      }
      return (
        <OwnedSlideImage
          key={element.element_id}
          userId={userId}
          artifactId={element.artifact_id}
          altText={element.alt_text}
          position={position}
        />
      )
    })}
  </div>
)

// Manage persisted presentations, slide feedback, revisions, and downloads.
const PresentationPanel = ({ userId, conversationId }: PresentationPanelProps) => {
  const [presentations, setPresentations] = useState<PresentationRecord[]>([])
  const [active, setActive] = useState<PresentationRecord | null>(null)
  const [selectedSlideId, setSelectedSlideId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [feedback, setFeedback] = useState('')
  const [pendingFeedback, setPendingFeedback] = useState<{
    slideId: string;
    content: string;
  } | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [draftSpecification, setDraftSpecification] = useState<PresentationDeckSpec | null>(null)
  const [expectedDraftSlides, setExpectedDraftSlides] = useState(0)
  const [autoImageMax, setAutoImageMax] = useState(0)
  const [isRevising, setIsRevising] = useState(false)
  const [imagePrompt, setImagePrompt] = useState('')
  const [isGeneratingImage, setIsGeneratingImage] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [viewedRevisionId, setViewedRevisionId] = useState<string | null>(null)

  // A past revision can be viewed read-only; otherwise the latest slides show.
  const viewedRevision = useMemo(
    () => (viewedRevisionId
      ? (active?.revisions || []).find(
          revision => revision.id === viewedRevisionId && revision.specification,
        ) || null
      : null),
    [viewedRevisionId, active?.revisions],
  )
  const isViewingHistory = viewedRevision != null
  const specification = viewedRevision?.specification
    || active?.current_revision?.specification
    || null
  const selectedSlide = useMemo(
    () => specification?.slides.find(slide => slide.slide_id === selectedSlideId)
      || specification?.slides[0]
      || null,
    [selectedSlideId, specification],
  )
  const selectedSlideImage = selectedSlide?.elements.find(
    element => element.type === 'image',
  )
  const failedPresentations = presentations.filter(
    presentation => presentation.current_revision === null
      && presentation.revisions[0]?.status === 'failed',
  )
  const creationProgress = presentationProgress(
    draftSpecification,
    expectedDraftSlides,
    autoImageMax,
  )
  // Reconstruct the selected slide's persisted feedback conversation from revisions.
  const slideFollowups = useMemo(
    () => (active?.revisions || [])
      .filter(revision => revision.target_slide_id === selectedSlide?.slide_id)
      .slice()
      .sort((left, right) => left.revision_number - right.revision_number),
    [active?.revisions, selectedSlide?.slide_id],
  )

  // Snap back to the latest slides whenever the deck or its newest revision changes.
  useEffect(() => {
    setViewedRevisionId(null)
  }, [active?.id, active?.current_revision_id])

  // Restore any unfinished durable job after navigation or a full reload.
  useEffect(() => {
    setActiveJobId(localStorage.getItem(presentationJobStorageKey(userId)))
  }, [userId])

  // Poll persisted worker progress and reconnect the preview to a finished deck.
  useEffect(() => {
    if (!activeJobId) return undefined
    const controller = new AbortController()

    // Follow one durable job until it reaches a visible terminal state.
    const monitor = async () => {
      setIsCreating(true)
      setError('')
      try {
        while (!controller.signal.aborted) {
          const job = await getPresentationJob(
            userId,
            activeJobId,
            controller.signal,
          )
          setAutoImageMax(job.auto_image_max)
          if (job.draft_specification) {
            setDraftSpecification(job.draft_specification)
            setExpectedDraftSlides(
              job.expected_slide_count
                || job.draft_specification.slides.length,
            )
          }
          if (job.status === 'ready') {
            if (!job.presentation) {
              throw new Error('Presentation job finished without a ready deck')
            }
            const created = job.presentation
            setActive(created)
            setPresentations(current => [
              created,
              ...current.filter(record => record.id !== created.id),
            ])
            setSelectedSlideId(
              created.current_revision?.specification?.slides[0]?.slide_id || '',
            )
            setNotice('Presentation ready. Every supported slide object is editable in PowerPoint.')
            localStorage.removeItem(presentationJobStorageKey(userId))
            setActiveJobId(null)
            return
          }
          if (job.status === 'failed' || job.status === 'cancelled') {
            throw new Error(
              job.status === 'cancelled'
                ? 'Presentation creation was cancelled.'
                : 'Unable to create the presentation.',
            )
          }
          await new Promise(resolve => window.setTimeout(resolve, 750))
        }
      } catch (jobError) {
        if (!controller.signal.aborted) {
          localStorage.removeItem(presentationJobStorageKey(userId))
          setActiveJobId(null)
          setError(
            jobError instanceof Error
              ? jobError.message
              : 'Unable to monitor the presentation.',
          )
        }
      } finally {
        if (!controller.signal.aborted) {
          setDraftSpecification(null)
          setExpectedDraftSlides(0)
          setAutoImageMax(0)
          setIsCreating(false)
        }
      }
    }

    void monitor()
    return () => controller.abort()
  }, [activeJobId, userId])

  // Load persisted deck summaries and restore the newest deck workspace.
  useEffect(() => {
    const controller = new AbortController()

    // Fetch recent decks and hydrate the first one with its full specification.
    const load = async () => {
      setIsLoading(true)
      setError('')
      try {
        const records = await getPresentations(userId, controller.signal)
        setPresentations(records)
        if (records.length > 0) {
          const detail = await getPresentation(
            userId,
            active?.id || records[0].id,
            controller.signal,
          )
          setActive(detail)
          setSelectedSlideId(
            detail.current_revision?.specification?.slides[0]?.slide_id || '',
          )
        } else {
          setActive(null)
          setSelectedSlideId('')
        }
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : 'Unable to load presentations.')
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }

    void load()
    return () => controller.abort()
  }, [refreshKey, userId])

  // Open one presentation and reset the selected slide to its first slide.
  const openPresentation = async (presentationId: string) => {
    setError('')
    try {
      const detail = await getPresentation(userId, presentationId)
      setActive(detail)
      setSelectedSlideId(
        detail.current_revision?.specification?.slides[0]?.slide_id || '',
      )
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to open the presentation.')
    }
  }

  // Queue one durable deck job so generation can continue outside this view.
  const submitCreation = async () => {
    const normalized = prompt.trim()
    if (!normalized || isCreating) return
    setIsCreating(true)
    setError('')
    setNotice('')
    setDraftSpecification(null)
    setExpectedDraftSlides(0)
    try {
      const queued = await createPresentation(
        userId,
        conversationId,
        normalized,
      )
      localStorage.setItem(presentationJobStorageKey(userId), queued.id)
      setActiveJobId(queued.id)
      setAutoImageMax(queued.auto_image_max)
      setPrompt('')
      setNotice('PresentationAgent is working in the background. You can continue chatting.')
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Unable to create the presentation.')
      setDraftSpecification(null)
      setExpectedDraftSlides(0)
      setAutoImageMax(0)
      setIsCreating(false)
    }
  }

  // Ask the worker to stop at its next safe slide checkpoint.
  const cancelCreation = async () => {
    if (!activeJobId) return
    try {
      await cancelPresentationJob(userId, activeJobId)
      setNotice('Cancellation requested. The worker will stop at the next safe checkpoint.')
    } catch (cancelError) {
      setError(
        cancelError instanceof Error
          ? cancelError.message
          : 'Unable to cancel the presentation.',
      )
    }
  }

  // Apply feedback to only the selected slide and promote the linked revision.
  const submitFeedback = async () => {
    const normalized = feedback.trim()
    const revisionId = active?.current_revision_id
    if (!active || !selectedSlide || !revisionId || !normalized || isRevising) return
    setIsRevising(true)
    setPendingFeedback({
      slideId: selectedSlide.slide_id,
      content: normalized,
    })
    setFeedback('')
    setError('')
    setNotice('')
    try {
      const revised = await revisePresentationSlide(
        userId,
        active.id,
        selectedSlide.slide_id,
        revisionId,
        normalized,
      )
      setActive(revised)
      setPresentations(current => current.map(item => (
        item.id === revised.id ? revised : item
      )))
      setSelectedSlideId(selectedSlide.slide_id)
      setNotice(`Slide revised as revision ${revised.current_revision?.revision_number}.`)
    } catch (revisionError) {
      setFeedback(normalized)
      try {
        const refreshed = await getPresentation(userId, active.id)
        setActive(refreshed)
        setPresentations(current => current.map(item => (
          item.id === refreshed.id ? refreshed : item
        )))
      } catch {
        // Preserve the original revision failure when refreshing history also fails.
      }
      setError(revisionError instanceof Error ? revisionError.message : 'Unable to revise the slide.')
    } finally {
      setPendingFeedback(null)
      setIsRevising(false)
    }
  }

  // Generate initial imagery or refine the selected slide's existing image.
  const addSlideImage = async () => {
    const revisionId = active?.current_revision_id
    if (
      !active
      || !selectedSlide
      || !revisionId
      || isGeneratingImage
    ) return
    setIsGeneratingImage(true)
    setError('')
    setNotice('')
    try {
      const revised = await generatePresentationSlideImage(
        userId,
        active.id,
        selectedSlide.slide_id,
        revisionId,
        imagePrompt,
      )
      setActive(revised)
      setPresentations(current => current.map(item => (
        item.id === revised.id ? revised : item
      )))
      setSelectedSlideId(selectedSlide.slide_id)
      setImagePrompt('')
      setNotice(selectedSlideImage
        ? `Slide image refined with FLUX in revision ${revised.current_revision?.revision_number}.`
        : `Local image added in revision ${revised.current_revision?.revision_number}.`)
    } catch (imageError) {
      setError(
        imageError instanceof Error
          ? imageError.message
          : 'Unable to generate imagery for the presentation.',
      )
    } finally {
      setIsGeneratingImage(false)
    }
  }

  // Download the current native PowerPoint revision through a temporary object URL.
  const saveCurrentRevision = async () => {
    if (!active?.current_revision_id) return
    setError('')
    try {
      const { blob, filename } = await downloadPresentation(
        userId,
        active.id,
        active.current_revision_id,
      )
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : 'Unable to download the presentation.')
    }
  }

  // Delete any owned deck after confirmation, including failed decks without slides.
  const removePresentation = async (presentation: PresentationRecord) => {
    if (!window.confirm(`Delete "${presentation.title}" and all revisions?`)) return
    setError('')
    try {
      await deletePresentation(userId, presentation.id)
      setPresentations(current => current.filter(item => item.id !== presentation.id))
      if (active?.id === presentation.id) {
        setActive(null)
        setSelectedSlideId('')
      }
      setNotice('Presentation deleted.')
      setRefreshKey(key => key + 1)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete the presentation.')
    }
  }

  // Delete only terminal failed decks while preserving ready and pending work.
  const removeFailedPresentations = async () => {
    if (
      failedPresentations.length === 0
      || !window.confirm(
        `Delete ${failedPresentations.length} failed presentation${failedPresentations.length === 1 ? '' : 's'}?`,
      )
    ) return
    setError('')
    try {
      await Promise.all(
        failedPresentations.map(
          presentation => deletePresentation(userId, presentation.id),
        ),
      )
      const failedIds = new Set(
        failedPresentations.map(presentation => presentation.id),
      )
      setPresentations(current => current.filter(item => !failedIds.has(item.id)))
      if (active && failedIds.has(active.id)) {
        setActive(null)
        setSelectedSlideId('')
      }
      setNotice(`${failedIds.size} failed presentation${failedIds.size === 1 ? '' : 's'} deleted.`)
      setRefreshKey(key => key + 1)
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : 'Unable to delete failed presentations.',
      )
      setRefreshKey(key => key + 1)
    }
  }

  return (
    <section className="min-h-0 flex-1 overflow-y-auto bg-[#f5f5f7] px-4 py-6 md:px-7 md:py-8">
      <div className="mx-auto max-w-[1500px]">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#0071e3]">PresentationAgent · PptxGenJS</p>
            <h2 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">Presentations</h2>
            <p className="mt-1 max-w-2xl text-sm text-[#6e6e73]">
              Create native editable PowerPoint decks, then revise one selected slide with AI feedback.
            </p>
          </div>
          <button
            type="button"
            aria-label="Refresh presentations"
            onClick={() => setRefreshKey(key => key + 1)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-black/10 bg-white hover:bg-[#f5f5f7]"
          >
            <RefreshCw size={17} />
          </button>
        </header>

        {error && <p role="alert" className="mb-4 rounded-2xl bg-[#fff1f0] px-4 py-3 text-sm text-[#c9342f]">{error}</p>}
        {notice && <p role="status" className="mb-4 rounded-2xl bg-[#eef8ff] px-4 py-3 text-sm text-[#0066cc]">{notice}</p>}

        <div className="mb-6 rounded-3xl border border-black/[0.06] bg-white p-5 shadow-sm">
          <label htmlFor="presentation-brief" className="text-sm font-semibold">Create a new deck</label>
          <textarea
            id="presentation-brief"
            value={prompt}
            onChange={event => setPrompt(event.target.value)}
            placeholder="Describe the audience, objective, key points, data, and desired number of slides."
            className="mt-3 min-h-24 w-full resize-y rounded-2xl border border-black/10 bg-[#fbfbfd] p-4 text-sm outline-none focus:border-black/20"
            disabled={isCreating}
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs text-[#86868b]">Qwen plans the deck in a background worker; deterministic code owns rendering and persistence.</p>
            <div className="flex items-center gap-2">
              {isCreating && activeJobId && (
                <button
                  type="button"
                  aria-label="Cancel presentation"
                  onClick={() => void cancelCreation()}
                  className="h-10 rounded-full border border-black/10 bg-white px-4 text-sm font-medium text-[#6e6e73]"
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                aria-label="Create presentation"
                onClick={() => void submitCreation()}
                disabled={!prompt.trim() || isCreating}
                className="flex h-10 items-center gap-2 rounded-full bg-[#0071e3] px-4 text-sm font-medium text-white disabled:bg-[#d2d2d7]"
              >
                {isCreating ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                {isCreating ? 'Using PresentationAgent…' : 'Create presentation'}
              </button>
            </div>
          </div>
        </div>

        {isCreating && (
          <section
            aria-label="Generating presentation preview"
            className="mb-6 rounded-3xl border border-[#0071e3]/20 bg-white p-4 shadow-sm md:p-6"
          >
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#0071e3]">
                  Building your deck
                </p>
                <h3 className="mt-1 text-xl font-semibold">
                  {draftSpecification?.title || 'Preparing your presentation'}
                </h3>
              </div>
              <p role="status" className="text-sm font-medium text-[#6e6e73]">
                {creationProgress.percent}%
              </p>
            </div>
            <div
              role="progressbar"
              aria-label="Presentation completion"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={creationProgress.percent}
              aria-valuetext={creationProgress.label}
              className="h-2 overflow-hidden rounded-full bg-[#e8e8ed]"
            >
              <div
                className="h-full rounded-full bg-[#0071e3] transition-[width] duration-500 ease-out"
                style={{ width: `${creationProgress.percent}%` }}
              />
            </div>
            <p className="mt-2 text-sm text-[#6e6e73]">{creationProgress.label}</p>
            {draftSpecification ? (
              <>
                <div className="mt-4 rounded-2xl bg-[#e8e8ed] p-3 shadow-inner">
                  <SlideCanvas
                    slide={draftSpecification.slides[draftSpecification.slides.length - 1]}
                    theme={draftSpecification.theme}
                    userId={userId}
                  />
                </div>
                <div
                  className="mt-4 flex gap-3 overflow-x-auto pb-2"
                  aria-label="Generated slide previews"
                >
                  {draftSpecification.slides.map((slide, index) => (
                    <div
                      key={slide.slide_id}
                      aria-label={`Generated slide ${index + 1}: ${slide.title}`}
                      className="w-36 flex-none overflow-hidden rounded-xl border border-black/10 bg-white p-1"
                    >
                      <SlideCanvas
                        slide={slide}
                        theme={draftSpecification.theme}
                        userId={userId}
                        compact
                      />
                      <span className="block truncate px-1 py-1 text-left text-[11px] text-[#6e6e73]">
                        {index + 1}. {slide.title}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="mt-4 h-40 animate-pulse rounded-2xl bg-[#f5f5f7]" />
            )}
          </section>
        )}

        {isLoading ? (
          <p role="status" className="animate-pulse text-sm text-[#6e6e73]">Loading presentations…</p>
        ) : presentations.length === 0 && !active ? (
          <div className="rounded-3xl border border-dashed border-black/10 bg-white/70 p-10 text-center">
            <FilePlus2 className="mx-auto text-[#86868b]" />
            <p className="mt-3 text-sm text-[#6e6e73]">No presentations yet.</p>
          </div>
        ) : (
          <div className="grid min-h-[650px] gap-5 xl:grid-cols-[230px_minmax(0,1fr)_300px]">
            <aside className="rounded-3xl border border-black/[0.06] bg-white p-3">
              <div className="flex items-center justify-between gap-2 px-2 py-2">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#86868b]">Decks</p>
                {failedPresentations.length > 0 && (
                  <button
                    type="button"
                    aria-label={`Delete all ${failedPresentations.length} failed presentations`}
                    onClick={() => void removeFailedPresentations()}
                    className="rounded-full bg-[#fff1f0] px-2.5 py-1 text-[11px] font-medium text-[#c9342f] hover:bg-[#ffe5e2]"
                  >
                    Clear failed ({failedPresentations.length})
                  </button>
                )}
              </div>
              <div className="space-y-1">
                {presentations.map(presentation => {
                  const failed = presentation.current_revision === null
                    && presentation.revisions[0]?.status === 'failed'
                  return (
                    <div
                      key={presentation.id}
                      className={`flex items-center gap-1 rounded-2xl pr-2 ${active?.id === presentation.id ? 'bg-[#f5f5f7]' : 'hover:bg-[#fbfbfd]'}`}
                    >
                    <button
                      type="button"
                      onClick={() => void openPresentation(presentation.id)}
                      className="min-w-0 flex-1 px-3 py-3 text-left"
                    >
                      <span className="block truncate text-sm font-medium">{presentation.title}</span>
                      <span className={`mt-1 block text-xs ${failed ? 'font-medium text-[#c9342f]' : 'text-[#86868b]'}`}>
                        {presentation.current_revision
                          ? `Revision ${presentation.current_revision.revision_number}`
                          : failed
                            ? 'Failed · no completed slides'
                            : 'No completed slides'}
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete presentation: ${presentation.title}`}
                      onClick={() => void removePresentation(presentation)}
                      className="flex h-8 flex-none items-center gap-1 rounded-full border border-[#c9342f]/20 px-2 text-[11px] font-medium text-[#c9342f] hover:bg-[#fff1f0]"
                    >
                      <Trash2 size={13} /> Delete
                    </button>
                    </div>
                  )
                })}
              </div>
            </aside>

            {active && specification && selectedSlide ? (
              <main className="min-w-0 rounded-3xl border border-black/[0.06] bg-white p-4 md:p-6">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xl font-semibold tracking-[-0.025em]">{active.title}</h3>
                    <p className="text-xs text-[#86868b]">
                      {isViewingHistory
                        ? `Viewing revision ${viewedRevision?.revision_number} (read-only) · ${specification.slides.length} slides`
                        : `Revision ${active.current_revision?.revision_number} · ${specification.slides.length} slides`}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      aria-label="Download editable PowerPoint"
                      onClick={() => void saveCurrentRevision()}
                      className="flex h-9 items-center gap-2 rounded-full bg-[#1d1d1f] px-3.5 text-xs font-medium text-white"
                    >
                      <Download size={14} /> Download .pptx
                    </button>
                    <button
                      type="button"
                      aria-label="Delete presentation"
                      onClick={() => void removePresentation(active)}
                      className="flex h-9 w-9 items-center justify-center rounded-full border border-black/10 text-[#c9342f]"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                {isViewingHistory && (
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#0071e3]/30 bg-[#eef6ff] px-4 py-2.5 text-xs text-[#0058b0]">
                    <span>Viewing a past revision (read-only). Edits always apply to the latest.</span>
                    <button
                      type="button"
                      onClick={() => setViewedRevisionId(null)}
                      className="rounded-full bg-[#0071e3] px-3 py-1 font-medium text-white"
                    >
                      Return to latest
                    </button>
                  </div>
                )}

                <div className="rounded-2xl bg-[#e8e8ed] p-3 shadow-inner">
                  <SlideCanvas
                    slide={selectedSlide}
                    theme={specification.theme}
                    userId={userId}
                  />
                </div>

                <div className="mt-4 flex gap-3 overflow-x-auto pb-2" aria-label="Presentation slides">
                  {specification.slides.map((slide, index) => (
                    <button
                      key={slide.slide_id}
                      type="button"
                      aria-label={`Select slide ${index + 1}: ${slide.title}`}
                      onClick={() => setSelectedSlideId(slide.slide_id)}
                      className={`w-36 flex-none overflow-hidden rounded-xl border-2 bg-white p-1 ${selectedSlide.slide_id === slide.slide_id ? 'border-[#0071e3]' : 'border-transparent'}`}
                    >
                      <SlideCanvas
                        slide={slide}
                        theme={specification.theme}
                        userId={userId}
                        compact
                      />
                      <span className="block truncate px-1 py-1 text-left text-[11px] text-[#6e6e73]">
                        {index + 1}. {slide.title}
                      </span>
                    </button>
                  ))}
                </div>
              </main>
            ) : active ? (
              <main className="flex items-center justify-center rounded-3xl border border-black/[0.06] bg-white p-10">
                <div className="max-w-md text-center">
                  <PresentationIcon className="mx-auto text-[#86868b]" />
                  <h3 className="mt-3 text-lg font-semibold">{active.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-[#6e6e73]">
                    {active.revisions[0]?.status === 'failed'
                      ? 'This presentation failed before any slides were completed.'
                      : 'This presentation has no completed slides yet.'}
                  </p>
                  <button
                    type="button"
                    aria-label="Delete incomplete presentation"
                    onClick={() => void removePresentation(active)}
                    className="mt-5 inline-flex h-9 items-center gap-2 rounded-full border border-[#c9342f]/20 px-4 text-xs font-medium text-[#c9342f] hover:bg-[#fff1f0]"
                  >
                    <Trash2 size={14} /> Delete presentation
                  </button>
                </div>
              </main>
            ) : (
              <main className="flex items-center justify-center rounded-3xl border border-black/[0.06] bg-white p-10 text-sm text-[#6e6e73]">
                Select a presentation.
              </main>
            )}

            <aside className="rounded-3xl border border-black/[0.06] bg-white p-5">
              {active && selectedSlide && active.current_revision_id ? (
                <>
                  <div className="flex items-center gap-2">
                    <PresentationIcon size={17} className="text-[#0071e3]" />
                    <h3 className="font-semibold">Revise this slide</h3>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-[#6e6e73]">
                    Selected: {selectedSlide.title}. Other slides remain unchanged.
                  </p>
                  <div
                    role="region"
                    aria-label={`Follow-up conversation for ${selectedSlide.title}`}
                    className="mt-4 max-h-80 space-y-3 overflow-y-auto rounded-2xl bg-[#f5f5f7] p-3"
                  >
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#86868b]">
                      Slide follow-ups
                    </p>
                    {slideFollowups.length === 0
                      && pendingFeedback?.slideId !== selectedSlide.slide_id && (
                      <p className="text-xs leading-5 text-[#86868b]">
                        No suggestions for this slide yet.
                      </p>
                    )}
                    {slideFollowups.map(revision => (
                      <div
                        key={revision.id}
                        aria-label={`Slide feedback revision ${revision.revision_number}`}
                        className="space-y-2"
                      >
                        <p className="ml-6 rounded-2xl rounded-br-md bg-[#0071e3] px-3 py-2 text-xs leading-5 text-white">
                          {revision.change_summary}
                        </p>
                        <div className="mr-6 rounded-2xl rounded-bl-md bg-white px-3 py-2 text-xs leading-5 text-[#3a3a3c]">
                          {revision.status === 'ready' ? (
                            <button
                              type="button"
                              disabled={!revision.specification}
                              onClick={() => setViewedRevisionId(
                                viewedRevisionId === revision.id ? null : revision.id,
                              )}
                              className="text-left underline decoration-dotted underline-offset-2 hover:text-[#0071e3] disabled:no-underline"
                            >
                              Applied in revision {revision.revision_number}.{' '}
                              {revision.specification
                                ? (viewedRevisionId === revision.id
                                    ? 'Viewing these slides — click to return to latest.'
                                    : 'View these slides.')
                                : 'This slide changed; all other slides were preserved.'}
                            </button>
                          ) : revision.status === 'failed' ? (
                            <p className="text-[#c9342f]">
                              I could not apply this suggestion. The previous ready slide remains active.
                            </p>
                          ) : (
                            <p>PresentationAgent is applying this suggestion…</p>
                          )}
                        </div>
                      </div>
                    ))}
                    {pendingFeedback?.slideId === selectedSlide.slide_id && (
                      <div aria-label="Pending slide feedback" className="space-y-2">
                        <p className="ml-6 rounded-2xl rounded-br-md bg-[#0071e3] px-3 py-2 text-xs leading-5 text-white">
                          {pendingFeedback.content}
                        </p>
                        <p className="mr-6 animate-pulse rounded-2xl rounded-bl-md bg-white px-3 py-2 text-xs leading-5 text-[#6e6e73]">
                          PresentationAgent is reviewing this slide…
                        </p>
                      </div>
                    )}
                  </div>
                  <textarea
                    aria-label="Slide feedback"
                    value={feedback}
                    onChange={event => setFeedback(event.target.value)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault()
                        if (feedback.trim() && !isRevising) void submitFeedback()
                      }
                    }}
                    placeholder="Make the chart clearer, rewrite the headline, add a comparison…"
                    className="mt-4 min-h-32 w-full resize-y rounded-2xl border border-black/10 bg-[#fbfbfd] p-3 text-sm outline-none focus:border-black/20"
                    disabled={isRevising}
                  />
                  <button
                    type="button"
                    aria-label="Apply slide feedback"
                    onClick={() => void submitFeedback()}
                    disabled={!feedback.trim() || isRevising}
                    className="mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-[#0071e3] px-4 text-sm font-medium text-white disabled:bg-[#d2d2d7]"
                  >
                    {isRevising ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                    {isRevising ? 'PresentationAgent is revising…' : 'Apply slide feedback'}
                  </button>

                  <div className="mt-7 border-t border-black/[0.06] pt-5">
                    <div className="flex items-center gap-2">
                      <ImagePlus size={16} className="text-[#0071e3]" />
                      <p className="text-sm font-semibold">Slide imagery</p>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-[#6e6e73]">
                      {selectedSlideImage
                        ? 'Describe one change. FLUX edits the current pixels and preserves the rest of the slide.'
                        : 'Optional. HiDream creates the first image while the deck remains usable.'}
                    </p>
                    <textarea
                      aria-label="Slide image prompt"
                      value={imagePrompt}
                      onChange={event => setImagePrompt(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault()
                          const blocked = isGeneratingImage
                            || Boolean(selectedSlideImage && !imagePrompt.trim())
                          if (!blocked) void addSlideImage()
                        }
                      }}
                      placeholder={selectedSlideImage
                        ? 'Example: Make only the horse chestnut brown.'
                        : 'Optional visual direction; leave blank to use the slide content.'}
                      className="mt-3 min-h-24 w-full resize-y rounded-2xl border border-black/10 bg-[#fbfbfd] p-3 text-sm outline-none focus:border-black/20"
                      disabled={isGeneratingImage}
                    />
                    <button
                      type="button"
                      aria-label={selectedSlideImage
                        ? 'Refine slide image'
                        : 'Generate slide image'}
                      onClick={() => void addSlideImage()}
                      disabled={isGeneratingImage || Boolean(selectedSlideImage && !imagePrompt.trim())}
                      className="mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-full border border-[#0071e3]/25 bg-[#eef8ff] px-4 text-sm font-medium text-[#0066cc] disabled:text-[#86868b]"
                    >
                      {isGeneratingImage
                        ? <Loader2 size={16} className="animate-spin" />
                        : <ImagePlus size={16} />}
                      {isGeneratingImage
                        ? (selectedSlideImage ? 'Refining with FLUX…' : 'Generating with HiDream…')
                        : (selectedSlideImage ? 'Refine slide image' : 'Generate slide image')}
                    </button>
                  </div>

                  <div className="mt-7 border-t border-black/[0.06] pt-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#86868b]">Revision history</p>
                    <div className="mt-3 space-y-3">
                      {active.revisions.map(revision => (
                        <div key={revision.id} className="rounded-2xl bg-[#f5f5f7] px-3 py-2.5">
                          <div className="flex justify-between gap-2 text-xs">
                            <span className="font-semibold">Revision {revision.revision_number}</span>
                            <span className={revision.status === 'ready' ? 'text-[#248a3d]' : revision.status === 'failed' ? 'text-[#c9342f]' : 'text-[#86868b]'}>
                              {revision.status}
                            </span>
                          </div>
                          <p className="mt-1 line-clamp-3 text-[11px] leading-4 text-[#6e6e73]">{revision.change_summary}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-[#6e6e73]">Select a deck and slide to provide feedback.</p>
              )}
            </aside>
          </div>
        )}
      </div>
    </section>
  )
}

export default PresentationPanel
