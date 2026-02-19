import { useState, useEffect, useRef, useCallback } from 'react'
import { TransformWrapper, TransformComponent, useControls } from 'react-zoom-pan-pinch'
import { X, ZoomIn, ZoomOut, RotateCcw, Box } from 'lucide-react'
import { fetchPageRegions } from '../lib/api'

function Controls({ title, onClose, showBoxes, onToggleBoxes, hasRegions }) {
  const { zoomIn, zoomOut, resetTransform } = useControls()
  return (
    <div className="flex items-center justify-between px-4 py-2 bg-black/60 text-white z-10">
      <h2 className="text-sm font-medium truncate">{title}</h2>
      <div className="flex items-center gap-2">
        {hasRegions && (
          <button
            onClick={onToggleBoxes}
            className={`p-1.5 rounded ${showBoxes ? 'bg-blue-500/60 hover:bg-blue-500/80' : 'hover:bg-white/20'}`}
            title={showBoxes ? 'Hide regions' : 'Show regions'}
          >
            <Box size={16} />
          </button>
        )}
        <button onClick={() => zoomIn()} className="p-1.5 hover:bg-white/20 rounded"><ZoomIn size={16} /></button>
        <button onClick={() => zoomOut()} className="p-1.5 hover:bg-white/20 rounded"><ZoomOut size={16} /></button>
        <button onClick={() => resetTransform()} className="p-1.5 hover:bg-white/20 rounded"><RotateCcw size={16} /></button>
        <button onClick={onClose} className="p-1.5 hover:bg-white/20 rounded ml-2"><X size={18} /></button>
      </div>
    </div>
  )
}

export default function PlanViewerModal({ pageName, title, imageUrl, selectedPointers, customHighlights = [], onClose }) {
  const modalTitle = title || pageName
  const [regions, setRegions] = useState([])
  const [showBoxes, setShowBoxes] = useState(true)

  useEffect(() => {
    fetchPageRegions(pageName).then(data => {
      let all = data.regions || []
      // If opened from workspace context, only show selected pointers
      // null = plans tree (show all), [] = workspace with none selected (show none)
      if (selectedPointers !== null && selectedPointers !== undefined) {
        const selected = new Set(selectedPointers)
        all = all.filter(r => selected.has(r.id))
      }
      setRegions(all)
    }).catch(() => {})
  }, [pageName, selectedPointers])

  const imgRef = useRef(null)
  const [imgSize, setImgSize] = useState(null)

  const onImgLoad = useCallback(() => {
    const el = imgRef.current
    if (el) setImgSize({ w: el.naturalWidth, h: el.naturalHeight })
  }, [])

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex flex-col">
      <TransformWrapper
        initialScale={1}
        minScale={0.1}
        maxScale={8}
        centerOnInit={true}
        doubleClick={{ mode: 'zoomIn', step: 0.7 }}
        wheel={{ step: 0.1 }}
      >
        <Controls
          title={modalTitle}
          onClose={onClose}
          showBoxes={showBoxes}
          onToggleBoxes={() => setShowBoxes(b => !b)}
          hasRegions={regions.length > 0 || customHighlights.length > 0}
        />
        <div className="flex-1 overflow-hidden">
          <TransformComponent
            wrapperStyle={{ width: '100%', height: '100%' }}
            contentStyle={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <div style={{ position: 'relative', display: 'inline-block' }}>
              <img
                ref={imgRef}
                src={imageUrl}
                alt={modalTitle}
                draggable={false}
                onLoad={onImgLoad}
                className="select-none"
                style={{ display: 'block' }}
              />
              {showBoxes && (regions.length > 0 || customHighlights.length > 0) && imgSize && (
                <svg
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    pointerEvents: 'none',
                  }}
                  viewBox={`0 0 ${imgSize.w} ${imgSize.h}`}
                  preserveAspectRatio="none"
                >
                  {/* Pass1 region boxes (blue) */}
                  {regions.map(r => {
                    if (!r.bbox) return null
                    const { x0, y0, x1, y1 } = r.bbox
                    return (
                      <rect
                        key={r.id}
                        x={x0 / 1000 * imgSize.w}
                        y={y0 / 1000 * imgSize.h}
                        width={(x1 - x0) / 1000 * imgSize.w}
                        height={(y1 - y0) / 1000 * imgSize.h}
                        fill="rgba(59, 130, 246, 0.08)"
                        stroke="rgba(59, 130, 246, 0.6)"
                        strokeWidth={3}
                      />
                    )
                  })}
                  {/* Custom highlights from Gemini vision (green) */}
                  {customHighlights.map((h, i) => {
                    if (!h.bbox) return null
                    const { x0, y0, x1, y1 } = h.bbox
                    return (
                      <g key={`hl-${i}`}>
                        <rect
                          x={x0 / 1000 * imgSize.w}
                          y={y0 / 1000 * imgSize.h}
                          width={(x1 - x0) / 1000 * imgSize.w}
                          height={(y1 - y0) / 1000 * imgSize.h}
                          fill="rgba(16, 185, 129, 0.1)"
                          stroke="rgba(16, 185, 129, 0.8)"
                          strokeWidth={2}
                        />
                      </g>
                    )
                  })}
                </svg>
              )}
            </div>
          </TransformComponent>
        </div>
      </TransformWrapper>
    </div>
  )
}
