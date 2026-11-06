import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2, Mail } from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, ErrorNote, Field, Modal, PageHeader, Spinner, Toggle, fmtDateTime, inputCls } from "../ui";

type Provider = { name: string; label: string; config_fields: { key: string; label: string; hint: string; optional?: boolean }[]; capabilities: Record<string, boolean> };
type Source = { id: number; provider: string; label: string; config: Record<string, string>; enabled: boolean; autopilot_enabled: boolean; status: string; last_run_at: string | null; last_error: string; job_count: number };
type MailConn = { id: number; provider: string; account: string; status: string; last_polled_at: string | null; last_error: string; scopes: string[] };
type Status = { gmail_configured: boolean; outlook_configured: boolean };

const EXAMPLES: Record<string, string> = {
  greenhouse: "e.g. stripe, airbnb, gitlab", lever: "e.g. palantir, spotify", ashby: "e.g. openai, notion, ramp",
  mycareersfuture: "e.g. AI solution architect",
};

function AddSource({ providers }: { providers: Provider[] }) {
  const qc = useQueryClient();
  const [prov, setProv] = useState<Provider | null>(null);
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/job-sources/${prov!.name}/connect`, { label, config: cfg }),
    onSuccess: () => { setProv(null); setCfg({}); setLabel(""); qc.invalidateQueries({ queryKey: ["sources"] }); },
  });
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {providers.map((p) => <Button key={p.name} onClick={() => setProv(p)}><Plus className="size-4" /> {p.label}</Button>)}
      </div>
      <Modal open={!!prov} onClose={() => setProv(null)} title={`Connect ${prov?.label ?? ""}`}
        footer={<><Button variant="ghost" onClick={() => setProv(null)}>Cancel</Button><Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>Connect</Button></>}>
        {prov && <>
          <p className="text-sm text-slate-500">
            {prov.name === "mycareersfuture" ? "Searches Singapore's MyCareersFuture listings for your keywords. Polled hourly, rate-limited."
              : `Watches one company's public ${prov.label} job board (official read-only API). Add one connection per company.`}
          </p>
          {prov.config_fields.map((f) => (
            <Field key={f.key} label={f.label} hint={f.optional ? "optional" : f.hint}>
              <input className={inputCls} value={cfg[f.key] ?? ""} placeholder={f.key === "board" || f.key === "search" ? EXAMPLES[prov.name] : f.hint}
                onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value })} />
            </Field>
          ))}
          {prov.name !== "mycareersfuture" && (
            <Field label="Company name" hint="optional, for display"><input className={inputCls} value={cfg.company ?? ""} onChange={(e) => setCfg({ ...cfg, company: e.target.value })} /></Field>
          )}
          <Field label="Label" hint="optional"><input className={inputCls} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <p className="text-xs text-slate-500">Capabilities: discovery ✓ · submission {prov.capabilities.submit ? "✓" : "✗ (handoff to employer page)"} · status {prov.capabilities.status ? "✓" : "✗ (via email)"}</p>
          <ErrorNote error={add.error} />
        </>}
      </Modal>
    </>
  );
}

