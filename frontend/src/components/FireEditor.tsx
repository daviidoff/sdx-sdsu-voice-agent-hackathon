import { Flame, PencilRuler, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { SimulatedFire } from '@/types'

export function FireEditor({ fire, fires, busy, drawing, onChange, onDraw, onSave, onDelete, onClose, onSelect }: {
  fire: SimulatedFire; fires: SimulatedFire[]; busy: boolean; drawing: boolean
  onChange: (fire: SimulatedFire) => void; onDraw: () => void; onSave: () => void
  onDelete: () => void; onClose: () => void; onSelect: (fire: SimulatedFire) => void
}) {
  return <div className="h-full space-y-4 overflow-y-auto p-4">
    <div className="flex items-center gap-2 text-base font-semibold"><Flame className="size-5 text-orange-600" />Fire simulation</div>
    <p className="text-sm text-muted-foreground">Draw a fixed fire perimeter on the map. Manage caller instructions with instruction zones.</p>
    <label className="block text-xs">Fire name<input maxLength={200} disabled={busy} className="mt-1 w-full rounded border p-2 text-sm" value={fire.label} onChange={(event) => onChange({ ...fire, label: event.target.value })} /></label>
    <div className="text-xs text-muted-foreground">{drawing ? 'Click around the fire boundary, then choose Finish.' : fire.polygon.length ? `${fire.polygon.length} perimeter corners · ${fire.updated_at ? 'Saved fire; save to apply edits' : 'Draft; save to keep this fire'}` : 'Draw at least three corners to create a fire.'}</div>
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={busy || drawing} onClick={onDraw}><PencilRuler />{fire.polygon.length ? 'Redraw perimeter' : 'Draw perimeter'}</Button>
      <Button disabled={busy || drawing || fire.polygon.length < 3 || !fire.label.trim()} onClick={onSave}>{busy ? 'Saving…' : 'Save fire'}</Button>
    </div>
    {fire.updated_at && <Button variant="destructive" disabled={busy || drawing} onClick={onDelete}><Trash2 />Delete fire</Button>}
    <Button variant="ghost" disabled={busy} onClick={onClose}>Close</Button>
    {fires.length > 0 && <div className="space-y-2 border-t pt-4"><div className="text-xs font-medium">Saved fires</div>{fires.map((item) => <button disabled={busy || drawing} key={item.id} className="block text-left text-sm underline" onClick={() => onSelect(item)}>{item.label}</button>)}</div>}
  </div>
}
