"use client";

import { useEffect, useState } from "react";
import { adminStatus, jobs, queueAdminScan, queueClustering, updateAdminSettings } from "../../lib/api";
import type { AdminStatus, Job } from "../../types";

export default function SettingsPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [items, setItems] = useState<Job[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function reload() {
    setStatus(await adminStatus());
    setItems(await jobs());
  }

  useEffect(() => {
    reload()
      .catch(() => setMessage("Admin API unavailable. Check that the API service is ready, then refresh."))
      .finally(() => setLoading(false));
  }, []);

  async function toggleWatch() {
    if (!status) return;
    await updateAdminSettings({ watch_enabled: status.settings.watch_enabled === "1" ? "0" : "1" });
    await reload();
  }

  async function setBackfill(value: "prompt" | "backfill") {
    await updateAdminSettings({ watch_backfill: value });
    await reload();
  }

  if (!status) return <main><div className="eyebrow">Operations</div><h1>Admin</h1><p className="muted">{loading ? "Loading admin state…" : message}</p></main>;
  const watching = status.settings.watch_enabled === "1";
  const watchInitialized = status.settings.watch_initialized === "1";
  return <main>
    <div className="eyebrow">Operations</div><h1>Admin</h1>
    <p className="lead">The app starts parked. Nothing watches or processes the mounted library until you enable it here.</p>
    <h2>Watch & ingest</h2>
    <div className="cards">
      <div className="card"><strong>Mounted directory</strong><p className="muted">{status.watch_root} · {status.root_available ? "available" : "not available"}</p><p className="hint">Change the host mount in Docker Compose, then restart Docker.</p></div>
      <div className="card actionCard"><strong>Continuous watch</strong><p className="muted">{watching ? "Enabled" : "Paused"}</p><p className="hint">Automatically import photos added to the library while watch is enabled.</p><fieldset className="radioGroup" disabled={watchInitialized}><legend>Existing photos</legend><p className="radioPrompt">When watch starts, what should happen to photos already in your library?</p><label className="radioOption"><input type="radio" name="watch-backfill" value="prompt" checked={status.settings.watch_backfill !== "backfill"} onChange={() => setBackfill("prompt")} /> <span className="radioCopy"><span>New photos only</span><span className="radioDescription">Leave existing photos untouched.</span></span></label><label className="radioOption"><input type="radio" name="watch-backfill" value="backfill" checked={status.settings.watch_backfill === "backfill"} onChange={() => setBackfill("backfill")} /> <span className="radioCopy"><span>Existing and new photos</span><span className="radioDescription">Import the current library, then watch for new photos.</span></span></label></fieldset>{watchInitialized && <p className="hint">The initial watch setup is complete.</p>}<button className="button cardAction" onClick={toggleWatch}>{watching ? "Pause watch" : "Enable watch"}</button></div>
      <div className="card actionCard"><strong>Library scan</strong><p className="muted">Import all existing media immediately, without enabling continuous watch.</p><button className="button cardAction" onClick={() => queueAdminScan().then(() => setMessage("Library scan queued."))}>Scan library now</button></div>
    </div>
    <h2>Jobs</h2>
    <div className="cards">{items.map((job) => <div className="card" key={job.id}><strong>#{job.id} · {job.kind}</strong><span className="muted">{job.status} · {Math.round(job.progress * 100)}%</span>{job.error && <p className="status">{job.error}</p>}</div>)}</div>
    {items.length === 0 && <p className="muted">No jobs yet.</p>}
    <h2>Clustering</h2><button className="button" onClick={() => queueClustering().then(() => setMessage("Clustering queued."))}>Run clustering</button>
    <h2>Status</h2><div className="cards"><div className="card"><strong>Catalog</strong><span className="muted">{status.counts.assets} assets · {status.counts.faces} faces · {status.counts.persons} people</span></div><div className="card"><strong>Models</strong><span className="muted">{status.models_ready ? "Ready" : "Loading"}</span></div>{status.disk && <div className="card"><strong>Disk</strong><span className="muted">{Math.round(status.disk.free / 1e9)} GB free</span></div>}</div>
    <p className="status" aria-live="polite">{message}</p>
  </main>;
}
