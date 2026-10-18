import { useState } from "react";
import { api } from "./api";
import { usePoll } from "./hooks";

const ORDER = ["script", "storyboard", "characters", "visuals", "voiceover", "animation", "subtitles", "sound", "assembly", "qc", "metadata", "thumbnail"];
const fmt = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString() : "—");
const mins = (s?: number) => (s == null ? "—" : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)}s`);
const cls = (s: string) => (["approved", "uploaded", "pending_approval", "done"].includes(s) ? "ok" : ["failed", "rejected"].includes(s) ? "bad" : "warn");

function Stages({ p }: { p: any }) {
  return <div className="stages" title={ORDER.map(s => `${s}: ${p.stages[s]?.status}`).join("\n")}>{ORDER.map(s => <span key={s} className={p.stages[s]?.status} />)}</div>;
}

export function Queue() {
  const projects = usePoll<any[]>("/api/projects", 2500); const jobs = usePoll<any[]>("/api/jobs", 2500);
  const act = async (path: string) => { try { await api(path, "POST"); } catch (e) { alert((e as Error).message); } projects.reload(); jobs.reload(); };
  const active = (projects.data || []).filter(p => ["queued", "producing", "revising", "failed", "planned"].includes(p.status));
  return <>
    <h2>Production queue &amp; active renders</h2>
    {active.length === 0 && <p className="mut">Nothing in production. Create projects from the Ideas tab.</p>}
    {active.map(p => <div className="card" key={p.id}>
      <div className="row"><b>#{p.id} {p.title}</b><span className={`pill ${cls(p.status)}`}>{p.status}</span><Stages p={p} />
        <span className="mut">current: {ORDER.find(s => p.stages[s]?.status === "running") || ORDER.find(s => p.stages[s]?.status !== "done") || "—"}</span>
        <span style={{ flex: 1 }} />
        {p.status !== "producing" && <button className="btn" onClick={() => act(`/api/projects/${p.id}/${p.status === "failed" ? "retry" : "produce"}`)}>{p.status === "failed" ? "Retry failed stage" : "Start production"}</button>}
      </div>
      {ORDER.filter(s => p.stages[s]?.error).map(s => <div className="err" key={s}>{s}: {p.stages[s].error}</div>)}
    </div>)}
    <h3>Recent jobs</h3>
    <table><thead><tr><th>Job</th><th>Project</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Created</th><th>Error</th></tr></thead>
      <tbody>{(jobs.data || []).slice(0, 15).map(j => <tr key={j.id}><td>{j.id}</td><td>{j.project_id}</td><td>{j.kind} {j.params !== "{}" && <span className="mut">{j.params}</span>}</td><td><span className={`pill ${cls(j.status)}`}>{j.status}</span></td><td>{j.attempts}</td><td>{fmt(j.created_at)}</td><td className="err">{j.error}</td></tr>)}</tbody></table>
  </>;
}

export function Review() {
  const list = usePoll<any[]>("/api/projects?status=pending_approval", 4000);
  const [open, setOpen] = useState<number | null>(null);
  const items = list.data || [];
  return <>
    <h2>Awaiting your approval</h2>
    <p className="mut">Automated checks verify technical validity only. Nothing is published unless you press Approve, and then only at the visibility you pick.</p>
    {items.length === 0 && <p className="mut">No videos awaiting approval.</p>}
    {items.map(p => <Reviewer key={p.id} id={p.id} open={open === p.id} toggle={() => setOpen(open === p.id ? null : p.id)} done={list.reload} />)}
  </>;
}

function Reviewer({ id, open, toggle, done }: { id: number; open: boolean; toggle: () => void; done: () => void }) {
  const d = usePoll<any>(`/api/projects/${id}`, 8000); const p = d.data;
  const [vis, setVis] = useState("private"); const [publishAt, setPublishAt] = useState(""); const [notes, setNotes] = useState("");
  const [scope, setScope] = useState("scenes"); const [scenes, setScenes] = useState(""); const [edit, setEdit] = useState(""); const [msg, setMsg] = useState("");
  if (!p) return <div className="card">Loading…</div>;
  const go = async (what: string, body: any) => { try { const r = await api(`/api/projects/${id}/${what}`, "POST", body); setMsg(JSON.stringify(r)); done(); } catch (e) { setMsg("Error: " + (e as Error).message); } };
  const failed = (p.qc?.checks || []).filter((c: any) => !c.ok);
  return <div className="card">
    <div className="row"><b>#{p.id} {p.metadata?.title || p.title}</b><span className="mut">runtime {mins(p.runtime_s)} · generated in {mins(p.production_seconds)} · est. cost ${p.est_cost_usd}</span>
      <span className={`pill ${p.qc?.technical_passed ? "ok" : "bad"}`}>technical QC {p.qc?.technical_passed ? "passed" : "FAILED"}</span><span style={{ flex: 1 }} /><button className="btn ghost" onClick={toggle}>{open ? "Hide" : "Review"}</button></div>
    {open && <>
      <div className="row" style={{ alignItems: "flex-start", marginTop: 10 }}>
        <video controls src={`/media/${id}/final.mp4`} poster={`/media/${id}/thumbnail.jpg`} />
        <div style={{ flex: 1, minWidth: 260 }}>
          <img className="thumb" src={`/media/${id}/thumbnail.jpg`} alt="thumbnail" />
          <h3>Title</h3><div>{p.metadata?.title}</div><h3>Description</h3><div style={{ whiteSpace: "pre-wrap" }}>{p.metadata?.description}</div>
          <h3>Production</h3><div className="mut">Rendered at {p.assembly?.rendered_at}, output {p.assembly?.output}{p.assembly?.upscaled && <b className="err"> — upscaled, not native {p.assembly?.output}</b>}</div>
          <div className="mut">Errors during production: {p.errors.length === 0 ? "none" : p.errors.length}</div>
          {p.errors.map((e: any) => <div className="err" key={e.id}>{e.stage}: {e.message.split("\n")[0]}</div>)}
        </div>
      </div>
      <h3>Automated checks</h3>
      <div className="mut">{p.qc?.checks.map((c: any) => <span key={c.name} className={`pill ${c.ok ? "ok" : "bad"}`} style={{ marginRight: 4 }} title={c.detail}>{c.name}</span>)}</div>
      {failed.length > 0 && <div className="err">Failed: {failed.map((c: any) => c.name).join(", ")}</div>}
      <div className="mut">{p.qc?.creative_review}</div>
      <h3>Scenes</h3>
      <table><tbody>{p.storyboard?.scenes.map((s: any) => <tr key={s.n}><td>{s.n}</td><td><img src={`/media/${id}/scenes/s${String(s.n).padStart(2, "0")}.png`} height={70} /></td><td>{s.narration}<div className="mut">{s.prompt}</div></td></tr>)}</tbody></table>
      <h3>Decision</h3>
      <div className="row">
        <select value={vis} onChange={e => setVis(e.target.value)}><option value="private">private</option><option value="unlisted">unlisted</option><option value="public">public (if enabled in settings)</option></select>
        <input type="datetime-local" value={publishAt} onChange={e => setPublishAt(e.target.value)} title="Optional scheduled publish time" />
        <input placeholder="notes" value={notes} onChange={e => setNotes(e.target.value)} />
        <button className="btn ok" onClick={() => go("approve", { visibility: vis, publish_at: publishAt ? new Date(publishAt).toISOString() : null, notes })}>Approve</button>
        <button className="btn bad" onClick={() => confirm("Reject and archive this project?") && go("reject", { notes })}>Reject</button>
      </div>
      <h3>Request revision</h3>
      <div className="row">
        <select value={scope} onChange={e => setScope(e.target.value)}><option value="scenes">scene visuals</option><option value="narration">narration</option><option value="captions">captions</option><option value="metadata">title/description</option></select>
        {scope !== "metadata" && <input placeholder="scene numbers e.g. 2,4" value={scenes} onChange={e => setScenes(e.target.value)} />}
      </div>
      <textarea placeholder={scope === "metadata" ? 'JSON: {"title":"…","description":"…"}' : "New text/prompt applied to the first listed scene (leave blank to re-roll the take for scenes)"} value={edit} onChange={e => setEdit(e.target.value)} />
      <button className="btn warn" onClick={() => {
        const ns = scenes.split(",").map(x => parseInt(x)).filter(Boolean); let edits: any = {};
        try { edits = scope === "metadata" ? JSON.parse(edit || "{}") : edit && ns.length ? { [ns[0]]: edit } : {}; } catch { return setMsg("Invalid JSON"); }
        go("revise", { scope, scenes: ns, edits, notes });
      }}>Send revision</button>
      {msg && <div className="mut" style={{ marginTop: 8 }}>{msg}</div>}
    </>}
  </div>;
}

export function Library() {
  const l = usePoll<any[]>("/api/projects", 4000);
  const rows = (l.data || []).filter(p => ["approved", "uploaded", "rejected", "pending_approval", "uploading"].includes(p.status) || p.has_video);
  const pub = async (id: number) => { try { await api(`/api/projects/${id}/publish`, "POST"); } catch (e) { alert((e as Error).message); } l.reload(); };
  return <><h2>Completed videos</h2><table><thead><tr><th></th><th>Project</th><th>Status</th><th>Approval</th><th>Upload</th><th></th></tr></thead><tbody>
    {rows.map(p => <tr key={p.id}><td>{p.has_video && <img src={`/media/${p.id}/thumbnail.jpg`} height={64} />}</td><td>#{p.id} {p.title}<div className="mut">{mins(p.production_seconds)} · ${p.est_cost_usd}</div></td>
      <td><span className={`pill ${cls(p.status)}`}>{p.status}</span></td><td><span className={`pill ${cls(p.approval_status)}`}>{p.approval_status}</span></td>
      <td>{p.upload_status}{p.youtube_video_id && <> · <a href={`https://youtu.be/${p.youtube_video_id}`} target="_blank" rel="noreferrer">{p.youtube_video_id}</a></>}</td>
      <td>{p.status === "approved" && p.upload_status !== "uploaded" && <button className="btn" onClick={() => pub(p.id)}>Publish to YouTube</button>}</td></tr>)}</tbody></table></>;
}

