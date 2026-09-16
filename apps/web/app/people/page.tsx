"use client";

import { useEffect, useState } from "react";
import { confirmSuggestion, people, queueClustering, rejectSuggestion, renamePerson } from "../../lib/api";
import type { ClusterSuggestion, FaceEnrichment, Person } from "../../types";

export default function PeoplePage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [suggestions, setSuggestions] = useState<ClusterSuggestion[]>([]);
  const [message, setMessage] = useState("");
  const [enrichment, setEnrichment] = useState<FaceEnrichment>({ total: 0, embeddings_ready: 0, embeddings_pending: 0, assets_processing: 0, clustering_status: "no_faces" });

  async function reload() {
    const result = await people().catch(() => ({ persons: [], suggestions: [], enrichment: { total: 0, embeddings_ready: 0, embeddings_pending: 0, assets_processing: 0, clustering_status: "no_faces" as const } }));
    setPersons(result.persons);
    setSuggestions(result.suggestions.filter((item) => item.status === "unreviewed"));
    setEnrichment(result.enrichment);
  }

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 3000);
    return () => window.clearInterval(timer);
  }, []);

  async function cluster() {
    await queueClustering();
    setMessage("Clustering queued. Refresh after the worker completes.");
  }

  const indexing = enrichment.clustering_status === "indexing";
  const processingAssets = enrichment.assets_processing > 0;
  const clustering = enrichment.clustering_status === "queued" || enrichment.clustering_status === "running";
  const enrichmentMessage = indexing
    ? `${enrichment.embeddings_ready.toLocaleString()} of ${enrichment.total.toLocaleString()} faces indexed. This run will cover indexed faces; run clustering again when indexing finishes.`
    : processingAssets
      ? `${enrichment.assets_processing.toLocaleString()} assets are still processing. This run covers indexed faces; run it again when processing finishes.`
    : clustering
      ? "Clustering is in progress. Suggestions will appear when the worker finishes."
      : enrichment.clustering_status === "completed_no_suggestions"
        ? "Clustering completed without finding new groups."
        : enrichment.clustering_status === "no_faces" ? "No faces have been indexed yet." : "Face indexing is complete. Clustering is ready.";

  return (
    <main>
      <div className="eyebrow">Identity review</div>
      <h1>People</h1>
      <p className="lead">Clusters are suggestions, not identities. Confirm only the groups that look right; your decisions survive future clustering runs.</p>
      <div className="card enrichmentCard"><strong>Face enrichment</strong><span className="muted">{enrichmentMessage}</span><span className="muted">{enrichment.embeddings_ready.toLocaleString()} embeddings ready · {enrichment.embeddings_pending.toLocaleString()} pending</span>{processingAssets && <span className="muted">{enrichment.assets_processing.toLocaleString()} assets still processing</span>}</div>
      <button className="button" disabled={clustering || enrichment.embeddings_ready === 0} onClick={cluster}>{clustering ? "Clustering in progress…" : indexing || processingAssets ? "Cluster indexed faces" : "Run clustering"}</button>
      <p className="status" aria-live="polite">{message}</p>
      <h2>Suggestions</h2>
      <div className="cards">
        {suggestions.map((suggestion) => <SuggestionCard key={suggestion.id} suggestion={suggestion} onDone={reload} />)}
      </div>
      {suggestions.length === 0 && <p className="muted">{enrichment.clustering_status === "completed_no_suggestions" ? "No unreviewed clusters were found." : "No unreviewed clusters yet."}</p>}
      <h2>Named people</h2>
      <div className="cards">
        {persons.map((person) => <PersonCard key={person.id} person={person} onSaved={reload} />)}
      </div>
    </main>
  );
}

function SuggestionCard({ suggestion, onDone }: { suggestion: ClusterSuggestion; onDone: () => void }) {
  const api = process.env.NEXT_PUBLIC_PICS_API_URL ?? "http://localhost:8000";
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  async function confirm() { setBusy(true); await confirmSuggestion(suggestion.id, name); await onDone(); setBusy(false); }
  async function reject() { setBusy(true); await rejectSuggestion(suggestion.id); await onDone(); setBusy(false); }
  return <div className="card"><strong>{suggestion.confidence} · {suggestion.face_count} faces</strong><div className="faceRow">{suggestion.faces.map((face) => <img key={face.face_id} src={`${api}${face.crop_url}`} alt="Face suggestion" />)}</div><input className="searchInput" value={name} placeholder="Name this person" onChange={(event) => setName(event.target.value)} /><div style={{ display: "flex", gap: 8, marginTop: 10 }}><button className="button" disabled={busy || !name.trim()} onClick={confirm}>Confirm</button><button className="button secondary" disabled={busy} onClick={reject}>Reject</button></div></div>;
}

function PersonCard({ person, onSaved }: { person: Person; onSaved: () => void }) {
  const [name, setName] = useState(person.name);
  return <div className="card"><strong>{person.face_count} face{person.face_count === 1 ? "" : "s"}</strong><input className="searchInput" value={name} placeholder="Name this person" onChange={(event) => setName(event.target.value)} /><button className="button" style={{ marginTop: 10 }} onClick={() => renamePerson(person.id, name).then(onSaved)}>Save name</button></div>;
}
