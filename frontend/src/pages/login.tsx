import { useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { lang, LANGS, setLang, t, type Lang } from "@/lib/i18n";

export function LoginPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.login(username, password);
      await qc.invalidateQueries();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("login.failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-background flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <div className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-md">
            <Archive className="size-4" />
          </div>
          <span className="text-lg font-semibold">{t("app.fullName")}</span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl leading-7">{t("login.title")}</CardTitle>
            <CardDescription>{t("login.desc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="username">{t("login.username")}</Label>
                <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="password">{t("login.password")}</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  autoFocus
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading || !password}>
                {loading && <LoaderCircle className="animate-spin" />}
                {t("login.title")}
              </Button>
            </form>
          </CardContent>
        </Card>
        <div className="text-muted-foreground mt-4 flex justify-center gap-3 text-xs">
          {(Object.keys(LANGS) as Lang[]).map((l) => (
            <button key={l} type="button" onClick={() => l !== lang && setLang(l)} className={l === lang ? "text-foreground font-semibold" : "hover:underline"}>
              {LANGS[l]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
