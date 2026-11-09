import type { CSSProperties } from 'react'
import { facilitySymbol } from './map-symbol-data'

export function FacilitySymbol({ type, className = '' }: { type: string; className?: string }) {
  const symbol = facilitySymbol(type)
  return <span className={`facility-symbol ${className}`} style={{ '--symbol-color': symbol.color } as CSSProperties}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {symbol.paths.map((d) => <path key={d} d={d} />)}
    </svg>
  </span>
}