export function Ideas() {
  const l = usePoll<any[]>("/api/ideas", 5000); const [n, setN] = useState(6); const [busy, setBusy] = useState(false);
  const gen = async () => { setBusy(true); try { await api(`/api/ideas/generate?count=${n}`, "POST"); } catch (e) { alert((e as Error).message); } setBusy(false); l.reload(); };
  const mk = async (id: number) => { try { const r = await api("/api/projects", "POST", { idea_id: id }); await api(`/api/projects/${r.id}/produce`, "POST"); } catch (e) { alert((e as Error).message); } l.reload(); };
  return <><h2>Story ideas</h2><div className="row"><input type="number" value={n} min={1} max={30} onChange={e => setN(+e.target.value)} style={{ width: 70 }} /><button className="btn" disabled={busy} onClick={gen}>{busy ? "Generating…" : "Generate ideas"}</button></div>
    <p className="mut">Scores are a simple heuristic on hook text, not a prediction of audience reaction. Duplicates are detected by word overlap with earlier ideas.</p>
    <table><thead><tr><th>Score</th><th>Title</th><th>Hook</th><th>Status</th><th></th></tr></thead><tbody>{(l.data || []).map(i => <tr key={i.id}><td>{i.score}</td><td>{i.title}</td><td>{i.hook}</td>
      <td><span className={`pill ${i.status === "duplicate" ? "bad" : i.status === "queued" ? "ok" : "warn"}`}>{i.status}{i.duplicate_of ? ` of #${i.duplicate_of}` : ""}</span></td>
      <td>{i.status === "new" && <button className="btn" onClick={() => mk(i.id)}>Produce</button>}</td></tr>)}</tbody></table></>;
}

