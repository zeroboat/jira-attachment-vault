// Types and calls for the backend (FastAPI) JSON API. Keep in sync with backend/app/schemas.py.

export type AttachmentState = "active" | "deleted_by_vault" | "missing_in_jira" | "restored";
export type JobStatus = "pending_approval" | "approved" | "running" | "done" | "failed" | "cancelled";
export type JobKind = "cleanup" | "restore" | "sync" | "full_sync";

export interface Attachment {
  id: string;
  issue_id: string;
  issue_key: string;
  project_key: string;
  issue_summary: string | null;
  issue_status: string | null;
  issue_status_category: string | null;
  filename: string;
  mime_type: string | null;
  size: number;
  author_name: string | null;
  created_at: string;
  sha256: string | null;
  backed_up_at: string | null;
  backup_error: string | null;
  backup_attempts: number;
  state: AttachmentState;
  last_seen_at: string;
  deleted_at: string | null;
  restored_as_id: string | null;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: string;
  attachment_id: string | null;
  issue_key: string | null;
  detail: Record<string, unknown> | null;
}

export interface Job {
  id: number;
  kind: JobKind;
  status: JobStatus;
  title: string;
  params: Record<string, unknown> | null;
  attachment_count: number;
  result: Record<string, any> | null;
  created_by: string | null;
  approved_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Totals {
  count: number;
  bytes: number;
}

export interface Dashboard {
  active: Totals;
  backed: Totals;
  pending: Totals;
  errors: Totals;
  freed: Totals;
  missing: Totals;
  stored_bytes: number;
  by_project: { project: string; count: number; bytes: number }[];
  largest: Attachment[];
  sync: {
    last_sync: string | null;
    last_full_sync: string | null;
    sync_result: Record<string, any> | null;
    backup_result: Record<string, any> | null;
    last_error: string | null;
  };
  pending_jobs: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
}

export interface Policy {
  older_than_days: number | null;
  min_size_mb: number | null;
  projects: string[];
  only_done: boolean;
  mime_prefix: string | null;
  filename_contains: string | null;
  skip_embedded: boolean;
}

export interface CleanupPreview {
  count: number;
  bytes: number;
  not_backed_up: number;
  items: Attachment[];
}

export interface AppConfig {
  user: string;
  dry_run: boolean;
  jira_base_url: string;
  timezone: string;
  storage_backend: string;
  jira_configured: boolean;
}

export interface Settings {
  jira_base_url: string;
  jira_email: string;
  jira_api_token_set: boolean;
  jira_projects: string[];
  jira_extra_jql: string;
  jira_user_timezone: string;
  jira_comment: boolean;
  jira_comment_lang: "en" | "ko";
  sync_interval_minutes: number;
  full_reconcile_hours: number;
  dry_run: boolean;
  storage_backend: string;
  storage_location: string;
  secret_key_ephemeral: boolean;
}

export type SettingsUpdate = Partial<Omit<Settings, "jira_api_token_set" | "storage_backend" | "storage_location" | "secret_key_ephemeral">> & {
  jira_api_token?: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((d: { loc?: string[]; msg?: string }) => `${d.loc?.at(-1) ?? ""}: ${d.msg ?? ""}`).join(", ")
            : JSON.stringify(data.detail);
    } catch {
      /* no body */
    }
    if (res.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("vault:unauthorized"));
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  login: (username: string, password: string) => request<{ ok: boolean }>("POST", "/auth/login", { username, password }),
  logout: () => request<{ ok: boolean }>("POST", "/auth/logout"),
  config: () => request<AppConfig>("GET", "/config"),
  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  projects: () => request<string[]>("GET", "/projects"),
  attachments: (p: { q?: string; project?: string; state?: string; backup?: string; sort?: string; page?: number }) =>
    request<Page<Attachment>>("GET", `/attachments${qs(p)}`),
  attachment: (id: string) =>
    request<{ attachment: Attachment; logs: AuditEntry[]; duplicates: Attachment[] }>("GET", `/attachments/${id}`),
  restore: (id: string) => request<Job>("POST", `/attachments/${id}/restore`),
  backupUrl: (id: string) => `/api/attachments/${id}/backup`,
  cleanupPreview: (p: Policy) => request<CleanupPreview>("POST", "/cleanup/preview", p),
  cleanupCreate: (p: Policy) => request<Job>("POST", "/cleanup/jobs", p),
  jobs: () => request<Job[]>("GET", "/jobs"),
  job: (id: number) => request<{ job: Job; items: Attachment[]; total_bytes: number }>("GET", `/jobs/${id}`),
  approve: (id: number) => request<Job>("POST", `/jobs/${id}/approve`),
  cancel: (id: number) => request<Job>("POST", `/jobs/${id}/cancel`),
  sync: (full: boolean) => request<Job>("POST", "/sync", { full }),
  audit: () => request<AuditEntry[]>("GET", "/audit"),
  settings: () => request<Settings>("GET", "/settings"),
  saveSettings: (s: SettingsUpdate) => request<Settings>("PUT", "/settings", s),
  testJira: (s: { jira_base_url: string; jira_email: string; jira_api_token: string }) =>
    request<{ ok: boolean; account?: string; error?: string }>("POST", "/settings/test-jira", s),
  changePassword: (current: string, next: string) => request<{ ok: boolean }>("POST", "/auth/password", { current, new: next }),
};
