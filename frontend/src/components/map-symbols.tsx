import type { CSSProperties } from 'react'
import { facilitySymbol } from './map-symbol-data'
import type { MapSymbol } from './map-symbol-data'

export function FacilitySymbol({ type, className = '' }: { type: string; className?: string }) {
  const symbol = facilitySymbol(type)
  return <span className={`facility-symbol ${className}`} style={{ '--symbol-color': symbol.color } as CSSProperties}>
    <SymbolGlyph symbol={symbol} />
  </span>
}

export function MapKeySymbol({ symbol, color = symbol.color }: { symbol: MapSymbol; color?: string }) {
  return <span className="map-key-symbol" style={{ color }}><SymbolGlyph symbol={symbol} filled /></span>
}

function SymbolGlyph({ symbol, filled }: { symbol: MapSymbol; filled?: boolean }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {symbol.paths.map((d, index) => <path key={d} d={d} fill={filled && index < symbol.filledPaths ? 'white' : undefined} />)}
  </svg>
}
