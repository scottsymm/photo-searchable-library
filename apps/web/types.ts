export interface Asset {
  id: number;
  path: string;
  mime: string;
  taken_at: string | null;
  place_city: string | null;
  place_country: string | null;
  thumbnail_url: string;
  distance?: number;
}

export interface Person {
  id: number;
  name: string;
  status: string;
  face_count: number;
}

export interface FaceSuggestion {
  face_id: number;
  distance: number | null;
  crop_url: string;
}

export interface ClusterSuggestion {
  id: number;
  run_id: number;
  face_count: number;
  confidence: "high" | "candidate";
  status: "unreviewed" | "confirmed" | "rejected";
  person_id: number | null;
  representative_url: string;
  faces: FaceSuggestion[];
}

export interface FaceEnrichment {
  total: number;
  embeddings_ready: number;
  embeddings_pending: number;
  assets_processing: number;
  clustering_status: "no_faces" | "indexing" | "ready" | "queued" | "running" | "completed_no_suggestions";
}

export interface Place {
  place_city: string;
  place_country: string;
  count: number;
}

export interface Job {
  id: number;
  kind: string;
  status: string;
  progress: number;
  error: string | null;
}

export interface AdminSettings {
  watch_enabled: "0" | "1";
  watch_backfill: "prompt" | "backfill" | "done";
  watch_initialized?: "0" | "1";
  [key: string]: string | undefined;
}

export interface AdminStatus {
  mount_source: string | null;
  watch_root: string;
  root_available: boolean;
  models_ready: boolean;
  disk: { total: number; used: number; free: number } | null;
  counts: { assets: number; faces: number; persons: number; jobs: number };
  settings: AdminSettings;
}

export interface LibraryInventory {
  root: string;
  available: boolean;
  media_files: number;
  extensions: Record<string, number>;
  photos_libraries: { name: string; path: string }[];
  directory_errors: string[];
  catalog: { assets: number; mounted_assets: number; faces: number };
}

export interface SourceStatus {
  id: number;
  kind: string;
  display_name: string;
  status: string;
  authorization_state: string | null;
  watch_enabled: boolean;
  ingest_mode: "bridge" | "watch" | "manual";
  last_sync_at: string | null;
  last_error: string | null;
  asset_count: number;
  imported_count: number;
}

export interface SourceSync {
  id: number;
  source_id: number;
  status: "queued" | "running" | "done" | "partial" | "error";
  limit_count: number;
  full_sync: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  imported_count: number;
  failed_count: number;
  error: string | null;
}

export type Readiness =
  | "not_configured"
  | "authorization_required"
  | "inventory_pending"
  | "connected"
  | "failed";

export type BridgeStatus =
  | "offline"
  | "authorization_required"
  | "inventory_pending"
  | "connected"
  | "syncing";

export interface FunnelStages {
  discovered: number;
  ready_to_import: number;
  importing: number;
  imported: number;
  processing: number;
  searchable: number;
  failed_or_blocked: number;
}

export interface SourceOverview {
  kind: string;
  display_name: string;
  readiness: Readiness;
  readiness_detail: string | null;
  bridge_status: BridgeStatus;
  bridge_last_seen_at: string | null;
  authorization_state: string | null;
  watch_enabled: boolean;
  ingest_mode: "bridge" | "watch" | "manual";
  reported_at: string | null;
  stages: FunnelStages;
  sync: SourceSync | null;
  actions: { can_sync: boolean };
}

export interface CatalogOverview {
  generated_at: string;
  funnel: FunnelStages;
  sources: SourceOverview[];
  context: {
    photos_libraries: { name: string; path: string }[];
    recent_imports: {
      id: number;
      source_kind: string | null;
      original_filename: string | null;
      imported_at: string | null;
      taken_at: string | null;
    }[];
    faces: { total: number; assigned: number; unassigned: number; embeddings_ready: number; embeddings_pending: number; clustering_status: FaceEnrichment["clustering_status"] };
    places: { located: number; unlocated: number };
  };
}
