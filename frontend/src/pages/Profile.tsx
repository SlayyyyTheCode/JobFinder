import { useRef, useState, DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, Check, Pencil, Trash2, Plus, FileText, ShieldCheck } from "lucide-react";
import { api, fileUrl, Fact } from "../api";
import { Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, Spinner, cx, inputCls, fmtDateTime } from "../ui";

type Resume = { id: number; filename: string; format: string; is_master: boolean; parse_status: string; parse_error: string; created_at: string };
type ProfileData = { groups: Record<string, Fact[]>; total: number; verified: number; low_confidence: number };

const LABELS: Record<string, string> = {
  contact: "Contact", summary: "Summary", employment: "Employment", project: "Projects", education: "Education",
  certification: "Certifications", skill: "Skills", language: "Languages", award: "Awards", publication: "Publications",
};

function Uploader() {
  const qc = useQueryClient();
  const ref = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const up = useMutation({
    mutationFn: (f: File) => api.upload("/resumes", f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) up.mutate(f);
  };
  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        className={cx("flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition",
          drag ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white")}>
        <Upload className="size-6 text-slate-400" aria-hidden />
        <p className="text-sm text-slate-600">Drop your resume here, or</p>
        <Button variant="primary" loading={up.isPending} onClick={() => ref.current?.click()}>Choose file</Button>
        <p className="text-xs text-slate-400">PDF, DOCX or DOC · max 10 MB · the original is stored unchanged</p>
        <input ref={ref} type="file" hidden accept=".pdf,.docx,.doc,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword"
          onChange={(e) => e.target.files?.[0] && up.mutate(e.target.files[0])} />
      </div>
      <div className="mt-2"><ErrorNote error={up.error} /></div>
    </div>
  );
}

function FactRow({ f, children }: { f: Fact; children?: React.ReactNode }) {
  const qc = useQueryClient();
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(f.text);
  const [data, setData] = useState<Record<string, any>>(f.data);
  const inv = () => qc.invalidateQueries({ queryKey: ["profile"] });
  const verify = useMutation({ mutationFn: (v: boolean) => api.post(`/candidate-profile/facts/${f.id}/verify`, { verified: v }), onSuccess: inv });
  const save = useMutation({
    mutationFn: () => api.patch(`/candidate-profile/facts/${f.id}`, f.type === "employment" ? { data } : { text }),
    onSuccess: () => { setEdit(false); inv(); },
  });
  const del = useMutation({ mutationFn: () => api.del(`/candidate-profile/facts/${f.id}`), onSuccess: inv });
  const low = f.confidence < 0.75 && !f.verified;
  return (
    <li className={cx("rounded-lg border px-3 py-2", low ? "border-amber-300 bg-amber-50/50" : "border-slate-200 bg-white")}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          {edit ? (
            f.type === "employment" ? (
              <div className="grid grid-cols-2 gap-2">
                {["title", "employer", "location", "start", "end"].map((k) => (
                  <Field key={k} label={k[0].toUpperCase() + k.slice(1)} hint={k === "start" || k === "end" ? "YYYY-MM or Present" : undefined}>
                    <input className={inputCls} value={data[k] ?? ""} onChange={(e) => setData({ ...data, [k]: e.target.value })} />
                  </Field>
                ))}
              </div>
            ) : (
              <textarea className={inputCls} rows={2} value={text} onChange={(e) => setText(e.target.value)} />
            )
          ) : (
            <p className={cx("text-sm", f.type === "employment" && "font-medium")}>{f.text}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {f.verified ? <Badge tone="green"><ShieldCheck className="size-3" /> verified</Badge> : <Badge tone={low ? "amber" : "slate"}>unverified</Badge>}
            {low && <Badge tone="amber" title="Could not be matched exactly to your resume text — check it">low confidence {Math.round(f.confidence * 100)}%</Badge>}
            {f.type === "skill" && f.data.level && f.data.level !== "unspecified" && <Badge>{f.data.level}</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          {edit ? (
            <>
              <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
              <Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant={f.verified ? "ghost" : "secondary"} onClick={() => verify.mutate(!f.verified)} aria-label={f.verified ? "Unverify" : "Verify"}>
                <Check className="size-3.5" /> {f.verified ? "Unverify" : "Verify"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEdit(true)} aria-label="Edit"><Pencil className="size-3.5" /></Button>
              <Button size="sm" variant="ghost" onClick={() => confirm("Remove this fact from your profile?") && del.mutate()} aria-label="Delete"><Trash2 className="size-3.5" /></Button>
            </>
          )}
        </div>
      </div>
      {children}
    </li>
  );
}

function AddFact({ parents }: { parents: Fact[] }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("skill");
  const [text, setText] = useState("");
  const [parent, setParent] = useState<number | "">("");
  const [data, setData] = useState<Record<string, string>>({});
  const add = useMutation({
    mutationFn: () => api.post("/candidate-profile/facts", { type, text, data, parent_id: parent || null }),
    onSuccess: () => { setOpen(false); setText(""); setData({}); qc.invalidateQueries({ queryKey: ["profile"] }); },
  });
  return (
    <>
      <Button onClick={() => setOpen(true)}><Plus className="size-4" /> Add fact</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Add a fact to your profile"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>Add</Button></>}>
        <p className="text-sm text-slate-500">Facts you add are treated as verified. Only add things that are true — tailored resumes are built only from these.</p>
        <Field label="Type">
          <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
            {["skill", "achievement", "employment", "project", "education", "certification", "language", "award", "summary"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
        {type === "employment" ? (
          <div className="grid grid-cols-2 gap-2">
            {["title", "employer", "location", "start", "end"].map((k) => (
              <Field key={k} label={k} hint={k === "start" || k === "end" ? "YYYY-MM" : undefined}>
                <input className={inputCls} value={data[k] ?? ""} onChange={(e) => setData({ ...data, [k]: e.target.value })} />
              </Field>
            ))}
          </div>
        ) : (
          <Field label="Text"><textarea className={inputCls} rows={3} value={text} onChange={(e) => setText(e.target.value)} /></Field>
        )}
        {type === "achievement" && (
          <Field label="Belongs to" hint="role or project">
            <select className={inputCls} value={parent} onChange={(e) => setParent(e.target.value ? Number(e.target.value) : "")}>
              <option value="">—</option>
              {parents.map((p) => <option key={p.id} value={p.id}>{p.text}</option>)}
            </select>
          </Field>
        )}
        <ErrorNote error={add.error} />
      </Modal>
    </>
  );
}

export default function Profile() {
  const qc = useQueryClient();
  const resumes = useQuery({
    queryKey: ["resumes"], queryFn: () => api.get<Resume[]>("/resumes"),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => r.parse_status === "pending" || r.parse_status === "parsing") ? 2000 : false),
  });
  const parsing = (resumes.data ?? []).some((r) => r.parse_status === "pending" || r.parse_status === "parsing");
  const prof = useQuery({ queryKey: ["profile", parsing], queryFn: () => api.get<ProfileData>("/candidate-profile") });
  const bulk = useMutation({ mutationFn: () => api.post<{ verified: number }>("/candidate-profile/verify-high-confidence"), onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }) });
  const reparse = useMutation({ mutationFn: (id: number) => api.post(`/resumes/${id}/parse`), onSuccess: () => qc.invalidateQueries({ queryKey: ["resumes"] }) });

  const g = prof.data?.groups ?? {};
  const achievements = (pid: number) => (g.achievement ?? []).filter((a) => a.parent_id === pid);
  const parents = [...(g.employment ?? []), ...(g.project ?? [])];
  const orphans = (g.achievement ?? []).filter((a) => !parents.some((p) => p.id === a.parent_id));

  return (
    <>
      <PageHeader title="Candidate profile" subtitle="Your fact ledger — the only source JobPilot uses to write resumes. Verify each fact."
        actions={<>
          <AddFact parents={parents} />
          <Button variant="primary" loading={bulk.isPending} onClick={() => bulk.mutate()} title="Verifies facts that exactly match your resume text">Verify high-confidence facts</Button>
        </>} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-1">
          <Uploader />
          <Card title="Uploaded resumes">
            {resumes.data?.length ? (
              <ul className="space-y-2">
                {resumes.data.map((r) => (
                  <li key={r.id} className="flex items-start gap-2 text-sm">
                    <FileText className="mt-0.5 size-4 text-slate-400" aria-hidden />
                    <div className="min-w-0 flex-1">
                      <a className="block truncate font-medium hover:underline" href={fileUrl(`/resumes/${r.id}/file`)} target="_blank" rel="noreferrer">{r.filename}</a>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        {r.is_master && <Badge tone="violet">master</Badge>}
                        {r.parse_status === "parsed" ? <Badge tone="green">parsed</Badge> : r.parse_status === "failed" ? <Badge tone="red">failed</Badge> : <Spinner label="parsing…" />}
                        {fmtDateTime(r.created_at)}
                      </div>
                      {r.parse_error && <p className="mt-1 text-xs text-red-600">{r.parse_error}</p>}
                      {r.parse_status === "failed" && <Button size="sm" className="mt-1" onClick={() => reparse.mutate(r.id)}>Retry</Button>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-slate-500">No resume yet.</p>}
          </Card>
          {prof.data && (
            <Card title="Verification">
              <p className="text-sm"><b>{prof.data.verified}</b> of {prof.data.total} facts verified.</p>
              {prof.data.low_confidence > 0 && <p className="mt-1 text-sm text-amber-700">{prof.data.low_confidence} low-confidence facts need a careful look.</p>}
              <p className="mt-2 text-xs text-slate-500">Only verified facts are used for tailoring.</p>
            </Card>
          )}
        </div>
        <div className="space-y-4 lg:col-span-2">
          {prof.isLoading ? <Spinner /> : !prof.data?.total ? (
            <Empty title="No profile yet">Upload a resume to extract your experience, skills and education.</Empty>
          ) : (
            Object.entries(LABELS).map(([type, label]) => {
              const items = g[type] ?? [];
              if (!items.length) return null;
              return (
                <Card key={type} title={`${label} (${items.length})`}>
                  {type === "skill" || type === "language" ? (
                    <ul className="grid gap-2 sm:grid-cols-2">{items.map((f) => <FactRow key={f.id} f={f} />)}</ul>
                  ) : (
                    <ul className="space-y-2">
                      {items.map((f) => (
                        <FactRow key={f.id} f={f}>
                          {(type === "employment" || type === "project") && achievements(f.id).length > 0 && (
                            <ul className="mt-2 space-y-1.5 border-l-2 border-slate-100 pl-3">
                              {achievements(f.id).map((a) => <FactRow key={a.id} f={a} />)}
                            </ul>
                          )}
                        </FactRow>
                      ))}
                    </ul>
                  )}
                </Card>
              );
            })
          )}
          {orphans.length > 0 && <Card title="Other achievements"><ul className="space-y-2">{orphans.map((f) => <FactRow key={f.id} f={f} />)}</ul></Card>}
        </div>
      </div>
    </>
  );
}
