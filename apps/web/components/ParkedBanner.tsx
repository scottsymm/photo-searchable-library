"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { adminStatus } from "../lib/api";

export function ParkedBanner() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    adminStatus().then((status) => setShow(status.settings.watch_enabled === "0")).catch(() => setShow(false));
  }, []);
  return show ? <div className="parkedBanner"><Link href="/settings">Photos are not being imported yet — configure ingest</Link></div> : null;
}
