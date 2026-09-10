"use client";

import { useEffect, useState } from "react";
import { adminStatus, jobs, queueAdminScan, queueClustering, updateAdminSettings } from "../../lib/api";
import type { AdminStatus, Job } from "../../types";

export default function SettingsPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [items, setItems] = useState<Job[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    setStatus(await adminStatus());
    setItems(await jobs());
  }

  useEffect(() => { reload().catch(() => setMessage("Admin API unavailable")); }, []);

  async function toggleWatch() {
    if (!status) return;
    await updateAdminSettings({ watch_enabled: status.settings.watch_enabled === "1" ? "0" : "1" });
    await reload();
  }

  async function setBackfill(value: "prompt" | "backfill") {
    await updateAdminSettings({ watch_backfill: value });
    await reload();
  }

  if (!status) return <main><div className="eyebrow">Operations</div><h1>Admin</h1><p className="muted">Loading admin state…</p></main>;
  const watching = status.settings.watch_enabled === "1";
  return <main>
    <div className="eyebrow">Operations</div><h1>Admin</h1>
    <p className="lead">The app starts parked. Nothing watches or processes the mounted library until you enable it here.</p>
    <h2>Watch & ingest</h2>
    <div className="cards">
      <div className="card"><strong>Mounted directory</strong><p className="muted">{status.watch_root} · {status.root_available ? "available" : "not available"}</p><p className="hint">Change the host mount in Docker Compose, then restart Docker.</p></div>
      <div className="card"><strong>Continuous watch</strong><p className="muted">{watching ? "Enabled" : "Paused"}</p><button className="button" onClick={toggleWatch}>{watching ? "Pause watch" : "Enable watch"}</button></div>
      <div className="card"><strong>Existing photos</strong><p className="muted">Choose whether enabling watch should backfill existing files.</p><div style={{ display: "flex", gap: 8 }}><button className="button" onClick={() => setBackfill("prompt")}>New only</button><button className="button" onClick={() => setBackfill("backfill")}>Backfill</button></div><button className="button" style={{ marginTop: 10 }} onClick={() => queueAdminScan().then(() => setMessage("Backfill scan queued."))}>Run scan now</button></div>
    </div>
    <h2>Jobs</h2>
    <div className="cards">{items.map((job) => <div className="card" key={job.id}><strong>#{job.id} · {job.kind}</strong><span className="muted">{job.status} · {Math.round(job.progress * 100)}%</span>{job.error && <p className="status">{job.error}</p>}</div>)}</div>
    {items.length === 0 && <p className="muted">No jobs yet.</p>}
    <h2>Clustering</h2><button className="button" onClick={() => queueClustering().then(() => setMessage("Clustering queued."))}>Run clustering</button>
    <h2>Status</h2><div className="cards"><div className="card"><strong>Catalog</strong><span className="muted">{status.counts.assets} assets · {status.counts.faces} faces · {status.counts.persons} people</span></div><div className="card"><strong>Models</strong><span className="muted">{status.models_ready ? "Ready" : "Loading"}</span></div>{status.disk && <div className="card"><strong>Disk</strong><span className="muted">{Math.round(status.disk.free / 1e9)} GB free</span></div>}</div>
    <p className="status" aria-live="polite">{message}</p>
  </main>;
}
