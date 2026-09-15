"use client";

import { useEffect, useState } from "react";
import { applePhotosStatus, libraryInventory } from "../../lib/api";
import type { LibraryInventory, SourceStatus } from "../../types";

export default function PhotosPage() {
  const [inventory, setInventory] = useState<LibraryInventory | null>(null);
  const [source, setSource] = useState<SourceStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    libraryInventory().then(setInventory).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Library inventory unavailable");
    });
    applePhotosStatus().then(setSource).catch(() => setSource(null));
  }, []);

  if (!inventory) return <main><div className="eyebrow">Source inventory</div><h1>Photos</h1><p className="muted">{error || "Reading the mounted source…"}</p></main>;

  return <main>
    <div className="eyebrow">Source inventory</div>
    <h1>Photos</h1>
    <p className="lead">What Pics can see in the mounted folder, before processing. This reads filenames and directory access only; it does not read Apple&apos;s Photos database.</p>
    <div className="cards">
      <div className="card"><strong>{inventory.media_files.toLocaleString()} media files visible</strong><span className="muted">Supported image and video extensions found by the same scan used for ingest.</span></div>
      <div className="card"><strong>{inventory.catalog.mounted_assets.toLocaleString()} files indexed</strong><span className="muted">{inventory.catalog.faces.toLocaleString()} faces detected from {inventory.catalog.assets.toLocaleString()} total catalog assets.</span></div>
      <div className="card"><strong>{inventory.photos_libraries.length} Photos library{inventory.photos_libraries.length === 1 ? "" : "ies"}</strong><span className="muted">A bundle is visible to the app, but its Apple albums and people are not imported.</span></div>
      <div className="card"><strong>{inventory.available ? "Mounted and readable" : "Not available"}</strong><span className="muted"><code>{inventory.root}</code></span></div>
    </div>
    {source && <><h2>Apple Photos bridge</h2><div className="cards"><div className="card"><strong>{source.status}</strong><span className="muted">Authorization: {source.authorization_state ?? "not requested"}</span></div><div className="card"><strong>{source.imported_count.toLocaleString()} imported</strong><span className="muted">{source.asset_count.toLocaleString()} assets reported by the bridge.</span></div><div className="card"><strong>Last sync</strong><span className="muted">{source.last_sync_at ?? "Never"}</span></div></div></>}
    <h2>File types</h2>
    <div className="cards">{Object.entries(inventory.extensions).map(([extension, count]) => <div className="card" key={extension}><strong>{extension}</strong><span className="muted">{count.toLocaleString()} files</span></div>)}</div>
    {inventory.photos_libraries.length > 0 && <><h2>Photos libraries</h2><div className="cards">{inventory.photos_libraries.map((library) => <div className="card" key={library.path}><strong>{library.name}</strong><span className="muted">Bundle is visible at <code>{library.path}</code></span></div>)}</div></>}
    {inventory.directory_errors.length > 0 && <><h2>Access warnings</h2><p className="status">{inventory.directory_errors.length} directories could not be read. macOS or Docker file permissions may be hiding media from the scan.</p><div className="card warningList">{inventory.directory_errors.map((warning) => <code key={warning}>{warning}</code>)}</div></>}
    {inventory.media_files === 0 && <p className="status">No supported media files are visible. Check the mounted source and grant Docker Desktop access to the folder containing the library.</p>}
  </main>;
}
