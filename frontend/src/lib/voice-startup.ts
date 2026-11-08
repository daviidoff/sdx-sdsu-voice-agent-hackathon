/** Wait without leaving the UI blocked; dispose resources that arrive after cancellation. */
export function waitForStartup<T>(pending: Promise<T>, signal: AbortSignal, disposeLate?: (value: T) => void | Promise<void>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let abandoned = signal.aborted;
    const abort = () => { abandoned = true; reject(signal.reason ?? new Error('Connection cancelled.')); };
    if (abandoned) abort(); else signal.addEventListener('abort', abort, {once:true});
    pending.then(value => {
      signal.removeEventListener('abort', abort);
      if (abandoned) { void Promise.resolve(disposeLate?.(value)).catch(() => {}); return; }
      resolve(value);
    }, reason => { signal.removeEventListener('abort', abort); if (!abandoned) reject(reason); });
  });
}