export function Characters() {
  const l = usePoll<any[]>("/api/characters", 8000);
  const empty = { id: "", name: "", appearance: "", clothing: "", face: "", personality: "", style: "cinematic painterly illustration", seed: 1, colors: { cloth: "#c8492f", accent: "#f2c14e" } };
  const [f, setF] = useState<any>(empty);
  const save = async () => { try { await api("/api/characters", "POST", f); setF(empty); l.reload(); } catch (e) { alert((e as Error).message); } };
  return <><h2>Character library</h2><div className="grid">{(l.data || []).map(c => <div className="card" key={c.id}>
    <b>{c.name}</b> <span className="mut">{c.id} · seed {c.seed}</span>
    <div className="row">{c.refs.map((r: string) => <img key={r} height={160} src={`/charmedia/${c.id}/${r.split("/").pop()}`} />)}{c.refs.length === 0 && <span className="mut">No reference image yet (created on first use).</span>}</div>
    <div>{c.appearance}</div><div className="mut">{c.clothing} · {c.face}</div><div className="mut">{c.personality}</div>
    <div className="row"><span className="pill" style={{ background: c.colors.cloth }}>cloth</span><span className="pill" style={{ background: c.colors.accent, color: "#000" }}>accent</span><button className="btn ghost" onClick={() => setF(c)}>Edit</button></div></div>)}</div>
    <h3>Add / edit character</h3><div className="card"><div className="grid">
      {(["id", "name", "appearance", "clothing", "face", "personality", "style"] as const).map(k => <label key={k}>{k}<br /><input style={{ width: "100%" }} value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></label>)}
      <label>seed<br /><input type="number" value={f.seed} onChange={e => setF({ ...f, seed: +e.target.value })} /></label>
      <label>cloth colour<br /><input type="color" value={f.colors.cloth} onChange={e => setF({ ...f, colors: { ...f.colors, cloth: e.target.value } })} /></label>
      <label>accent colour<br /><input type="color" value={f.colors.accent} onChange={e => setF({ ...f, colors: { ...f.colors, accent: e.target.value } })} /></label></div>
      <button className="btn" disabled={!f.id || !f.name} onClick={save}>Save character</button></div></>;
}

