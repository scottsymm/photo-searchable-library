import type { Asset, ClusterSuggestion, Job, Person, Place } from "../types";

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