function Mailboxes() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/status") });
  const { data } = useQuery({
    queryKey: ["mail"], queryFn: () => api.get<{ connections: MailConn[]; pending: Record<string, { state: string; error: string }> }>("/email/connections"),
    refetchInterval: (q) => (Object.values(q.state.data?.pending ?? {}).some((p) => p.state === "running") ? 2000 : false),
  });
  const inv = () => qc.invalidateQueries({ queryKey: ["mail"] });
  const connect = useMutation({ mutationFn: (p: string) => api.post(`/email/${p}/connect`), onSuccess: inv });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/email/connections/${id}`), onSuccess: inv });
  const poll = useMutation({ mutationFn: (id: number) => api.post(`/email/connections/${id}/poll`), onSuccess: inv });
  const ok = { gmail: st.data?.gmail_configured, outlook: st.data?.outlook_configured };
  return (
    <Card title={<span className="inline-flex items-center gap-1.5"><Mail className="size-4" /> Mailboxes</span>}>
      <p className="mb-3 text-sm text-slate-500">Read-only access. JobPilot scans for application confirmations, interview invites, rejections and job alerts. Unrelated emails are skipped and no message bodies are stored.</p>
      <div className="flex flex-wrap gap-2">
        {(["gmail", "outlook"] as const).map((p) => (
          <Button key={p} disabled={!ok[p]} loading={data?.pending[p]?.state === "running"} onClick={() => connect.mutate(p)}
            title={!ok[p] ? "OAuth app not configured — see docs/SETUP_OAUTH.md" : undefined}>
            <Plus className="size-4" /> {p === "gmail" ? "Connect Gmail" : "Connect Outlook / Hotmail"}
          </Button>
        ))}
      </div>
      {(!ok.gmail || !ok.outlook) && <p className="mt-2 text-xs text-amber-700">To enable a mailbox, register an OAuth app and add it to .env — steps in docs/SETUP_OAUTH.md.</p>}
      {Object.entries(data?.pending ?? {}).map(([p, s]) => s.state === "running" ? <p key={p} className="mt-2 text-sm text-slate-600">Waiting for you to approve access in the browser window…</p> : s.state === "error" ? <ErrorNote key={p} error={new Error(s.error)} /> : null)}
      <ul className="mt-4 space-y-2">
        {data?.connections.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm">
            <b>{c.account || c.provider}</b><Badge>{c.provider}</Badge>
            <Badge tone={c.status === "connected" ? "green" : "red"}>{c.status.replace("_", " ")}</Badge>
            <span className="text-xs text-slate-400">{c.last_polled_at ? `checked ${fmtDateTime(c.last_polled_at)}` : "not checked yet"}</span>
            {c.last_error && <span className="w-full text-xs text-red-600">{c.last_error}</span>}
            <div className="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => poll.mutate(c.id)}><RefreshCw className="size-3.5" /> Check now</Button>
              <Button size="sm" variant="ghost" onClick={() => confirm("Disconnect and delete stored tokens?") && del.mutate(c.id)}><Trash2 className="size-3.5" /> Disconnect</Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function Connections() {
  const qc = useQueryClient();
  const prov = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/providers") });
  const src = useQuery({ queryKey: ["sources"], queryFn: () => api.get<Source[]>("/job-sources"), refetchInterval: 10000 });
  const inv = () => qc.invalidateQueries({ queryKey: ["sources"] });
  const patch = useMutation({ mutationFn: (x: { id: number; b: Partial<Source> }) => api.patch(`/job-sources/${x.id}`, x.b), onSuccess: inv });
  const poll = useMutation({ mutationFn: (id: number) => api.post(`/job-sources/${id}/poll`), onSuccess: inv });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/job-sources/${id}`), onSuccess: inv });
  return (
    <>
      <PageHeader title="Connections" subtitle="Job sources JobPilot watches, and the mailboxes it monitors for application updates." />
      <div className="space-y-6">
        <Card title="Job sources">
          {prov.data ? <AddSource providers={prov.data} /> : <Spinner />}
          <p className="mt-3 text-xs text-slate-500">LinkedIn, Indeed and JobStreet don't offer public APIs. To use them, set up their job-alert emails and connect your mailbox below — JobPilot imports the jobs from the alerts.</p>
          <ul className="mt-4 space-y-2">
            {src.data?.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 p-3 text-sm">
                <Toggle label={`Enable ${s.label}`} checked={s.enabled} onChange={(v) => patch.mutate({ id: s.id, b: { enabled: v } })} />
                <div className="min-w-0">
                  <div className="font-medium">{s.label}</div>
                  <div className="text-xs text-slate-500">{s.job_count} jobs · {s.last_run_at ? `checked ${fmtDateTime(s.last_run_at)}` : "first check queued"}</div>
                  {s.last_error && <div className="text-xs text-red-600">{s.last_error}</div>}
                </div>
                <Badge tone={s.status === "ok" ? "green" : "red"}>{s.status}</Badge>
                {s.autopilot_enabled && <Badge tone="violet">autopilot</Badge>}
                <div className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" loading={poll.isPending && poll.variables === s.id} onClick={() => poll.mutate(s.id)}><RefreshCw className="size-3.5" /> Check now</Button>
                  <Button size="sm" variant="ghost" onClick={() => confirm(`Remove ${s.label}?`) && del.mutate(s.id)}><Trash2 className="size-3.5" /></Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <Mailboxes />
      </div>
    </>
  );
}
