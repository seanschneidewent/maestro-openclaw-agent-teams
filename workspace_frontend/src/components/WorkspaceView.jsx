import { useMemo, useState } from 'react'
import { FileText, ImageIcon, Wand2 } from 'lucide-react'
import { api } from '../lib/api'
import MarkdownText from './MarkdownText'

const OVERLAY_COLORS = [
  'rgba(14, 165, 233, 0.25)',
  'rgba(34, 197, 94, 0.24)',
  'rgba(245, 158, 11, 0.24)',
  'rgba(239, 68, 68, 0.22)',
  'rgba(168, 85, 247, 0.22)',
  'rgba(20, 184, 166, 0.24)',
]

const OVERLAY_BORDERS = [
  'rgba(2, 132, 199, 0.95)',
  'rgba(21, 128, 61, 0.95)',
  'rgba(180, 83, 9, 0.95)',
  'rgba(185, 28, 28, 0.9)',
  'rgba(126, 34, 206, 0.9)',
  'rgba(15, 118, 110, 0.95)',
]

function preferredThumbWidth() {
  const viewport = typeof window !== 'undefined' ? window.innerWidth : 1280
  const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1
  const contentWidth = Math.min(1152, Math.max(360, viewport - 48))
  return Math.max(900, Math.min(2400, Math.round(contentWidth * dpr)))
}

const THUMB_WIDTH = preferredThumbWidth()
const THUMB_QUALITY = 90

