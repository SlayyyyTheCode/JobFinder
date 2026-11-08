export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    const msg =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in (detail as Record<string, unknown>)
          ? String((detail as Record<string, unknown>).message)
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg).join("; ")
            : `Request failed (${status})`;
    super(msg);
    this.status = status;
    this.detail = detail;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`/api/v1${path}`, { ...init, credentials: "same-origin" });
  if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("jp-unauthorized"));
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(p: string) => req<T>("GET", p),
  post: <T>(p: string, b?: unknown) => req<T>("POST", p, b ?? {}),
  put: <T>(p: string, b: unknown) => req<T>("PUT", p, b),
  patch: <T>(p: string, b: unknown) => req<T>("PATCH", p, b),
  del: <T>(p: string) => req<T>("DELETE", p),
  upload: <T>(p: string, f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return req<T>("POST", p, fd);
  },
};

export const fileUrl = (p: string) => `/api/v1${p}`;

// ---------- types ----------
export type Fact = {
  id: number; type: string; text: string; data: Record<string, any>; parent_id: number | null;
  confidence: number; verified: boolean; notes: string; source_excerpt: string; version: number;
};
export type Match = {
  score: number; eligible: boolean; hard_failures: string[]; breakdown: Record<string, number>;
  strong_matches: string[]; gaps: string[]; explanation: string; recommended_action: string; created_at: string;
};
export type Job = {
  id: number; provider: string; external_id: string; title: string; company: string; location: string;
  url: string; apply_url: string; work_arrangement: string; employment_type: string;
  salary_min: number | null; salary_max: number | null; salary_currency: string; salary_period: string;
  description?: string; requirements?: Record<string, any>; posted_at: string | null; discovered_at: string;
  saved: boolean; dismissed: boolean; match?: Match | null; application?: { id: number; status: string } | null;
};
export type Issue = { check: string; severity: "fail" | "warn"; message: string; item: string };
export type Tailoring = {
  id: number; job_id: number; status: string; qa_status: string; error: string; options: Record<string, any>;
  content: Record<string, any>; qa: { issues?: Issue[]; pages?: number }; change_report: Record<string, any>;
  cover_letter: string; docx_path: string; pdf_path: string; cover_docx_path: string; model: string;
  prompt_version: string; created_at: string;
  job: { id: number; title: string; company: string; url: string }; application: Application | null;
};
export type Application = {
  id: number; job_id: number; tailoring_id: number | null; status: string; provider_status: string;
  method: string; user_approved: boolean; approved_by: string; submitted_at: string | null;
  confirmation_id: string; notes: string; follow_up_at: string | null; created_at: string; updated_at: string;
  job?: { id: number; title: string; company: string; location: string; provider: string };
};
export type Notification = {
  id: number; type: string; title: string; body: string; link: string; important: boolean;
  read_at: string | null; created_at: string;
};
