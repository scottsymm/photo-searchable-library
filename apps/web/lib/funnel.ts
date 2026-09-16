import type { BridgeStatus, FunnelStages, Readiness, SourceOverview } from "../types";

export interface StageMeta {
  key: keyof FunnelStages;
  label: string;
  approximate: boolean;
  tone: "default" | "goal" | "bad";
}

export const STAGES: StageMeta[] = [
  { key: "discovered", label: "Discovered", approximate: false, tone: "default" },
  { key: "ready_to_import", label: "Ready to import", approximate: false, tone: "default" },
  { key: "importing", label: "Importing", approximate: true, tone: "default" },
  { key: "imported", label: "Imported", approximate: false, tone: "default" },
  { key: "processing", label: "Processing", approximate: false, tone: "default" },
  { key: "searchable", label: "Searchable", approximate: false, tone: "goal" },
  { key: "failed_or_blocked", label: "Failed / Blocked", approximate: true, tone: "bad" },
];

const READINESS_LABELS: Record<Readiness, string> = {
  not_configured: "Not configured",
  authorization_required: "Authorization required",
  inventory_pending: "Inventory pending",
  connected: "Connected",
  failed: "Failed",
};

export function readinessLabel(state: Readiness): string {
  return READINESS_LABELS[state];
}

const BRIDGE_LABELS: Record<BridgeStatus, string> = {
  offline: "Bridge offline",
  authorization_required: "Photos access required",
  inventory_pending: "Reading Photos library",
  connected: "Connected",
  syncing: "Syncing",
};

export function bridgeLabel(state: BridgeStatus): string {
  return BRIDGE_LABELS[state];
}

export function freshnessLabel(source: SourceOverview, now: Date = new Date()): string {
  if (source.kind === "uploads") return "live";
  if (!source.reported_at) return "never synced";
  const then = new Date(source.reported_at);
  if (source.kind !== "mounted_folder") return `as of last sync ${then.toLocaleString()}`;
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60000));
  if (minutes < 1) return "scanned just now";
  if (minutes < 60) return `scanned ${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `scanned ${hours} h ago`;
  return `scanned ${Math.floor(hours / 24)} d ago`;
}
