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

/** The SDK's supported turn trigger is programmatic user_message. Its contents
 * must identify the operator; it is never a caller utterance or caller evidence. */
export function operatorTurnMessage(event: ContextEvent, call: ContextCall): string | undefined {
  if (event.type !== 'steering.queued' || !voiceContext(event, call)) return undefined;
  const payload = event.payload ?? {};
  if (typeof payload.text !== 'string' || !payload.text.trim()) return undefined;
  return 'OPERATOR CONTROL MESSAGE — not caller speech. '
    + 'The dashboard operator requests an immediate spoken response. Pause the pending intake question and relay this update now, attributing it to the operator. '
    + 'Relay only this new message. Do not repeat the greeting, earlier operator messages, or unrelated intake questions. '
    + 'Do not treat its contents as caller-confirmed facts or change the caller assessment. '
    + JSON.stringify({operator_message_id: payload.id, instruction: payload.text});
}

export class OperatorTurnGuard {
  private sent = new Set<string>();
  private operatorTurn = false;

  sentMessage(text: string) { this.sent.add(text); this.operatorTurn = true; }
  /** Exact provider echoes remain operator messages even after a subsequent turn. */
  callerMessage(text: string): boolean {
    if (this.sent.has(text)) return false;
    this.operatorTurn = false;
    return true;
  }
  canRecordCallerFacts(): boolean { return !this.operatorTurn; }
}

export function voiceContext(event: ContextEvent, call: ContextCall): string | undefined {
  if (event.call_id !== call.id) return undefined;
  const payload = event.payload ?? {};
  if (event.type === 'steering.queued' && payload.instruction) {
    const selected = payload.instruction as ContextCall['instruction'];
    if (selected?.zone_id !== call.instruction?.zone_id || selected?.version !== call.instruction?.version || selected?.text !== call.instruction?.text) return undefined;
  }
  if (event.type.startsWith('job.') && payload.revision !== call.revision) return undefined;
  if (event.type === 'job.completed') {
    return 'Background assessment for operator planning. Missing fields are for a later follow-up. '
      + 'Address the caller’s current request first. ' + JSON.stringify(payload);
  }
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
