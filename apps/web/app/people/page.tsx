"use client";

import { useEffect, useState } from "react";
import { people, renamePerson } from "../../lib/api";
import type { Person } from "../../types";

export default function PeoplePage() {
  const [items, setItems] = useState<Person[]>([]);
  useEffect(() => { people().then(setItems).catch(() => setItems([])); }, []);
  return <main><div className="eyebrow">Identity review</div><h1>People</h1><p className="lead">Clusters start unnamed. Give the useful ones names, and review merge/split decisions as the archive grows.</p><div className="cards">{items.map((person) => <PersonCard key={person.id} person={person} onSaved={(name) => setItems((current) => current.map((item) => item.id === person.id ? { ...item, name } : item))} />)}</div>{items.length === 0 && <p className="muted">No face clusters yet. Run an index job first.</p>}</main>;
}

function PersonCard({ person, onSaved }: { person: Person; onSaved: (name: string) => void }) {
  const [name, setName] = useState(person.name);
  return <div className="card"><strong>{person.face_count} face{person.face_count === 1 ? "" : "s"}</strong><input className="searchInput" value={name} placeholder="Name this person" onChange={(event) => setName(event.target.value)} /><button className="button" style={{ marginTop: 10 }} onClick={() => renamePerson(person.id, name).then(() => onSaved(name))}>Save name</button></div>;
}
