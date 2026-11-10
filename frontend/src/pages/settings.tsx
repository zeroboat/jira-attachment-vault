import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CircleCheck, HardDrive, KeyRound, LoaderCircle, Plug, ShieldAlert, ShieldCheck, TriangleAlert } from "lucide-react";

import { ConfirmButton, PageHeader } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, ApiError, type Settings } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { t } from "@/lib/i18n";

/** Editable form state; numbers and lists are kept as strings while typing. */
interface Form {
  jira_base_url: string;
  jira_email: string;
  jira_api_token: string;
  jira_projects: string;
  jira_extra_jql: string;
  jira_user_timezone: string;
  jira_comment: boolean;
  jira_comment_lang: "en" | "ko";
  sync_interval_minutes: string;
  full_reconcile_hours: string;
}

const toForm = (s: Settings): Form => ({
  jira_base_url: s.jira_base_url,
  jira_email: s.jira_email,
  jira_api_token: "",
  jira_projects: s.jira_projects.join(", "),
  jira_extra_jql: s.jira_extra_jql,
  jira_user_timezone: s.jira_user_timezone,
  jira_comment: s.jira_comment,
  jira_comment_lang: s.jira_comment_lang,
  sync_interval_minutes: String(s.sync_interval_minutes),
  full_reconcile_hours: String(s.full_reconcile_hours),
});

const TIMEZONES: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
})();

const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : t("common.requestFailed"));

