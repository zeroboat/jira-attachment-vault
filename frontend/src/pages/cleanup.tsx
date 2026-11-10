import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Eraser, Info, Search, ShieldCheck } from "lucide-react";

import { BackupBadge, ConfirmButton, EmptyState, FileLink, IssueLink, PageHeader } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError, type Policy } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { t } from "@/lib/i18n";
import { formatBytes, formatDate, formatNumber } from "@/lib/utils";

interface Form {
  older_than_days: string;
  min_size_mb: string;
  projects: string;
  mime_prefix: string;
  filename_contains: string;
  only_done: boolean;
  skip_embedded: boolean;
}

const PRESETS: { label: string; form: Partial<Form> }[] = [
  { label: t("cleanup.preset.big"), form: { older_than_days: "365", min_size_mb: "100", mime_prefix: "" } },
  { label: t("cleanup.preset.video"), form: { older_than_days: "180", min_size_mb: "", mime_prefix: "video/" } },
  { label: t("cleanup.preset.all"), form: { older_than_days: "730", min_size_mb: "", mime_prefix: "" } },
];

function toPolicy(f: Form): Policy {
  return {
    older_than_days: f.older_than_days ? Number(f.older_than_days) : null,
    min_size_mb: f.min_size_mb ? Number(f.min_size_mb) : null,
    projects: f.projects.split(",").map((s) => s.trim()).filter(Boolean),
    only_done: f.only_done,
    mime_prefix: f.mime_prefix.trim() || null,
    filename_contains: f.filename_contains.trim() || null,
    skip_embedded: f.skip_embedded,
  };
}

