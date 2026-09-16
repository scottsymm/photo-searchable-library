title: Same-Person Cluster Linking — Spec
tags:
  - spec
  - same-person-linking
  - face-clustering
  - people
keywords:
  - face clustering
  - person deduplication
  - cluster suggestions
  - merge people
  - person aliases
  - people search
distilled: 2026-09-15

# Same-Person Cluster Linking — Spec

## Problem Statement

The People review screen presents face-clustering suggestions, and conservative
clustering deliberately splits one real person into several clusters — most
visibly the same person at different ages or life stages. There is currently no
way to tell the app "these clusters are the same person." Worse, naming a
cluster always creates a brand-new person, so confirming several clusters for
one individual produces duplicate people with the same typed name. Names are
free text and are not an identity key, so nothing reconciles them.

## Target Audience

The library owner reviewing their own photos (single-user, self-managed). The
flow should be quick for someone who already knows who people are, without
requiring power-user mental overhead.

## Core Value Proposition

Give the human an explicit, reliable way to consolidate clusters into one
durable person — the way Apple Photos and Google Photos do — so that one person
(across every age and life stage) is findable under a single identity, while
clustering stays conservative and decisions survive future runs.

## MVP Scope

**In scope**

- Retain confirm-a-cluster-to-a-person behavior.
- Merge action in the People UI to combine two or more people into one durable
  person; confirmed `person_faces` links are preserved and survive re-clustering.
- At merge time, the user picks which name and which representative face survive.
- "Confirm into existing person" picker on the suggestion card: search and
  select an existing person instead of always creating a new one.
- Add optional **aliases** ("also known as") to a person; people search matches
  both canonical name and aliases.
- People search available at two points: (a) at merge/confirm time to find and
  pick the right existing person, and (b) global photo search ("all photos of
  Dad") returning every life stage under one identity.

**Out of scope (parked)**

- Relationship tags (Mom, brother, colleague).
- Notes / favorite flag.
- Contact-style fields (birthday, email, address).
- Silent name-based auto-dedupe — explicitly rejected because two different
  people can legitimately share a name.
- Changes to the clustering algorithm itself (splitting by age is expected and
  correct behavior).

## Success Metrics

- A user can reduce N duplicate people for one individual down to a single
  person, and that consolidation holds after another clustering run.
- Confirming a cluster for someone who already exists links to that existing
  person rather than creating a duplicate.
- Searching a person's name or alias returns photos spanning all merged
  clusters/life stages.
- No confirmed face links are lost by a merge or by a subsequent clustering run.

## Key Risks & Open Questions

- Existing behavior has likely already created duplicate people (same typed
  name). Need to decide whether v1 includes cleanup/merge of pre-existing
  duplicates or only prevents new ones. (Merge UI covers cleanup manually.)
- UI placement and interaction of the merge control and person picker — settled
  in tech-incept/design.
- Alias data model and how search indexes aliases — settled in tech-incept.
- Whether "pick representative face at merge time" needs a face chooser or just
  a choice between the two people's current representatives.
