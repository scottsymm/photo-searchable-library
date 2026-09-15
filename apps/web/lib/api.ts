import type { AdminSettings, AdminStatus, Asset, ClusterSuggestion, Job, LibraryInventory, Person, Place, SourceStatus, SourceSync } from "../types";

const API = process.env.NEXT_PUBLIC_PICS_API_URL ?? "http://localhost:8000";

function apiUrl(path: string): string {
  return `${API}${path}`;
}

export async function search(params: Record<string, string | undefined>): Promise<Asset[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value);
  }
  const response = await fetch(apiUrl(`/search?${query}`), { cache: "no-store" });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  return (await response.json()).results;
}

export async function people(): Promise<{ persons: Person[]; suggestions: ClusterSuggestion[] }> {
  const response = await fetch(apiUrl("/persons"), { cache: "no-store" });
  if (!response.ok) throw new Error("People request failed");
  return response.json();
}

export async function places(): Promise<Place[]> {
  const response = await fetch(apiUrl("/places"), { cache: "no-store" });
  if (!response.ok) throw new Error("Places request failed");
  return (await response.json()).places;
}

export async function jobs(): Promise<Job[]> {
  const response = await fetch(apiUrl("/jobs"), { cache: "no-store" });
  if (!response.ok) throw new Error("Jobs request failed");
  return (await response.json()).jobs;
}

export async function renamePerson(id: number, name: string): Promise<void> {
  const response = await fetch(apiUrl(`/persons/${id}`), {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw new Error("Rename failed");
}

export async function queueClustering(): Promise<void> {
  const response = await fetch(apiUrl("/persons/cluster"), { method: "POST" });
  if (!response.ok) throw new Error("Clustering request failed");
}

export async function confirmSuggestion(id: number, name: string): Promise<void> {
  const response = await fetch(apiUrl(`/persons/suggestions/${id}/confirm`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw new Error("Could not confirm cluster");
}

export async function rejectSuggestion(id: number): Promise<void> {
  const response = await fetch(apiUrl(`/persons/suggestions/${id}/reject`), { method: "POST" });
  if (!response.ok) throw new Error("Could not reject cluster");
}

export async function adminStatus(): Promise<AdminStatus> {
  const response = await fetch(apiUrl("/admin/status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Status request failed");
  return response.json();
}

export async function libraryInventory(): Promise<LibraryInventory> {
  const response = await fetch(apiUrl("/admin/library"), { cache: "no-store" });
  if (!response.ok) throw new Error("Library inventory request failed");
  return response.json();
}

export async function updateAdminSettings(update: Partial<AdminSettings>): Promise<AdminSettings> {
  const response = await fetch(apiUrl("/admin/settings"), {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) throw new Error("Settings update failed");
  return (await response.json()).settings;
}

export async function queueAdminScan(root?: string): Promise<void> {
  const response = await fetch(apiUrl("/admin/scan"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(root ? { root } : {}),
  });
  if (!response.ok) throw new Error("Scan request failed");
}

export async function applePhotosStatus(): Promise<SourceStatus> {
  const response = await fetch(apiUrl("/sources/apple-photos/status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Apple Photos status request failed");
  return (await response.json()).source;
}

export async function requestApplePhotosSync(limit = 25, full = false): Promise<SourceSync> {
  const response = await fetch(apiUrl("/sources/apple-photos/sync"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ limit, full }),
  });
  if (!response.ok) throw new Error("Apple Photos sync request failed");
  return (await response.json()).sync;
}

export async function applePhotosSyncStatus(): Promise<SourceSync | null> {
  const response = await fetch(apiUrl("/sources/apple-photos/sync/status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Apple Photos sync status request failed");
  return (await response.json()).sync;
}
