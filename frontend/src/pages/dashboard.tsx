import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowUpRight, Clock, RefreshCw, TriangleAlert } from "lucide-react";

import { BackupBadge, FileLink, IssueLink, PageHeader } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";
import { cn, formatBytes, formatDate, formatNumber, timeAgo } from "@/lib/utils";

/** "110 GB" → split number and unit so the unit renders smaller */
function Figure({ bytes, className }: { bytes: number; className?: string }) {
  const [num, unit] = formatBytes(bytes).split(" ");
  return (
    <span className={cn("tabular text-[28px] leading-8 font-[650] tracking-[-0.02em]", className)}>
      {num}
      <span className="ml-1 text-sm font-semibold tracking-normal">{unit}</span>
    </span>
  );
}

function StatTile({ label, bytes, sub, feature }: { label: string; bytes: number; sub: React.ReactNode; feature?: boolean }) {
  return (
    <div
      className={cn(
        "grid gap-0.5 rounded-lg border px-[18px] py-4",
        feature ? "bg-primary border-primary text-primary-foreground" : "bg-card",
      )}
    >
      <span className={cn("text-xs font-[550]", feature ? "opacity-85" : "text-muted-foreground")}>{label}</span>
      <Figure bytes={bytes} />
      <span className={cn("text-xs", feature ? "opacity-85" : "text-muted-foreground")}>{sub}</span>
    </div>
  );
}

