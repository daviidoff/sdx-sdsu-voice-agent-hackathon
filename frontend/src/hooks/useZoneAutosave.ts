import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/feed'
import type { Zone } from '@/types'

export const zoneContent = (zone: Zone) => JSON.stringify([zone.label, zone.area, zone.level, zone.instruction, zone.polygon])
const valid = (zone: Zone) => !!(zone.label.trim() && zone.instruction.trim() && (zone.polygon.length >= 3 || zone.area?.trim()))
type Status = 'pending' | 'saving' | 'saved' | 'incomplete' | 'error'
type Job = { zone: Zone; revision: number; saving: boolean; timer?: ReturnType<typeof setTimeout>; status: Status; error?: string }

// Own the queue above the editor so closing a panel never discards a pending save.
// Serialize writes per zone so an older request cannot overwrite newer typing.
export function useZoneAutosave(onSaved: (zone: Zone, submitted: Zone) => void) {
  const jobs = useRef(new Map<string, Job>())
  const callback = useRef(onSaved)
  useEffect(() => { callback.current = onSaved }, [onSaved])
  const [statuses, setStatuses] = useState<Record<string, { status: Status; error?: string; zone: Zone; saving: boolean }>>({})
  const report = (id: string, job: Job) => setStatuses((current) => ({ ...current, [id]: { status: job.status, error: job.error, zone: job.zone, saving: job.saving } }))
  const flush = async (id: string) => {
    const job = jobs.current.get(id)
    if (!job || job.saving || !valid(job.zone)) return
    clearTimeout(job.timer)
    const revision = job.revision, submitted = job.zone
    job.saving = true; job.status = 'saving'; job.error = undefined; report(id, job)
    try {
      const saved = await api<Zone>('/api/dashboard/zones', { ...submitted, area: submitted.area?.trim() || submitted.label })
      callback.current(saved, submitted)
      job.zone = { ...job.zone, version: saved.version }
      if (job.revision === revision) job.status = 'saved'
    } catch (error) {
      if (job.revision === revision) { job.status = 'error'; job.error = error instanceof Error ? error.message : 'Could not save' }
    } finally {
      job.saving = false
      if (job.revision !== revision) {
        job.status = valid(job.zone) ? 'pending' : 'incomplete'
        clearTimeout(job.timer)
        if (valid(job.zone)) job.timer = setTimeout(() => void flush(id), 650)
      }
      report(id, job)
    }
  }
  const schedule = (zone: Zone) => {
    const previous = jobs.current.get(zone.id)
    if (previous && zoneContent(previous.zone) === zoneContent(zone)) return
    const job: Job = previous ?? { zone, revision: 0, saving: false, status: 'pending' }
    clearTimeout(job.timer)
    job.zone = zone; job.revision++; job.error = undefined
    job.status = valid(zone) ? 'pending' : 'incomplete'
    jobs.current.set(zone.id, job)
    report(zone.id, job)
    if (valid(zone)) job.timer = setTimeout(() => void flush(zone.id), 650)
  }
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if ([...jobs.current.values()].some((job) => job.saving || job.status !== 'saved')) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])
  const forget = (id: string) => { clearTimeout(jobs.current.get(id)?.timer); jobs.current.delete(id); setStatuses((current) => { const next = { ...current }; delete next[id]; return next }) }
  return { schedule, statuses, retry: (id: string) => void flush(id), forget, drafts: Object.values(statuses).filter((job) => job.status !== 'saved').map((job) => job.zone) }
}