export function CleanupPage() {
  const navigate = useNavigate();
  const { data: cfg } = useConfig();
  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [form, setForm] = useState<Form>({
    older_than_days: "365",
    min_size_mb: "100",
    projects: "",
    mime_prefix: "",
    filename_contains: "",
    only_done: true,
    skip_embedded: true,
  });
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  const preview = useMutation({ mutationFn: (p: Policy) => api.cleanupPreview(p) });
  const create = useMutation({
    mutationFn: (p: Policy) => api.cleanupCreate(p),
    onSuccess: (job) => {
      toast.success(t("cleanup.created"), { description: t("cleanup.approveToRun") });
      navigate(`/jobs/${job.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : t("common.requestFailed")),
  });
  const result = preview.data;

  return (
    <>
      <PageHeader title={t("cleanup.title")} description={t("cleanup.desc")} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("cleanup.rules")}</CardTitle>
            <CardDescription className="flex flex-wrap gap-1.5 pt-1">
              {PRESETS.map((p) => (
                <Button key={p.label} variant="secondary" size="sm" className="h-7 text-xs" onClick={() => set(p.form)}>
                  {p.label}
                </Button>
              ))}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-5"
              onSubmit={(e) => {
                e.preventDefault();
                preview.mutate(toPolicy(form));
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("cleanup.age")} hint={t("cleanup.ageHint")}>
                  <Input type="number" min={0} value={form.older_than_days} onChange={(e) => set({ older_than_days: e.target.value })} placeholder="365" />
                </Field>
                <Field label={t("cleanup.minSize")} hint={t("cleanup.minSizeHint")}>
                  <Input type="number" min={0} value={form.min_size_mb} onChange={(e) => set({ min_size_mb: e.target.value })} placeholder="100" />
                </Field>
                <Field label={t("cleanup.projects")} hint={projects?.length ? t("cleanup.projectsEg", { list: projects.slice(0, 3).join(", ") }) : t("cleanup.projectsHint")}>
                  <Input value={form.projects} onChange={(e) => set({ projects: e.target.value })} placeholder={t("cleanup.all")} />
                </Field>
                <Field label={t("cleanup.mime")} hint="video/, image/, application/zip …">
                  <Input value={form.mime_prefix} onChange={(e) => set({ mime_prefix: e.target.value })} placeholder={t("cleanup.all")} />
                </Field>
                <Field label={t("cleanup.nameContains")} className="sm:col-span-2">
                  <Input value={form.filename_contains} onChange={(e) => set({ filename_contains: e.target.value })} placeholder={t("cleanup.nameEg")} />
                </Field>
              </div>
              <div className="grid gap-3">
                <CheckRow
                  id="only_done"
                  checked={form.only_done}
                  onChange={(v) => set({ only_done: v })}
                  label={t("cleanup.onlyDone")}
                  hint={t("cleanup.onlyDoneHint")}
                />
                <CheckRow
                  id="skip_embedded"
                  checked={form.skip_embedded}
                  onChange={(v) => set({ skip_embedded: v })}
                  label={t("cleanup.skipEmbedded")}
                  hint={t("cleanup.skipEmbeddedHint")}
                />
              </div>
              <div className="flex justify-end">
                <Button type="submit" variant="outline" disabled={preview.isPending}>
                  <Search /> {t("cleanup.preview")}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card className="bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="text-success-ink size-4" /> {t("cleanup.safety")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="text-muted-foreground grid gap-3 text-sm">
              {[
                [t("cleanup.safe1"), t("cleanup.safe1d")],
                [t("cleanup.safe2"), t("cleanup.safe2d")],
                [t("cleanup.safe3"), t("cleanup.safe3d")],
                [t("cleanup.safe4"), t("cleanup.safe4d")],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="bg-primary-soft text-primary-ink flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-[650]">
                    {i + 1}
                  </span>
                  <span>
                    <span className="text-foreground font-medium">{t}</span>
                    <br />
                    {d}
                  </span>
                </li>
              ))}
            </ol>
            {cfg?.dry_run && (
              <div className="bg-warning-soft text-warning-ink mt-5 flex gap-2 rounded-sm p-3 text-xs">
                <Info className="mt-0.5 size-3.5 shrink-0" />
                {t("cleanup.dryRun")}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {result && (
        <Card className="mt-6 gap-0 pb-3 [&>[data-slot=table-container]]:px-3">
          <CardHeader className="pb-5">
            <CardTitle className="text-lg">
              {t("cleanup.targets", { n: formatNumber(result.count) })} · <span className="tabular">{formatBytes(result.bytes)}</span>
            </CardTitle>
            <CardDescription>
              {result.not_backed_up > 0
                ? t("cleanup.notBacked", { n: formatNumber(result.not_backed_up) })
                : t("cleanup.allBacked")}
              {result.count > result.items.length && t("cleanup.topN", { n: result.items.length })}
            </CardDescription>
            {result.count > 0 && (
              <div className="col-start-2 row-span-2 row-start-1 self-center">
                <ConfirmButton
                  variant="destructive"
                  title={t("cleanup.confirmQ", { n: formatNumber(result.count) })}
                  description={
t("cleanup.confirmDesc", { size: formatBytes(result.bytes) })
                  }
                  confirmLabel={t("cleanup.confirm")}
                  destructive
                  onConfirm={() => create.mutate(toPolicy(form))}
                  disabled={create.isPending}
                >
                  <Eraser /> {t("cleanup.createBtn")}
                </ConfirmButton>
              </div>
            )}
          </CardHeader>
          {result.items.length > 0 ? (
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
                {result.items.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <FileLink a={a} />
                    </TableCell>
                    <TableCell>
                      <IssueLink issueKey={a.issue_key} />
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{a.issue_status ?? "-"}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground tabular">{formatDate(a.created_at, false)}</TableCell>
                    <TableCell className="tabular text-right font-medium">{formatBytes(a.size)}</TableCell>
                    <TableCell>
                      <BackupBadge a={a} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={Search} title={t("cleanup.noMatch")} />
          )}
        </Card>
      )}
    </>
  );
}

function Field({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={`grid gap-1.5 ${className ?? ""}`}>
      <Label>{label}</Label>
      {children}
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

function CheckRow({ id, checked, onChange, label, hint }: { id: string; checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <div className="flex items-start gap-3">
      <Checkbox id={id} checked={checked} onCheckedChange={(v) => onChange(v === true)} className="mt-0.5" />
      <Label htmlFor={id} className="grid cursor-pointer gap-1 font-normal">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground text-xs">{hint}</span>
      </Label>
    </div>
  );
}
