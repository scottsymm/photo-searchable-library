---
title: Face Clustering and Review — Spike Findings
tags:
  - spike
  - face-clustering-review
  - computer-vision
  - insightface
  - human-in-the-loop
keywords:
  - DBSCAN face clustering
  - InsightFace embeddings
  - person clusters
  - merge split review
  - face identity
  - representative crops
created: 2026-09-09
updated: 2026-09-09
---

# Face Clustering and Review — Spike

## Question

Can InsightFace face embeddings from this photo library produce useful person
clusters automatically, or does every face need manual identification?

## Sample and method

- **Sample:** 200 real images selected deterministically from `~/Pictures`.
- **Faces:** 87 detections with confidence >= 0.5.
- **Detector:** InsightFace `buffalo_l`, CPU execution provider.
- **Embedding:** normalized 512-dimensional face embeddings.
- **Algorithms:** DBSCAN with cosine distance and average-linkage agglomerative
  clustering.
- **Review:** representative crop sheets generated for the most useful DBSCAN
  and agglomerative configurations.

The sample had 171 photos without a detected face, 11 with one face, 12 with

## Results

### DBSCAN

| Configuration | Clusters | Cluster sizes | Noise faces |
|---|---:|---|---:|
| `eps=.20, min_samples=2` | 1 | 2 | 85 / 87 |
| `eps=.25, min_samples=2` | 1 | 3 | 84 / 87 |
| `eps=.30, min_samples=2` | 4 | 4, 2, 2, 2 | 77 / 87 |
| `eps=.40, min_samples=2` | 5 | 5, 4, 4, 2, 2 | 70 / 87 |
| `eps=.25, min_samples=3` | 1 | 3 | 84 / 87 |
| **`eps=.30, min_samples=3`** | **1** | **4** | **83 / 87** |
| `eps=.40, min_samples=3` | 3 | 5, 4, 4 | 74 / 87 |

The `eps=.30, min_samples=3` representative sheet showed four crops of the
