import { useState } from "react";
import { api } from "./api";
import { usePoll } from "./hooks";
import { Queue, Review, Library, Ideas, Characters, Settings, System, Publishing, Analytics } from "./pages";

const TABS = ["Queue", "Review", "Library", "Ideas", "Characters", "Settings", "System", "Publishing", "Analytics"] as const;
type Tab = typeof TABS[number];

export default function App() {
  const [tab, setTab] = useState<Tab>("Review");
  const st = usePoll<any>("/api/status", 3000);
  const s = st.data;
  const toggle = async () => { await api(`/api/worker/${s.worker_enabled ? "stop" : "start"}`, "POST"); st.reload(); };
  return (<>
    <header>
      <b>AI Video Factory</b>
      {st.error && <span className="pill bad">API unreachable: {st.error}</span>}
      {s && <>
        <span className={`pill ${s.worker_enabled ? "ok" : "warn"}`}>worker {s.worker_enabled ? "running" : "stopped"}</span>
        <button className="btn ghost" onClick={toggle}>{s.worker_enabled ? "Stop worker" : "Start worker"}</button>
        <span className="mut">LLM: {s.providers.llm} · Images: {s.providers.image} · TTS: {s.providers.tts} · Quality: {s.quality}</span>
        <span className={`pill ${s.youtube_authorised ? "ok" : "warn"}`}>YouTube {s.youtube_authorised ? "authorised" : "not authorised"}</span>
        {s.pending_approval > 0 && <span className="pill warn">{s.pending_approval} awaiting approval</span>}
      </>}
    </header>
    <nav>{TABS.map(t => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
    <main>
      {tab === "Queue" && <Queue />}{tab === "Review" && <Review />}{tab === "Library" && <Library />}{tab === "Ideas" && <Ideas />}
      {tab === "Characters" && <Characters />}{tab === "Settings" && <Settings />}{tab === "System" && <System status={s} />}
      {tab === "Publishing" && <Publishing />}{tab === "Analytics" && <Analytics />}
    </main>
  </>);
}
