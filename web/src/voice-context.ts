/** Translate persisted backend changes into current, explicitly attributed voice context. */
export type ContextEvent = {
  call_id: string;
  type: string;
  payload: Record<string, unknown> | null;
};
export type ContextCall = {
  id: string;
  revision: number;
  assessment: Record<string, unknown>;
  instruction?: {zone_id?: string | null; version?: number | null; [key: string]: unknown} | null;
};

export function voiceContext(event: ContextEvent, call: ContextCall): string | undefined {
  if (event.call_id !== call.id) return undefined;
  const payload = event.payload ?? {};
  if (event.type === 'steering.queued' && payload.instruction) {
    const selected = payload.instruction as ContextCall['instruction'];
    if (selected?.zone_id !== call.instruction?.zone_id || selected?.version !== call.instruction?.version || selected?.text !== call.instruction?.text) return undefined;
  }
  if (event.type.startsWith('job.') && payload.revision !== call.revision) return undefined;
  if (event.type === 'instruction.updated') {
    const current = call.instruction;
    if (event.payload === null ? current != null : payload.zone_id !== current?.zone_id || payload.version !== current?.version) return undefined;
    return 'CURRENT OPERATOR INSTRUCTION UPDATE. This is backend context, not caller speech. '
      + 'Supersede earlier guidance. Address changed guidance and the caller’s present concern before returning to a pending intake question. '
      + JSON.stringify(current ?? {instruction: null, message: 'Previous location-specific guidance is cleared. Resolve the current location before advising.'});
  }
  if (event.type === 'assessment.updated') {
    // An older event can be delivered after a correction. Always send the current snapshot.
    return 'CURRENT CONFIRMED FACTS from the backend, not new caller speech: '
      + JSON.stringify({revision: call.revision, assessment: call.assessment, instruction: call.instruction})
      + '. These facts supersede earlier facts. Do not ask again about fields already answered. '
      + 'If location or guidance changed, address that before resuming the pending intake question.';
  }
  return `Responder update (${event.type}). Operator context, not caller speech: ${JSON.stringify(payload)}`;
}
