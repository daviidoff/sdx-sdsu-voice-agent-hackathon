// One visual vocabulary for map pins, contact cards, and the map key.
const symbols = {
  shelter: { label: 'Shelter', color: '#0f766e', paths: ['m3 10 9-7 9 7', 'M5 9v12h14V9', 'M9 21v-8h6v8'] },
  school: { label: 'School', color: '#0f766e', paths: ['m3 10 9-7 9 7', 'M5 9v12h14V9', 'M9 21v-8h6v8'] },
  care: { label: 'Care facility', color: '#7c3aed', paths: ['M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z', 'M8 12h8', 'M12 8v8'] },
  clinic: { label: 'Health clinic', color: '#2563eb', paths: ['M8 3h8v5h5v8h-5v5H8v-5H3V8h5Z'] },
  community: { label: 'Community contact', color: '#475569', paths: ['M4 21V7l8-4 8 4v14Z', 'M9 21v-5h6v5', 'M8 8h.01M16 8h.01M8 12h.01M16 12h.01'] },
  engine: { label: 'Fire engine', color: '#b91c1c', paths: ['M3 5h11v12H3Z', 'M14 10h4l3 4v3h-7', 'M5 9h7M5 12h7', 'M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0', 'M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0'] },
  ambulance: { label: 'Ambulance', color: '#2563eb', paths: ['M3 5h11v12H3Z', 'M14 10h4l3 4v3h-7', 'M6 10h5M8.5 7.5v5', 'M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0', 'M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0'] },
  wheelchair_van: { label: 'Accessible transport', color: '#2563eb', paths: ['M12 5a1 1 0 1 0 0-2 1 1 0 0 0 0 2', 'm12 7-1 6h6l3 6', 'M11 9h5', 'M8 11a5 5 0 1 0 7 7'] },
}

export type MapSymbol = typeof symbols[keyof typeof symbols]

export function facilitySymbol(type: string): MapSymbol {
  if (['assisted_living', 'memory_care', 'care_home', 'disability_support'].includes(type)) return symbols.care
  if (['health_clinic', 'clinic', 'hospital'].includes(type)) return symbols.clinic
  if (type === 'shelter' || type === 'school') return symbols[type]
  return symbols.community
}

export const crewSymbol = (kind: 'engine' | 'ambulance' | 'wheelchair_van') => symbols[kind]

// Paths are static application assets, never imported facility content.
export const symbolMarkup = (symbol: MapSymbol) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbol.paths.map((d) => `<path d="${d}"/>`).join('')}</svg>`
