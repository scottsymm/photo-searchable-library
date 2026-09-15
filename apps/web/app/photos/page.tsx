"use client";

import { useEffect, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { applePhotosSyncStatus, catalogOverview, requestApplePhotosSync, thumbnailUrl } from "../../lib/api";
import { STAGES, bridgeLabel, freshnessLabel, readinessLabel } from "../../lib/funnel";
import type { CatalogOverview, FunnelStages, SourceOverview, SourceSync } from "../../types";

function badgeClass(source: SourceOverview): string {
  if (source.ingest_mode === "manual") return "badge badgeMuted";
  if (source.ingest_mode === "watch") return source.watch_enabled ? "badge badgeOk" : "badge badgeMuted";
  if (source.readiness === "connected") return "badge badgeOk";
  if (source.readiness === "failed" || source.readiness === "authorization_required") return "badge badgeWarn";
  return "badge badgeMuted";
}

function bridgeNextStep(source: SourceOverview): string | null {
  if (source.kind !== "apple_photos") return null;
  if (source.readiness === "not_configured") return "Start the macOS bridge to connect this library.";
  if (source.readiness === "authorization_required") return "Allow Pics access to Photos when macOS prompts, then restart the bridge.";
  if (source.readiness === "inventory_pending") return "Keep the bridge running while it reports the Photos library inventory.";
  return null;
}

function sourceLabel(source: SourceOverview): string {
  if (source.ingest_mode === "manual") return "Manual upload";
  if (source.ingest_mode === "watch") return source.watch_enabled ? "Watching" : "Watch paused";
  return source.kind === "apple_photos" ? bridgeLabel(source.bridge_status) : readinessLabel(source.readiness);
}

function SourceCard(props: { source: SourceOverview; photosLibraries: { name: string; path: string }[]; sync: SourceSync | null; syncing: boolean; onSync: (full: boolean) => void; onRequestFullSync: () => void }) {
  const { source, photosLibraries, sync, syncing, onSync, onRequestFullSync } = props;
  const [copied, setCopied] = useState(false);
  const syncActive = sync !== null && ["queued", "running"].includes(sync.status);
  const numbersHidden = ["not_configured", "authorization_required", "inventory_pending"].includes(source.readiness);
  const bridgeReady = source.kind !== "apple_photos" || source.bridge_status === "connected";
  const bridgeOffline = source.kind === "apple_photos" && source.bridge_status === "offline";
  const bridgeNeedsAccess = source.kind === "apple_photos" && source.bridge_status === "authorization_required";
  return (
    <div className="card actionCard">
      <strong>{source.display_name} <span className={badgeClass(source)}>{sourceLabel(source)}</span></strong>
      {source.kind === "apple_photos" && bridgeOffline && <span className="muted">Library detected, but the macOS bridge is not connected.</span>}
      {source.kind === "apple_photos" && bridgeNeedsAccess && <span className="muted">Allow Pics access to Photos in macOS, then keep the bridge running.</span>}
      {source.kind === "apple_photos" && source.bridge_status === "inventory_pending" && <span className="muted">Connected. Reading your Photos library inventory…</span>}
      {source.kind !== "apple_photos" && (numbersHidden ? <span className="muted">{source.readiness_detail ?? "No inventory reported yet."}</span> : <div className="sourceFacts"><span>{source.stages.discovered.toLocaleString()} discovered · {source.stages.searchable.toLocaleString()} searchable</span>{source.ingest_mode === "watch" ? <span className="muted">{source.watch_enabled ? "Watching for new files" : "Continuous watch is paused"}</span> : <span className="muted">Files uploaded directly to Pics</span>}{source.ingest_mode === "watch" && <a className="cardLink" href="/settings">Manage watch settings</a>}{source.readiness === "failed" && source.readiness_detail && <span className="status">{source.readiness_detail}</span>}</div>)}
      {bridgeOffline && <details className="setupDetails"><summary>How to connect</summary><ol><li>From the Pics project folder, run the bridge command below.</li><li>Allow Photos access when macOS prompts.</li><li>Keep the bridge running, then return here.</li></ol><div className="commandRow"><code>pnpm bridge:watch</code><button className="copyButton" type="button" aria-label="Copy bridge command" onClick={() => { void navigator.clipboard.writeText("pnpm bridge:watch").then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1600); }); }}><svg aria-hidden="true" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>{copied ? "Copied" : "Copy"}</button></div>{photosLibraries.length > 0 && <span className="muted">Detected library: {photosLibraries[0].path}</span>}</details>}
      {bridgeNextStep(source) && bridgeNeedsAccess && <div className="nextStep"><strong>Next step</strong><span>{bridgeNextStep(source)}</span></div>}
      {source.actions.can_sync && bridgeReady && <div className="syncControls"><button className="button" onClick={() => onSync(false)} disabled={syncing || syncActive}>{sync?.status === "queued" ? "Waiting for bridge…" : sync?.status === "running" ? "Import in progress…" : syncing ? "Requesting import…" : "Import latest 25"}</button><button className="button secondary" onClick={onRequestFullSync} disabled={syncing || syncActive}>Import entire library</button>{sync?.status === "done" && <span className="muted">Last {sync.full_sync ? "full" : "bounded"} import added {sync.imported_count.toLocaleString()} assets.</span>}{sync?.status === "partial" && <span className="status">Partial import: {sync.imported_count.toLocaleString()} imported, {sync.failed_count.toLocaleString()} failed.</span>}</div>}
      {source.kind === "uploads" && <span className="muted cardAction">Upload via CLI or API</span>}
    </div>
  );
}

