# Same-Person Cluster Linking Implementation Plan

*Created: 2026-09-15*

**Goal:** Let users confirm face clusters into existing people, merge duplicate people with explicit name and representative-face choices, and find each person through canonical names or aliases across all life stages.

**Architecture:** Extend the existing SQLite/API/Next.js stack without changing the clustering algorithm. Add a relational `person_aliases` table, use `persons.prototype_face_id` as the representative face, extend existing confirmation and merge endpoints, add a debounced server-side person search endpoint, and update the People UI.

**Tech Stack:** SQLite, FastAPI/Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest.

**Source:** `artifacts/pics/same-person-linking/same-person-linking-design.md`

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/schema.py` | Modify | Add `person_aliases`, index, and schema version 4 |
| `packages/core/tests/test_schema.py` | Create or modify existing schema test file | Verify alias migration is additive and repeatable |
| `apps/api/api/persons.py` | Modify | Return person metadata; confirm existing people; search people; alias CRUD; merge choices |
| `apps/api/api/search.py` | Modify | Match `who` against canonical names and aliases |
| `apps/api/tests/test_persons.py` | Modify | Verify person confirmation, search, aliases, and merge behavior |
| `apps/api/tests/test_search.py` | Create or modify existing search test file | Verify alias-aware photo filtering |
| `apps/web/types.ts` | Modify | Add representative, alias, person-search, and action types |
| `apps/web/lib/api.ts` | Modify | Add typed API clients for person search, aliases, confirmation, and merge |
| `apps/web/app/people/page.tsx` | Modify | Add debounced picker, merge workflow, thumbnails, and alias editor |
| `apps/web/app/globals.css` | Modify | Style person thumbnails, picker results, merge controls, and aliases |

## Tasks

### Task 1: Add the aliases schema migration

**Files:**
- Modify: `packages/core/core/schema.py`
- Create or modify: `packages/core/tests/test_schema.py`

- [x] Add this table to `SCHEMA` after `persons` and before tables that reference person identity:

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

- [x] Change the value written by `migrate()` from schema version `'3'` to `'4'`; do not remove or rewrite any existing tables or rows.
- [x] Add a migration test that creates an in-memory catalog, runs `migrate(conn)`, asserts `person_aliases` exists with `id`, `person_id`, `alias`, and `created_at`, and asserts `schema_meta.version == '4'`.
- [x] Add a repeatability test that inserts a person and alias, runs `migrate(conn)` a second time, and verifies the alias remains present and only one `person_aliases` table exists.
- [x] Verify:

```bash
uv run --project packages/core pytest packages/core/tests
```

Expected: all core tests pass, including the schema migration tests.

### Task 2: Add API response helpers for aliases and representative faces

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/tests/test_persons.py`

- [x] Add a helper that converts a person row into the API shape `{id, name, status, face_count, aliases, representative_url}`. Load aliases ordered by `id`; set `representative_url` to `/persons/faces/{prototype_face_id}/crop` when `prototype_face_id` is non-null, otherwise `None`.
- [x] Update `GET /persons` to select `persons.prototype_face_id` and construct every person through the helper. Keep the existing face count and ordering.
- [x] Add a test fixture person with one `person_faces` link, one alias, and a prototype face; assert `GET /persons` returns the alias, correct face count, and representative URL.
- [x] Add a test for an existing person without a prototype face; assert the URL is `null` rather than failing the response.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_persons.py
```

Expected: existing people tests and the new response-shape tests pass.

### Task 3: Extend confirmation to set or reuse a representative person

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/tests/test_persons.py`

- [x] In `POST /persons/suggestions/{suggestion_id}/confirm`, retain the existing rejected-suggestion and unknown-person checks.
- [x] When `request.person_id` is absent, create the person with `name=request.name or ''` and `prototype_face_id=suggestion['representative_face_id']` in the same insert.
- [x] When `request.person_id` is present, do not modify the existing person's name or prototype; insert the suggestion's suggested faces into that person and mark the suggestion confirmed as today.
- [x] Keep `INSERT OR IGNORE` for `person_faces` so repeated face links do not fail.
- [x] Test that confirming a new suggestion creates exactly one person, stores the requested name, and stores the suggestion representative face as `prototype_face_id`.
- [x] Test that confirming another suggestion with `person_id` creates no new person, preserves the existing name and prototype, and links all suggestion faces to that person.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_persons.py -q
```

Expected: confirmation tests pass, including both new-person and existing-person paths.

### Task 4: Add server-side person search

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/tests/test_persons.py`

