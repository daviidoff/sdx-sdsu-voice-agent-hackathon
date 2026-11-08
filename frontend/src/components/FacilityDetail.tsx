import type { Facility } from '@/types'
import { Badge } from '@/components/ui/badge'

function SourceLink({ url, children }: { url?: string; children: React.ReactNode }) {
  // Imported website text/URLs are untrusted data.
  if (!url || !/^https?:\/\//i.test(url)) return <span>{children}</span>
  return <a className="break-all text-blue-700 underline" href={url} target="_blank" rel="noreferrer">{children}</a>
}

export function FacilityDetail({ facility: f }: { facility: Facility }) {
  const d = f.discovery
  const phones = d?.phone_candidates.filter((p, i, all) => all.findIndex((other) => other.number === p.number && other.extension === p.extension) === i) ?? []
  return <div className="space-y-4 p-4 text-sm">
    <div><Badge variant="outline">{f.simulated ? 'Demonstration record' : d ? 'Discovered · needs review' : 'Team contact'}</Badge>
      <h2 className="mt-3 text-lg font-semibold">{f.name}</h2><p className="text-muted-foreground">{f.type.replaceAll('_', ' ')}</p></div>
    <p>{f.address || 'Street address not recorded'}<br /><span className="text-xs text-muted-foreground">{f.area}</span></p>
    {f.position && <p className="text-xs">Coordinates: {f.position.join(', ')}</p>}
    <div className="rounded-lg border bg-amber-50 p-3 text-xs">Public contact lead. Phone reachability, reception identity, current needs, and capacity are unconfirmed.</div>
    <section className="space-y-2"><h3 className="font-semibold">Phone numbers</h3>
      {d ? phones.length ? phones.map((p, i) => <div key={i} className="rounded border p-3">
        <div className="select-all font-mono">{p.number}{p.extension ? ` ext. ${p.extension}` : ''}</div>
        <div className="mt-1 text-xs text-muted-foreground">{p.role === 'reception' ? 'Labeled reception' : p.role === 'main' ? 'Labeled main / switchboard' : 'General contact'} · format checked</div>
        {p.raw && <p className="text-xs">As published: {p.raw}</p>}
        <SourceLink url={p.source_url || d.source_url}>Phone source</SourceLink>
      </div>) : <p>Phone not found.</p> : <p>{f.contact || 'Phone not recorded'}</p>}
      {d && phones.length > 1 && <p className="text-xs">Review all candidates before selecting a number.</p>}
    </section>
    {d?.website && <SourceLink url={d.website}>Facility website</SourceLink>}
    {d && <>
      <section className="space-y-2"><h3 className="font-semibold">Sources and gathered information</h3>
        {d.evidence.map((e, i) => <div key={e.evidence_id || i} className="space-y-1 rounded border p-3 text-xs">
          <SourceLink url={e.source_url}>{f.simulated ? 'Mock directory evidence' : e.source === 'osm' ? 'OpenStreetMap listing' : 'Website evidence'}</SourceLink>
          <p className="text-muted-foreground">Retrieved {new Date(e.retrieved_at).toLocaleString()}</p>
          {e.excerpt && <p className="break-words">{e.excerpt}</p>}
          {e.observed?.osm_tags && <dl className="space-y-1">{Object.entries(e.observed.osm_tags).map(([key, value]) => <div key={key}><dt className="inline font-medium">{key}: </dt><dd className="inline break-words">{value}</dd></div>)}</dl>}
        </div>)}
      </section>
      {d.flags.length > 0 && <section><h3 className="font-semibold">Review notes</h3><ul className="mt-2 list-disc space-y-1 pl-4 text-xs">{d.flags.map((flag) => <li key={flag}>{flag.replaceAll('_', ' ')}</li>)}</ul></section>}
      {d.website_enrichment && <section className="text-xs"><h3 className="mb-2 font-semibold">Website check</h3><p>{(d.website_enrichment.reason || d.website_enrichment.status).replaceAll('_', ' ')}</p>
        {d.website_enrichment.errors.map((e, i) => <p key={i} className="mt-1 break-words">{e.code.replaceAll('_', ' ')} · <SourceLink url={e.url}>Page</SourceLink></p>)}
      </section>}
      <p className="text-xs text-muted-foreground">Incident: {f.incidentId}<br />Updated {new Date(f.updatedAt!).toLocaleString()}</p>
      {d.evidence.some((e) => e.source === 'osm') && <p className="text-xs"><SourceLink url="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors · ODbL</SourceLink></p>}
    </>}
  </div>
}
