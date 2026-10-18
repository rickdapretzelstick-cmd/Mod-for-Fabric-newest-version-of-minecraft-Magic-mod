export async function api<T = any>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let data: any = text; try { data = JSON.parse(text); } catch { /* keep text */ }
  if (!r.ok) throw new Error(typeof data === "object" && data?.detail ? String(data.detail) : text || r.statusText);
  return data as T;
}