/** Hero element: a bar split into 2–3 parts. Fixed color order primary → mint → rest; numbers live in the legend. */
function CapacityGauge({
  parts,
}: {
  parts: { label: string; bytes: number; tone: "primary" | "mint" | "rest"; href?: string }[];
}) {
  const total = parts.reduce((s, p) => s + p.bytes, 0) || 1;
  const toneCls = { primary: "bg-primary", mint: "bg-mint", rest: "bg-gauge-rest" };
  return (
    <div className="grid gap-3">
      <div
        className="flex h-3 gap-[2px] overflow-hidden rounded-full"
        role="img"
        aria-label={parts.map((p) => `${p.label} ${formatBytes(p.bytes)}`).join(", ")}
      >
        {parts
          .filter((p) => p.bytes > 0)
          .map((p) => (
            <div key={p.label} className={cn("h-full min-w-1", toneCls[p.tone])} style={{ flexGrow: p.bytes / total }} />
          ))}
      </div>
      <div className="text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
        {parts.map((p) => {
          const body = (
            <>
              <i className={cn("size-2.5 rounded-[3px]", toneCls[p.tone])} />
              {p.label} <b className="text-foreground tabular font-[650]">{formatBytes(p.bytes)}</b>
            </>
          );
          return p.href ? (
            <Link key={p.label} to={p.href} className="inline-flex items-center gap-1.5 hover:underline">
              {body}
            </Link>
          ) : (
            <span key={p.label} className="inline-flex items-center gap-1.5">
              {body}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 30_000 });
  const sync = useMutation({
    mutationFn: (full: boolean) => api.sync(full),
    onSuccess: (_job, full) => {
      toast.success(full ? t("dash.fullStarted") : t("dash.syncStarted"), {
        description: t("dash.seeJobs"),
      });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("dash.retry")),
  });

  if (isLoading || !data) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-16 w-72" />
        <div className="grid gap-2 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-40 rounded-lg" />
      </div>
    );
  }

  const s = data.sync;
  const original = data.active.bytes + data.freed.bytes;
  const pct = data.active.count ? (data.backed.count / data.active.count) * 100 : 0;
  const maxProject = Math.max(1, ...data.by_project.map((p) => p.bytes));

  return (
    <>
      <PageHeader
        title={t("dash.title")}
        description={s.last_sync ? t("dash.lastSync", { ago: timeAgo(s.last_sync) }) : t("dash.neverSynced")}
        actions={
          <>
            <Button variant="outline" onClick={() => sync.mutate(true)} disabled={sync.isPending}>
              {t("dash.fullSync")}
            </Button>
            <Button onClick={() => sync.mutate(false)} disabled={sync.isPending}>
              <RefreshCw className={sync.isPending ? "animate-spin" : ""} /> {t("dash.syncNow")}
            </Button>
          </>
        }
      />

      {s.last_error && (
        <div className="bg-destructive-soft text-destructive-ink mb-3 flex gap-3 rounded-md p-4 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0">
            <div className="font-semibold">{t("dash.syncFailed")}</div>
            <div className="mt-1 font-mono text-xs break-all opacity-80">{s.last_error}</div>
          </div>
        </div>
      )}
      {data.pending_jobs > 0 && (
        <Link
          to="/jobs"
          className="bg-warning-soft text-warning-ink mb-3 flex items-center gap-3 rounded-md px-4 py-3 text-sm transition-opacity hover:opacity-90"
        >
          <Clock className="size-4" />
          <span className="flex-1 font-medium">{t("dash.pendingJobs", { n: data.pending_jobs })}</span>
          <ArrowUpRight className="size-4" />
        </Link>
      )}

      <div className="grid gap-2 sm:grid-cols-3">
        <StatTile feature label={t("dash.inJira")} bytes={data.active.bytes} sub={t("common.files", { n: formatNumber(data.active.count) })} />
        <StatTile label={t("dash.freed")} bytes={data.freed.bytes} sub={t("dash.freedSub", { n: formatNumber(data.freed.count) })} />
        <StatTile label={t("dash.stored")} bytes={data.stored_bytes} sub={t("dash.storedSub")} />
      </div>

      <Card className="mt-2 gap-5">
        <CardHeader>
          <CardTitle>{t("dash.capacity")}</CardTitle>
          <CardDescription>
            {t("dash.backedPct", { n: formatNumber(data.active.count), pct: pct.toFixed(1) })}
            {data.errors.count > 0 && (
              <Link to="/attachments?backup=error" className="text-destructive-ink ml-1.5 font-medium hover:underline">
                {t("dash.backupErrors", { n: data.errors.count })}
              </Link>
            )}
          </CardDescription>
          <CardAction>
            <Figure bytes={original} className="text-lg leading-[26px]" />
          </CardAction>
        </CardHeader>
        <CardContent>
          <CapacityGauge
            parts={[
              { label: t("dash.gauge.backed"), bytes: data.backed.bytes, tone: "primary", href: "/attachments?backup=yes&state=active" },
              { label: t("dash.gauge.freed"), bytes: data.freed.bytes, tone: "mint", href: "/attachments?state=deleted_by_vault" },
              { label: t("dash.gauge.pending"), bytes: data.pending.bytes, tone: "rest", href: "/attachments?backup=no&state=active" },
            ]}
          />
        </CardContent>
      </Card>

      <div className="mt-2 grid gap-2 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>{t("dash.byProject")}</CardTitle>
            <CardDescription>{t("dash.byProjectDesc")}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3.5">
            {data.by_project.map((p) => (
              <Link
                key={p.project}
                to={`/attachments?project=${p.project}`}
                className="group grid grid-cols-[56px_1fr_auto] items-center gap-3 rounded-sm"
              >
                <span className="text-sm font-semibold group-hover:underline">{p.project}</span>
                <span className="bg-muted h-2 overflow-hidden rounded-full">
                  <span className="bg-primary block h-full rounded-full" style={{ width: `${(p.bytes / maxProject) * 100}%` }} />
                </span>
                <span className="tabular w-32 text-right text-[13px]">
                  <span className="font-semibold">{formatBytes(p.bytes)}</span>
                  <span className="text-muted-foreground"> · {formatNumber(p.count)}</span>
                </span>
              </Link>
            ))}
            {data.by_project.length === 0 && (
              <p className="text-muted-foreground text-sm">{t("dash.noData")}</p>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("dash.sync")}</CardTitle>
            <CardDescription>{t("dash.syncDesc")}</CardDescription>
          </CardHeader>
          <CardContent className="grid text-sm">
            <Row label={t("dash.row.lastSync")} value={s.last_sync ? timeAgo(s.last_sync) : t("common.none")} hint={formatDate(s.last_sync)} />
            {s.sync_result && (
              <Row
                label={t("dash.row.issues")}
                value={formatNumber(s.sync_result.issues)}
                hint={t("dash.row.issuesHint", { n: s.sync_result.new ?? 0 }) + (s.sync_result.missing ? t("dash.row.missingHint", { n: s.sync_result.missing }) : "")}
              />
            )}
            {s.backup_result && (
              <Row
                label={t("dash.row.lastBackup")}
                value={formatNumber(s.backup_result.ok)}
                hint={formatBytes(s.backup_result.bytes) + (s.backup_result.failed ? t("dash.row.failedHint", { n: s.backup_result.failed }) : "")}
              />
            )}
            <Row label={t("dash.row.lastFull")} value={s.last_full_sync ? timeAgo(s.last_full_sync) : t("common.none")} hint={formatDate(s.last_full_sync)} />
            {data.missing.count > 0 && (
              <Link to="/attachments?state=missing_in_jira" className="text-primary-ink pt-3 text-[13px] font-medium hover:underline">
                {t("dash.viewMissing", { n: data.missing.count })}
              </Link>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-2 gap-4">
        <CardHeader>
          <CardTitle>{t("dash.largest")}</CardTitle>
          <CardDescription>{t("dash.largestDesc")}</CardDescription>
          <CardAction>
            <Button variant="outline" size="sm" asChild>
              <Link to="/cleanup">{t("dash.setRules")}</Link>
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("col.file")}</TableHead>
                <TableHead>{t("col.issue")}</TableHead>
                <TableHead>{t("col.issueStatus")}</TableHead>
                <TableHead>{t("col.uploaded")}</TableHead>
                <TableHead className="text-right">{t("col.size")}</TableHead>
                <TableHead>{t("col.backup")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.largest.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <FileLink a={a} />
                  </TableCell>
                  <TableCell>
                    <IssueLink issueKey={a.issue_key} />
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{a.issue_status ?? "-"}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground tabular">{formatDate(a.created_at, false)}</TableCell>
                  <TableCell className="tabular text-right font-semibold">{formatBytes(a.size)}</TableCell>
                  <TableCell>
                    <BackupBadge a={a} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}

function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-2.5 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">
        <span className="font-semibold">{value}</span>
        {hint && <span className="text-muted-foreground block text-xs">{hint}</span>}
      </span>
    </div>
  );
}
