import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Pause, Play, Zap, ShieldAlert } from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, ErrorNote, Field, Modal, PageHeader, Segmented, Spinner, TagInput, Toggle, fmtDateTime, inputCls } from "../ui";

type Policy = {
  enabled: boolean; paused: boolean; minimum_match_score: number; max_applications_per_day: number; max_applications_per_week: number;
  require_job_open_check: boolean; require_verified_candidate_facts: boolean; require_qa_pass: boolean; generate_cover_letter: boolean;
  tailoring_tone: string; tailoring_length: string; max_job_age_days: number;
  auto_submit: { enabled: boolean; supported_providers_only: boolean; pause_on_captcha_or_mfa: boolean; pause_on_sensitive_questions: boolean; pause_on_unknown_questions: boolean };
  excluded_employers: string[]; excluded_keywords: string[]; require_user_approval_for: string[];
};
type Source = { id: number; provider: string; label: string; enabled: boolean; autopilot_enabled: boolean };
type Act = { id: number; action: string; entity: string; entity_id: number | null; meta: Record<string, any>; ts: string };

export default function Autopilot() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["autopilot"], queryFn: () => api.get<{ policy: Policy; remaining_today: number; sources: Source[] }>("/autopilot/settings") });
  const act = useQuery({ queryKey: ["autopilot-activity"], queryFn: () => api.get<Act[]>("/autopilot/activity"), refetchInterval: 15000 });
  const [p, setP] = useState<Policy | null>(null);
  const [consent, setConsent] = useState(false);
  useEffect(() => { if (data) setP(data.policy); }, [data]);
  const inv = () => { qc.invalidateQueries({ queryKey: ["autopilot"] }); qc.invalidateQueries({ queryKey: ["autopilot-activity"] }); };
  const save = useMutation({ mutationFn: (pol: Policy) => api.put("/autopilot/settings", pol), onSuccess: inv });
  const pause = useMutation({ mutationFn: (v: boolean) => api.post(v ? "/autopilot/pause" : "/autopilot/resume"), onSuccess: inv });
  const run = useMutation({ mutationFn: () => api.post("/autopilot/run"), onSuccess: inv });
  const src = useMutation({ mutationFn: (x: { id: number; v: boolean }) => api.patch(`/job-sources/${x.id}`, { autopilot_enabled: x.v }), onSuccess: inv });
  if (!data || !p) return <Spinner />;
  const set = (patch: Partial<Policy>) => setP({ ...p, ...patch });
  const live = data.policy;
  return (
    <>
      <PageHeader title="Autopilot control centre" subtitle="Off by default. Finds matching jobs, tailors and checks your resume, and queues applications for you to submit."
        actions={live.enabled && (live.paused
          ? <Button variant="primary" loading={pause.isPending} onClick={() => pause.mutate(false)}><Play className="size-4" /> Resume</Button>
          : <Button variant="danger" loading={pause.isPending} onClick={() => pause.mutate(true)}><Pause className="size-4" /> Pause all automation</Button>)} />
      <div className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <Toggle label="Enable autopilot" checked={live.enabled} onChange={(v) => (v ? setConsent(true) : save.mutate({ ...p, enabled: false }))} />
        <div>
          <div className="font-medium">{live.enabled ? (live.paused ? "Autopilot is paused" : "Autopilot is on") : "Autopilot is off"}</div>
          <div className="text-sm text-slate-500">{live.enabled && `${data.remaining_today} application(s) left today · runs every 30 minutes`}</div>
        </div>
        {live.enabled && !live.paused && <Button className="ml-auto" loading={run.isPending} onClick={() => run.mutate()}><Zap className="size-4" /> Run now</Button>}
      </div>
      <div className="mb-6 flex gap-3 rounded-xl bg-sky-50 p-4 text-sm text-sky-900">
        <ShieldAlert className="size-5 shrink-0" />
        <div>
          <b>How submission works:</b> none of the connected sources (Greenhouse, Lever, Ashby, MyCareersFuture) offer an official API for candidates to submit applications.
          Autopilot prepares each application — matched, tailored, factuality-checked and approved — then notifies you to submit on the employer's page in one click.
          It never fills third-party forms, answers sensitive questions, or bypasses CAPTCHA/MFA.
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Rules" actions={<Button variant="primary" size="sm" loading={save.isPending} onClick={() => save.mutate(p)}>Save rules</Button>}>
            <ErrorNote error={save.error} />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Minimum match score" hint={`${p.minimum_match_score}`}>
                <input type="range" min={50} max={100} value={p.minimum_match_score} onChange={(e) => set({ minimum_match_score: Number(e.target.value) })} className="w-full accent-brand-600" />
              </Field>
              <Field label="Only jobs posted within (days)"><input type="number" className={inputCls} value={p.max_job_age_days} onChange={(e) => set({ max_job_age_days: Number(e.target.value) })} /></Field>
              <Field label="Max applications per day"><input type="number" min={0} className={inputCls} value={p.max_applications_per_day} onChange={(e) => set({ max_applications_per_day: Number(e.target.value) })} /></Field>
              <Field label="Max applications per week"><input type="number" min={0} className={inputCls} value={p.max_applications_per_week} onChange={(e) => set({ max_applications_per_week: Number(e.target.value) })} /></Field>
              <Field label="Wording">
                <Segmented label="Wording" value={p.tailoring_tone} onChange={(v) => set({ tailoring_tone: v })} options={[{ value: "conservative", label: "Conservative" }, { value: "balanced", label: "Balanced" }, { value: "targeted", label: "Targeted" }]} />
              </Field>
              <Field label="Length">
                <Segmented label="Length" value={p.tailoring_length} onChange={(v) => set({ tailoring_length: v })} options={[{ value: "one_page", label: "1 page" }, { value: "two_page", label: "2 pages" }, { value: "flexible", label: "Flexible" }]} />
              </Field>
            </div>
            <div className="mt-4 space-y-2">
              {([
                ["require_qa_pass", "Only queue resumes that pass every check (warnings go to you)"],
                ["require_verified_candidate_facts", "Use verified facts only"],
                ["require_job_open_check", "Check the job is still open (where the source reports it)"],
                ["generate_cover_letter", "Generate a cover letter"],
              ] as [keyof Policy, string][]).map(([k, label]) => (
                <div key={k} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">{label}<Toggle label={label} checked={Boolean(p[k])} onChange={(v) => set({ [k]: v } as Partial<Policy>)} /></div>
              ))}
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="Excluded employers"><TagInput value={p.excluded_employers} onChange={(v) => set({ excluded_employers: v })} /></Field>
              <Field label="Excluded keywords"><TagInput value={p.excluded_keywords} onChange={(v) => set({ excluded_keywords: v })} /></Field>
            </div>
            <div className="mt-4">
              <div className="text-sm font-medium">Always needs your input</div>
              <div className="mt-1 flex flex-wrap gap-1.5">{p.require_user_approval_for.map((x) => <Badge key={x} tone="amber">{x.replace(/_/g, " ")}</Badge>)}</div>
              <p className="mt-1 text-xs text-slate-500">These can't be turned off. Save your answers under <Link className="underline" to="/settings">Settings → Application answers</Link>.</p>
            </div>
          </Card>
          <Card title="Recent automated actions">
            {!act.data?.length ? <p className="text-sm text-slate-500">No activity yet.</p> : (
              <ul className="divide-y divide-slate-100 text-sm">
                {act.data.map((e) => (
                  <li key={e.id} className="py-2">
                    <div className="flex items-center gap-2">
                      <Badge tone={e.action === "autopilot.exception" ? "amber" : "slate"}>{e.action.replace("autopilot.", "").replace(/[._]/g, " ")}</Badge>
                      <span className="text-xs text-slate-400">{fmtDateTime(e.ts)}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-600">
                      {e.meta.title ? `${e.meta.title} at ${e.meta.company}: ${e.meta.reason}` :
                        Object.entries(e.meta).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card title="Sources autopilot may use">
          {!data.sources.length ? <p className="text-sm text-slate-500">No sources. <Link className="text-brand-700 underline" to="/connections">Connect one</Link>.</p> : (
            <ul className="space-y-2">
              {data.sources.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2 text-sm">
                  <span>{s.label}</span>
                  <Toggle label={`Autopilot for ${s.label}`} checked={s.autopilot_enabled} onChange={(v) => src.mutate({ id: s.id, v })} />
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-slate-500">Each source must be enabled separately. Changes are recorded as consent events.</p>
        </Card>
      </div>
      <Modal open={consent} onClose={() => setConsent(false)} title="Turn on autopilot?"
        footer={<><Button variant="ghost" onClick={() => setConsent(false)}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => { save.mutate({ ...p, enabled: true, paused: false }); setConsent(false); }}>I understand — turn on</Button></>}>
        <ul className="ml-4 list-disc space-y-1.5 text-sm text-slate-700">
          <li>Autopilot will score new jobs from the sources you enable and tailor resumes for those above your minimum score.</li>
          <li>Resumes are written only from your verified facts and must pass the factuality checks.</li>
          <li>It prepares at most {p.max_applications_per_day} application(s) a day and {p.max_applications_per_week} a week.</li>
          <li>You still submit each application on the employer's site. Sensitive questions always need your answer.</li>
          <li>You can pause everything instantly. Every action is logged.</li>
        </ul>
      </Modal>
    </>
  );
}
