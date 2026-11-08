import { Megaphone, ShieldAlert, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import type { Zone } from '@/types'

const LEVELS: { level: Zone['level']; label: string; tone: string }[] = [
  { level: 'evacuate', label: 'Evacuate now', tone: 'border-red-300 bg-red-50 text-red-800' },
  { level: 'warning', label: 'Evacuation warning', tone: 'border-amber-300 bg-amber-50 text-amber-800' },
]

// Police / emergency services edit a marked area. Changes apply live: callers inside get this instruction.
export function ZoneEditor({
  zone,
  callersInside,
  onChange,
  onDelete,
  onNotify,
  onClose,
}: {
  zone: Zone
  callersInside: number
  onChange: (zone: Zone) => void
  onDelete: () => void
  onNotify: () => void
  onClose: () => void
}) {
  const setLevel = (level: Zone['level']) =>
    onChange({ ...zone, level, label: `Zone ${zone.id} — ${level === 'evacuate' ? 'Evacuate now' : 'Evacuation warning'}` })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between p-4">
        <div>
          <div className="flex items-center gap-1.5 text-base font-semibold"><ShieldAlert className="size-4" /> Edit zone {zone.id}</div>
          <div className="text-xs text-muted-foreground">Police / emergency services · changes apply to callers right away</div>
        </div>
        <Button size="icon" variant="ghost" onClick={onClose}><X /></Button>
      </div>
      <Separator />
      <div className="flex flex-col gap-4 p-4">
        <label className="grid gap-1.5 text-xs font-medium">
          Name
          <Input value={zone.label} onChange={(e) => onChange({ ...zone, label: e.target.value })} />
        </label>
        <div className="grid gap-1.5 text-xs font-medium">
          Level
          <div className="grid grid-cols-2 gap-2">
            {LEVELS.map((l) => (
              <button
                key={l.level}
                onClick={() => setLevel(l.level)}
                className={cn('rounded-md border px-3 py-2 text-xs font-medium', zone.level === l.level ? l.tone : 'hover:bg-muted')}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
        <label className="grid gap-1.5 text-xs font-medium">
          Instruction the agent gives callers in this zone
          <textarea
            value={zone.instruction}
            onChange={(e) => onChange({ ...zone, instruction: e.target.value })}
            rows={4}
            className="rounded-md border bg-transparent px-3 py-2 text-sm font-normal outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </label>
        <div className="rounded-md border bg-muted/50 p-3 text-xs">
          <div className="font-medium">{callersInside} active {callersInside === 1 ? 'caller' : 'callers'} inside this zone</div>
          <div className="mt-0.5 text-muted-foreground">New callers here hear this instruction automatically. Callers already on the line can be told now.</div>
          <Button size="sm" className="mt-2 w-full" onClick={onNotify} disabled={!callersInside}>
            <Megaphone /> Tell callers in this zone now
          </Button>
        </div>
        <Button size="sm" variant="destructive" onClick={onDelete}>
          <Trash2 /> Delete zone
        </Button>
      </div>
    </div>
  )
}
