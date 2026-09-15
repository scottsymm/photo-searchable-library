"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { adminStatus, catalogOverview } from "../lib/api";

export function ParkedBanner() {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const [status, overview] = await Promise.all([adminStatus(), catalogOverview()]);
        if (!active || status.settings.watch_enabled !== "0") return;
        const source = overview.sources.find((item) => item.kind === "apple_photos");
        const searchable = source?.stages.searchable ?? 0;
        const processing = source?.stages.processing ?? 0;
        if (searchable > 0 || processing > 0) {
          const progress = processing > 0 ? `, ${processing.toLocaleString()} processing` : "";
          setMessage(`Folder watch is paused. Apple Photos: ${searchable.toLocaleString()} searchable${progress}.`);
        } else {
          setMessage("Folder watch is paused. Configure folder ingest in settings.");
        }
      } catch {
        if (active) setMessage(null);
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  return message ? <div className="parkedBanner"><Link href="/settings">{message}</Link></div> : null;
}
