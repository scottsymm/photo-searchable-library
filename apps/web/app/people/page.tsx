"use client";

import { useEffect, useState } from "react";
import { confirmSuggestion, people, queueClustering, rejectSuggestion, renamePerson } from "../../lib/api";
import type { ClusterSuggestion, Person } from "../../types";

export default function PeoplePage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [suggestions, setSuggestions] = useState<ClusterSuggestion[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    const result = await people().catch(() => ({ persons: [], suggestions: [] }));
    setPersons(result.persons);
    setSuggestions(result.suggestions.filter((item) => item.status === "unreviewed"));
  }

  useEffect(() => { reload(); }, []);

  async function cluster() {
    await queueClustering();
    setMessage("Clustering queued. Refresh after the worker completes.");
  }

  return (
    <main>
      <div className="eyebrow">Identity review</div>
      <h1>People</h1>
      <p className="lead">Clusters are suggestions, not identities. Confirm only the groups that look right; your decisions survive future clustering runs.</p>
      <button className="button" onClick={cluster}>Run clustering</button>
      <p className="status" aria-live="polite">{message}</p>
      <h2>Suggestions</h2>
      <div className="cards">
        {suggestions.map((suggestion) => <SuggestionCard key={suggestion.id} suggestion={suggestion} onDone={reload} />)}
      </div>
      {suggestions.length === 0 && <p className="muted">No unreviewed clusters. Run clustering after indexing faces.</p>}
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
