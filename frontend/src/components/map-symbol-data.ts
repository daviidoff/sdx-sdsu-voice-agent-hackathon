export type MapSymbol = { color: string; paths: readonly string[]; filledPaths: number }

// The leading paths form the filled silhouette. The remaining paths add detail.
const symbols = {
  shelter: { color: '#0f766e', filledPaths: 1, paths: ['M3 10 12 3l9 7h-2v11H5V10Z', 'M9 21v-8h6v8'] },
  school: { color: '#0f766e', filledPaths: 1, paths: ['M3 10 12 3l9 7h-2v11H5V10Z', 'M9 21v-8h6v8'] },
  care: { color: '#6d28d9', filledPaths: 1, paths: ['M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z', 'M8 12h8', 'M12 8v8'] },
  clinic: { color: '#1d4ed8', filledPaths: 1, paths: ['M8 3h8v5h5v8h-5v5H8v-5H3V8h5Z'] },
  community: { color: '#475569', filledPaths: 1, paths: ['M4 21V7l8-4 8 4v14Z', 'M9 21v-5h6v5', 'M8 8h.01M16 8h.01M8 12h.01M16 12h.01'] },
  engine: { color: '#b91c1c', filledPaths: 3, paths: ['M3 5h11v5h4l3 4v3H3Z', 'M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z', 'M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z', 'M14 10v7M5 9h7m-7 3h7'] },
  ambulance: { color: '#1d4ed8', filledPaths: 3, paths: ['M3 5h11v5h4l3 4v3H3Z', 'M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z', 'M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z', 'M14 10v7M6 10h5m-2.5-2.5v5'] },
  wheelchair_van: { color: '#1d4ed8', filledPaths: 2, paths: ['M3 5h11v5h4l3 4v3H3Z', 'M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z', 'M14 10v7M8 8h.01M8 10v2h2l1 2M6 11a2 2 0 1 0 3 3'] },
  caller: { color: '#475569', filledPaths: 1, paths: ['M6 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-2.3a1 1 0 0 0-.7-1l-4.1-1.4a1 1 0 0 0-1 .2L13.5 17a13.5 13.5 0 0 1-6.5-6.5l1.5-1.7a1 1 0 0 0 .2-1L7.3 3.7A1 1 0 0 0 6 3Z'] },
} satisfies Record<string, MapSymbol>

export const callerSymbol: MapSymbol = symbols.caller

export function facilitySymbol(type: string): MapSymbol {
  if (['assisted_living', 'memory_care', 'care_home', 'disability_support'].includes(type)) return symbols.care
  if (['health_clinic', 'clinic', 'hospital'].includes(type)) return symbols.clinic
  if (type === 'shelter' || type === 'school') return symbols[type]
  return symbols.community
}

export const crewSymbol = (kind: 'engine' | 'ambulance' | 'wheelchair_van') => symbols[kind]

// Paths are static application assets, never imported facility content.
export const symbolMarkup = (symbol: MapSymbol) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbol.paths.map((d, index) => `<path d="${d}"${index < symbol.filledPaths ? ' fill="#fff"' : ''}/>`).join('')}</svg>`
