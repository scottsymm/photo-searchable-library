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
