"use client";

import { useEffect, useState } from "react";
import { addAlias, confirmSuggestion, mergePersons, people, queueClustering, rejectSuggestion, removeAlias, renamePerson, searchPersons } from "../../lib/api";
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
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [busy, setBusy] = useState(false);
  async function confirm() {
    setBusy(true);
    await confirmSuggestion(suggestion.id, selectedPerson ? { person_id: selectedPerson.id } : { name });
    await onDone();
    setBusy(false);
  }
  async function reject() { setBusy(true); await rejectSuggestion(suggestion.id); await onDone(); setBusy(false); }
  return <div className="card"><strong>{suggestion.confidence} · {suggestion.face_count} faces</strong><div className="faceRow">{suggestion.faces.map((face) => <img key={face.face_id} src={`${api}${face.crop_url}`} alt="Face suggestion" />)}</div>{selectedPerson ? <div className="selectedPerson"><PersonSummary person={selectedPerson} /><button className="button secondary" disabled={busy} onClick={() => setSelectedPerson(null)}>Choose another</button></div> : <><input className="searchInput" value={name} placeholder="Name this person" onChange={(event) => setName(event.target.value)} /><PersonPicker onSelect={setSelectedPerson} /></>}<div style={{ display: "flex", gap: 8, marginTop: 10 }}><button className="button" disabled={busy || (!name.trim() && !selectedPerson)} onClick={confirm}>Confirm</button><button className="button secondary" disabled={busy} onClick={reject}>Reject</button></div></div>;
}

function PersonCard({ person, onSaved }: { person: Person; onSaved: () => void }) {
  const [name, setName] = useState(person.name);
  const [alias, setAlias] = useState("");
  const [mergeSource, setMergeSource] = useState<Person | null>(null);
  const [mergeName, setMergeName] = useState(person.name);
  const [mergeFace, setMergeFace] = useState<number | undefined>(person.prototype_face_id ?? undefined);
  const [busy, setBusy] = useState(false);
  const api = process.env.NEXT_PUBLIC_PICS_API_URL ?? "http://localhost:8000";
  async function saveName() { setBusy(true); await renamePerson(person.id, name); await onSaved(); setBusy(false); }
  async function saveAlias() { if (!alias.trim()) return; setBusy(true); await addAlias(person.id, alias); setAlias(""); await onSaved(); setBusy(false); }
  async function removePersonAlias(aliasId: number) { setBusy(true); await removeAlias(person.id, aliasId); await onSaved(); setBusy(false); }
  async function merge() {
    if (!mergeSource || !window.confirm(`Merge ${mergeSource.name || "unnamed person"} into ${person.name || "unnamed person"}?`)) return;
    setBusy(true);
    await mergePersons(person.id, mergeSource.id, { name: mergeName, representative_face_id: mergeFace });
    await onSaved();
    setMergeSource(null);
    setBusy(false);
  }
  return <div className="card personCard"><PersonSummary person={person} /><strong>{person.face_count} face{person.face_count === 1 ? "" : "s"}</strong><input className="searchInput" value={name} placeholder="Name this person" onChange={(event) => setName(event.target.value)} /><button className="button" style={{ marginTop: 10 }} disabled={busy || !name.trim()} onClick={saveName}>Save name</button><div className="aliasList">{person.aliases.map((item) => <span className="aliasChip" key={item.id}>{item.alias}<button aria-label={`Remove alias ${item.alias}`} disabled={busy} onClick={() => removePersonAlias(item.id)}>×</button></span>)}</div><div className="aliasRow"><input className="searchInput" value={alias} placeholder="Add an alias" onChange={(event) => setAlias(event.target.value)} /><button className="button secondary" disabled={busy || !alias.trim()} onClick={saveAlias}>Add alias</button></div>{mergeSource ? <div className="mergePanel"><strong>Merge with {mergeSource.name || "unnamed person"}</strong><input className="searchInput" value={mergeName} onChange={(event) => setMergeName(event.target.value)} aria-label="Final person name" /><div className="representativeChoices"><label><input type="radio" checked={mergeFace === undefined} onChange={() => setMergeFace(undefined)} /> No representative</label>{person.representative_url && <label><input type="radio" checked={mergeFace === person.prototype_face_id} onChange={() => setMergeFace(person.prototype_face_id ?? undefined)} /> Keep current face</label>}{mergeSource.representative_url && <label><input type="radio" checked={mergeFace === mergeSource.prototype_face_id} onChange={() => setMergeFace(mergeSource.prototype_face_id ?? undefined)} /> Use other person's face</label>}</div><button className="button" disabled={busy || !mergeName.trim()} onClick={merge}>Merge people</button><button className="button secondary" disabled={busy} onClick={() => setMergeSource(null)}>Cancel</button></div> : <PersonPicker excludeId={person.id} onSelect={(selected) => { setMergeSource(selected); setMergeName(person.name); setMergeFace(person.prototype_face_id ?? selected.prototype_face_id ?? undefined); }} />}</div>;
}

function PersonSummary({ person }: { person: Person }) {
  const api = process.env.NEXT_PUBLIC_PICS_API_URL ?? "http://localhost:8000";
  return <div className="personSummary">{person.representative_url ? <img src={`${api}${person.representative_url}`} alt={`${person.name || "Unnamed person"} representative`} /> : <div className="personPlaceholder" aria-hidden="true">?</div>}<span>{person.name || "Unnamed person"}</span>{person.aliases.length > 0 && <small>{person.aliases.map((item) => item.alias).join(", ")}</small>}</div>;
}

function PersonPicker({ onSelect, excludeId }: { onSelect: (person: Person) => void; excludeId?: number }) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Person[]>([]);
  useEffect(() => {
    if (!query.trim()) { setMatches([]); return; }
    let active = true;
    const timer = window.setTimeout(() => { void searchPersons(query).then((result) => { if (active) setMatches(result.filter((person) => person.id !== excludeId)); }).catch(() => { if (active) setMatches([]); }); }, 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [query, excludeId]);
  return <div className="personPicker"><input className="searchInput" value={query} placeholder="Search existing people" onChange={(event) => setQuery(event.target.value)} aria-label="Search existing people" />{matches.length > 0 && <div className="pickerResults">{matches.map((person) => <button className="pickerResult" key={person.id} onClick={() => { onSelect(person); setQuery(""); setMatches([]); }}><PersonSummary person={person} /><span>{person.face_count} faces</span></button>)}</div>}</div>;
}
