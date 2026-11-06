import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Bookmark, EyeOff, Wand2, RefreshCw, Link2, ClipboardPaste, MessageSquareText } from "lucide-react";
import { api, ApiError, Job, Match } from "../api";
import {
  Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, ScoreBadge, Segmented, Spinner, StatusBadge, Toggle, cx,
  fmtDate, fmtSalary, inputCls, QaBadge,
} from "../ui";

type JobDetail = {
  job: Job; match: Match | null; application: { id: number; status: string } | null;
  tailorings: { id: number; status: string; qa_status: string; created_at: string; error: string }[];
  duplicates: { id: number; provider: string; url: string }[];
};

function AddJob() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [mode, setMode] = useState<"url" | "paste" | null>(null);
  const [url, setUrl] = useState("");
  const [f, setF] = useState({ title: "", company: "", location: "", description: "", url: "" });
  const [hint, setHint] = useState("");
  const done = (j: Job) => { setMode(null); qc.invalidateQueries({ queryKey: ["jobs"] }); nav(`/discover/${j.id}`); };
  const imp = useMutation({
    mutationFn: () => api.post<Job>("/jobs/import-url", { url }),
    onSuccess: done,
    onError: (e) => {
      if (e instanceof ApiError && (e.detail as any)?.needs_paste) {
        setHint((e.detail as any).message); setF({ ...f, url }); setMode("paste");
      }
    },
  });
  const man = useMutation({ mutationFn: () => api.post<Job>("/jobs/manual", f), onSuccess: done });
  return (
    <>
      <Button onClick={() => setMode("url")}><Link2 className="size-4" /> Import URL</Button>
      <Button onClick={() => setMode("paste")}><ClipboardPaste className="size-4" /> Paste description</Button>
      <Modal open={mode === "url"} onClose={() => setMode(null)} title="Import a job from a URL"
        footer={<><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button><Button variant="primary" loading={imp.isPending} onClick={() => imp.mutate()}>Import</Button></>}>
        <Field label="Job URL" hint="Greenhouse, Lever, Ashby, MyCareersFuture or any page with structured job data">
          <input className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" autoFocus />
        </Field>
        <p className="text-xs text-slate-500">LinkedIn, Indeed and similar sites don't allow automated retrieval — paste those descriptions instead.</p>
        {!(imp.error instanceof ApiError && (imp.error.detail as any)?.needs_paste) && <ErrorNote error={imp.error} />}
      </Modal>
      <Modal open={mode === "paste"} onClose={() => setMode(null)} title="Paste a job description"
        footer={<><Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button><Button variant="primary" loading={man.isPending} onClick={() => man.mutate()}>Add job</Button></>}>
        {hint && <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">{hint}</p>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Job title"><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Company"><input className={inputCls} value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></Field>
          <Field label="Location"><input className={inputCls} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
          <Field label="Application URL"><input className={inputCls} value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
        </div>
        <Field label="Full job description"><textarea className={inputCls} rows={10} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <ErrorNote error={man.error} />
      </Modal>
    </>
  );
}

