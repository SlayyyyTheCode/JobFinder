import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Send, Download, Clock } from "lucide-react";
import { api, Application, fileUrl, Job } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Field, PageHeader, Segmented, Spinner, StatusBadge, cx, fmtDate, fmtDateTime, inputCls, QaBadge } from "../ui";

type Detail = {
  application: Application; job: Job;
  events: { id: number; event_type: string; from_status: string; to_status: string; source: string; detail: Record<string, any>; occurred_at: string }[];
  emails: { id: number; subject: string; sender: string; event_type: string; received_at: string; confidence: number }[];
  tailoring: { id: number; qa_status: string; status: string; has_cover: boolean } | null;
  preflight: string[];
};

const GROUPS: Record<string, string[]> = {
  review: ["READY_FOR_REVIEW", "APPROVED", "ACTION_REQUIRED", "FAILED"],
  active: ["SUBMITTING", "SUBMITTED", "ACKNOWLEDGED", "IN_REVIEW", "INTERVIEW"],
  closed: ["OFFER", "REJECTED", "WITHDRAWN", "CLOSED", "UNKNOWN"],
};

export function SubmitPanel({ appId }: { appId: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["app", appId], queryFn: () => api.get<Detail>(`/applications/${appId}`) });
  const [opened, setOpened] = useState(false);
  const [conf, setConf] = useState("");
  const inv = () => { qc.invalidateQueries({ queryKey: ["app", appId] }); qc.invalidateQueries({ queryKey: ["apps"] }); qc.invalidateQueries({ queryKey: ["tailoring"] }); };
  const handoff = useMutation({
    mutationFn: () => api.post<{ url: string }>(`/applications/${appId}/handoff`),
    onSuccess: (r) => { window.open(r.url, "_blank", "noopener"); setOpened(true); inv(); },
  });
  const submitted = useMutation({ mutationFn: () => api.post(`/applications/${appId}/submitted`, { confirmation_id: conf }), onSuccess: inv });
  if (!data) return null;
  const a = data.application;
  if (a.submitted_at) return <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Submitted {fmtDateTime(a.submitted_at)}{a.confirmation_id && ` · ref ${a.confirmation_id}`}.</p>;
  return (
    <Card title={<span className="inline-flex items-center gap-1.5"><Send className="size-4" /> Submit application</span>}>
      <ol className="space-y-3 text-sm">
        <li>
          <b>1. Download your documents</b>
          {data.tailoring ? (
            <div className="mt-1 flex flex-wrap gap-2">
              <a href={fileUrl(`/tailorings/${data.tailoring.id}/download/pdf`)}><Button size="sm"><Download className="size-3.5" /> Resume PDF</Button></a>
              <a href={fileUrl(`/tailorings/${data.tailoring.id}/download/docx`)}><Button size="sm"><Download className="size-3.5" /> Resume DOCX</Button></a>
              {data.tailoring.has_cover && <a href={fileUrl(`/tailorings/${data.tailoring.id}/download/cover`)}><Button size="sm"><Download className="size-3.5" /> Cover letter</Button></a>}
            </div>
          ) : <p className="text-slate-500">No tailored resume attached.</p>}
        </li>
        <li>
          <b>2. Apply on the official page</b>
          <p className="text-xs text-slate-500">This source has no candidate submission API, so you submit on the employer's page. JobPilot never fills forms for you or bypasses CAPTCHAs.</p>
          {data.preflight.length > 0 && <ul className="mt-1 list-disc pl-5 text-red-700">{data.preflight.map((p) => <li key={p}>{p}</li>)}</ul>}
          <Button className="mt-1" variant="primary" size="sm" loading={handoff.isPending} disabled={data.preflight.length > 0} onClick={() => handoff.mutate()}>
            <ExternalLink className="size-3.5" /> Open application page
          </Button>
          <ErrorNote error={handoff.error} />
        </li>
        <li className={cx(!opened && "opacity-90")}>
          <b>3. Confirm you submitted</b>
          <div className="mt-1 flex flex-wrap gap-2">
            <input className={inputCls + " max-w-xs"} placeholder="Confirmation / reference (optional)" value={conf} onChange={(e) => setConf(e.target.value)} />
            <Button size="sm" loading={submitted.isPending} onClick={() => submitted.mutate()}>Mark as submitted</Button>
          </div>
          <p className="mt-1 text-xs text-slate-500">Only mark it once the employer's site confirms your application. A connected mailbox will pick up the confirmation email too.</p>
          <ErrorNote error={submitted.error} />
        </li>
      </ol>
    </Card>
  );
}

