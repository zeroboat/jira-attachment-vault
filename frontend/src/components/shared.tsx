import * as React from "react";
import { Link } from "react-router";
import { CircleCheck, Clock, ExternalLink, LoaderCircle, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import type { Attachment, AttachmentState, JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useConfig } from "@/lib/config";
import { label, t } from "@/lib/i18n";

const STATES: AttachmentState[] = ["active", "deleted_by_vault", "missing_in_jira", "restored"];
export const STATE_LABEL = Object.fromEntries(STATES.map((s) => [s, label("state", s)])) as Record<AttachmentState, string>;

export function StateBadge({ state }: { state: AttachmentState }) {
  const variant = ({ active: "secondary", deleted_by_vault: "warning", missing_in_jira: "destructive", restored: "info" } as const)[state];
  return <Badge variant={variant}>{STATE_LABEL[state] ?? state}</Badge>;
}

export function BackupBadge({ a }: { a: Pick<Attachment, "sha256" | "backup_error"> }) {
  if (a.sha256)
    return (
      <Badge variant="success">
        <CircleCheck /> {t("backup.done")}
      </Badge>
    );
  if (a.backup_error)
    return (
      <Badge variant="destructive" title={a.backup_error}>
        <TriangleAlert /> {t("backup.error")}
      </Badge>
    );
  return (
    <Badge variant="secondary">
      <Clock /> {t("backup.pending")}
    </Badge>
  );
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const variant = (
    { pending_approval: "warning", approved: "info", running: "info", done: "success", failed: "destructive", cancelled: "secondary" } as const
  )[status];
  return (
    <Badge variant={variant}>
      {(status === "running" || status === "approved") && <LoaderCircle className="animate-spin" />}
      {label("jobStatus", status)}
    </Badge>
  );
}

export function IssueLink({ issueKey, className }: { issueKey: string; className?: string }) {
  const { data } = useConfig();
  if (!data?.jira_base_url) return <span className={className}>{issueKey}</span>;
  return (
    <a
      href={`${data.jira_base_url}/browse/${issueKey}`}
      target="_blank"
      rel="noreferrer"
      className={cn("text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-[13px] font-medium hover:underline", className)}
      onClick={(e) => e.stopPropagation()}
    >
      {issueKey}
      <ExternalLink className="size-3 opacity-50" />
    </a>
  );
}

export function FileLink({ a }: { a: Pick<Attachment, "id" | "filename" | "mime_type"> }) {
  return (
    <Link to={`/attachments/${a.id}`} className="block max-w-[340px] truncate font-semibold hover:underline" title={a.filename}>
      {a.filename}
    </Link>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 pt-2">
      <div>
        <h1 className="text-[28px] leading-9 font-[650] tracking-[-0.02em]">{title}</h1>
        {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="bg-primary-soft text-primary-ink mb-1 flex size-10 items-center justify-center rounded-full">
        <Icon className="size-5" />
      </div>
      <p className="font-medium">{title}</p>
      {children && <p className="text-muted-foreground max-w-sm text-sm">{children}</p>}
    </div>
  );
}

export function ConfirmButton({
  title,
  description,
  confirmLabel,
  destructive,
  onConfirm,
  children,
  ...buttonProps
}: React.ComponentProps<typeof Button> & {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button {...buttonProps}>{children}</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div>{description}</div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className={destructive ? "bg-destructive hover:bg-destructive/90 text-white" : undefined}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