function TailorDialog({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const [o, setO] = useState({ tone: "balanced", length: "two_page", include_projects: true, cover_letter: false, motivation: "",
    ordering: "relevance", spelling: "uk", date_format: "MMM YYYY", template: "classic" });
  const go = useMutation({
    mutationFn: () => api.post<{ id: number }>(`/jobs/${job.id}/tailor-resume`, { options: o }),
    onSuccess: (t) => nav(`/studio/${t.id}`),
  });
  return (
    <Modal open={open} onClose={onClose} title={`Tailor resume: ${job.title}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={go.isPending} onClick={() => go.mutate()}><Wand2 className="size-4" /> Generate</Button></>}>
      <p className="text-sm text-slate-500">Uses only your verified facts. Requirements you don't meet are reported as gaps, never invented.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Wording">
          <Segmented label="Wording" value={o.tone} onChange={(v) => setO({ ...o, tone: v })}
            options={[{ value: "conservative", label: "Conservative" }, { value: "balanced", label: "Balanced" }, { value: "targeted", label: "Targeted" }]} />
        </Field>
        <Field label="Length">
          <Segmented label="Length" value={o.length} onChange={(v) => setO({ ...o, length: v })}
            options={[{ value: "one_page", label: "1 page" }, { value: "two_page", label: "2 pages" }, { value: "flexible", label: "Flexible" }]} />
        </Field>
        <Field label="Section order">
          <Segmented label="Order" value={o.ordering} onChange={(v) => setO({ ...o, ordering: v })}
            options={[{ value: "relevance", label: "By relevance" }, { value: "preserve", label: "Original" }]} />
        </Field>
        <Field label="Spelling & dates">
          <div className="flex gap-2">
            <select className={inputCls} value={o.spelling} onChange={(e) => setO({ ...o, spelling: e.target.value })} aria-label="Spelling">
              <option value="uk">UK English</option><option value="us">US English</option>
            </select>
            <select className={inputCls} value={o.date_format} onChange={(e) => setO({ ...o, date_format: e.target.value })} aria-label="Date format">
              <option>MMM YYYY</option><option>MM/YYYY</option><option>YYYY</option>
            </select>
          </div>
        </Field>
        <Field label="Template">
          <select className={inputCls} value={o.template} onChange={(e) => setO({ ...o, template: e.target.value })}>
            <option value="classic">Classic (ATS-safe)</option><option value="modern">Modern (ATS-safe)</option>
          </select>
        </Field>
      </div>
      <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">Include projects <Toggle label="Include projects" checked={o.include_projects} onChange={(v) => setO({ ...o, include_projects: v })} /></div>
      <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">Generate cover letter <Toggle label="Cover letter" checked={o.cover_letter} onChange={(v) => setO({ ...o, cover_letter: v })} /></div>
      {o.cover_letter && (
        <Field label="Why this role? (optional)" hint="Your own words — JobPilot won't invent motivation">
          <textarea className={inputCls} rows={3} value={o.motivation} onChange={(e) => setO({ ...o, motivation: e.target.value })} />
        </Field>
      )}
      <ErrorNote error={go.error} />
    </Modal>
  );
}

function QuestionHelper({ jobId }: { jobId: number }) {
  const [q, setQ] = useState("");
  const ask = useMutation({ mutationFn: () => api.post<{ sensitive: boolean; answer: string; source: string }>(`/jobs/${jobId}/draft-answer`, { question: q }) });
  return (
    <Card title={<span className="inline-flex items-center gap-1.5"><MessageSquareText className="size-4" /> Application question helper</span>}>
      <div className="flex gap-2">
        <input className={inputCls} placeholder="Paste an application question…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button loading={ask.isPending} onClick={() => ask.mutate()} disabled={!q.trim()}>Draft</Button>
      </div>
      <ErrorNote error={ask.error} />
      {ask.data && (
        <div className={cx("mt-3 rounded-lg p-3 text-sm", ask.data.sensitive ? "bg-amber-50 text-amber-900" : "bg-slate-50")}>
          {ask.data.answer && <p className="whitespace-pre-wrap">{ask.data.answer}</p>}
          <p className="mt-1 text-xs opacity-80">{ask.data.sensitive && "Sensitive question · "}{ask.data.source}</p>
        </div>
      )}
    </Card>
  );
}

function JobPanel({ id }: { id: number }) {
  const qc = useQueryClient();
  const [tailorOpen, setTailorOpen] = useState(false);
  const [desc, setDesc] = useState("");
  const [scoringSince, setScoringSince] = useState<number | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["job", id], queryFn: () => api.get<JobDetail>(`/jobs/${id}`),
    refetchInterval: () => (scoringSince ? 3000 : false),
  });
  const inv = () => { qc.invalidateQueries({ queryKey: ["job", id] }); qc.invalidateQueries({ queryKey: ["jobs"] }); };
  const patch = useMutation({
    mutationFn: (b: Partial<Job>) => api.patch(`/jobs/${id}`, b),
    onSuccess: (_r, b) => { if (b.description) setScoringSince(Date.now()); inv(); },
  });
  const rescore = useMutation({ mutationFn: () => api.post(`/jobs/${id}/match`), onSuccess: () => { setScoringSince(Date.now()); inv(); } });
  useEffect(() => { setDesc(""); setScoringSince(null); }, [id]);
  // stop polling once a fresh score arrives (or after 3 minutes)
  useEffect(() => {
    if (!scoringSince || !data) return;
    const fresh = data.match && new Date(data.match.created_at).getTime() >= scoringSince - 5000;
    if (fresh || Date.now() - scoringSince > 180000) setScoringSince(null);
  }, [data, scoringSince]);
  if (isLoading || !data) return <Spinner />;
  const { job, match } = data;
  const thin = (job.description ?? "").length < 300;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{job.title}</h2>
            <p className="text-slate-600">{job.company}{job.location && ` · ${job.location}`}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <ScoreBadge score={match?.score} eligible={match?.eligible} />
              {job.work_arrangement && <Badge>{job.work_arrangement}</Badge>}
              {job.employment_type && <Badge>{job.employment_type}</Badge>}
              {fmtSalary(job) && <Badge tone="blue">{fmtSalary(job)}</Badge>}
              <Badge>via {job.provider}</Badge>
              {job.posted_at && <Badge>posted {fmtDate(job.posted_at)}</Badge>}
              {data.application && <Link to={`/applications/${data.application.id}`}><StatusBadge status={data.application.status} /></Link>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => setTailorOpen(true)} disabled={thin}><Wand2 className="size-4" /> Tailor resume</Button>
            {job.url && <a href={job.url} target="_blank" rel="noreferrer"><Button><ExternalLink className="size-4" /> Original</Button></a>}
            <Button onClick={() => patch.mutate({ saved: !job.saved })} aria-pressed={job.saved}><Bookmark className={cx("size-4", job.saved && "fill-current")} /> {job.saved ? "Saved" : "Save"}</Button>
            <Button variant="ghost" onClick={() => patch.mutate({ dismissed: !job.dismissed })}><EyeOff className="size-4" /> {job.dismissed ? "Restore" : "Dismiss"}</Button>
          </div>
        </div>
      </Card>
      {thin && (
        <Card title="Full description needed">
          <p className="mb-2 text-sm text-slate-500">This job came from an alert or a site that doesn't share the full description. Paste it to score and tailor.</p>
          <textarea className={inputCls} rows={6} value={desc} onChange={(e) => setDesc(e.target.value)} />
          <Button className="mt-2" variant="primary" disabled={desc.length < 100} loading={patch.isPending} onClick={() => patch.mutate({ description: desc })}>Save description</Button>
        </Card>
      )}
      <Card title="Fit assessment" actions={<Button size="sm" variant="ghost" loading={rescore.isPending} onClick={() => rescore.mutate()}><RefreshCw className="size-3.5" /> Re-score</Button>}>
        {scoringSince ? <Spinner label="Scoring against your profile…" /> : !match ? (
          <div className="text-sm text-slate-500">
            Not scored yet — jobs that pass your hard requirements and target titles are scored automatically.
            <Button className="ml-2" size="sm" loading={rescore.isPending} onClick={() => rescore.mutate()} disabled={thin}>Score this job</Button>
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p><b>{match.recommended_action}.</b> {match.explanation}</p>
            {match.hard_failures.length > 0 && (
              <div className="rounded-lg bg-red-50 p-3 text-red-800"><b>Hard requirements not met:</b><ul className="ml-4 list-disc">{match.hard_failures.map((h) => <li key={h}>{h}</li>)}</ul></div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <div><h3 className="mb-1 font-medium text-emerald-700">Evidenced in your profile</h3><ul className="ml-4 list-disc text-slate-700">{match.strong_matches.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div><h3 className="mb-1 font-medium text-amber-700">Gaps / not evidenced</h3><ul className="ml-4 list-disc text-slate-700">{match.gaps.map((x) => <li key={x}>{x}</li>)}</ul></div>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {Object.entries(match.breakdown).map(([k, v]) => <Badge key={k}>{k}: {Math.round(v)}</Badge>)}
            </div>
            <p className="text-xs text-slate-400">Scores are estimates of fit, not predictions of interview probability.</p>
          </div>
        )}
      </Card>
      {data.tailorings.length > 0 && (
        <Card title="Tailored resumes for this job">
          <ul className="space-y-1 text-sm">
            {data.tailorings.map((t) => (
              <li key={t.id} className="flex items-center gap-2">
                <Link className="text-brand-700 hover:underline" to={`/studio/${t.id}`}>Version #{t.id}</Link>
                <Badge>{t.status}</Badge>{t.status !== "generating" && t.status !== "failed" && <QaBadge status={t.qa_status} />}
                <span className="text-xs text-slate-400">{fmtDate(t.created_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <QuestionHelper jobId={job.id} />
      <Card title="Job description"><div className="prose-job max-h-[32rem] overflow-auto text-sm text-slate-700">{job.description}</div></Card>
      <TailorDialog job={job} open={tailorOpen} onClose={() => setTailorOpen(false)} />
    </div>
  );
}

export default function Discover() {
  const { jobId } = useParams();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [show, setShow] = useState("active");
  const [minScore, setMinScore] = useState(0);
  const jobs = useQuery({
    queryKey: ["jobs", q, show, minScore],
    queryFn: () => api.get<Job[]>(`/jobs?q=${encodeURIComponent(q)}&show=${show}&min_score=${minScore}`),
    refetchInterval: 15000,
  });
  return (
    <>
      <PageHeader title="Discover jobs" subtitle="Jobs from your connected sources, ranked against your profile and preferences." actions={<AddJob />} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input className={inputCls + " max-w-xs"} placeholder="Search title, company, location" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search jobs" />
        <Segmented label="Show" value={show} onChange={setShow} options={[
          { value: "active", label: "All" }, { value: "eligible", label: "Eligible" }, { value: "saved", label: "Saved" }, { value: "dismissed", label: "Dismissed" }]} />
        <select className={inputCls + " max-w-40"} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} aria-label="Minimum score">
          <option value={0}>Any score</option><option value={60}>Score ≥ 60</option><option value={75}>Score ≥ 75</option><option value={85}>Score ≥ 85</option>
        </select>
      </div>
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2">
          {jobs.isLoading ? <Spinner /> : !jobs.data?.length ? (
            <Empty title="No jobs yet">Connect a source under <Link className="text-brand-700 underline" to="/connections">Connections</Link>, or import/paste a job above.</Empty>
          ) : (
            <ul className="space-y-2">
              {jobs.data.map((j) => (
                <li key={j.id}>
                  <button onClick={() => nav(`/discover/${j.id}`)}
                    className={cx("w-full rounded-xl border bg-white p-3 text-left shadow-sm transition hover:border-brand-500",
                      String(j.id) === jobId ? "border-brand-500 ring-2 ring-brand-100" : "border-slate-200")}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{j.title}</div>
                        <div className="truncate text-sm text-slate-500">{j.company}{j.location && ` · ${j.location}`}</div>
                      </div>
                      <ScoreBadge score={j.match?.score} eligible={j.match?.eligible} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {j.application && <StatusBadge status={j.application.status} />}
                      {fmtSalary(j) && <Badge tone="blue">{fmtSalary(j)}</Badge>}
                      <span className="text-xs text-slate-400">{j.provider} · {fmtDate(j.posted_at || j.discovered_at)}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="lg:col-span-3">
          {jobId ? <JobPanel id={Number(jobId)} /> : <Empty title="Select a job">Pick a job to see its fit assessment and tailor your resume.</Empty>}
        </div>
      </div>
    </>
  );
}
