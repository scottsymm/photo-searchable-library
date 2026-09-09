"use client";

import { useEffect, useState } from "react";
import { jobs } from "../../lib/api";
import type { Job } from "../../types";

export default function SettingsPage() {
  const [items, setItems] = useState<Job[]>([]);
  useEffect(() => { jobs().then(setItems).catch(() => setItems([])); }, []);
  return <main><div className="eyebrow">Operations</div><h1>Settings</h1><p className="lead">Indexing is deliberately observable. Long-running work belongs to the worker, not the request that started it.</p><h2>Recent jobs</h2><div className="cards">{items.map((job) => <div className="card" key={job.id}><strong>#{job.id} · {job.kind}</strong><span className="muted">{job.status} · {Math.round(job.progress * 100)}%</span>{job.error && <p className="status">{job.error}</p>}</div>)}</div>{items.length === 0 && <p className="muted">No jobs yet.</p>}</main>;
}
