import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { setDisplayTimezone } from "@/lib/utils";

export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const cfg = await api.config();
      setDisplayTimezone(cfg.timezone);
      return cfg;
    },
    staleTime: Infinity,
    retry: false,
  });
}
