import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, Copy, Download, RotateCcw } from "lucide-react";

import { BackupBadge, ConfirmButton, IssueLink, StateBadge } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { label, t } from "@/lib/i18n";
import { formatBytes, formatDate } from "@/lib/utils";

export function AttachmentDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["attachment", id], queryFn: () => api.attachment(id) });
  const restore = useMutation({
    mutationFn: () => api.restore(id),
    onSuccess: (job) => {
      toast.success(t("detail.restoreCreated"), { description: t("detail.approveToRun") });
      navigate(`/jobs/${job.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("common.requestFailed")),
  });

  if (isLoading || !data) return <Skeleton className="h-96" />;
  const a = data.attachment;

  return (
    <>
      <Button variant="ghost" size="sm" className="text-muted-foreground mb-3 -ml-2" onClick={() => navigate(-1)}>
        <ChevronLeft /> {t("common.back")}
      </Button>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{a.filename}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <StateBadge state={a.state} />
            <BackupBadge a={a} />
            <span className="text-muted-foreground">
              {formatBytes(a.size)} · {a.mime_type ?? t("detail.unknownType")}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          {a.sha256 && (
            <Button variant="outline" asChild>
              <a href={api.backupUrl(a.id)}>
                <Download /> {t("detail.download")}
              </a>
            </Button>
          )}
          {a.sha256 && a.state !== "active" && a.state !== "restored" && (
            <ConfirmButton
              title={t("detail.restoreQ")}
              description={
                <>
                  {t("detail.restoreDesc", { key: a.issue_key })}
                  <br />
                  <span className="text-xs">{t("detail.restoreNote")}</span>
                </>
              }
              confirmLabel={t("detail.restoreConfirm")}
              onConfirm={() => restore.mutate()}
              disabled={restore.isPending}
            >
              <RotateCcw /> {t("detail.restoreBtn")}
            </ConfirmButton>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("detail.info")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-3 text-sm">
              <dt className="text-muted-foreground">{t("col.issue")}</dt>
              <dd className="min-w-0">
                <IssueLink issueKey={a.issue_key} /> <span className="ml-1">{a.issue_summary}</span>
                {a.issue_status && (
                  <Badge variant="outline" className="ml-2">
                    {a.issue_status}
                  </Badge>
                )}
              </dd>
              <dt className="text-muted-foreground">{t("detail.project")}</dt>
              <dd>{a.project_key}</dd>
              <dt className="text-muted-foreground">{t("col.uploader")}</dt>
              <dd>{a.author_name ?? "-"}</dd>
              <dt className="text-muted-foreground">{t("col.uploaded")}</dt>
              <dd className="tabular">{formatDate(a.created_at)}</dd>
              <dt className="text-muted-foreground">{t("detail.attId")}</dt>
              <dd className="font-mono text-xs">{a.id}</dd>
              {a.deleted_at && (
                <>
                  <dt className="text-muted-foreground">{t("detail.cleanedAt")}</dt>
                  <dd className="tabular">{formatDate(a.deleted_at)}</dd>
                </>
              )}
              {a.restored_as_id && (
                <>
                  <dt className="text-muted-foreground">{t("detail.restored")}</dt>
                  <dd>{t("detail.restoredAs", { id: a.restored_as_id })}</dd>
                </>
              )}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("detail.backup")}</CardTitle>
            <CardDescription>{a.sha256 ? t("detail.savedAt", { date: formatDate(a.backed_up_at) }) : t("detail.attempts", { n: a.backup_attempts })}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            {a.sha256 ? (
              <div>
                <div className="text-muted-foreground mb-1 text-xs">SHA-256</div>
                <button
                  className="bg-muted hover:bg-muted/70 flex w-full items-center gap-2 rounded-md p-2 text-left font-mono text-[11px] break-all"
                  onClick={() => {
                    navigator.clipboard.writeText(a.sha256!);
                    toast(t("detail.copied"));
                  }}
                >
                  <span className="flex-1">{a.sha256}</span>
                  <Copy className="text-muted-foreground size-3.5 shrink-0" />
                </button>
              </div>
            ) : (
              <p className="text-muted-foreground">{t("detail.notBacked")}</p>
            )}
            {a.backup_error && <p className="text-destructive text-xs break-all">{a.backup_error}</p>}
            {data.duplicates.length > 0 && (
              <div>
                <div className="text-muted-foreground mb-1.5 text-xs">{t("detail.dupes", { n: data.duplicates.length })}</div>
                <ul className="grid gap-1">
                  {data.duplicates.map((d) => (
                    <li key={d.id} className="truncate text-xs">
                      <Link to={`/attachments/${d.id}`} className="hover:underline">
                        {d.issue_key} · {d.filename}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4 gap-0 pb-3 [&>[data-slot=table-container]]:px-3">
        <CardHeader className="pb-4">
          <CardTitle>{t("detail.log")}</CardTitle>
        </CardHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("col.time")}</TableHead>
              <TableHead>{t("col.who")}</TableHead>
              <TableHead>{t("col.what")}</TableHead>
              <TableHead>{t("col.detail")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.logs.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="tabular text-muted-foreground">{formatDate(l.at)}</TableCell>
                <TableCell>{l.actor}</TableCell>
                <TableCell>{label("action", l.action)}</TableCell>
                <TableCell className="text-muted-foreground font-mono text-xs">{l.detail ? JSON.stringify(l.detail) : ""}</TableCell>
              </TableRow>
            ))}
            {data.logs.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground py-8 text-center">
                  {t("detail.noLog")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}