export function Settings() {
  const s = usePoll<any>("/api/settings", 60000); const [msg, setMsg] = useState("");
  if (!s.data) return <p>Loading…</p>; const d = s.data;
  const put = async (patch: any) => { try { await api("/api/settings", "PUT", patch); setMsg("Saved"); s.reload(); } catch (e) { setMsg((e as Error).message); } };
  return <><h2>Production settings</h2><div className="card"><div className="row">
    <label>Quality <select value={d.quality} onChange={e => put({ quality: e.target.value })}>{Object.keys(d.quality_presets).map(k => <option key={k}>{k}</option>)}</select></label>
    <span className="mut">{d.quality_presets[d.quality].note}</span></div>
    <div className="row" style={{ marginTop: 8 }}><label>Max attempts per stage <input type="number" style={{ width: 70 }} defaultValue={d.jobs.max_attempts} onBlur={e => put({ jobs: { max_attempts: +e.target.value } })} /></label>
      <label>Stage timeout (s) <input type="number" style={{ width: 90 }} defaultValue={d.jobs.stage_timeout_s} onBlur={e => put({ jobs: { stage_timeout_s: +e.target.value } })} /></label>
      <label>Min free disk (GB) <input type="number" style={{ width: 70 }} defaultValue={d.jobs.min_free_disk_gb} onBlur={e => put({ jobs: { min_free_disk_gb: +e.target.value } })} /></label></div>
    <div className="row" style={{ marginTop: 8 }}><label>Ollama model <input defaultValue={d.llm.model} onBlur={e => put({ llm: { model: e.target.value } })} /></label>
      <label>ComfyUI checkpoint <input defaultValue={d.image.checkpoint} onBlur={e => put({ image: { checkpoint: e.target.value } })} /></label></div>
    <div className="row" style={{ marginTop: 8 }}><label><input type="checkbox" defaultChecked={d.publish.allow_public} onChange={e => put({ publish: { allow_public: e.target.checked } })} /> Allow approving as public (default off; first uploads should be private)</label></div>
    {msg && <div className="mut">{msg}</div>}</div><h3>Full configuration</h3><pre className="card">{JSON.stringify(d, null, 2)}</pre></>;
}