function PageCard({ page, onPageClick }) {
  const thumbUrl = api.getPageThumbUrl(page.page_name, THUMB_WIDTH, THUMB_QUALITY)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(false)
  const [activeBoxKey, setActiveBoxKey] = useState(null)

  const overlayBoxes = useMemo(() => {
    const pointerBboxes = page.pointer_bboxes || []
    const pointerBoxes = pointerBboxes
      .map((pb, index) => {
        const bbox = pb.bbox || {}
        const x = (bbox.x0 || 0) / 1000
        const y = (bbox.y0 || 0) / 1000
        const width = ((bbox.x1 || 0) - (bbox.x0 || 0)) / 1000
        const height = ((bbox.y1 || 0) - (bbox.y0 || 0)) / 1000

        if (width <= 0 || height <= 0) return null

        const fill = OVERLAY_COLORS[index % OVERLAY_COLORS.length]
        const border = OVERLAY_BORDERS[index % OVERLAY_BORDERS.length]

        return {
          key: pb.id,
          label: pb.label || pb.id,
          kind: 'pointer',
          style: {
            left: `${Math.max(0, Math.min(1, x)) * 100}%`,
            top: `${Math.max(0, Math.min(1, y)) * 100}%`,
            width: `${Math.max(0, Math.min(1, width)) * 100}%`,
            height: `${Math.max(0, Math.min(1, height)) * 100}%`,
            backgroundColor: fill,
            borderColor: border,
          },
        }
      })
      .filter(Boolean)

    const customHighlights = (page.custom_highlights || [])
      .map((h, index) => {
        const bbox = h.bbox || {}
        const x = (bbox.x0 || 0) / 1000
        const y = (bbox.y0 || 0) / 1000
        const width = ((bbox.x1 || 0) - (bbox.x0 || 0)) / 1000
        const height = ((bbox.y1 || 0) - (bbox.y0 || 0)) / 1000

        if (width <= 0 || height <= 0) return null

        return {
          key: `hl_${index}`,
          label: h.label || h.query || 'Highlight',
          kind: 'highlight',
          style: {
            left: `${Math.max(0, Math.min(1, x)) * 100}%`,
            top: `${Math.max(0, Math.min(1, y)) * 100}%`,
            width: `${Math.max(0, Math.min(1, width)) * 100}%`,
            height: `${Math.max(0, Math.min(1, height)) * 100}%`,
            backgroundColor: 'rgba(234, 88, 12, 0.12)',
            borderColor: 'rgba(234, 88, 12, 0.95)',
          },
        }
      })
      .filter(Boolean)

    return [...pointerBoxes, ...customHighlights]
  }, [page.pointer_bboxes, page.custom_highlights])

  const activeLabel = overlayBoxes.find((box) => box.key === activeBoxKey)?.label || null

  return (
    <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
      <div
        onClick={() => onPageClick(page.page_name, page.selected_pointers, page.custom_highlights)}
        role="button"
        tabIndex={0}
        className="w-full text-left cursor-pointer"
      >
        <div className="relative bg-slate-100">
          {!error ? (
            <>
              {!loaded && (
                <div className="w-full min-h-44 flex items-center justify-center">
                  <FileText size={32} className="text-slate-300" />
                </div>
              )}
              <img
                src={thumbUrl}
                alt={page.page_name}
                className={`w-full h-auto block ${loaded ? '' : 'opacity-0'}`}
                onLoad={() => setLoaded(true)}
                onError={() => setError(true)}
                loading="lazy"
              />

              {loaded && overlayBoxes.length > 0 && (
                <div className="absolute inset-0 pointer-events-none">
                  {overlayBoxes.map((box) => (
                    <div
                      key={box.key}
                      className="absolute border-2 rounded-sm pointer-events-auto"
                      style={box.style}
                      onClick={(event) => {
                        event.stopPropagation()
                        setActiveBoxKey((prev) => (prev === box.key ? null : box.key))
                      }}
                      role="button"
                      tabIndex={0}
                      title={box.label}
                    />
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="w-full min-h-44 flex items-center justify-center">
              <FileText size={32} className="text-slate-300" />
            </div>
          )}
        </div>
      </div>

      <div className="p-4">
        <h3 className="text-sm font-semibold text-slate-800">{page.page_name}</h3>
        {page.description && <MarkdownText content={page.description} size="xs" className="mt-1 text-slate-600" />}
        {overlayBoxes.length > 0 && (
          <div className="mt-2 flex gap-1.5 flex-wrap">
            {overlayBoxes.some((box) => box.kind === 'pointer') && (
              <span className="text-[11px] px-2 py-1 rounded-full bg-cyan-50 text-cyan-700 border border-cyan-200">
                {overlayBoxes.filter((box) => box.kind === 'pointer').length} pointer
                {overlayBoxes.filter((box) => box.kind === 'pointer').length === 1 ? '' : 's'}
              </span>
            )}
            {overlayBoxes.some((box) => box.kind === 'highlight') && (
              <span className="text-[11px] px-2 py-1 rounded-full bg-orange-50 text-orange-700 border border-orange-200">
                {overlayBoxes.filter((box) => box.kind === 'highlight').length} highlight
                {overlayBoxes.filter((box) => box.kind === 'highlight').length === 1 ? '' : 's'}
              </span>
            )}
          </div>
        )}
        {activeLabel && <div className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-2 mt-2">{activeLabel}</div>}
      </div>
    </div>
  )
}

function GeneratedImageCard({ image, wsSlug, onImageClick }) {
  const thumbUrl = api.getGeneratedImageThumbUrl(wsSlug, image.filename, THUMB_WIDTH, THUMB_QUALITY)
  const fullUrl = api.getGeneratedImageUrl(wsSlug, image.filename)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(false)

  return (
    <div className="bg-white border border-emerald-200 rounded-2xl shadow-sm overflow-hidden">
      <div onClick={() => onImageClick(fullUrl, image)} role="button" tabIndex={0} className="w-full text-left cursor-pointer">
        <div className="relative bg-slate-100">
          {!error ? (
            <>
              {!loaded && (
                <div className="w-full min-h-44 flex items-center justify-center">
                  <ImageIcon size={32} className="text-emerald-300" />
                </div>
              )}
              <img
                src={thumbUrl}
                alt={image.prompt || 'Generated image'}
                className={`w-full h-auto block ${loaded ? '' : 'opacity-0'}`}
                onLoad={() => setLoaded(true)}
                onError={() => setError(true)}
                loading="lazy"
              />
            </>
          ) : (
            <div className="w-full min-h-44 flex items-center justify-center">
              <ImageIcon size={32} className="text-slate-300" />
            </div>
          )}
        </div>
      </div>

      <div className="p-4">
        <div className="flex items-center gap-1.5 mb-1">
          <Wand2 size={12} className="text-emerald-600" />
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">AI Generated</span>
        </div>
        <MarkdownText content={image.prompt} size="xs" className="mt-1.5 text-slate-600" />
        {image.description && image.description !== image.prompt && (
          <MarkdownText content={image.description} size="xs" className="mt-1 text-slate-500 italic" />
        )}
        {image.reference_pages && image.reference_pages.length > 0 && (
          <p className="text-[11px] text-slate-400 mt-1.5">Ref: {image.reference_pages.join(', ')}</p>
        )}
      </div>
    </div>
  )
}

export default function WorkspaceView({ workspace, onPageClick, onImageClick }) {
  if (!workspace) {
    return (
      <div className="flex-1 overflow-y-auto p-6 bg-gradient-to-b from-slate-50 to-white">
        <div className="max-w-6xl mx-auto bg-white border border-slate-200 rounded-xl min-h-80 flex items-center justify-center text-slate-400">
          <div className="text-center p-6">
            <FileText size={48} className="mx-auto mb-3 text-slate-300" />
            <p className="text-lg font-medium">Maestro</p>
            <p className="text-sm mt-1">Use the floating Workspaces button to pick or create a workspace</p>
          </div>
        </div>
      </div>
    )
  }

  const pages = workspace.pages || []
  const notes = workspace.notes || []
  const generatedImages = workspace.generated_images || []

  return (
    <>
      <div className="px-6 py-4 border-b border-slate-200 bg-white/95 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{workspace.title || workspace.slug}</h2>
            {workspace.description && <MarkdownText content={workspace.description} size="sm" className="mt-1 text-slate-600" />}
          </div>
          <div className="text-right text-xs text-slate-500">
            <div>{pages.length} pages</div>
            {generatedImages.length > 0 && <div>{generatedImages.length} generated</div>}
            <div>{notes.length} notes</div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 bg-gradient-to-b from-slate-50 to-white">
        <section className="max-w-6xl mx-auto space-y-4">
          {pages.map((page) => (
            <PageCard key={page.page_name} page={page} onPageClick={onPageClick} />
          ))}
          {generatedImages.map((image) => (
            <GeneratedImageCard key={image.filename} image={image} wsSlug={workspace.slug} onImageClick={onImageClick || (() => {})} />
          ))}
          {pages.length === 0 && generatedImages.length === 0 && (
            <div className="text-center text-slate-400 py-12 bg-white rounded-xl border border-slate-200">
              <p>No pages in this workspace yet</p>
            </div>
          )}
        </section>
      </div>
    </>
  )
}
