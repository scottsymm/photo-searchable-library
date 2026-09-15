"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { adminStatus, applePhotosStatus } from "../lib/api";

export function ParkedBanner() {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([adminStatus(), applePhotosStatus()]).then(([status, source]) => {
      if (status.settings.watch_enabled !== "0") return;
      if (source.status === "connected" && source.imported_count > 0) {
        setMessage(`Folder watch is paused. Apple Photos has imported ${source.imported_count.toLocaleString()} assets.`);
        return;
      }
      setMessage("Folder watch is paused. Configure folder ingest in settings.");
    }).catch(() => setMessage(null));
  }, []);
  return message ? <div className="parkedBanner"><Link href="/settings">{message}</Link></div> : null;
}