- [x] Add `GET /persons/search?q=` before the `/{person_id}` routes so `/search` is not interpreted as an integer person ID.
- [x] Strip `q`; return `{ "persons": [] }` for an empty value.
- [x] Query people where `persons.name LIKE ? COLLATE NOCASE` or an alias row matches `person_aliases.alias LIKE ? COLLATE NOCASE`, using `%{q}%` for both parameters.
- [x] Return at most 20 matches ordered by `face_count DESC, persons.id`, using the same person response helper as `GET /persons`.
- [x] Test canonical-name substring matching, alias substring matching, case-insensitive matching, face-count ordering, the 20-result cap, and empty-query behavior.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_persons.py -q
```

Expected: person-search tests pass without changing the existing `GET /persons` contract.

### Task 5: Add alias create and delete endpoints

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/tests/test_persons.py`

- [x] Add `AliasRequest` with `alias: str` and a non-empty trimmed validation rule.
- [x] Add `POST /persons/{person_id}/aliases`: return 404 for an unknown person; trim the alias; insert with `INSERT OR IGNORE`; return the created or existing alias row as `{id, person_id, alias}`.
- [x] Add `DELETE /persons/{person_id}/aliases/{alias_id}`: delete only an alias belonging to that person; return 404 if either relationship is absent; return `{ok: true}` on success.
- [x] Test trimming, duplicate alias idempotency, unknown-person 404, successful deletion, and deleting an alias under the wrong person returning 404.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_persons.py -q
```

Expected: alias CRUD tests pass.

### Task 6: Extend merge with name, representative, and alias preservation

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/tests/test_persons.py`

- [x] Add `MergeRequest` with optional `name` and optional `representative_face_id`.
- [x] Keep the current 400 self-merge and 404 person checks.
- [x] Execute the complete merge inside one transaction: move source `person_faces` to the survivor, reassign `cluster_suggestions.person_id`, and copy the source person's non-empty name plus all source aliases into the survivor's aliases using `INSERT OR IGNORE`.
- [x] If `request.name` is provided, trim and reject an empty result; copy the survivor's old non-empty name into aliases unless it equals the final name, then update the survivor's name.
- [x] If `request.representative_face_id` is provided, validate that the face is now linked to `keep_id` after face movement; return 400 if not, otherwise update `persons.prototype_face_id`.
- [x] Delete the source person only after aliases have been copied. Rely on foreign-key cascade for source aliases.
- [x] Commit only after all steps succeed; rollback on any exception and return a stable 400 response for invalid representative selection.
- [x] Test that merge preserves all faces and suggestions, applies the selected name and representative, copies source name and aliases, and deletes the source person.
- [x] Test that an invalid representative face is rejected and leaves both people unchanged.
- [x] Test that self-merge remains a 400 response.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_persons.py -q
```

Expected: merge tests pass and existing merge behavior remains intact.

### Task 7: Make global `who` search alias-aware

**Files:**
- Modify: `apps/api/api/search.py`
- Create or modify: `apps/api/tests/test_search.py`

- [x] Change `_filter_ids()` so a `who` value uses `%{who}%` with `COLLATE NOCASE` against `persons.name` or `person_aliases.alias`.
- [x] Keep the existing asset, place, date, and tag filters unchanged.
- [x] Use the existing joins through `faces` and `person_faces`; use `LEFT JOIN person_aliases` so canonical-name matches still work when a person has no aliases.
- [x] Test that a canonical name returns all linked assets, an alias returns the same assets, matching is case-insensitive and substring-based, and an unrelated name returns no assets.
- [x] Verify:

```bash
uv run --project apps/api pytest apps/api/tests/test_search.py -q
```

Expected: alias-aware `who` tests pass and non-person search filters remain green.

### Task 8: Add typed web API contracts and clients

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/lib/api.ts`

- [x] Extend `Person` with `prototype_face_id: number | null`, `representative_url: string | null`, and alias records containing `id` and `alias`.
- [x] Add `PersonMatch` containing `id`, `name`, `face_count`, `aliases`, and `representative_url`.
- [x] Change `confirmSuggestion` to accept `{name?: string; person_id?: number}` and send that object as JSON.
- [x] Add `searchPersons(query)` calling `GET /persons/search?q=...` and returning `PersonMatch[]`.
- [x] Add `mergePersons(keepId, removeId, update)` calling the extended merge endpoint with `{name?: string; representative_face_id?: number}`.
- [x] Add `addAlias(personId, alias)` and `removeAlias(personId, aliasId)` clients.
- [x] Verify:

```bash
pnpm --filter web check
```

Expected: TypeScript passes with no errors.

