import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { diffWords } from "diff";
import { Download, CheckCircle2, XCircle, AlertTriangle, ExternalLink } from "lucide-react";
import { api, fileUrl, Tailoring, Issue } from "../api";
import { Badge, Button, Card, ErrorNote, PageHeader, QaBadge, Segmented, Spinner, StatusBadge, cx, inputCls } from "../ui";
import { SubmitPanel } from "./Applications";

type Tab = "preview" | "compare" | "report" | "qa" | "edit" | "cover";

function Compare({ master, tailored }: { master: string; tailored: string }) {
  const parts = useMemo(() => diffWords(master, tailored), [master, tailored]);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-600">Master resume</h3>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-4 font-sans text-[13px] leading-relaxed">
          {parts.map((p, i) => (p.added ? null : <span key={i} className={p.removed ? "bg-red-100 text-red-800 line-through decoration-red-400" : ""}>{p.value}</span>))}
        </pre>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-600">Tailored resume</h3>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-4 font-sans text-[13px] leading-relaxed">
          {parts.map((p, i) => (p.removed ? null : <span key={i} className={p.added ? "bg-emerald-100 text-emerald-900" : ""}>{p.value}</span>))}
        </pre>
      </div>
    </div>
  );
}

function List({ title, items, tone }: { title: string; items?: string[]; tone?: string }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className={cx("mb-1 text-sm font-semibold", tone)}>{title}</h3>
      <ul className="ml-4 list-disc space-y-0.5 text-sm text-slate-700">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

function QaList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <p className="flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="size-4" /> Every claim traced to a verified fact. No issues found.</p>;
  return (
    <ul className="space-y-2">
      {issues.map((i, n) => (
        <li key={n} className={cx("rounded-lg p-3 text-sm", i.severity === "fail" ? "bg-red-50 text-red-900" : "bg-amber-50 text-amber-900")}>
          <div className="flex items-center gap-2 font-medium">
            {i.severity === "fail" ? <XCircle className="size-4" /> : <AlertTriangle className="size-4" />}
            <Badge tone={i.severity === "fail" ? "red" : "amber"}>{i.check}</Badge> {i.message}
          </div>
          {i.item && <p className="mt-1 pl-6 italic opacity-80">“{i.item}”</p>}
        </li>
      ))}
    </ul>
  );
}

