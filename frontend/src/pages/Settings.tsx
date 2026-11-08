import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ShieldAlert } from "lucide-react";
import { api, fileUrl } from "../api";
import { Badge, Button, Card, ErrorNote, Modal, PageHeader, Spinner, Toggle, fmtDateTime, inputCls } from "../ui";

type Answer = { key: string; question: string; category: string; answer: string; confirmed: boolean };
type Task = { id: number; kind: string; status: string; attempts: number; last_error: string; updated_at: string };
type Audit = { id: number; actor: string; action: string; entity: string; entity_id: number | null; ts: string };
type Status = { hosted: boolean; llm: { provider: string; model: string; fast_model: string; configured: boolean } };

function ApiKeyForm({ configured }: { configured: boolean }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: () => api.put("/settings/gemini-key", { api_key: key }),
    onSuccess: () => { setKey(""); qc.invalidateQueries({ queryKey: ["status"] }); },
  });
  const clear = useMutation({ mutationFn: () => api.del("/settings/gemini-key"), onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }) });
  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <label className="block text-sm font-medium" htmlFor="gkey">Gemini API key</label>
      <div className="mt-1 flex gap-2">
        <input id="gkey" type="password" autoComplete="off" className={inputCls} value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={configured ? "Key saved — paste a new one to replace" : "Paste your key from aistudio.google.com/apikey"} />
        <Button variant="primary" disabled={key.length < 20} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
        {configured && <Button variant="ghost" onClick={() => clear.mutate()}>Remove</Button>}
      </div>
      <p className="mt-1 text-xs text-slate-500">Checked with Gemini, then stored in Windows Credential Manager — not in a file.</p>
      <ErrorNote error={save.error} />
      {save.isSuccess && <p className="mt-1 text-sm text-emerald-600">Key verified and saved.</p>}
    </div>
  );
}

function AnswerRow({ a }: { a: Answer }) {
  const qc = useQueryClient();
  const [v, setV] = useState(a.answer);
  const [c, setC] = useState(a.confirmed);
  const save = useMutation({ mutationFn: () => api.put("/answers", { key: a.key, question: a.question, answer: v, confirmed: c }), onSuccess: () => qc.invalidateQueries({ queryKey: ["answers"] }) });
  const dirty = v !== a.answer || c !== a.confirmed;
  return (
    <li className="rounded-lg border border-slate-200 p-3">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium">{a.question}{a.category === "sensitive" && <Badge tone="amber">sensitive</Badge>}</div>
      <textarea className={inputCls} rows={2} value={v} onChange={(e) => setV(e.target.value)} placeholder="Your answer, in your words" />
      <div className="mt-2 flex items-center gap-2 text-sm">
        <Toggle label="Confirmed" checked={c} onChange={setC} /> <span>I confirm this answer is accurate</span>
        <Button size="sm" className="ml-auto" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </li>
  );
}

export default function Settings() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/status") });
  const answers = useQuery({ queryKey: ["answers"], queryFn: () => api.get<Answer[]>("/answers") });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Task[]>("/tasks"), refetchInterval: 10000 });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<Audit[]>("/audit?limit=100") });
  const retry = useMutation({ mutationFn: (id: number) => api.post(`/tasks/${id}/retry`), onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }) });
  const [delOpen, setDelOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const wipe = useMutation({ mutationFn: () => api.post("/delete-all-data", { confirm: confirmText }), onSuccess: () => { setDelOpen(false); qc.invalidateQueries(); } });
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="AI model">
          {st.data ? (
            <div className="space-y-1 text-sm">
              <p>Provider: <b>{st.data.llm.provider}</b> {st.data.llm.configured ? <Badge tone="green">configured</Badge> : <Badge tone="red">API key missing</Badge>}</p>
              <p>Main model: <code>{st.data.llm.model}</code> · fast model: <code>{st.data.llm.fast_model}</code></p>
              <p className="pt-2 text-xs text-slate-500">To switch model or provider, edit <code>LLM_PROVIDER</code>, <code>LLM_MODEL</code> and <code>LLM_FAST_MODEL</code> in <code>.env</code> and restart. Every generated resume records the model and prompt version used.</p>
              {st.data.llm.provider === "gemini" && !st.data.hosted && <ApiKeyForm configured={st.data.llm.configured} />}
              {st.data.hosted && <p className="pt-2 text-xs text-slate-500">The API key is set on the server with the <code>GEMINI_API_KEY</code> environment variable.</p>}
            </div>
          ) : <Spinner />}
        </Card>
        <Card title="Your data">
          <p className="text-sm text-slate-600">Everything is stored locally on this computer. OAuth tokens are encrypted with a key kept in Windows Credential Manager.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a href={fileUrl("/export")}><Button><Download className="size-4" /> Export all data</Button></a>
            <Button variant="danger" onClick={() => setDelOpen(true)}>Delete all data</Button>
          </div>
        </Card>
        <Card title="Application answers" className="lg:col-span-2">
          <p className="mb-3 flex items-start gap-2 text-sm text-slate-600"><ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
            JobPilot never guesses sensitive declarations (work authorisation, clearance, criminal history, demographics, disability, conflicts of interest, legal declarations, salary). Only answers you write and confirm here are ever offered.</p>
          {answers.data ? <ul className="grid gap-3 md:grid-cols-2">{answers.data.map((a) => <AnswerRow key={a.key} a={a} />)}</ul> : <Spinner />}
        </Card>
        <Card title="Background tasks">
          <ul className="max-h-80 space-y-1.5 overflow-auto text-sm">
            {tasks.data?.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={t.status === "done" ? "green" : t.status === "dead" ? "red" : t.status === "running" ? "blue" : "slate"}>{t.status}</Badge>
                <code className="text-xs">{t.kind}</code><span className="text-xs text-slate-400">{fmtDateTime(t.updated_at)}</span>
                {t.status === "dead" && <Button size="sm" variant="ghost" onClick={() => retry.mutate(t.id)}>Retry</Button>}
                {t.last_error && t.status !== "done" && <p className="w-full truncate text-xs text-red-600" title={t.last_error}>{t.last_error.split("\n")[0]}</p>}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Audit log">
          <ul className="max-h-80 space-y-1 overflow-auto text-xs">
            {audit.data?.map((e) => (
              <li key={e.id} className="flex gap-2"><span className="w-28 shrink-0 text-slate-400">{fmtDateTime(e.ts)}</span><Badge>{e.actor}</Badge><span>{e.action}</span>{e.entity_id && <span className="text-slate-400">#{e.entity_id}</span>}</li>
            ))}
          </ul>
        </Card>
      </div>
      <Modal open={delOpen} onClose={() => setDelOpen(false)} title="Delete all data?"
        footer={<><Button variant="ghost" onClick={() => setDelOpen(false)}>Cancel</Button><Button variant="danger" disabled={confirmText !== "DELETE"} loading={wipe.isPending} onClick={() => wipe.mutate()}>Delete everything</Button></>}>
        <p className="text-sm">This permanently deletes your resumes, profile, jobs, tailored documents, applications and mailbox connections from this computer. The audit log and consent records are kept. Type <b>DELETE</b> to confirm.</p>
        <input className={inputCls} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} aria-label="Type DELETE to confirm" />
        <ErrorNote error={wipe.error} />
      </Modal>
    </>
  );
}
