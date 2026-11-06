import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Application } from "../api";
import { Badge, Button, Card, Empty, PageHeader, Segmented, Spinner, fmtDateTime, inputCls } from "../ui";

type Ev = {
  id: number; sender: string; subject: string; event_type: string; company: string; role: string; confidence: number;
  application_id: number | null; link_status: string; received_at: string;
};

function Row({ e, apps }: { e: Ev; apps: Application[] }) {
  const qc = useQueryClient();
  const [sel, setSel] = useState<number | "">(e.application_id ?? "");
  const conf = useMutation({
    mutationFn: (appId: number | null) => api.post(`/email/events/${e.id}/confirm`, { application_id: appId }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["email-events"] }); qc.invalidateQueries({ queryKey: ["apps"] }); },
  });
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={["interview", "offer"].includes(e.event_type) ? "green" : e.event_type === "rejection" ? "red" : "blue"}>{e.event_type.replace("_", " ")}</Badge>
        <span className="font-medium">{e.subject}</span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{e.sender} · {fmtDateTime(e.received_at)}{e.company && ` · company: ${e.company}`}{e.role && ` · role: ${e.role}`} · match confidence {Math.round(e.confidence * 100)}%</p>
      {e.link_status === "needs_confirmation" && (
        <div className="mt-3 flex flex-wrap gap-2">
          <select className={inputCls + " max-w-md"} value={sel} onChange={(x) => setSel(x.target.value ? Number(x.target.value) : "")} aria-label="Application">
            <option value="">Choose the application this email is about…</option>
            {apps.map((a) => <option key={a.id} value={a.id}>{a.job?.title} — {a.job?.company}</option>)}
          </select>
          <Button variant="primary" disabled={!sel} loading={conf.isPending} onClick={() => conf.mutate(Number(sel))}>Link</Button>
          <Button variant="ghost" onClick={() => conf.mutate(null)}>Not job-related</Button>
        </div>
      )}
    </li>
  );
}

export default function Inbox() {
  const [st, setSt] = useState("needs_confirmation");
  const evs = useQuery({ queryKey: ["email-events", st], queryFn: () => api.get<Ev[]>(`/email/events${st ? `?status=${st}` : ""}`) });
  const apps = useQuery({ queryKey: ["apps"], queryFn: () => api.get<Application[]>("/applications") });
  return (
    <>
      <PageHeader title="Email matches" subtitle="Job emails detected in your connected mailbox. Only subject, sender and extracted details are stored — never message bodies." />
      <div className="mb-4">
        <Segmented label="Filter" value={st} onChange={setSt} options={[
          { value: "needs_confirmation", label: "Needs confirmation" }, { value: "linked", label: "Linked" },
          { value: "alert_imported", label: "Job alerts" }, { value: "ignored", label: "Ignored" }]} />
      </div>
      {evs.isLoading ? <Spinner /> : !evs.data?.length ? <Empty title="Nothing to show" /> : (
        <ul className="space-y-3">{evs.data.map((e) => <Row key={e.id} e={e} apps={apps.data ?? []} />)}</ul>
      )}
      <Card className="mt-6" title="How matching works">
        <p className="text-sm text-slate-600">Emails are pre-filtered by job keywords and recruiting-system senders; only those are classified. High-confidence matches update your application automatically (status only ever moves forward). Anything ambiguous waits here for you.</p>
      </Card>
    </>
  );
}
