import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import { t } from "@/lib/i18n";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBytes(n: number | null | undefined): string {
  let v = Number(n ?? 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return i === 0 ? `${v} B` : `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

export function formatNumber(n: number | null | undefined): string {
  return new Intl.NumberFormat("en-US").format(n ?? 0);
}

let tz = "Asia/Seoul";
export function setDisplayTimezone(value: string) {
  tz = value || "Asia/Seoul";
}

export function formatDate(iso: string | null | undefined, withTime: boolean | "seconds" = true): string {
  if (!iso) return "-";
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}),
    ...(withTime === "seconds" ? { second: "2-digit" } : {}),
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const date = `${get("year")}-${get("month")}-${get("day")}`;
  if (!withTime) return date;
  return `${date} ${get("hour")}:${get("minute")}` + (withTime === "seconds" ? `:${get("second")}` : "");
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "-";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return t("time.justNow");
  if (diff < 3600) return t("time.min", { n: Math.floor(diff / 60) });
  if (diff < 86400) return t("time.hour", { n: Math.floor(diff / 3600) });
  return t("time.day", { n: Math.floor(diff / 86400) });
}