### Task 9: Build the debounced suggestion person picker

**Files:**
- Modify: `apps/web/app/people/page.tsx`

- [x] Add a reusable client-side hook or local effect that waits approximately 250 ms after picker input changes, cancels the prior timer/request, skips blank queries, and ignores stale responses.
- [x] Extend `SuggestionCard` with an explicit mode: create a new person by entering a name, or search/select an existing person. Do not silently deduplicate typed names.
- [x] Render search matches with representative thumbnail when available, name, alias context, and face count. Selecting a match stores its `person_id` and enables confirmation without requiring a new name.
- [x] Submit `{person_id}` for an existing match and `{name}` for a new person. Clear picker state after successful confirmation and retain the existing reload behavior.
- [x] Preserve reject behavior and disable all actions while the request is busy.
- [x] Verify manually with the running web/API apps: search for an existing canonical name and alias, select the person, confirm a suggestion, reload, and verify no duplicate person was created.

### Task 10: Add person thumbnails and alias editing

**Files:**
- Modify: `apps/web/app/people/page.tsx`

- [x] Update `PersonCard` to render the representative thumbnail when `representative_url` exists and an accessible placeholder otherwise.
- [x] Render aliases as removable chips or rows. Add an alias input and submit action using `addAlias`; remove aliases using `removeAlias`; reload after each successful mutation.
- [x] Keep canonical name editing separate from aliases and preserve existing rename behavior.
- [x] Ensure blank alias submissions are disabled client-side and errors do not leave the card permanently busy.
- [x] Verify manually that aliases can be added, displayed after reload, removed, and used by the suggestion picker.

### Task 11: Add the merge workflow with explicit final choices

**Files:**
- Modify: `apps/web/app/people/page.tsx`

- [x] Add a Merge action to each named person card that opens a merge panel or dialog.
- [x] Reuse the debounced person search client to select the source person to merge into the current survivor; prevent selecting the same person.
- [x] Show the two candidate representative faces and provide a required choice for the final representative when both exist. If only one exists, select it by default; if neither exists, omit the face choice.
- [x] Provide a final-name choice/input initialized to the survivor's name. Submit the chosen name and representative face ID to `mergePersons`.
- [x] Confirm the destructive operation before submitting; after success reload the people list and close the merge UI.
- [x] Verify manually by merging two people created from separate clusters: choose the source person's representative and a final name, reload, confirm one person remains with the combined face count, and verify the source is gone.

### Task 12: Style the new identity-review controls

**Files:**
- Modify: `apps/web/app/globals.css`

- [x] Add styles for representative thumbnails, picker result rows, alias chips/remove buttons, merge panel/dialog controls, and selected-result states using the existing CSS variables and card language.
- [x] Ensure picker results can scroll without expanding the card indefinitely and controls remain usable at the existing 650px mobile breakpoint.
- [x] Preserve visible `:focus-visible` outlines for inputs, buttons, picker results, and alias removal controls.
- [x] Verify:

```bash
pnpm --filter web check
pnpm --filter web build
```

Expected: TypeScript and production build pass.

### Task 13: Run the complete verification suite

**Files:**
- No source changes; verification only.

- [ ] Run all Python tests:

```bash
uv run --project packages/core pytest packages/core/tests
uv run --project apps/api pytest apps/api/tests
uv run --project services/worker pytest services/worker/tests
```

- [ ] Run web checks and tests:

```bash
pnpm --filter web check
pnpm --filter web test
pnpm --filter web build
```

- [ ] Perform the end-to-end acceptance flow against the development apps:
  - Confirm one cluster as a new named person and verify its representative face appears.
  - Confirm a second cluster into that existing person through the debounced picker.
  - Add an alias and find the person through the picker using that alias.
  - Merge two separately named duplicate people, choosing the final name and representative face.
  - Search photos with `who=<canonical name>` and `who=<alias>` and verify both return photos from all merged life stages.
  - Run clustering again and verify confirmed face links and names remain unchanged.

## Verification Summary

- [ ] Core tests pass: `uv run --project packages/core pytest packages/core/tests`
- [ ] API tests pass: `uv run --project apps/api pytest apps/api/tests`
- [ ] Worker tests pass: `uv run --project services/worker pytest services/worker/tests`
- [ ] Web typecheck passes: `pnpm --filter web check`
- [ ] Web tests pass: `pnpm --filter web test`
- [ ] Web production build passes: `pnpm --filter web build`
- [ ] End-to-end flow confirms existing-person linking, aliases, merge choices, alias photo search, and persistence across re-clustering.