function Editor({ t }: { t: Tailoring }) {
  const qc = useQueryClient();
  const [c, setC] = useState<Record<string, any>>(t.content);
  useEffect(() => setC(t.content), [t.content]);
  const view = t.content.view ?? {};
  const save = useMutation({
    mutationFn: () => { const { view: _v, ...rest } = c; return api.patch(`/tailorings/${t.id}`, { content: rest }); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring", t.id] }),
  });
  if (t.status === "approved") return <p className="text-sm text-slate-500">Approved resumes are locked. Tailor again to make a new version.</p>;
  const setBullet = (sec: "roles" | "projects", ri: number, bi: number, text: string) => {
    const next = structuredClone(c);
    next[sec][ri].bullets[bi].text = text;
    setC(next);
  };
  const delBullet = (sec: "roles" | "projects", ri: number, bi: number) => {
    const next = structuredClone(c);
    next[sec][ri].bullets.splice(bi, 1);
    setC(next);
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">Edit wording here. Employer names, titles and dates come from your profile and can't be changed here. Your edits are re-checked against your facts.</p>
      <label className="block">
        <span className="text-sm font-medium">Summary</span>
        <textarea className={inputCls + " mt-1"} rows={3} value={c.summary ?? ""} onChange={(e) => setC({ ...c, summary: e.target.value })} />
      </label>
      {(["roles", "projects"] as const).map((sec) => (c[sec] ?? []).map((r: any, ri: number) => (
        <div key={`${sec}${ri}`} className="rounded-lg border border-slate-200 p-3">
          <div className="mb-2 text-sm font-semibold">{sec === "roles" ? `${view.experience?.[ri]?.title ?? ""} — ${view.experience?.[ri]?.employer ?? ""}` : view.projects?.[ri]?.name ?? "Project"}</div>
          {r.bullets.map((b: any, bi: number) => (
            <div key={bi} className="mb-2 flex gap-2">
              <textarea className={inputCls} rows={2} value={b.text} onChange={(e) => setBullet(sec, ri, bi, e.target.value)} aria-label="Bullet text" />
              <div className="flex flex-col items-end gap-1">
                <span className="text-[10px] text-slate-400">{b.fact_ids.join(", ")}</span>
                <Button size="sm" variant="ghost" onClick={() => delBullet(sec, ri, bi)}>Remove</Button>
              </div>
            </div>
          ))}
        </div>
      )))}
      <ErrorNote error={save.error} />
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save & re-check</Button>
    </div>
  );
}

export default function Studio() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("preview");
  const { data: t } = useQuery({
    queryKey: ["tailoring", Number(id)], queryFn: () => api.get<Tailoring>(`/tailorings/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2500 : false),
  });
  const inv = () => qc.invalidateQueries({ queryKey: ["tailoring", Number(id)] });
  const approve = useMutation({ mutationFn: () => api.post(`/tailorings/${id}/approve`), onSuccess: inv });
  const reject = useMutation({ mutationFn: () => api.post(`/tailorings/${id}/reject`), onSuccess: inv });
  const [nonce, setNonce] = useState(0);
  useEffect(() => setNonce((n) => n + 1), [t?.qa_status, t?.content]);

  if (!t) return <Spinner />;
  if (t.status === "generating") return (
    <Card><div className="space-y-2 py-8 text-center"><Spinner label="Tailoring your resume from verified facts, then checking every claim…" /><p className="text-xs text-slate-400">Usually under 2 minutes.</p></div></Card>
  );
  if (t.status === "failed") return (
    <>
      <PageHeader title="Tailoring failed" />
      <ErrorNote error={new Error(t.error)} />
      <Link className="mt-4 inline-block text-brand-700 underline" to={`/discover/${t.job_id}`}>Back to job</Link>
    </>
  );
  const issues = t.qa.issues ?? [];
  const cr = t.change_report ?? {};
  return (
    <>
      <PageHeader title="Resume studio"
        subtitle={<>For <Link className="text-brand-700 hover:underline" to={`/discover/${t.job.id}`}>{t.job.title} at {t.job.company}</Link> · model {t.model} · {t.prompt_version}</>}
        actions={<>
          <a href={fileUrl(`/tailorings/${t.id}/download/docx`)}><Button><Download className="size-4" /> DOCX</Button></a>
          <a href={fileUrl(`/tailorings/${t.id}/download/pdf`)}><Button><Download className="size-4" /> PDF</Button></a>
          {t.cover_docx_path && <a href={fileUrl(`/tailorings/${t.id}/download/cover`)}><Button><Download className="size-4" /> Cover letter</Button></a>}
        </>} />
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <QaBadge status={t.qa_status} />
        <Badge>{t.status}</Badge>
        {t.qa.pages != null && <Badge>{t.qa.pages} page{t.qa.pages === 1 ? "" : "s"}</Badge>}
        {t.application && <Link to={`/applications/${t.application.id}`}><StatusBadge status={t.application.status} /></Link>}
        <div className="ml-auto flex gap-2">
          {t.status === "draft" && <>
            <Button variant="ghost" loading={reject.isPending} onClick={() => reject.mutate()}>Reject</Button>
            <Button variant="primary" loading={approve.isPending} disabled={t.qa_status === "fail"} onClick={() => approve.mutate()}
              title={t.qa_status === "fail" ? "Fix the failed checks first" : undefined}>
              <CheckCircle2 className="size-4" /> Approve resume
            </Button>
          </>}
        </div>
      </div>
      <ErrorNote error={approve.error} />
      {t.qa_status === "fail" && <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">This version contains claims that couldn't be traced to your verified facts. Edit them or regenerate — it can't be approved as is.</p>}
      {t.application && t.status === "approved" && <div className="mb-4"><SubmitPanel appId={t.application.id} /></div>}
      <div className="mb-4">
        <Segmented label="View" value={tab} onChange={setTab} options={[
          { value: "preview", label: "Preview" }, { value: "compare", label: "Compare" }, { value: "report", label: "Change report" },
          { value: "qa", label: `Checks (${issues.length})` }, { value: "edit", label: "Edit" },
          ...(t.cover_letter ? [{ value: "cover" as Tab, label: "Cover letter" }] : [])]} />
      </div>
      {tab === "preview" && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <iframe key={nonce} title="Resume preview" src={fileUrl(`/tailorings/${t.id}/preview`)} className="h-[80vh] w-full" />
        </div>
      )}
      {tab === "compare" && <Compare master={cr.master_text ?? ""} tailored={cr.tailored_text ?? ""} />}
      {tab === "report" && (
        <Card>
          <div className="grid gap-5 md:grid-cols-2">
            <List title="Sections changed" items={cr.sections_changed} />
            <List title="Job keywords incorporated" items={cr.keywords_incorporated} tone="text-emerald-700" />
            <List title="Experience prioritised" items={cr.experience_prioritised} />
            <List title="Requirements NOT evidenced by your profile" items={cr.unsupported_requirements} tone="text-amber-700" />
            <List title="Wording to confirm" items={cr.needs_confirmation} tone="text-amber-700" />
            <List title="Content left out" items={cr.content_removed} tone="text-slate-500" />
          </div>
          <p className="mt-4 text-xs text-slate-500">Gaps are never filled in for you. If you do have that experience, add it to your profile and tailor again.</p>
        </Card>
      )}
      {tab === "qa" && <Card><QaList issues={issues} /></Card>}
      {tab === "edit" && <Card><Editor t={t} /></Card>}
      {tab === "cover" && <Card><div className="prose-job text-sm">{t.cover_letter}</div><a className="mt-3 inline-block" href={fileUrl(`/tailorings/${t.id}/download/cover`)}><Button><Download className="size-4" /> Download DOCX</Button></a></Card>}
      {t.status === "approved" && <p className="mt-4 flex items-center gap-1.5 text-sm text-emerald-700"><ExternalLink className="size-4" /> Approved. Use the panel above to open the official application page.</p>}
    </>
  );
}
