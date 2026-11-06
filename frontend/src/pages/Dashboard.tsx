import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CheckCircle2, Circle, AlertTriangle } from "lucide-react";
import { api } from "../api";
import { Card, PageHeader, Spinner, Badge, fmtDateTime } from "../ui";

type Status = {
  llm: { provider: string; model: string; configured: boolean };
  gmail_configured: boolean; outlook_configured: boolean; has_resume: boolean; verified_facts: number;
  preferences_set: boolean; sources: number; mailboxes: number;
};
type Dash = {
  jobs_discovered: number; jobs_matching: number; awaiting_review: number; approved: number; submitted: number;
  interviews: number; offers: number; rejections: number; action_required: number; email_to_confirm: number;
  follow_ups_due: { id: number }[]; failed_tasks: number;
  autopilot: { enabled: boolean; paused: boolean; remaining_today: number };
  autopilot_exceptions: { id: number; meta: Record<string, string>; ts: string }[];
};

export default function Dashboard() {
  const st = useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/status") });
  const d = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard"), refetchInterval: 15000 });
  if (!st.data || !d.data) return <Spinner />;
  const s = st.data, x = d.data;
  const steps = [
    { done: s.llm.configured, label: "Add your Gemini API key to .env", to: "/settings", warn: true },
    { done: s.has_resume, label: "Upload your resume (PDF, DOCX or DOC)", to: "/profile" },
    { done: s.verified_facts > 0, label: "Review and verify your extracted profile", to: "/profile" },
    { done: s.preferences_set, label: "Set job preferences and hard requirements", to: "/preferences" },
    { done: s.sources > 0, label: "Connect a job source (Greenhouse, Lever, Ashby, MyCareersFuture)", to: "/connections" },
    { done: s.mailboxes > 0, label: "Connect Gmail or Outlook for status tracking (optional)", to: "/connections" },
  ];
  const setupDone = steps.every((x) => x.done);
  const stats = [
    { label: "Jobs discovered", v: x.jobs_discovered, to: "/discover" },
    { label: "Good matches (≥60)", v: x.jobs_matching, to: "/discover" },
    { label: "Awaiting your review", v: x.awaiting_review, to: "/applications" },
    { label: "Approved, ready to submit", v: x.approved, to: "/applications" },
    { label: "Submitted", v: x.submitted, to: "/applications" },
    { label: "Interviews", v: x.interviews, to: "/applications" },
    { label: "Offers", v: x.offers, to: "/applications" },
    { label: "Rejections", v: x.rejections, to: "/applications" },
  ];
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Your job search at a glance." />
      {!setupDone && (
        <Card title="Get set up" className="mb-6">
          <ol className="space-y-2">
            {steps.map((step) => (
              <li key={step.label}>
                <Link to={step.to} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50">
                  {step.done ? <CheckCircle2 className="size-5 text-emerald-600" aria-label="done" /> :
                    step.warn ? <AlertTriangle className="size-5 text-amber-500" aria-label="required" /> : <Circle className="size-5 text-slate-300" aria-label="to do" />}
                  <span className={step.done ? "text-slate-400 line-through" : ""}>{step.label}</span>
                </Link>
              </li>
            ))}
          </ol>
        </Card>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((t) => (
          <Link key={t.label} to={t.to} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-brand-500">
            <div className="text-2xl font-semibold tabular-nums">{t.v}</div>
            <div className="mt-1 text-xs text-slate-500">{t.label}</div>
          </Link>
        ))}
      </div>
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <Card title="Needs your attention">
          <ul className="space-y-2 text-sm">
            {x.action_required > 0 && <li><Link className="text-brand-700 hover:underline" to="/applications">{x.action_required} application(s) need action</Link></li>}
            {x.email_to_confirm > 0 && <li><Link className="text-brand-700 hover:underline" to="/inbox">{x.email_to_confirm} email(s) to match to applications</Link></li>}
            {x.follow_ups_due.length > 0 && <li><Link className="text-brand-700 hover:underline" to="/applications">{x.follow_ups_due.length} follow-up(s) due</Link></li>}
            {x.failed_tasks > 0 && <li><Link className="text-red-700 hover:underline" to="/settings">{x.failed_tasks} background task(s) failed</Link></li>}
            {x.action_required + x.email_to_confirm + x.follow_ups_due.length + x.failed_tasks === 0 && <li className="text-slate-500">All clear.</li>}
          </ul>
        </Card>
        <Card title="Autopilot" actions={<Link to="/autopilot" className="text-xs text-brand-700 hover:underline">Open control centre</Link>}>
          <div className="flex items-center gap-2 text-sm">
            {x.autopilot.enabled ? (x.autopilot.paused ? <Badge tone="amber">paused</Badge> : <Badge tone="green">running</Badge>) : <Badge>off</Badge>}
            {x.autopilot.enabled && <span className="text-slate-500">{x.autopilot.remaining_today} application(s) left today</span>}
          </div>
          {x.autopilot_exceptions.length > 0 && (
            <ul className="mt-3 space-y-1.5 text-xs">
              {x.autopilot_exceptions.map((e) => (
                <li key={e.id} className="rounded-md bg-amber-50 px-2 py-1.5 text-amber-900">
                  <b>{e.meta.title}</b> at {e.meta.company}: {e.meta.reason} <span className="text-amber-700">({fmtDateTime(e.ts)})</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
