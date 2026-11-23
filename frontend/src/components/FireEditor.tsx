import { PencilRuler, RotateCcw, Trash2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import type { SimulatedFire } from '@/types'

export function FireEditor({ fire, fires, busy, drawing, onChange, onDraw, onSave, onReplay, onDelete, onClose, onSelect }: {
  fire: SimulatedFire; fires: SimulatedFire[]; busy: boolean; drawing: boolean
  onChange: (fire: SimulatedFire) => void; onDraw: () => void; onSave: () => void; onReplay: () => void
  onDelete: () => void; onClose: () => void; onSelect: (fire: SimulatedFire) => void
}) {
  const saved = fires.find(({ id }) => id === fire.id)
  const ignitionChanged = JSON.stringify(fire.polygon) !== JSON.stringify(saved?.polygon)
  const changed = ignitionChanged || fire.label.trim() !== saved?.label
  return <div className="h-full space-y-4 overflow-y-auto p-4">
    <p className="text-sm text-muted-foreground">The fire spreads from the drawn ignition area using simulated wind and fuel. The demo repeats after burnout.</p>
    <label className="block text-xs">Fire name<Input maxLength={200} disabled={busy} className="mt-1 h-auto p-2 text-sm" value={fire.label} onChange={(event) => onChange({ ...fire, label: event.target.value })} /></label>
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={busy || drawing} onClick={onDraw}><PencilRuler />{fire.polygon.length ? 'Redraw ignition area' : 'Draw ignition area'}</Button>
      {changed && <Button disabled={busy || drawing || fire.polygon.length < 3 || !fire.label.trim()} onClick={onSave}>{busy ? 'Saving…' : ignitionChanged ? 'Start simulation' : 'Save name'}</Button>}
      {saved && !ignitionChanged && <Button variant="outline" disabled={busy || drawing} onClick={onReplay}><RotateCcw />Replay fire</Button>}
    </div>
    {fire.updated_at && <Button variant="destructive" disabled={busy || drawing} onClick={onDelete}><Trash2 />Delete fire</Button>}
    <Button variant="ghost" disabled={busy} onClick={onClose}>Close</Button>
    {fires.length > 0 && <div className="space-y-2 border-t pt-4"><div className="text-xs font-medium">Saved fires</div>{fires.map((item) => <button disabled={busy || drawing} key={item.id} className="block text-left text-sm underline" onClick={() => onSelect(item)}>{item.label}</button>)}</div>}
  </div>
}
