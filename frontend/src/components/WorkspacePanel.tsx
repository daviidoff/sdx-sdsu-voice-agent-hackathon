import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent, ReactNode } from 'react'
import { GripHorizontal, Maximize2, X } from 'lucide-react'

/** Floating desktop window; a single focused bottom sheet on smaller screens. */
export function WorkspacePanel({ title, side = 'left', open, active, onFocus, onClose, children, resetKey = 0 }: {
  title: string; side?: 'left' | 'right'; open: boolean; active: boolean
  onFocus: () => void; onClose: () => void; children: ReactNode; resetKey?: number
}) {
  const panel = useRef<HTMLElement>(null)
  const [rect, setRect] = useState<{ x: number; y: number; width: number; height: number }>()
  const gesture = useRef<{ mode: 'move' | 'resize'; x: number; y: number; rect: NonNullable<typeof rect> }>(null)
  const constrain = (value: NonNullable<typeof rect>) => {
    const parent = panel.current?.parentElement
    if (!parent) return value
    const width = Math.min(Math.max(280, value.width), parent.clientWidth - 24)
    const height = Math.min(Math.max(220, value.height), parent.clientHeight - 24)
    return { width, height, x: Math.max(12, Math.min(value.x, parent.clientWidth - width - 12)), y: Math.max(12, Math.min(value.y, parent.clientHeight - height - 12)) }
  }
  const [lastReset, setLastReset] = useState(resetKey)
  if (lastReset !== resetKey) { setLastReset(resetKey); setRect(undefined) }
  useEffect(() => {
    const parent = panel.current?.parentElement
    if (!parent) return
    const observer = new ResizeObserver(() => setRect((value) => value ? constrain(value) : value))
    observer.observe(parent)
    return () => observer.disconnect()
  }, [])
  const start = (event: PointerEvent<HTMLElement>, mode: 'move' | 'resize') => {
    if (event.button !== 0 || window.matchMedia('(max-width: 900px)').matches) return
    if ((event.target as HTMLElement).closest('button') && mode === 'move') return
    const node = panel.current!
    gesture.current = { mode, x: event.clientX, y: event.clientY, rect: { x: node.offsetLeft, y: node.offsetTop, width: node.offsetWidth, height: node.offsetHeight } }
    event.currentTarget.setPointerCapture(event.pointerId)
    onFocus()
    event.preventDefault()
  }
  const move = (event: PointerEvent<HTMLElement>) => {
    const current = gesture.current
    if (!current) return
    const dx = event.clientX - current.x, dy = event.clientY - current.y
    setRect(constrain(current.mode === 'move'
      ? { ...current.rect, x: current.rect.x + dx, y: current.rect.y + dy }
      : { ...current.rect, width: current.rect.width + dx, height: current.rect.height + dy }))
  }
  const stop = () => { gesture.current = null }
  const style: CSSProperties = rect ? { left: rect.x, top: rect.y, width: rect.width, height: rect.height, right: 'auto', bottom: 'auto' } : {}
  return <section ref={panel} aria-label={`${title} panel`} hidden={!open} data-active={active} data-side={side}
    className="workspace-panel" style={style} onPointerDownCapture={onFocus} onFocusCapture={onFocus}>
    <header className="workspace-panel-handle" tabIndex={0} aria-label={`Move ${title} panel with arrow keys`}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget || window.matchMedia('(max-width: 900px)').matches) return
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
        event.preventDefault()
        const node = panel.current!
        setRect(constrain({ x: node.offsetLeft + (event.key === 'ArrowRight' ? 24 : event.key === 'ArrowLeft' ? -24 : 0), y: node.offsetTop + (event.key === 'ArrowDown' ? 24 : event.key === 'ArrowUp' ? -24 : 0), width: node.offsetWidth, height: node.offsetHeight }))
      }} onPointerDown={(e) => start(e, 'move')} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}>
      <GripHorizontal className="panel-grip size-4 text-muted-foreground" aria-hidden="true" />
      <h2 className="min-w-0 flex-1 truncate text-xs font-semibold">{title}</h2>
      <button className="panel-icon panel-reset" aria-label={`Reset ${title} position`} title="Reset position and size" onClick={() => setRect(undefined)}><Maximize2 className="size-3.5" /></button>
      <button className="panel-icon" aria-label={`Close ${title}`} title="Close panel" onClick={onClose}><X className="size-4" /></button>
    </header>
    <div className="min-h-0 min-w-0 flex-1 overflow-auto">{children}</div>
    <div role="separator" aria-label={`Resize ${title}`} aria-orientation="horizontal" tabIndex={0} className="panel-resize"
      onPointerDown={(e) => start(e, 'resize')} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}
      onKeyDown={(event) => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
        event.preventDefault()
        const node = panel.current!
        setRect(constrain({ x: node.offsetLeft, y: node.offsetTop, width: node.offsetWidth + (event.key === 'ArrowRight' ? 24 : event.key === 'ArrowLeft' ? -24 : 0), height: node.offsetHeight + (event.key === 'ArrowDown' ? 24 : event.key === 'ArrowUp' ? -24 : 0) }))
      }} />
  </section>
}
