import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Button, Card, ErrorNote, PageHeader, Segmented, Spinner, TagInput, inputCls } from "../ui";

type Rule = "hard" | "soft" | "info";
type Crit = { rule_type: Rule; value: any; description: string };
type Prefs = { criteria: Record<string, Crit>; weights: Record<string, number> };

const LIST_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "titles", label: "Target job titles", placeholder: "AI Solution Architect, AI Engineer…" },
  { key: "job_functions", label: "Job functions", placeholder: "AI/ML, data, product…" },
  { key: "industries", label: "Industries", placeholder: "Technology, finance, consulting…" },
  { key: "seniority", label: "Seniority", placeholder: "senior, lead…" },
  { key: "locations", label: "Locations", placeholder: "Singapore, Remote…" },
  { key: "work_arrangement", label: "Work arrangement", placeholder: "onsite, hybrid, remote" },
  { key: "employment_type", label: "Employment type", placeholder: "Permanent, Contract…" },
  { key: "required_skills", label: "Skills the role should use", placeholder: "Python, LLMs…" },
  { key: "preferred_companies", label: "Preferred employers", placeholder: "Company names" },
  { key: "excluded_companies", label: "Excluded employers", placeholder: "Never apply to…" },
  { key: "excluded_keywords", label: "Excluded keywords", placeholder: "internship, sales quota…" },
];
const RULES = [
  { value: "hard" as Rule, label: "Hard" },
  { value: "soft" as Rule, label: "Soft" },
  { value: "info" as Rule, label: "Info" },
];
const WEIGHT_LABELS: Record<string, string> = {
  skills: "Required skills & experience", role: "Role & responsibility fit", seniority: "Seniority",
  industry: "Industry / domain", location: "Location & work arrangement", salary: "Salary",
};

export default function Preferences() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["prefs"], queryFn: () => api.get<Prefs>("/preferences") });
  const [c, setC] = useState<Record<string, Crit>>({});
  const [w, setW] = useState<Record<string, number>>({});
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data) { setC(data.criteria); setW(data.weights); } }, [data]);
  const save = useMutation({
    mutationFn: () => api.put("/preferences", { criteria: c, weights: w }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["prefs"] }); setSaved(true); setTimeout(() => setSaved(false), 2500); },
  });
  if (!data || !Object.keys(c).length) return <Spinner />;
  const set = (k: string, patch: Partial<Crit>) => setC({ ...c, [k]: { ...c[k], ...patch } });
  const sal = c.salary_min?.value ?? { amount: "", currency: "SGD", period: "month" };
  const total = Object.values(w).reduce((a, b) => a + Number(b), 0);

  return (
    <>
      <PageHeader title="Job preferences"
        subtitle={<><b>Hard</b> = job is excluded if not met · <b>Soft</b> = affects ranking only · <b>Info</b> = shown, not scored</>}
        actions={<>{saved && <span className="self-center text-sm text-emerald-600">Saved</span>}<Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save preferences</Button></>} />
      <ErrorNote error={save.error} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {LIST_FIELDS.map(({ key, label, placeholder }) => (
            <div key={key} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium">{label}</div>
                  <div className="text-xs text-slate-500">{c[key]?.description}</div>
                </div>
                <Segmented label={`${label} rule type`} value={c[key]?.rule_type ?? "soft"} options={RULES} onChange={(v) => set(key, { rule_type: v })} />
              </div>
              <TagInput value={c[key]?.value ?? []} onChange={(v) => set(key, { value: v })} placeholder={placeholder} />
            </div>
          ))}
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">Minimum salary</div>
              <Segmented label="Salary rule type" value={c.salary_min.rule_type} options={RULES} onChange={(v) => set("salary_min", { rule_type: v })} />
            </div>
            <div className="flex flex-wrap gap-2">
              <input aria-label="Amount" type="number" className={inputCls + " max-w-40"} value={sal.amount ?? ""} placeholder="Amount"
                onChange={(e) => set("salary_min", { value: { ...sal, amount: e.target.value ? Number(e.target.value) : null } })} />
              <input aria-label="Currency" className={inputCls + " max-w-24"} value={sal.currency ?? ""} onChange={(e) => set("salary_min", { value: { ...sal, currency: e.target.value.toUpperCase() } })} />
              <select aria-label="Period" className={inputCls + " max-w-32"} value={sal.period ?? "month"} onChange={(e) => set("salary_min", { value: { ...sal, period: e.target.value } })}>
                <option value="month">per month</option><option value="year">per year</option><option value="hour">per hour</option>
              </select>
            </div>
            <p className="mt-2 text-xs text-slate-500">Jobs without a stated salary are never excluded on salary.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["max_posting_age_days", "min_years_gap"] as const).map((k) => (
              <div key={k} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-sm font-medium">{k === "max_posting_age_days" ? "Max posting age (days)" : "Experience gap allowed (years)"}</div>
                  <Segmented label="rule type" value={c[k].rule_type} options={RULES} onChange={(v) => set(k, { rule_type: v })} />
                </div>
                <input type="number" className={inputCls} value={c[k].value ?? ""} onChange={(e) => set(k, { value: e.target.value ? Number(e.target.value) : null })} />
              </div>
            ))}
          </div>
        </div>
        <div>
          <Card title="Scoring weights">
            <p className="mb-3 text-xs text-slate-500">Hard requirements are applied first. These weights rank the remaining jobs. Normalised to 100%.</p>
            <div className="space-y-3">
              {Object.keys(WEIGHT_LABELS).map((k) => (
                <label key={k} className="block">
                  <div className="flex justify-between text-sm"><span>{WEIGHT_LABELS[k]}</span><span className="tabular-nums text-slate-500">{total ? Math.round((Number(w[k]) * 100) / total) : 0}%</span></div>
                  <input type="range" min={0} max={50} value={w[k] ?? 0} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} className="w-full accent-brand-600" />
                </label>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
