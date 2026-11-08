import { useRef, useState } from 'react'
import { api } from '@/lib/feed'

export function DiscoveryImport({ onImported, onError }: { onImported: (message: string) => void; onError: (message: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  return <>
    <button className="shrink-0 underline" disabled={busy} onClick={() => input.current?.click()}>{busy ? 'Importing…' : 'Import crawler results'}</button>
    <input ref={input} type="file" accept=".json,application/json" className="hidden" aria-label="Crawler report JSON" onChange={async (event) => {
      const file = event.target.files?.[0]
      if (!file) return
      setBusy(true); onError('')
      try {
        if (file.size > 10_000_000) throw new Error('Report must be smaller than 10 MB.')
        const receipt = await api<{ imported: number; unchanged: number }>('/api/discovery/import', JSON.parse(await file.text()))
        onImported(`${receipt.imported} facilities saved; ${receipt.unchanged} unchanged. Select Contacts or a map marker to inspect sources.`)
      } catch (error) { onError(error instanceof Error ? error.message : 'Import failed') }
      finally { setBusy(false); event.target.value = '' }
    }} />
  </>
}