export function System({ status }: { status: any }) {
  const errs = usePoll<any[]>("/api/errors", 5000); const r = status?.resources; const g = r?.gpu;
  const Bar = ({ v }: { v: number }) => <div className="bar"><div style={{ width: `${Math.min(100, v)}%` }} /></div>;
  return <><h2>Hardware</h2><div className="grid">
    <div className="card"><b>CPU</b><Bar v={r?.cpu_pct || 0} />{r?.cpu_pct}%</div>
    <div className="card"><b>RAM</b><Bar v={(r?.ram_used_gb / r?.ram_total_gb) * 100 || 0} />{r?.ram_used_gb} / {r?.ram_total_gb} GB</div>
    <div className="card"><b>Disk</b>{r?.disk_free_gb} GB free of {r?.disk_total_gb} GB</div>
    <div className="card"><b>GPU</b>{g ? <><div>{g.name} · driver {g.driver} · CC {g.compute_capability}</div><Bar v={(g.vram_used_mb / g.vram_total_mb) * 100} />{g.vram_used_mb} / {g.vram_total_mb} MB · {g.util_pct}% · {g.temp_c}°C</> : <div className="mut">No NVIDIA GPU detected (nvidia-smi unavailable)</div>}</div></div>
    <h2 style={{ marginTop: 20 }}>Error log</h2><table><thead><tr><th>When</th><th>Project</th><th>Stage</th><th>Message</th></tr></thead><tbody>{(errs.data || []).map(e => <tr key={e.id}><td>{fmt(e.created_at)}</td><td>{e.project_id}</td><td>{e.stage}</td><td className="err">{e.message}</td></tr>)}</tbody></table></>;
}

export function Publishing() {
  const u = usePoll<any[]>("/api/uploads", 5000);
  return <><h2>Publishing history</h2><table><thead><tr><th>When</th><th>Project</th><th>Result</th><th>Visibility</th><th>YouTube ID</th><th>Message</th></tr></thead><tbody>
    {(u.data || []).map(x => <tr key={x.id}><td>{fmt(x.created_at)}</td><td>#{x.project_id} {x.title}</td><td><span className={`pill ${x.status === "uploaded" ? "ok" : "bad"}`}>{x.status}</span></td><td>{x.visibility}</td><td>{x.youtube_video_id}</td><td>{x.message}</td></tr>)}</tbody></table>
    {(u.data || []).length === 0 && <p className="mut">No upload attempts yet.</p>}</>;
}

export function Analytics() {
  const a = usePoll<any>("/api/analytics", 10000); const [msg, setMsg] = useState("");
  const refresh = async () => { try { setMsg(JSON.stringify(await api("/api/analytics/refresh", "POST"))); a.reload(); } catch (e) { setMsg((e as Error).message); } };
  return <><h2>Analytics</h2><div className="row"><button className="btn" onClick={refresh}>Fetch from YouTube</button><span className="mut">{msg}</span></div>
    <p className="mut">Only real numbers fetched from the YouTube Data API are shown. {a.data && !a.data.authorised && "YouTube is not authorised yet."}</p>
    <table><thead><tr><th>Fetched</th><th>Video</th><th>Views</th><th>Likes</th><th>Comments</th></tr></thead><tbody>{(a.data?.rows || []).map((r: any) => <tr key={r.id}><td>{fmt(r.fetched_at)}</td><td>{r.title}</td><td>{r.views}</td><td>{r.likes}</td><td>{r.comments}</td></tr>)}</tbody></table></>;
}
