import { ArrowUpRight, MapPinned, MessageSquareText, PhoneCall, ScanSearch } from 'lucide-react'

export function OutreachOverview({ completed, needs }: { completed: number; needs: number }) {
  return <div className="outreach-overview h-full overflow-y-auto p-6">
    <div className="mb-7 flex items-center gap-2 text-xs font-medium text-teal-800"><span className="size-1.5 rounded-full bg-teal-600" /> SAN DIEGO</div>
    <div className="mb-5 flex size-12 items-center justify-center rounded-2xl border border-teal-200 bg-teal-50 text-teal-700"><MessageSquareText className="size-6" strokeWidth={1.6} /></div>
    <h2 className="text-2xl font-semibold tracking-tight">Every conversation.<br />A clearer picture.</h2>
    <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">Discover local contacts, learn what they need, and bring their reports into one place.</p>
    <div className="my-6 grid grid-cols-2 gap-3">
      <div className="rounded-xl border bg-white p-4"><div className="text-2xl font-semibold tabular-nums">{completed}</div><div className="mt-1 text-xs text-muted-foreground">Completed calls</div></div>
      <div className="rounded-xl border bg-white p-4"><div className="text-2xl font-semibold tabular-nums">{needs}</div><div className="mt-1 text-xs text-muted-foreground">Reported assistance needs</div></div>
    </div>
    <div className="mb-4 flex items-center justify-between"><h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Start an outreach</h3><ArrowUpRight className="size-4 text-muted-foreground" /></div>
    <ol className="space-y-5">
      {[
        { icon: MapPinned, title: 'Choose an area', text: 'Select published instruction areas in the list or on the map.' },
        { icon: ScanSearch, title: 'Find a local contact', text: 'Run a search, then select a discovered clinic to review its details.' },
        { icon: PhoneCall, title: 'Hear what’s needed', text: 'Choose Open clinic caller and answer with your microphone. You play the clinic.' },
      ].map(({ icon: Icon, title, text }, index) => <li key={title} className="flex gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-white text-slate-600"><Icon className="size-4" /></span>
        <div><h4 className="text-sm font-medium"><span className="mr-1 text-muted-foreground">0{index + 1}</span> {title}</h4><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{text}</p></div>
      </li>)}
    </ol>
  </div>
}