export function ApplicationDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["app", Number(id)], queryFn: () => api.get<Detail>(`/applications/${id}`) });
  const states = useQuery({ queryKey: ["states"], queryFn: () => api.get<{ pipeline: string[]; exceptions: string[] }>("/application-states") });
  const [status, setStatus] = useState("");
  const [note, setNote] = useState("");
  const inv = () => qc.invalidateQueries({ queryKey: ["app", Number(id)] });
  const setSt = useMutation({ mutationFn: () => api.post(`/applications/${id}/events`, { status, note }), onSuccess: () => { setNote(""); inv(); } });
  const patch = useMutation({ mutationFn: (b: Record<string, unknown>) => api.patch(`/applications/${id}`, b), onSuccess: inv });
  const approve = useMutation({ mutationFn: () => api.post(`/applications/${id}/approve`), onSuccess: inv });
  if (!data) return <Spinner />;
  const { application: a, job } = data;
  return (
    <>
      <PageHeader title={job.title} subtitle={<><Link className="hover:underline" to={`/discover/${job.id}`}>{job.company}</Link>{job.location && ` · ${job.location}`}</>}
        actions={<StatusBadge status={a.status} />} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {a.status === "READY_FOR_REVIEW" && data.tailoring && (
            <Card title="Review required">
              <p className="text-sm">Review the tailored resume before approving.</p>
              <div className="mt-2 flex gap-2">
                <Link to={`/studio/${data.tailoring.id}`}><Button variant="primary">Open resume studio</Button></Link>
                {data.tailoring.qa_status !== "fail" && <Button loading={approve.isPending} onClick={() => approve.mutate()}>Approve as is</Button>}
              </div>
              <ErrorNote error={approve.error} />
            </Card>
          )}
          {a.status !== "READY_FOR_REVIEW" && <SubmitPanel appId={a.id} />}
          <Card title="Timeline">
            <ol className="relative space-y-4 border-l border-slate-200 pl-5">
              {data.events.map((e) => (
                <li key={e.id}>
                  <span className="absolute -left-1.5 mt-1.5 size-3 rounded-full border-2 border-white bg-brand-500" />
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <b>{e.event_type.replace(/_/g, " ")}</b>
                    {e.to_status && e.to_status !== e.from_status && <StatusBadge status={e.to_status} />}
                    {e.detail?.ignored_target && <Badge title="Automated update would have moved status backwards">ignored → {e.detail.ignored_target.toLowerCase()}</Badge>}
                    <Badge>{e.source}</Badge>
                  </div>
                  <div className="text-xs text-slate-500">{fmtDateTime(e.occurred_at)}{e.detail?.subject && ` · “${e.detail.subject}”`}{e.detail?.note && ` · ${e.detail.note}`}</div>
                </li>
              ))}
            </ol>
          </Card>
          {data.emails.length > 0 && (
            <Card title="Linked emails">
              <ul className="space-y-1 text-sm">{data.emails.map((m) => <li key={m.id}><Badge>{m.event_type}</Badge> {m.subject} <span className="text-xs text-slate-400">{fmtDateTime(m.received_at)}</span></li>)}</ul>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Details">
            <dl className="space-y-1.5 text-sm">
              <div className="flex justify-between"><dt className="text-slate-500">Source</dt><dd>{job.provider}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Method</dt><dd>{a.method}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Approved by</dt><dd>{a.approved_by || "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Submitted</dt><dd>{fmtDate(a.submitted_at) || "—"}</dd></div>
              {a.provider_status && <div className="flex justify-between"><dt className="text-slate-500">Last signal</dt><dd>{a.provider_status}</dd></div>}
              {data.tailoring && <div className="flex justify-between"><dt className="text-slate-500">Resume</dt><dd><Link className="text-brand-700 hover:underline" to={`/studio/${data.tailoring.id}`}>#{data.tailoring.id}</Link> <QaBadge status={data.tailoring.qa_status} /></dd></div>}
            </dl>
          </Card>
          <Card title="Update status manually">
            <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="New status">
              <option value="">Choose status…</option>
              {[...(states.data?.pipeline ?? []), ...(states.data?.exceptions ?? [])].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").toLowerCase()}</option>)}
            </select>
            <input className={inputCls + " mt-2"} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button className="mt-2" disabled={!status} loading={setSt.isPending} onClick={() => setSt.mutate()}>Update</Button>
          </Card>
          <Card title="Notes & follow-up">
            <Field label="Follow up on">
              <input type="date" className={inputCls} defaultValue={a.follow_up_at?.slice(0, 10) ?? ""} onChange={(e) => patch.mutate({ follow_up_at: e.target.value })} />
            </Field>
            <textarea className={inputCls + " mt-3"} rows={4} defaultValue={a.notes} placeholder="Recruiter name, interview prep…" onBlur={(e) => e.target.value !== a.notes && patch.mutate({ notes: e.target.value })} />
          </Card>
        </div>
      </div>
    </>
  );
}

export default function Applications() {
  const [group, setGroup] = useState("review");
  const { data, isLoading } = useQuery({ queryKey: ["apps"], queryFn: () => api.get<Application[]>("/applications"), refetchInterval: 15000 });
  const rows = (data ?? []).filter((a) => GROUPS[group].includes(a.status));
  const count = (g: string) => (data ?? []).filter((a) => GROUPS[g].includes(a.status)).length;
  return (
    <>
      <PageHeader title="Applications" subtitle="Every application, its documents and its status history." />
      <div className="mb-4">
        <Segmented label="Group" value={group} onChange={setGroup} options={[
          { value: "review", label: `To do (${count("review")})` }, { value: "active", label: `In progress (${count("active")})` }, { value: "closed", label: `Closed (${count("closed")})` }]} />
      </div>
      {isLoading ? <Spinner /> : !rows.length ? <Empty title="Nothing here">Tailor a resume from <Link className="text-brand-700 underline" to="/discover">Discover</Link> to start an application.</Empty> : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">Role</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Submitted</th><th className="px-4 py-2">Updated</th><th className="px-4 py-2"></th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((a) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5"><Link to={`/applications/${a.id}`} className="font-medium hover:underline">{a.job?.title}</Link><div className="text-xs text-slate-500">{a.job?.company} · {a.job?.provider}</div></td>
                  <td className="px-4 py-2.5"><StatusBadge status={a.status} />{a.approved_by === "autopilot" && <Badge tone="violet">autopilot</Badge>}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(a.submitted_at) || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-600">{fmtDate(a.updated_at)}</td>
                  <td className="px-4 py-2.5 text-right">{a.follow_up_at && new Date(a.follow_up_at) <= new Date() && GROUPS.active.includes(a.status) && <Badge tone="amber"><Clock className="size-3" /> follow up</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