export function SettingsPage() {
  const qc = useQueryClient();
  const { data: cfg } = useConfig();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [form, setForm] = useState<Form | null>(null);
  useEffect(() => {
    if (data) setForm(toForm(data));
  }, [data]);

  const refresh = (s: Settings) => {
    qc.setQueryData(["settings"], s);
    qc.invalidateQueries({ queryKey: ["config"] });
  };

  const save = useMutation({
    mutationFn: (f: Form) =>
      api.saveSettings({
        jira_base_url: f.jira_base_url.trim(),
        jira_email: f.jira_email.trim(),
        jira_api_token: f.jira_api_token,
        jira_projects: f.jira_projects.split(",").map((p) => p.trim()).filter(Boolean),
        jira_extra_jql: f.jira_extra_jql.trim(),
        jira_user_timezone: f.jira_user_timezone.trim(),
        jira_comment: f.jira_comment,
        jira_comment_lang: f.jira_comment_lang,
        sync_interval_minutes: Number(f.sync_interval_minutes),
        full_reconcile_hours: Number(f.full_reconcile_hours),
      }),
    onSuccess: (s) => {
      refresh(s);
      toast.success(t("settings.saved"));
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const dryRun = useMutation({
    mutationFn: (on: boolean) => api.saveSettings({ dry_run: on }),
    onSuccess: (s) => {
      refresh(s);
      toast.success(s.dry_run ? t("settings.dryRunOnDone") : t("settings.dryRunOffDone"));
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const test = useMutation({
    mutationFn: (f: Form) =>
      api.testJira({ jira_base_url: f.jira_base_url.trim(), jira_email: f.jira_email.trim(), jira_api_token: f.jira_api_token }),
  });

  if (!data || !form) return <Skeleton className="h-96" />;
  const set = (patch: Partial<Form>) => {
    setForm({ ...form, ...patch });
    test.reset();
  };

  return (
    <>
      <PageHeader title={t("settings.title")} description={t("settings.desc")} />

      {!cfg?.jira_configured && (
        <div className="bg-primary-soft text-primary-ink mb-4 flex gap-3 rounded-md p-4 text-sm">
          <Plug className="mt-0.5 size-4 shrink-0" />
          <div>
            <div className="font-semibold">{t("settings.welcome")}</div>
            <div className="mt-0.5">{t("settings.welcomeHint")}</div>
          </div>
        </div>
      )}
      {data.secret_key_ephemeral && (
        <div className="bg-warning-soft text-warning-ink mb-4 flex gap-3 rounded-md p-4 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          {t("settings.ephemeralKey")}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <form
          className="grid gap-4 lg:col-span-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(form);
          }}
        >
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.jira")}</CardTitle>
              <CardDescription>{t("settings.jiraDesc")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label={t("settings.url")} className="sm:col-span-2">
                <Input value={form.jira_base_url} onChange={(e) => set({ jira_base_url: e.target.value })} placeholder="https://your-company.atlassian.net" required />
              </Field>
              <Field label={t("settings.email")}>
                <Input type="email" value={form.jira_email} onChange={(e) => set({ jira_email: e.target.value })} autoComplete="off" required />
              </Field>
              <Field label={t("settings.token")} hint={data.jira_api_token_set ? t("settings.tokenKeep") : t("settings.tokenHint")}>
                <Input
                  type="password"
                  value={form.jira_api_token}
                  onChange={(e) => set({ jira_api_token: e.target.value })}
                  placeholder={data.jira_api_token_set ? "••••••••" : ""}
                  autoComplete="new-password"
                  required={!data.jira_api_token_set}
                />
              </Field>
              <Field label={t("settings.projects")} hint={t("settings.projectsHint")}>
                <Input value={form.jira_projects} onChange={(e) => set({ jira_projects: e.target.value })} placeholder="OPS, DEV" />
              </Field>
              <Field label={t("settings.timezone")} hint={t("settings.timezoneHint")}>
                <Input list="tz-list" value={form.jira_user_timezone} onChange={(e) => set({ jira_user_timezone: e.target.value })} />
                <datalist id="tz-list">
                  {TIMEZONES.map((z) => (
                    <option key={z} value={z} />
                  ))}
                </datalist>
              </Field>
              <Field label={t("settings.jql")} hint={t("settings.jqlHint")} className="sm:col-span-2">
                <Input value={form.jira_extra_jql} onChange={(e) => set({ jira_extra_jql: e.target.value })} placeholder="issuetype != Epic" />
              </Field>
              <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
                <Button type="button" variant="outline" onClick={() => test.mutate(form)} disabled={test.isPending || !form.jira_base_url}>
                  {test.isPending ? <LoaderCircle className="animate-spin" /> : <Plug />} {t("settings.test")}
                </Button>
                {test.data?.ok && (
                  <span className="text-success-ink flex items-center gap-1.5 text-sm">
                    <CircleCheck className="size-4" /> {t("settings.testOk", { account: test.data.account ?? "" })}
                  </span>
                )}
                {test.data && !test.data.ok && <span className="text-destructive text-sm">{test.data.error}</span>}
                {test.error && <span className="text-destructive text-sm">{errMsg(test.error)}</span>}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("settings.comments")}</CardTitle>
              <CardDescription>{t("settings.commentsDesc")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="flex items-start gap-3 sm:col-span-2">
                <Checkbox id="jira_comment" checked={form.jira_comment} onCheckedChange={(v) => set({ jira_comment: v === true })} className="mt-0.5" />
                <Label htmlFor="jira_comment" className="grid cursor-pointer gap-1 font-normal">
                  <span className="font-medium">{t("settings.commentOn")}</span>
                  <span className="text-muted-foreground text-xs">{t("settings.commentOnHint")}</span>
                </Label>
              </div>
              <Field label={t("settings.commentLang")}>
                <Select value={form.jira_comment_lang} onValueChange={(v) => set({ jira_comment_lang: v as "en" | "ko" })} disabled={!form.jira_comment}>
                  <SelectTrigger className="bg-background w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="ko">한국어</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("settings.sync")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label={t("settings.interval")} hint={t("settings.intervalHint")}>
                <Input type="number" min={1} max={1440} value={form.sync_interval_minutes} onChange={(e) => set({ sync_interval_minutes: e.target.value })} required />
              </Field>
              <Field label={t("settings.fullInterval")} hint={t("settings.fullIntervalHint")}>
                <Input type="number" min={1} max={720} value={form.full_reconcile_hours} onChange={(e) => set({ full_reconcile_hours: e.target.value })} required />
              </Field>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setForm(toForm(data))} disabled={save.isPending}>
              {t("settings.reset")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <LoaderCircle className="animate-spin" />} {t("settings.save")}
            </Button>
          </div>
        </form>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {data.dry_run ? <ShieldCheck className="text-success-ink size-4" /> : <ShieldAlert className="text-destructive size-4" />}
                {t("settings.dryRun")}
              </CardTitle>
              <CardDescription>{data.dry_run ? t("settings.dryRunOn") : t("settings.dryRunOff")}</CardDescription>
            </CardHeader>
            <CardContent>
              {data.dry_run ? (
                <ConfirmButton
                  variant="destructive"
                  className="w-full"
                  title={t("settings.dryRunOffQ")}
                  description={t("settings.dryRunOffDesc")}
                  confirmLabel={t("settings.dryRunOffConfirm")}
                  destructive
                  onConfirm={() => dryRun.mutate(false)}
                  disabled={dryRun.isPending}
                >
                  {t("settings.dryRunOffBtn")}
                </ConfirmButton>
              ) : (
                <Button variant="outline" className="w-full" onClick={() => dryRun.mutate(true)} disabled={dryRun.isPending}>
                  {t("settings.dryRunOnBtn")}
                </Button>
              )}
            </CardContent>
          </Card>

          <PasswordCard />

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <HardDrive className="size-4" /> {t("settings.storage")}
              </CardTitle>
              <CardDescription>{t("settings.storageDesc")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              <div>
                <Badge variant="secondary">{data.storage_backend}</Badge>
              </div>
              <div className="text-muted-foreground font-mono text-xs break-all">{data.storage_location}</div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success(t("settings.passwordChanged"));
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const mismatch = confirm !== "" && confirm !== next;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4" /> {t("settings.password")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            change.mutate();
          }}
        >
          <Field label={t("settings.currentPassword")}>
            <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
          </Field>
          <Field label={t("settings.newPassword")} hint={t("settings.passwordHint")}>
            <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={8} required />
          </Field>
          <Field label={t("settings.confirmPassword")}>
            <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required aria-invalid={mismatch} />
            {mismatch && <span className="text-destructive text-xs">{t("settings.mismatch")}</span>}
          </Field>
          <Button type="submit" variant="outline" disabled={change.isPending || mismatch || next.length < 8}>
            {t("settings.changePassword")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: React.ReactNode }) {
  return (
    <Label className={`grid content-start gap-1.5 ${className ?? ""}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="text-muted-foreground text-xs font-normal">{hint}</span>}
    </Label>
  );
}