export default function PhotosPage() {
  const [overview, setOverview] = useState<CatalogOverview | null>(null);
  const [sync, setSync] = useState<SourceSync | null>(null);
  const [expanded, setExpanded] = useState<keyof FunnelStages | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [confirmFullSync, setConfirmFullSync] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    catalogOverview().then(setOverview).catch((reason) => setError(reason instanceof Error ? reason.message : "Catalog overview unavailable"));
    applePhotosSyncStatus().then(setSync).catch(() => setSync(null));
  }, []);

  useEffect(() => {
    if (!sync || !["queued", "running"].includes(sync.status)) return;
    const timer = window.setInterval(() => {
      applePhotosSyncStatus().then(setSync).catch(() => undefined);
      catalogOverview().then(setOverview).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [sync]);

  async function startSync(fullSync = false) {
    setSyncing(true);
    setSyncError("");
    try { setSync(await requestApplePhotosSync(25, fullSync)); }
    catch (reason) { setSyncError(reason instanceof Error ? reason.message : "Could not request Apple Photos sync"); }
    finally { setSyncing(false); }
  }

  if (!overview) return <main><div className="eyebrow">Catalog overview</div><h1>Photos</h1><p className="muted">{error || "Reading the catalog…"}</p></main>;

  const sourceNames = Object.fromEntries(overview.sources.map((s) => [s.kind, s.display_name]));
  const faces = overview.context.faces;
  const places = overview.context.places;
  const assignedPct = faces.total > 0 ? (faces.assigned / faces.total) * 100 : 0;
  const locatedTotal = places.located + places.unlocated;
  const locatedPct = locatedTotal > 0 ? (places.located / locatedTotal) * 100 : 0;

  return <>
    <main>
      <div className="eyebrow">Catalog overview</div><h1>Photos</h1>
      <p className="lead">The state of your catalog and its connections — where every asset is, and what needs attention.</p>
      <h2>Asset funnel</h2>
      <div className="funnel">{STAGES.map((stage) => { const value = overview.funnel[stage.key]; const classes = ["funnelStage"]; if (stage.tone === "goal") classes.push("funnelStageGoal"); if (stage.tone === "bad" && value > 0) classes.push("funnelStageBad"); if (stage.approximate) classes.push("funnelStageApprox"); return <button key={stage.key} className={classes.join(" ")} aria-pressed={expanded === stage.key} onClick={() => setExpanded(expanded === stage.key ? null : stage.key)}><span className="stageLabel">{stage.label}</span><span className="stageValue">{value.toLocaleString()}</span>{stage.approximate && <span className="stageApprox">approx</span>}</button>; })}</div>
      <p className="funnelNote">Discovered counts are as of each source&apos;s last report. Select a stage for its per-source breakdown.</p>
      {expanded && <div className="drilldown"><strong>{STAGES.find((s) => s.key === expanded)?.label} — by source</strong>{overview.sources.map((source) => { const value = source.stages[expanded]; const max = Math.max(1, ...overview.sources.map((s) => s.stages[expanded])); return <div className="barRow" key={source.kind}><span>{source.display_name}</span><span className="barTrack"><span className="barFill" style={{ width: `${(value / max) * 100}%` }} /></span><strong>{value.toLocaleString()}</strong></div>; })}</div>}
      <h2>Source connections</h2>{syncError && <p className="status">{syncError}</p>}<div className="cards">{overview.sources.map((source) => <SourceCard key={source.kind} source={source} photosLibraries={overview.context.photos_libraries} sync={source.kind === "apple_photos" ? sync : null} syncing={syncing} onSync={(full) => void startSync(full)} onRequestFullSync={() => setConfirmFullSync(true)} />)}</div>
      {overview.context.photos_libraries.length > 0 && <><h2>Detected Photos libraries</h2><div className="cards">{overview.context.photos_libraries.map((library) => <div className="card" key={library.path}><strong>{library.name}</strong><span className="muted">Detected at <code>{library.path}</code>. Docker does not scan inside this Apple-managed bundle; the macOS bridge must report authorization and inventory.</span></div>)}</div></>}
      <h2>Recent imports</h2>{overview.context.recent_imports.length === 0 ? <p className="muted">No assets imported yet.</p> : <div className="thumbRow">{overview.context.recent_imports.map((asset) => <figure key={asset.id} className="photo"><img src={thumbnailUrl(asset.id)} alt={asset.original_filename ?? "Imported asset"} loading="lazy" /><figcaption>{sourceNames[asset.source_kind ?? ""] ?? "Pics"}</figcaption></figure>)}</div>}
      <h2>Catalog context</h2><div className="cards"><div className="card"><strong>Faces &amp; people</strong><span className="contextValue">{faces.total.toLocaleString()} faces</span><span className="muted">{faces.assigned.toLocaleString()} assigned to people · {faces.unassigned.toLocaleString()} unassigned</span><div className="proportionBar"><span style={{ width: `${assignedPct}%`, background: "#2e7d4f" }} /></div></div><div className="card"><strong>Places</strong><span className="contextValue">{places.located.toLocaleString()} located</span><span className="muted">{places.unlocated.toLocaleString()} assets without location data</span><div className="proportionBar"><span style={{ width: `${locatedPct}%`, background: "#4f6b8a" }} /></div></div></div>
    </main>
    <ConfirmDialog open={confirmFullSync} title="Run a full Apple Photos sync?" description="Pics will scan the entire Photos library and import only assets it does not already know about. The local bridge must be running." confirmLabel="Start full sync" onCancel={() => setConfirmFullSync(false)} onConfirm={() => { setConfirmFullSync(false); void startSync(true); }} />
  </>;
}
