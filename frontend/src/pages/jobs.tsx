import { Link, useNavigate, useParams } from "react-router";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, ChevronLeft, ChevronRight, CircleCheck, ListChecks, MessageSquare, Play, TriangleAlert } from "lucide-react";

import { ConfirmButton, EmptyState, FileLink, IssueLink, JobStatusBadge, PageHeader, StateBadge } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError, can, type Job, type JobLogLine, type JobProgress } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { label, reasonLabel, t, type Key } from "@/lib/i18n";
import { cn, formatBytes, formatDate, formatNumber } from "@/lib/utils";

export function JobsPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 5000 });
  return (
    <>
      <PageHeader title={t("jobs.title")} description={t("jobs.desc")} />
      <Card className="gap-0 overflow-hidden p-3">
        {isLoading ? (
          <Skeleton className="m-4 h-40" />
        ) : data && data.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>{t("jobs.kind")}</TableHead>
                <TableHead>{t("jobs.content")}</TableHead>
                <TableHead className="text-right">{t("jobs.targets")}</TableHead>
                <TableHead>{t("col.state")}</TableHead>
                <TableHead>{t("jobs.reqApp")}</TableHead>
                <TableHead>{t("jobs.created")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((j) => (
                <TableRow key={j.id} className="cursor-pointer" onClick={() => navigate(`/jobs/${j.id}`)}>
                  <TableCell className="text-muted-foreground tabular">{j.id}</TableCell>
                  <TableCell className="font-medium">{label("jobKind", j.kind)}</TableCell>
                  <TableCell className="max-w-[320px] truncate">{j.title}</TableCell>
                  <TableCell className="tabular text-right">{j.attachment_count ? formatNumber(j.attachment_count) : ""}</TableCell>
                  <TableCell>
                    <JobStatusBadge status={j.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {j.created_by ?? "-"} / {j.approved_by ?? "-"}
                  </TableCell>
                  <TableCell className="text-muted-foreground tabular">{formatDate(j.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState icon={ListChecks} title={t("jobs.empty")}>
            {t("jobs.emptyHint")}
          </EmptyState>
        )}
      </Card>
    </>
  );
}

export function JobDetailPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const { data: cfg } = useConfig();
  const { data, isLoading } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.job(id),
    refetchInterval: (q) => (["approved", "running"].includes(q.state.data?.job.status ?? "") ? 2000 : false),
  });
  const onDone = (msg: string) => () => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["job", id] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const onErr = (e: Error) => toast.error(e instanceof ApiError ? e.message : t("common.requestFailed"));
  const approve = useMutation({ mutationFn: () => api.approve(id), onSuccess: onDone(t("jobs.approved")), onError: onErr });
  const cancel = useMutation({ mutationFn: () => api.cancel(id), onSuccess: onDone(t("jobs.cancelled")), onError: onErr });

  if (isLoading || !data) return <Skeleton className="h-96" />;
  const { job, total_bytes } = data;
  const isCleanup = job.kind === "cleanup";

  return (
    <>
      <Button variant="ghost" size="sm" className="text-muted-foreground mb-3 -ml-2" asChild>
        <Link to="/jobs">
          <ChevronLeft /> {t("jobs.list")}
        </Link>
      </Button>
      <PageHeader
        title={t("jobs.heading", { id: job.id, kind: label("jobKind", job.kind) })}
        description={job.title}
        actions={
          <>
            {(job.status === "pending_approval" || job.status === "approved") && (can(cfg?.role, "approver") || job.created_by === cfg?.user) && (
              <Button variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                <Ban /> {t("common.cancel")}
              </Button>
            )}
            {job.status === "pending_approval" && can(cfg?.role, "approver") && (
              <ConfirmButton
                variant={isCleanup ? "destructive" : "default"}
                title={isCleanup ? t("jobs.approveCleanupQ") : t("jobs.approveRestoreQ")}
                description={
                  isCleanup
                    ? cfg?.dry_run
                      ? t("jobs.dryRunDesc")
                      : t("jobs.cleanupDesc", {
                          summary: `${t("jobs.attachments", { n: formatNumber(job.attachment_count) })} · ${formatBytes(total_bytes)}`,
                        })
                    : t("jobs.restoreDesc")
                }
                confirmLabel={t("jobs.approveRun")}
                destructive={isCleanup && !cfg?.dry_run}
                onConfirm={() => approve.mutate()}
                disabled={approve.isPending}
              >
                <Play /> {t("jobs.approveRun")}
              </ConfirmButton>
            )}
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="gap-3 py-5">
          <CardHeader className="px-5">
            <CardDescription>{t("jobs.status")}</CardDescription>
          </CardHeader>
          <CardContent className="px-5">
            <JobStatusBadge status={job.status} />
            {data.progress && <Progress p={data.progress} />}
            <div className="text-muted-foreground mt-3 grid gap-1 text-xs">
              <span>{t("jobs.requested", { who: job.created_by ?? "-", date: formatDate(job.created_at) })}</span>
              {job.approved_by && <span>{t("jobs.approvedBy", { who: job.approved_by })}</span>}
              {job.finished_at && <span>{t("jobs.finished", { date: formatDate(job.finished_at) })}</span>}
            </div>
          </CardContent>
        </Card>
        {job.attachment_count > 0 && (
          <Card className="gap-3 py-5">
            <CardHeader className="px-5">
              <CardDescription>{t("jobs.targets")}</CardDescription>
              <CardTitle className="tabular text-2xl">{formatBytes(total_bytes)}</CardTitle>
            </CardHeader>
            <CardContent className="text-muted-foreground px-5 text-xs">{t("jobs.attachments", { n: formatNumber(job.attachment_count) })}</CardContent>
          </Card>
        )}
        {job.result && <ResultCard job={job} />}
      </div>

      <JobLogCard jobId={job.id} live={["approved", "running"].includes(job.status)} />

      {job.attachment_count > 0 && <JobItemsCard jobId={job.id} live={["approved", "running"].includes(job.status)} />}
    </>
  );
}

/** Every target attachment, a page at a time (largest first). */
function JobItemsCard({ jobId, live }: { jobId: number; live: boolean }) {
  const [page, setPage] = useState(1);
  const { data } = useQuery({
    queryKey: ["jobItems", jobId, page],
    queryFn: () => api.jobItems(jobId, page),
    placeholderData: (prev) => prev,
    refetchInterval: live ? 5000 : false, // states change as the job runs
  });
  if (!data) return null;
  const items = data.items;
  return (
    <Card className="mt-4 gap-0 pb-3 [&>[data-slot=table-container]]:px-3">
      <CardHeader className="pb-4">
        <CardTitle>{t("jobs.targetAtts")}</CardTitle>
        <CardDescription>{t("jobs.bySize", { n: formatNumber(data.total) })}</CardDescription>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("col.file")}</TableHead>
            <TableHead>{t("col.issue")}</TableHead>
            <TableHead>{t("col.uploaded")}</TableHead>
            <TableHead className="text-right">{t("col.size")}</TableHead>
            <TableHead>{t("jobs.currentState")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((a) => (
            <TableRow key={a.id}>
              <TableCell>
                <FileLink a={a} />
              </TableCell>
              <TableCell>
                <IssueLink issueKey={a.issue_key} />
              </TableCell>
              <TableCell className="text-muted-foreground tabular">{formatDate(a.created_at, false)}</TableCell>
              <TableCell className="tabular text-right font-medium">{formatBytes(a.size)}</TableCell>
              <TableCell>
                <StateBadge state={a.state} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data.pages > 1 && (
        <div className="flex items-center justify-end gap-2 px-5 pt-3 text-sm">
          <span className="text-muted-foreground mr-2 tabular">{t("att.page", { page: data.page, pages: data.pages })}</span>
          <Button variant="outline" size="sm" disabled={data.page <= 1} onClick={() => setPage(data.page - 1)}>
            <ChevronLeft /> {t("att.prev")}
          </Button>
          <Button variant="outline" size="sm" disabled={data.page >= data.pages} onClick={() => setPage(data.page + 1)}>
            {t("att.next")} <ChevronRight />
          </Button>
        </div>
      )}
    </Card>
  );
}

function Progress({ p }: { p: JobProgress }) {
  if (p.total === null) return <div className="text-muted-foreground mt-3 text-xs">{t("progress.sync", { done: formatNumber(p.done) })}</div>;
  const pct = p.total ? Math.min(100, Math.floor((p.done / p.total) * 100)) : 100;
  return (
    <div className="mt-3 grid gap-1.5">
      <div className="flex justify-between text-xs">
        <span>{t(`progress.${p.phase}` as Key)}</span>
        <span className="tabular text-muted-foreground">
          {formatNumber(p.done)} / {formatNumber(p.total)} · {pct}%
        </span>
      </div>
      <div className="bg-muted h-2 overflow-hidden rounded-full" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="bg-primary h-full transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function logText(l: JobLogLine): string {
  const d: Record<string, any> = { ...(l.data ?? {}) };
  if (typeof d.size === "number") d.size = formatBytes(d.size);
  if (d.reason) d.reason = reasonLabel(d.reason);
  d.file ??= d.id ?? "";
  d.dry = d.dry_run ? t("log.dry") : "";
  return t(`log.${l.event}` as Key, d);
}

const LOG_LIMIT = 1000; // server default for /jobs/{id}/log

/** Step-by-step log written by the worker (latest lines); polls while the job runs. */
function JobLogCard({ jobId, live }: { jobId: number; live: boolean }) {
  const [problems, setProblems] = useState(false);
  const { data } = useQuery({
    queryKey: ["jobLog", jobId],
    queryFn: () => api.jobLog(jobId),
    refetchInterval: live ? 2000 : false,
  });
  const lines = (data ?? []).filter((l) => !problems || l.level !== "info");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (live && box.current) box.current.scrollTop = box.current.scrollHeight; // follow new lines while running
  }, [data, live]);
  return (
    <Card className="mt-4 gap-0 pb-3">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle>{t("log.title")}</CardTitle>
        <label className="text-muted-foreground flex items-center gap-2 text-xs">
          <input type="checkbox" checked={problems} onChange={(e) => setProblems(e.target.checked)} />
          {t("log.problems")}
        </label>
      </CardHeader>
      {(data?.length ?? 0) >= LOG_LIMIT && <CardDescription className="px-5 pb-2">{t("log.tail", { n: formatNumber(LOG_LIMIT) })}</CardDescription>}
      <CardContent ref={box} className="max-h-[480px] overflow-auto px-5 font-mono text-xs">
        {lines.length === 0 ? (
          <span className="text-muted-foreground">{t("log.empty")}</span>
        ) : (
          lines.map((l) => (
            <div key={l.id} className={cn("flex gap-3 py-0.5", l.level === "error" && "text-destructive", l.level === "warn" && "text-warning-ink")}>
              <span className="text-muted-foreground shrink-0 tabular">{formatDate(l.at, "seconds")}</span>
              {l.issue_key && <span className="shrink-0">{l.issue_key}</span>}
              <span className="break-all">{logText(l)}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** Outcome of the silent notice comments posted to issues */
function CommentResult({ c }: { c?: { enabled: boolean; ok: number; failed: number; errors: Record<string, string> } }) {
  if (!c || !c.enabled || (c.ok === 0 && c.failed === 0)) return null;
  return (
    <div className="mt-1.5 border-t pt-1.5">
      <span className="flex items-center gap-1">
        <MessageSquare className="size-3" /> {t("jobs.comments", { n: c.ok })}
        {c.failed > 0 && <span className="text-destructive">{t("jobs.commentsFailed", { n: c.failed })}</span>}
      </span>
      {Object.entries(c.errors ?? {}).slice(0, 5).map(([key, why]) => (
        <span key={key} className="text-destructive block">
          {key}: {why}
        </span>
      ))}
    </div>
  );
}

function ResultCard({ job }: { job: Job }) {
  const r = job.result!;
  if (r.error) {
    return (
      <Card className="bg-destructive-soft border-transparent gap-3 py-5">
        <CardHeader className="px-5">
          <CardDescription className="text-destructive flex items-center gap-1.5">
            <TriangleAlert className="size-3.5" /> {t("jobs.error")}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-5 font-mono text-xs break-all">{r.error}</CardContent>
      </Card>
    );
  }
  if (job.kind === "cleanup") {
    return (
      <Card className="gap-3 py-5">
        <CardHeader className="px-5">
          <CardDescription className="flex items-center gap-1.5">
            <CircleCheck className="text-success-ink size-3.5" /> {t("jobs.result")}{r.dry_run ? t("jobs.dryRunTag") : ""}
          </CardDescription>
          <CardTitle className="tabular text-2xl">{t("jobs.freed", { size: formatBytes(r.freed_bytes) })}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground grid gap-1 px-5 text-xs">
          <span>{t("jobs.cleanupSummary", { d: r.deleted, s: r.skipped, f: r.failed })}</span>
          {Object.entries((r.reasons ?? {}) as Record<string, string[]>).map(([reason, ids]) => (
            <span key={reason}>
              {reasonLabel(reason)}: {ids.length}
            </span>
          ))}
          <CommentResult c={r.comments} />
        </CardContent>
      </Card>
    );
  }
  if (job.kind === "restore") {
    return (
      <Card className="gap-3 py-5">
        <CardHeader className="px-5">
          <CardDescription>{t("jobs.result")}</CardDescription>
          <CardTitle className="text-2xl">{t("jobs.restored", { n: r.restored })}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground grid gap-1 px-5 text-xs">
          <span>{t("jobs.failed", { n: r.failed })}</span>
          <CommentResult c={r.comments} />
        </CardContent>
      </Card>
    );
  }
  return (
    <Card className="gap-3 py-5">
      <CardHeader className="px-5">
        <CardDescription>{t("jobs.result")}</CardDescription>
        <CardTitle className="text-2xl">{t("jobs.issuesChecked", { n: formatNumber(r.sync?.issues) })}</CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground px-5 text-xs">
        {t("jobs.syncSummary", { n: r.sync?.new ?? 0, b: r.backup?.ok ?? 0 })}
      </CardContent>
    </Card>
  );
}
