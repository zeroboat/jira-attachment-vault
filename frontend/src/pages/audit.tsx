import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";

import { EmptyState, PageHeader } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { label, t } from "@/lib/i18n";
import { formatDate } from "@/lib/utils";

const TONE: Record<string, "warning" | "destructive" | "success" | "info" | "secondary"> = {
  deleted: "destructive",
  dry_run_delete: "warning",
  restored: "info",
  backed_up: "success",
  missing_in_jira: "warning",
};

export function AuditPage() {
  const { data, isLoading } = useQuery({ queryKey: ["audit"], queryFn: api.audit });
  return (
    <>
      <PageHeader title={t("audit.title")} description={t("audit.desc")} />
      <Card className="gap-0 overflow-hidden p-3">
        {isLoading ? (
          <Skeleton className="m-4 h-60" />
        ) : data && data.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("col.time")}</TableHead>
                <TableHead>{t("col.who")}</TableHead>
                <TableHead>{t("col.what")}</TableHead>
                <TableHead>{t("col.issue")}</TableHead>
                <TableHead>{t("col.detail")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((l) => (
                <TableRow key={l.id}>
                  <TableCell className="text-muted-foreground tabular">{formatDate(l.at)}</TableCell>
                  <TableCell>{l.actor}</TableCell>
                  <TableCell>
                    <Badge variant={TONE[l.action] ?? "secondary"}>{label("action", l.action)}</Badge>
                  </TableCell>
                  <TableCell>
                    {l.attachment_id ? (
                      <Link to={`/attachments/${l.attachment_id}`} className="font-mono text-xs hover:underline">
                        {l.issue_key ?? l.attachment_id}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-[360px] truncate font-mono text-xs">
                    {l.detail ? JSON.stringify(l.detail) : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState icon={History} title={t("audit.empty")} />
        )}
      </Card>
    </>
  );
}
