import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Polls an endpoint; the UI only ever shows what the server reports. */
export function usePoll<T = any>(path: string, ms = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setData(await api<T>(path)); setError(null); } catch (e) { setError((e as Error).message); }
  }, [path]);
  useEffect(() => { load(); const t = setInterval(load, ms); return () => clearInterval(t); }, [load, ms]);
  return { data, error, reload: load };
}
