"use client";

import { useEffect, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { applePhotosStatus, applePhotosSyncStatus, libraryInventory, requestApplePhotosSync } from "../../lib/api";
import type { LibraryInventory, SourceStatus, SourceSync } from "../../types";

export default function PhotosPage() {
  const [inventory, setInventory] = useState<LibraryInventory | null>(null);
  const [source, setSource] = useState<SourceStatus | null>(null);
  const [sync, setSync] = useState<SourceSync | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [confirmFullSync, setConfirmFullSync] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    libraryInventory().then(setInventory).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Library inventory unavailable");
    });
    applePhotosStatus().then(setSource).catch(() => setSource(null));
    applePhotosSyncStatus().then(setSync).catch(() => setSync(null));
  }, []);

  useEffect(() => {
    if (!sync || !["queued", "running"].includes(sync.status)) return;
    const timer = window.setInterval(() => {
      applePhotosSyncStatus().then(setSync).catch(() => undefined);
      applePhotosStatus().then(setSource).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [sync]);

  async function startSync(fullSync = false) {
    setSyncing(true);
    setSyncError("");
    try {
      setSync(await requestApplePhotosSync(25, fullSync));
    } catch (reason) {
      setSyncError(reason instanceof Error ? reason.message : "Could not request Apple Photos sync");
    } finally {
      setSyncing(false);
    }
  }

  function requestFullSync() {
    setConfirmFullSync(true);
  }

  if (!inventory) return <main><div className="eyebrow">Source inventory</div><h1>Photos</h1><p className="muted">{error || "Reading the mounted source…"}</p></main>;

  return <>
    <main>
    <div className="eyebrow">Source inventory</div>
    <h1>Photos</h1>
    <p className="lead">What Pics can see in the mounted folder, before processing. This reads filenames and directory access only; it does not read Apple&apos;s Photos database.</p>
    <div className="cards">
      <div className="card"><strong>{inventory.media_files.toLocaleString()} media files visible</strong><span className="muted">Supported image and video extensions found by the same scan used for ingest.</span></div>
      <div className="card"><strong>{inventory.catalog.mounted_assets.toLocaleString()} files indexed</strong><span className="muted">{inventory.catalog.faces.toLocaleString()} faces detected from {inventory.catalog.assets.toLocaleString()} total catalog assets.</span></div>
      <div className="card"><strong>{inventory.photos_libraries.length} Photos library{inventory.photos_libraries.length === 1 ? "" : "ies"}</strong><span className="muted">The bundle is visible, but Docker does not scan inside it. The Apple Photos bridge handles imports through PhotoKit.</span></div>
      <div className="card"><strong>{inventory.available ? "Mounted and readable" : "Not available"}</strong><span className="muted"><code>{inventory.root}</code></span></div>
    </div>
    {source && <><h2>Apple Photos bridge</h2><p className="sourceSummary">{source.imported_count > 0 ? `${source.imported_count.toLocaleString()} assets have been imported from Apple Photos and are available in Pics.` : "No Apple Photos assets have been imported yet."}</p><div className="syncControls"><button className="button" onClick={() => startSync(false)} disabled={syncing || sync?.status === "queued" || sync?.status === "running"}>{sync?.status === "queued" ? "Waiting for bridge…" : sync?.status === "running" ? "Sync in progress…" : syncing ? "Requesting sync…" : "Sync latest 25"}</button><button className="button secondary" onClick={requestFullSync} disabled={syncing || sync?.status === "queued" || sync?.status === "running"}>Full sync</button><span className="muted">The local macOS bridge must be running in watch mode. Full sync imports all missing assets.</span>{syncError && <span className="status">{syncError}</span>}{sync?.status === "done" && <span className="muted">Last {sync.full_sync ? "full" : "bounded"} sync imported {sync.imported_count.toLocaleString()} assets.</span>}{sync?.status === "partial" && <span className="status">Partial sync: {sync.imported_count.toLocaleString()} imported, {sync.failed_count.toLocaleString()} failed. {sync.error ?? "Retry the sync to try failed assets again."}</span>}{sync?.status === "error" && <span className="status">Last sync failed: {sync.error ?? "Unknown error"}</span>}</div><div className="cards"><div className="card"><strong>{source.status}</strong><span className="muted">Authorization: {source.authorization_state ?? "not requested"}</span></div><div className="card"><strong>{source.imported_count.toLocaleString()} imported</strong><span className="muted">Assets successfully added to the Pics catalog.</span></div><div className="card"><strong>{source.asset_count > 0 ? `${source.asset_count.toLocaleString()} in Apple Photos` : "Library total pending"}</strong><span className="muted">{source.asset_count > 0 ? "Assets reported during the last bridge sync." : "The bridge will report the library total on its next sync."}</span></div><div className="card"><strong>Last sync</strong><span className="muted">{source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : "Never"}</span></div></div></>}
    <h2>File types</h2>
    <div className="cards">{Object.entries(inventory.extensions).map(([extension, count]) => <div className="card" key={extension}><strong>{extension}</strong><span className="muted">{count.toLocaleString()} files</span></div>)}</div>
    {inventory.photos_libraries.length > 0 && <><h2>Photos libraries</h2><div className="cards">{inventory.photos_libraries.map((library) => <div className="card" key={library.path}><strong>{library.name}</strong><span className="muted">Bundle is visible at <code>{library.path}</code>. Contents are intentionally not traversed by Docker.</span></div>)}</div></>}
    {inventory.directory_errors.length > 0 && <><h2>Access warnings</h2><p className="status">{inventory.directory_errors.length} directories could not be read. macOS or Docker file permissions may be hiding media from the scan.</p><div className="card warningList">{inventory.directory_errors.map((warning) => <code key={warning}>{warning}</code>)}</div></>}
    {inventory.media_files === 0 && <p className="status">No supported media files are visible. Check the mounted source and grant Docker Desktop access to the folder containing the library.</p>}
    </main>
    <ConfirmDialog open={confirmFullSync} title="Run a full Apple Photos sync?" description="Pics will scan the entire Photos library and import only assets it does not already know about. The local bridge must be running." confirmLabel="Start full sync" onCancel={() => setConfirmFullSync(false)} onConfirm={() => { setConfirmFullSync(false); void startSync(true); }} />
  </>;
}
