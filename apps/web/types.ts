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
