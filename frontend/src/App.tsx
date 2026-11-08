import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, UserRound, SlidersHorizontal, Search, FileCheck2, Mail, Bot, PlugZap, Settings as SettingsIcon, Bell, LogOut,
} from "lucide-react";
import { api, Notification } from "./api";
import { Spinner, cx, fmtDateTime } from "./ui";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Profile from "./pages/Profile";
import Preferences from "./pages/Preferences";
import Discover from "./pages/Discover";
import Studio from "./pages/Studio";
import Applications, { ApplicationDetail } from "./pages/Applications";
import Inbox from "./pages/Inbox";
import Autopilot from "./pages/Autopilot";
import Connections from "./pages/Connections";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/profile", label: "Profile", icon: UserRound },
  { to: "/preferences", label: "Preferences", icon: SlidersHorizontal },
  { to: "/discover", label: "Discover jobs", icon: Search },
  { to: "/applications", label: "Applications", icon: FileCheck2 },
  { to: "/inbox", label: "Email matches", icon: Mail },
  { to: "/autopilot", label: "Autopilot", icon: Bot },
  { to: "/connections", label: "Connections", icon: PlugZap },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function Notifications() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<{ items: Notification[]; unread: number }>("/notifications"),
    refetchInterval: 10000,
  });
  const readAll = useMutation({ mutationFn: () => api.post("/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const open1 = async (n: Notification) => {
    if (!n.read_at) await api.post(`/notifications/${n.id}/read`);
    qc.invalidateQueries({ queryKey: ["notifications"] });
    setOpen(false);
    if (n.link) nav(n.link);
  };
  return (
    <div className="relative">
      <button aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`} onClick={() => setOpen(!open)}
        className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100">
        <Bell className="size-5" />
        {!!data?.unread && <span className="absolute right-1 top-1 rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-4 text-white">{data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-96 rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-brand-600 hover:underline" onClick={() => readAll.mutate()}>Mark all read</button>
          </div>
          <ul className="max-h-96 overflow-auto">
            {data?.items.length ? data.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => open1(n)} className={cx("block w-full px-4 py-3 text-left hover:bg-slate-50", !n.read_at && "bg-brand-50/50")}>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {n.important && <span className="size-2 rounded-full bg-red-500" aria-label="important" />}
                    {n.title}
                  </div>
                  {n.body && <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{n.body}</p>}
                  <p className="mt-1 text-[11px] text-slate-400">{fmtDateTime(n.created_at)}</p>
                </button>
              </li>
            )) : <li className="px-4 py-6 text-center text-sm text-slate-500">Nothing yet.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const qc = useQueryClient();
  const auth = useQuery({ queryKey: ["auth"], queryFn: () => api.get<{ hosted: boolean; authenticated: boolean }>("/auth/status"), retry: false });
  useEffect(() => {
    const h = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener("jp-unauthorized", h);
    return () => window.removeEventListener("jp-unauthorized", h);
  }, [qc]);
  if (auth.isLoading) return <div className="p-8"><Spinner /></div>;
  if (auth.data?.hosted && !auth.data.authenticated) return <Login onDone={() => qc.invalidateQueries()} />;
  return <Shell hosted={!!auth.data?.hosted} />;
}

function Shell({ hosted }: { hosted: boolean }) {
  const qc = useQueryClient();
  const logout = useMutation({ mutationFn: () => api.post("/auth/logout"), onSuccess: () => qc.invalidateQueries({ queryKey: ["auth"] }) });
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="grid size-8 place-items-center rounded-lg bg-brand-600 text-white font-bold">J</div>
          <span className="text-lg font-semibold tracking-tight">JobPilot</span>
        </div>
        <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900")}>
              <Icon className="size-4" aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <p className="px-5 py-4 text-[11px] leading-snug text-slate-400">Automate the workflow, not the truth.</p>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-2 md:justify-end">
          <span className="font-semibold md:hidden">JobPilot</span>
          <div className="flex items-center gap-1">
            <Notifications />
            {hosted && (
              <button onClick={() => logout.mutate()} className="flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm text-slate-600 hover:bg-slate-100" aria-label="Sign out">
                <LogOut className="size-4" aria-hidden /> <span className="hidden sm:inline">Sign out</span>
              </button>
            )}
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-3 py-2 md:hidden" aria-label="Main mobile">
          {NAV.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => cx("whitespace-nowrap rounded-md px-2.5 py-1 text-xs", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600")}>{label}</NavLink>
          ))}
        </nav>
        <main className="flex-1 overflow-auto px-6 py-8">
          <div className="mx-auto max-w-6xl">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/preferences" element={<Preferences />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/discover/:jobId" element={<Discover />} />
              <Route path="/studio/:id" element={<Studio />} />
              <Route path="/applications" element={<Applications />} />
              <Route path="/applications/:id" element={<ApplicationDetail />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/autopilot" element={<Autopilot />} />
              <Route path="/connections" element={<Connections />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
}
