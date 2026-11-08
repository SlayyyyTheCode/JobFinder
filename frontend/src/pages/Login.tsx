import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api";
import { Button, ErrorNote, inputCls } from "../ui";

export default function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const login = useMutation({ mutationFn: () => api.post("/auth/login", { password: pw }), onSuccess: onDone });
  const submit = (e: FormEvent) => { e.preventDefault(); if (pw) login.mutate(); };
  return (
    <div className="grid min-h-full place-items-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid size-9 place-items-center rounded-lg bg-brand-600 font-bold text-white">J</div>
          <span className="text-xl font-semibold tracking-tight">JobPilot</span>
        </div>
        <label htmlFor="pw" className="text-sm font-medium text-slate-700">Password</label>
        <input id="pw" type="password" autoFocus autoComplete="current-password" className={inputCls + " mt-1"} value={pw}
          onChange={(e) => setPw(e.target.value)} />
        <div className="mt-3"><ErrorNote error={login.error} /></div>
        <Button type="submit" variant="primary" className="mt-4 w-full" loading={login.isPending} disabled={!pw}>Sign in</Button>
        <p className="mt-4 text-center text-xs text-slate-400">Private instance. Your resume and job data are only visible after sign-in.</p>
      </form>
    </div>
  );
}
