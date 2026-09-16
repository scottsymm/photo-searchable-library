title: Same-Person Cluster Linking — Design
tags:
  - design
  - same-person-linking
  - face-clustering
  - people
keywords:
  - face clustering
  - person deduplication
  - person aliases
  - merge people
  - people search
  - representative face
designed: 2026-09-15
---

# Same-Person Cluster Linking — Design

Requirements source: `same-person-linking-spec.md` (same directory).

This is a UI-led feature over an identity model that already exists. The durable
`persons` table, `person_faces` links, the confirm endpoint (which already
accepts an existing `person_id`), and a `merge` endpoint are all present. The
work adds: an aliases table, an activated representative face, richer
merge/confirm contracts, a person-search endpoint, and the People UI to drive
all of it.

## Architecture Overview

Three layers change, no new services:

- **Core / schema** (`packages/core/core/schema.py`) — add a relational
  `person_aliases` table; bump schema version `3 → 4`. Migration stays additive
  and idempotent (matches the existing `CREATE TABLE IF NOT EXISTS` + guarded
  `ALTER` pattern).
- **API** (`apps/api/api/persons.py`, `apps/api/api/search.py`) — extend
  `GET /persons`, `confirm`, and `merge`; add a person-search endpoint and alias
  CRUD; make `who` photo search alias-aware.
- **Web** (`apps/web/app/people/page.tsx`, `lib/api.ts`, `types.ts`) — person
  picker on suggestion cards, a merge control with name + representative choice,
  person thumbnails, and an alias editor on person cards.

Clustering itself is untouched — splitting a person by age is correct behavior.

## Data Model

New table:

```sql
CREATE TABLE IF NOT EXISTS person_aliases (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(person_id, alias)
);
CREATE INDEX IF NOT EXISTS person_aliases_person_idx ON person_aliases(person_id);
```

Reused, previously-dormant column: `persons.prototype_face_id` becomes the
person's **representative face**. It is set on confirm (to the cluster's
representative face) and chosen explicitly on merge. `ON DELETE CASCADE` on
`person_id` means aliases disappear with a deleted (merged-away) person, so merge
must copy aliases across *before* deleting the source (see Merge).

Matching semantics (per Q1): **case-insensitive substring** (`LIKE %q%`,
`COLLATE NOCASE`) against the person's `name` and any `alias`. Used by both the
picker and global `who` search.

## Components & Interfaces

### 1. `GET /persons` (extend)

Each person in the response gains:

- `representative_url: string | null` — `/persons/faces/{prototype_face_id}/crop`
  when set, else `null`.
- `aliases: string[]` — from `person_aliases`.

Backfill: for existing people with no `prototype_face_id`, leave `null` (UI shows
a placeholder). No migration-time backfill required.

### 2. `GET /persons/search?q=` (new)

- Server-side, case-insensitive substring match on `name` OR any `alias`.
- Returns `{ persons: [{ id, name, representative_url, aliases, face_count }] }`,
  ordered by `face_count DESC`, capped (e.g. 20).
- Empty/whitespace `q` returns an empty list.
- Called by the suggestion-card picker, **debounced client-side** (per Q4,
  ~250 ms).

### 3. `POST /persons/suggestions/{id}/confirm` (extend)

Already accepts `{ name?, person_id? }`. Additions:

- When creating a **new** person, also set `prototype_face_id` to the
  suggestion's `representative_face_id`.
- When `person_id` is supplied (existing person, from the picker), link the
  suggestion's faces into that person and do **not** overwrite its name or
  representative. This is the "confirm into existing person" path.

### 4. `POST /persons/{keep_id}/merge/{remove_id}` (extend)

Now accepts an optional JSON body `{ name?: string, representative_face_id?: int }`
(per Q3, one source into one target at a time). Transaction:

1. Move `person_faces` from `remove_id` to `keep_id` (existing behavior).
2. Reassign `cluster_suggestions.person_id` (existing behavior).
3. **Copy aliases**: insert `remove_id`'s `name` and each of its aliases as
   aliases of `keep_id` (`INSERT OR IGNORE`, skip blanks and any equal to the
   survivor's final name) — so search still finds the person under the old name.
4. If `name` given, update the survivor's name; the old survivor name also
   becomes an alias (so nothing becomes unsearchable).
5. If `representative_face_id` given, validate it now belongs to `keep_id`
   (via `person_faces`) and set `prototype_face_id`; else keep the survivor's.
6. Delete `remove_id` (cascades its now-copied aliases away).

### 5. Alias CRUD (new)

- `POST /persons/{id}/aliases` `{ alias }` → insert (trimmed, non-empty,
  `INSERT OR IGNORE` on the unique constraint). 404 if person missing.
- `DELETE /persons/{id}/aliases/{alias_id}` → delete. 404 if missing.

### 6. `who` photo search (extend, `search.py`)

The `who` filter subquery changes from exact `persons.name = ?` to matching
`name` OR any `alias`, case-insensitive substring, e.g.:

```sql
AND id IN (
  SELECT faces.asset_id FROM faces
  JOIN person_faces ON person_faces.face_id = faces.id
  JOIN persons ON persons.id = person_faces.person_id
  LEFT JOIN person_aliases ON person_aliases.person_id = persons.id
  WHERE persons.name LIKE ? COLLATE NOCASE
     OR person_aliases.alias LIKE ? COLLATE NOCASE
)
```

This is what makes one identity (all merged life stages) findable under either
its name or an alias.

### 7. Web UI (`apps/web`)

- **`types.ts`** — `Person` gains `representative_url: string | null` and
  `aliases: string[]`; add a `PersonMatch` type for search results.
- **`lib/api.ts`** — `confirmSuggestion(id, { name?, person_id? })`;
  `searchPersons(q)`; `mergePersons(keepId, removeId, { name?, representativeFaceId? })`;
  `addAlias(id, alias)`, `removeAlias(id, aliasId)`.
- **`SuggestionCard`** — keep the free-text name field for new people, plus a
  debounced person-search box; selecting a match confirms into that existing
  person (`person_id`), typing a name confirms as new.
- **`PersonCard`** — render `representative_url` thumbnail (placeholder if null),
  editable aliases (add/remove chips), and a **Merge** action: pick another
  person (reuse the search box), then choose surviving name and representative
  face (the two candidates' current representatives).

## Data Flow

- **Confirm new**: card → `confirm {name}` → create person (name +
  `prototype_face_id`) → link faces → suggestion `confirmed`.
- **Confirm into existing**: card picker → `confirm {person_id}` → link faces to
  existing person → suggestion `confirmed`.
- **Merge**: person card → pick target + name + representative → `merge` →
  faces + suggestions + aliases move to survivor, source deleted.
- **Search**: `who=Dad` → assets whose faces belong to a person whose name or
  alias matches → spans every merged cluster.

## Key Decisions

- **Relational aliases, substring matching** (Q1). Case-insensitive substring
  via `LIKE ... COLLATE NOCASE`.
- **`prototype_face_id` is the representative** (Q2), set on confirm, chosen on
  merge.
- **Extend the existing merge endpoint, one-at-a-time** (Q3); merge preserves the
  removed person's name and aliases as searchable aliases of the survivor.
- **Dedicated debounced search endpoint** for the picker (Q4).
- **No name-based auto-dedupe** — creating a new person is always explicit;
  linking to an existing one is always an explicit pick.
- **Pre-existing duplicates** (spec open question) are cleaned up manually via
  the new Merge UI; no automated reconciliation in v1.

## Error Handling

- Merge: 400 if `keep_id == remove_id`; 404 if either person missing; 400 if a
  supplied `representative_face_id` does not belong to the survivor after the
  face move. Whole merge runs in one transaction — partial merges never persist.
- Confirm: existing 409 on a rejected suggestion and 404 on unknown
  `person_id` are retained.
- Aliases: blank/whitespace rejected; duplicates are no-ops via `INSERT OR
  IGNORE`; 404 on unknown person/alias.
- Search: empty `q` → empty list (no full-table scan surprise).

## Testing Approach

- **Core** (`packages/core/tests`): schema migration produces `person_aliases`
  and reports version `4`; re-running migration on an existing catalog is safe.
- **API** (`apps/api/tests/test_persons.py`):
  - confirm as new person sets `prototype_face_id`;
  - confirm with `person_id` links faces without creating a duplicate person;
  - merge moves faces + suggestions, applies chosen name/representative, and
    copies the removed name + aliases onto the survivor;
  - merge rejects a `representative_face_id` not owned by the survivor;
  - `GET /persons/search` matches by name and by alias, case-insensitively, as
    substrings; empty `q` returns empty;
  - alias add/remove happy paths and 404s.
- **API** (`apps/api/tests/test_search.py` or existing search tests): `who`
  matches an alias, not just the canonical name.
- **Web**: type/client compile-level coverage for the new API calls and shapes
  (no heavy component tests; this repo keeps web tests light).

## File Map

| File | Action |
|---|---|
| `packages/core/core/schema.py` | Add `person_aliases`, bump version `3 → 4` |
| `apps/api/api/persons.py` | Extend `GET /persons`, `confirm`, `merge`; add search + alias CRUD |
| `apps/api/api/search.py` | Alias-aware `who` filter |
| `apps/api/tests/test_persons.py` | New/updated endpoint tests |
| `apps/web/types.ts` | `Person.representative_url`, `Person.aliases`, `PersonMatch` |
| `apps/web/lib/api.ts` | New/updated client calls |
| `apps/web/app/people/page.tsx` | Picker, merge, thumbnails, alias editor |
| `apps/web/app/globals.css` | Styles for picker/thumbnail/alias chips |
| `tools/cli/pics_cli/__main__.py` | (optional) show aliases in `people` output |
