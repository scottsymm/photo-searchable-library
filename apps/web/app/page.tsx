"use client";

import { FormEvent, useState } from "react";
import { search } from "../lib/api";
import { parseQuery } from "../lib/search-parser";
import type { Asset } from "../types";

export default function Home() {
  const [query, setQuery] = useState("");
  const [assets, setAssets] = useState<Asset[]>([]);
  const [status, setStatus] = useState("Try: “birthday cake at the beach”");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseQuery(query);
    setStatus("Searching your library…");
    try {
      const results = await search({ q: parsed.text, ...parsed });
      setAssets(results);
      setStatus(`${results.length} result${results.length === 1 ? "" : "s"}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Search unavailable");
    }
  }

  return (
    <main>
      <div className="eyebrow">Private visual archive</div>
      <h1>Find the photo you can almost remember.</h1>
      <p className="lead">Search by what happened, who was there, where it was, or when it happened. Your originals stay on your machine.</p>
      <form className="searchForm" onSubmit={submit}>
        <input className="searchInput" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="a picnic with Sam in 2021" aria-label="Search photos" />
        <button className="button" type="submit">Search</button>
      </form>
      <p className="hint">Structured filters also work: <code>who:Sam place:Lisbon before:2020</code></p>
      <p className="status" aria-live="polite">{status}</p>
      <div className="grid">
        {assets.map((asset) => (
          <figure className="photo" key={asset.id}>
            <img src={`${process.env.NEXT_PUBLIC_PICS_API_URL ?? "http://localhost:8000"}${asset.thumbnail_url}`} alt={asset.path} />
            <figcaption>{asset.taken_at ?? asset.place_city ?? asset.path}</figcaption>
          </figure>
        ))}
      </div>
    </main>
  );
}
