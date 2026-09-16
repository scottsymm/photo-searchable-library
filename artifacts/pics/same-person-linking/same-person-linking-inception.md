title: Same-Person Cluster Linking
tags:
  - inception
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
incepted: 2026-09-15

# Same-Person Cluster Linking

## Idea

> Conservative face clustering deliberately splits one real person into several
> suggestion clusters — most visibly the same person at different ages or life
> stages. The app currently offers no way to say "these clusters are the same
> person," and naming a cluster silently creates a brand-new person, so
> duplicates pile up. This feature adds an explicit human-driven way to link
> clusters to one durable person and to search for people, matching how Apple
> Photos and Google Photos handle the same problem.

## Goal

**Success criteria**

- A user can fold two or more people/clusters into a single durable person, and
  the confirmed face links survive future clustering runs.
- At merge time the user chooses which name and which representative face win.
- A user can name a person and later find them by that name (or an alias).
- Naming a cluster no longer forces creation of a new person when the person
  already exists — the user can pick an existing person.
- Open: exact placement/interaction of the merge UI and the person picker
  (settled in tech-incept/design).

**v1 feature list**

- Confirm a cluster to a person (existing behavior retained).
- Merge action in the People UI that combines people, with pick-at-merge-time
  choice of surviving name and representative face.
- "Confirm into existing person" picker on the suggestion card (search/select an
  existing person instead of always creating a new one).
- Person model gains optional **aliases** ("also known as"); search matches name
  and aliases.
- People search usable both at merge/confirm time (pick the right person) and as
  global photo search ("all photos of Dad", spanning every life stage).

**Parked for later (explicitly out of v1)**

- Relationship tags (Mom, brother, colleague).
- Notes / favorite flag.
- Any contact-style fields (birthday, email, address).
- Silent name-based auto-dedupe (rejected: two different people can share a name).

## Interview Results

**When you see multiple suggestion cards that are clearly the same person, what do you want to do — merge before naming, or name each and have them collapse automatically?**
Not sure yet. The current driving case is the same person at a different age or stage of life, showing up as separate clusters. There may be other cases but they aren't clear yet. Asked for guidance.

**Guidance given: is "one person split into several clusters" a bug or expected?**
It is expected and healthy. Face embeddings drift with age, facial hair, glasses, weight, lighting, and expression. This app's clustering is deliberately conservative (high eps, min_samples=3), so it will split one real person into several tight clusters rather than risk merging two different people. The fix belongs in the review UI, not the algorithm.

**Guidance given: how do mature photo apps solve this?**
Apple Photos and Google Photos keep clustering conservative and give the human an explicit merge / "this is the same person" action. They do not use the typed name as the identity key, because name-as-key is fragile (two different people can share a name; it forces identical spelling every time) and merge matches how people actually review.

**Guidance given: recommended direction for this app**
The backend already has a merge endpoint that moves all face links onto one surviving person, and the data model already supports one person owning many clusters. The gap is UI. Recommended: (1) confirm each cluster to a person as today; (2) add a merge action in the People UI; (3) optionally add a "confirm into existing person" picker on the suggestion card. Steer away from silent name-based dedupe.

**Confirm-then-merge, or a "confirm into existing person" picker as the primary path?**
Confirm and merge.

**On merge, whose name and representative face should win — always the target, or pick at merge time?**
Pick at merge time.

**Is naming required for v1, or can clusters stay anonymous and be named later?**
Naming is needed, so we can search for existing people. Also wondering whether the Name field needs to become more than a single field.

**Guidance given: should the Name field grow into more fields?**
Recommend v1 = name + optional aliases ("also known as"). Aliases earn their place because the same person across life stages is often known by different names (maiden name, nickname, Bob vs Robert), and search should still find them. Relationship tag (Mom, brother) and notes/favorite are nice-to-have and clearly parked for later. Avoid turning a person into a mini-CRM (birthday, email, address) — scope creep that does not help find or group photos.

**What is the primary action for "search for existing people" — pick at merge/confirm time, global photo search, or both?**
Both. Go with the recommendation.

**For the age/life-stage case: one name shows all stages, or keep a stage findable on its own?**
One person, all stages — that is the point of merging. Go with the recommendation.

## Timeline

> Small, well-scoped UI-led feature. The durable person model, `person_faces`
> links, and a merge endpoint already exist; the confirm-into-existing-person
> picker and aliases are the main additions. Aim for a single implementation
> pass after tech-incept.

> (written at distill; leave placeholder during interview)
