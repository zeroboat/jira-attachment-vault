import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { setLang, type Lang } from "@/lib/i18n";
import { setDisplayTimezone } from "@/lib/utils";

/** Save the app-wide language (DB), then switch this browser to it. */
export async function chooseLang(l: Lang) {
  await api.saveSettings({ jira_comment_lang: l });
  setLang(l);
}

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const cfg = await api.config();
      setDisplayTimezone(cfg.timezone);
      setLang(cfg.lang as Lang); // follow the language saved in Settings (reloads only if it differs)
      return cfg;
    },
    staleTime: Infinity,
    retry: false,
  });
}
