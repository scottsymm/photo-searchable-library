"use client";

import { useEffect, useState } from "react";
import { places } from "../../lib/api";
import type { Place } from "../../types";

export default function PlacesPage() {
  const [items, setItems] = useState<Place[]>([]);
  useEffect(() => { places().then(setItems).catch(() => setItems([])); }, []);
  return <main><div className="eyebrow">Geography</div><h1>Places</h1><p className="lead">A quiet index of where your camera has been.</p><div className="cards">{items.map((place) => <div className="card" key={`${place.place_city}-${place.place_country}`}><strong>{place.place_city}</strong><span className="muted">{place.place_country} · {place.count} photos</span></div>)}</div>{items.length === 0 && <p className="muted">No places indexed yet.</p>}</main>;
}
