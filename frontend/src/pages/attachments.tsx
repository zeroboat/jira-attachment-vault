import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Paperclip, Search, X } from "lucide-react";

import { BackupBadge, FileLink, IssueLink, PageHeader, StateBadge, STATE_LABEL, EmptyState } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatBytes, formatDate, formatNumber } from "@/lib/utils";

const ALL = "__all";

export function AttachmentsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const q = params.get("q") ?? "";
  const project = params.get("project") ?? "";
  const state = params.get("state") ?? "";
  const backup = params.get("backup") ?? "";
  const sort = params.get("sort") ?? "created_desc";
  const page = Number(params.get("page") ?? 1);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);

  const update = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v && v !== ALL) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next);
  };

  // Search once typing pauses
  useEffect(() => {
    if (search === q) return;
    const t = setTimeout(() => update({ q: search }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["attachments", { q, project, state, backup, sort, page }],
    queryFn: () => api.attachments({ q, project, state, backup, sort, page }),
    placeholderData: keepPreviousData,
  });
  const filtered = q || project || state || backup;

  return (
    <>
      <PageHeader title={t("att.title")} description={data ? t("common.files", { n: formatNumber(data.total) }) : " "} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("att.search")}
            className="bg-background pl-8"
          />
        </div>
        <FilterSelect
          value={project}
          onChange={(v) => update({ project: v })}
          placeholder={t("att.allProjects")}
          options={(projects ?? []).map((p) => [p, p])}
        />
        <FilterSelect
          value={state}
          onChange={(v) => update({ state: v })}
          placeholder={t("att.allStates")}
          options={Object.entries(STATE_LABEL)}
        />
        <FilterSelect
          value={backup}
          onChange={(v) => update({ backup: v })}
          placeholder={t("att.allBackups")}
          options={[
            ["yes", t("att.backup.yes")],
            ["no", t("att.backup.no")],
            ["error", t("att.backup.error")],
          ]}
        />
        <FilterSelect
          value={sort}
          onChange={(v) => update({ sort: v })}
          placeholder={t("att.sort")}
          allowAll={false}
          options={[
            ["created_desc", t("att.sort.created_desc")],
            ["created_asc", t("att.sort.created_asc")],
            ["size_desc", t("att.sort.size_desc")],
            ["size_asc", t("att.sort.size_asc")],
          ]}
        />
        {filtered && (
          <Button variant="ghost" size="sm" onClick={() => setParams(new URLSearchParams())}>
            <X /> {t("att.reset")}
          </Button>
        )}
      </div>

      <Card className="gap-0 overflow-hidden p-3">
        {isLoading ? (
          <div className="grid gap-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : data && data.items.length > 0 ? (
          <Table className={isFetching ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <TableHeader>
              <TableRow>
                <TableHead>{t("col.file")}</TableHead>
                <TableHead>{t("col.issue")}</TableHead>
                <TableHead>{t("col.uploader")}</TableHead>
                <TableHead>{t("col.uploaded")}</TableHead>
                <TableHead className="text-right">{t("col.size")}</TableHead>
                <TableHead>{t("col.state")}</TableHead>
                <TableHead>{t("col.backup")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((a) => (
                <TableRow key={a.id} className="cursor-pointer" onClick={() => navigate(`/attachments/${a.id}`)}>
                  <TableCell>
                    <FileLink a={a} />
                    <div className="text-muted-foreground max-w-[340px] truncate text-xs">{a.mime_type}</div>
                  </TableCell>
                  <TableCell>
                    <IssueLink issueKey={a.issue_key} />
                    <div className="text-muted-foreground max-w-[220px] truncate text-xs">{a.issue_summary}</div>
                  </TableCell>
                  <TableCell>{a.author_name ?? "-"}</TableCell>
                  <TableCell className="text-muted-foreground tabular">{formatDate(a.created_at)}</TableCell>
                  <TableCell className="tabular text-right font-medium">{formatBytes(a.size)}</TableCell>
                  <TableCell>
                    <StateBadge state={a.state} />
                  </TableCell>
                  <TableCell>
                    <BackupBadge a={a} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState icon={Paperclip} title={t("att.empty")}>
            {t("att.emptyHint")}
          </EmptyState>
        )}
      </Card>

      {data && data.pages > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2 text-sm">
          <span className="text-muted-foreground mr-2 tabular">
            {t("att.page", { page: data.page, pages: data.pages })}
          </span>
          <Button variant="outline" size="sm" disabled={data.page <= 1} onClick={() => update({ page: String(data.page - 1) })}>
            <ChevronLeft /> {t("att.prev")}
          </Button>
          <Button variant="outline" size="sm" disabled={data.page >= data.pages} onClick={() => update({ page: String(data.page + 1) })}>
            {t("att.next")} <ChevronRight />
          </Button>
        </div>
      )}
    </>
  );
}

function FilterSelect({
  value,
  onChange,
  placeholder,
  options,
  allowAll = true,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: [string, string][];
  allowAll?: boolean;
}) {
  return (
    <Select value={value || (allowAll ? ALL : undefined)} onValueChange={onChange}>
      <SelectTrigger className="bg-background min-w-36">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {allowAll && <SelectItem value={ALL}>{placeholder}</SelectItem>}
        {options.map(([v, label]) => (
          <SelectItem key={v} value={v}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
