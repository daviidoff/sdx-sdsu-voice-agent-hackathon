/** Crawler v1 wire contract. No Supabase schema or calling implementation implied. */
export type Category =
  | "care_home" | "disability_support" | "health_clinic"
  | "shelter" | "accessible_transport" | "community_organization";
export type Source = "maps" | "web" | "osm";
export interface Attribution { text: string; url: string; license: string }
export interface DiscoveryRequest {
  incident_id: string;
  locations: string[];
  categories: Category[];
  country_code?: string;
  sources?: Source[];
  bounds?: [number, number, number, number] | null;
  max_tasks?: number;
  max_results_per_task?: number;
  max_leads?: number;
  concurrency?: number;
  task_timeout_seconds?: number;
  max_charge_usd_per_task?: number;
  enrich_websites?: boolean;
  max_websites?: number;
}
export interface PhoneCandidate {
  number: string;
  extension: string | null;
  raw: string;
  verification: "format_only";
  role?: "reception" | "main" | "general";
  source_url?: string;
  extraction_method?: "tel_link" | "labeled_text";
  excerpt?: string;
}
export interface Coordinates { lat: number; lng: number }
export interface Evidence {
  evidence_id: string;
  source: Source | "website";
  source_url: string | null;
  retrieved_at: string;
  source_updated_at: null;
  task_id: string;
  provider_run_id: string | null;
  query: string;
  search_location: string;
  observed: {
    name: string;
    address: string | null;
    coordinates: Coordinates | null;
    phone_raw: string | null;
    phone: PhoneCandidate | null;
    listed_closed: boolean;
    phone_candidates?: PhoneCandidate[];
    phone_tags?: Record<string, string>;
    osm_tags?: Record<string, string>;
    coordinate_basis?: "node" | "bounding_box_center";
  };
  excerpt: string | null;
  attribution?: Attribution;
}
export interface DiscoveryLead {
  lead_id: string;
  incident_id: string;
  name: string;
  place_ids: string[];
  categories: Category[];
  category_basis: "search_query_unverified";
  address: string | null;
  coordinates: Coordinates | null;
  area_match: "inside" | "outside" | "unknown" | "not_checked";
  website: string | null;
  source_url: string | null;
  phone_candidates: PhoneCandidate[];
  phone: PhoneCandidate | null;
  listed_closed: boolean;
  evidence: Evidence[];
  is_mock: boolean;
  review_status: "needs_review";
  contact_status: "not_contacted";
  safety_status: "unknown";
  capacity_status: "unknown";
  flags: string[];
  next_action: "verify_contact_and_location" | "research_needed";
  website_enrichment?: {
    status: "skipped" | "candidates_found" | "failed" | "no_phone_found";
    reason?: string;
    pages: { url: string; retrieved_at: string; candidates_found: number }[];
    errors: { url: string; code: string }[];
  };
  handoff: {
    status: "draft";
    dial_allowed: false;
    requires: string[];
    suggested_questions: string[];
  };
}
export interface SearchTask {
  task_id: string;
  location: string;
  category: Category;
  source: Source;
  query: string;
}
export interface TaskReport extends SearchTask {
  started_at: string;
  finished_at: string;
  status: "succeeded" | "failed";
  provider_run_id?: string | null;
  provider_build_id?: string | null;
  records_received?: number;
  invalid_records?: number;
  limit_reached?: boolean;
  error_code?: string;
  cleanup_failed?: boolean;
  warnings?: string[];
}
export interface DiscoveryResult {
  schema_version: "1.0";
  run_id: string;
  request_key: string;
  incident_id: string;
  mode: "mock" | "live";
  status: "completed" | "partial" | "failed";
  started_at: string;
  finished_at: string;
  request: DiscoveryRequest;
  summary: {
    tasks_planned: number; tasks_executed: number; tasks_failed: number; tasks_skipped: number;
    leads_found: number; leads_returned: number; leads_omitted: number; leads_with_phone: number;
  };
  coverage: { population_coverage: "unknown"; exhaustive: false; note: string };
  tasks: TaskReport[];
  skipped_tasks: (SearchTask & { reason: "max_tasks" })[];
  leads: DiscoveryLead[];
  attributions?: Attribution[];
  website_enrichment?: {
    websites_attempted: number; leads_enriched: number; http_requests: number;
    max_websites: number; incomplete: boolean; unresolved: number;
  } | null;
  execution?: { runtime: "daytona"; sandbox_id: string };
}
