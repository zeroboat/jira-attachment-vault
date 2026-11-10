import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Check, Eraser, HardDrive, History, Languages, LayoutDashboard, ListChecks, LogOut, Paperclip, Settings, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { lang, LANGS, setLang, t, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const STORAGE_LABEL: Record<string, string> = { local: t("storage.local"), seaweedfs: "SeaweedFS", s3: t("storage.s3") };

const NAV = [
  { to: "/", label: t("nav.dashboard"), icon: LayoutDashboard, end: true },
  { to: "/attachments", label: t("nav.attachments"), icon: Paperclip },
  { to: "/cleanup", label: t("nav.cleanup"), icon: Eraser },
  { to: "/jobs", label: t("nav.jobs"), icon: ListChecks, badge: true },
  { to: "/audit", label: t("nav.audit"), icon: History },
  { to: "/settings", label: t("nav.settings"), icon: Settings },
];

export function AppLayout() {
  const { data: cfg } = useConfig();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: jobs } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 10_000 });
  const pending = jobs?.filter((j) => j.status === "pending_approval").length ?? 0;
  const { pathname } = useLocation();

  const logout = async () => {
    await api.logout();
    qc.clear();
    navigate("/login");
  };

  // First run: nothing works until the Jira connection is set up.
  if (cfg && !cfg.jira_configured && pathname !== "/settings") return <Navigate to="/settings" replace />;

  return (
    <div className="bg-background flex min-h-svh">
      {/* Sidebar sits on the canvas; only the current page is raised as a surface. */}
      <aside className="sticky top-0 hidden h-svh w-[232px] shrink-0 flex-col px-3 py-4 md:flex">
        <div className="flex items-center gap-2.5 px-2 pt-1 pb-5">
          <div className="bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-sm">
            <Archive className="size-4" />
          </div>
          <span className="text-[15px] font-[650]">{t("app.name")}</span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5" aria-label={t("nav.main")}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex h-[38px] items-center gap-2.5 rounded-sm px-3 text-sm font-medium transition-colors",
                  "focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2",
                  isActive
                    ? "bg-card text-foreground ring-border font-[650] ring-1 ring-inset"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              <item.icon className="size-[18px]" />
              <span className="flex-1">{item.label}</span>
              {item.badge && pending > 0 && (
                <span
                  className="bg-warning-soft text-warning-ink h-5 min-w-5 rounded-full px-1.5 text-center text-[11px] leading-5 font-[650]"
                  aria-label={t("nav.pending", { n: pending })}
                >
                  {pending}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="text-muted-foreground flex items-center gap-1.5 px-3 text-xs">
          <HardDrive className="size-3.5" />
          {t("nav.storage", { name: STORAGE_LABEL[cfg?.storage_backend ?? ""] ?? cfg?.storage_backend ?? "" })}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-2 px-4 md:px-8">
          <div className="text-[15px] font-[650] md:hidden">{t("app.name")}</div>
          <div className="flex-1 md:hidden" />
          {cfg?.dry_run && (
            <Badge variant="warning" className="h-7 px-3 text-xs">
              <ShieldAlert /> {t("nav.dryRun")}
            </Badge>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="text-foreground gap-2 pl-1.5">
                <span className="bg-primary-soft text-primary-ink flex size-6 items-center justify-center rounded-full text-[11px] font-[650]">
                  {cfg?.user?.slice(0, 1).toUpperCase()}
                </span>
                {cfg?.user}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">{t("nav.admin")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-muted-foreground flex items-center gap-1.5 text-xs font-normal">
                <Languages className="size-3.5" /> {t("lang.label")}
              </DropdownMenuLabel>
              {(Object.keys(LANGS) as Lang[]).map((l) => (
                <DropdownMenuItem key={l} onSelect={() => l !== lang && setLang(l)}>
                  <Check className={l === lang ? "" : "invisible"} /> {LANGS[l]}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={logout}>
                <LogOut /> {t("nav.logout")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        {/* Mobile: top menu instead of the sidebar */}
        <nav className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden" aria-label={t("nav.main")}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex h-8 shrink-0 items-center rounded-full px-3 text-[13px] font-medium",
                  isActive ? "bg-card ring-border font-[650] ring-1" : "text-muted-foreground",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 pt-2 pb-10 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
