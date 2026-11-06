import { ReactNode, useEffect, useState, KeyboardEvent, ButtonHTMLAttributes } from "react";
import { Loader2, X } from "lucide-react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};
export function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 shadow-sm",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  const s = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:opacity-50 disabled:cursor-not-allowed", v, s, className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Badge({ tone = "slate", children, title }: { tone?: "slate" | "green" | "amber" | "red" | "blue" | "violet"; children: ReactNode; title?: string }) {
  const t = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
    violet: "bg-brand-50 text-brand-700 ring-brand-100",
  }[tone];
  return <span title={title} className={cx("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ring-transparent", t)}>{children}</span>;
}

export function ScoreBadge({ score, eligible }: { score?: number | null; eligible?: boolean }) {
  if (score == null) return <Badge>not scored</Badge>;
  if (eligible === false) return <Badge tone="red" title="Excluded by a hard requirement">excluded</Badge>;
  const tone = score >= 80 ? "green" : score >= 60 ? "amber" : "slate";
  return <Badge tone={tone} title="Estimated fit — not a prediction of interview chance">{Math.round(score)} fit</Badge>;
}

const STATUS_TONE: Record<string, "slate" | "green" | "amber" | "red" | "blue" | "violet"> = {
  READY_FOR_REVIEW: "amber", APPROVED: "violet", SUBMITTING: "blue", SUBMITTED: "blue", ACKNOWLEDGED: "blue",
  IN_REVIEW: "blue", INTERVIEW: "green", OFFER: "green", REJECTED: "red", WITHDRAWN: "slate", CLOSED: "slate",
  FAILED: "red", ACTION_REQUIRED: "amber", UNKNOWN: "slate",
};
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "slate"}>{status.replace(/_/g, " ").toLowerCase()}</Badge>;
}

export function QaBadge({ status }: { status: string }) {
  const tone = status === "pass" ? "green" : status === "warn" ? "amber" : status === "fail" ? "red" : "slate";
  const label = status === "pass" ? "QA passed" : status === "warn" ? "QA: review needed" : status === "fail" ? "QA failed" : status;
  return <Badge tone={tone}>{label}</Badge>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label ?? "Loading…"}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white/60 p-8 text-center">
      <p className="font-medium text-slate-700">{title}</p>
      {children && <div className="mt-2 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{(error as Error).message ?? String(error)}</p>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {hint && <span className="ml-2 text-xs text-slate-500">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100";

export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((x) => x.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
  };
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2 py-1.5 shadow-sm focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-sm">
          {t}
          <button type="button" aria-label={`Remove ${t}`} className="text-slate-400 hover:text-slate-700" onClick={() => onChange(value.filter((x) => x !== t))}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input className="min-w-32 flex-1 border-0 bg-transparent p-1 text-sm outline-none" value={draft} placeholder={value.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onBlur={add} />
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 text-xs">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cx("rounded-md px-2.5 py-1 font-medium", value === o.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cx("relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:opacity-50", checked ? "bg-brand-600" : "bg-slate-300")}>
      <span className={cx("inline-block size-5 rounded-full bg-white shadow transition", checked ? "translate-x-5" : "translate-x-0.5")} />
    </button>
  );
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="max-h-[90vh] w-full max-w-xl overflow-auto rounded-2xl bg-white shadow-xl" onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100"><X className="size-4" /></button>
        </header>
        <div className="space-y-4 p-5">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");
export const fmtDateTime = (s?: string | null) => (s ? new Date(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
export const fmtSalary = (j: { salary_min: number | null; salary_max: number | null; salary_currency: string; salary_period: string }) => {
  if (j.salary_min == null && j.salary_max == null) return "";
  const n = (x: number | null) => (x == null ? "" : x.toLocaleString());
  const range = j.salary_min != null && j.salary_max != null ? `${n(j.salary_min)}–${n(j.salary_max)}` : n(j.salary_min ?? j.salary_max);
  return `${j.salary_currency} ${range}${j.salary_period ? ` / ${j.salary_period.replace(/^per[- ]/, "")}` : ""}`.trim();
};
