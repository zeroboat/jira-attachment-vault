import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useNavigate } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "./index.css";
import { AppLayout } from "@/components/layout";
import { Toaster } from "@/components/ui/misc";
import { useConfig } from "@/lib/config";
import { AttachmentDetailPage } from "@/pages/attachment-detail";
import { AttachmentsPage } from "@/pages/attachments";
import { AuditPage } from "@/pages/audit";
import { CleanupPage } from "@/pages/cleanup";
import { DashboardPage } from "@/pages/dashboard";
import { JobDetailPage, JobsPage } from "@/pages/jobs";
import { LoginPage } from "@/pages/login";
import { SettingsPage } from "@/pages/settings";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: (n, err: any) => err?.status !== 401 && n < 2, refetchOnWindowFocus: false } },
});

/** Auth guard. Sends the user to the login page when the session expires. */
function RequireAuth() {
  const navigate = useNavigate();
  const { isLoading, isError } = useConfig();
  useEffect(() => {
    const onUnauthorized = () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    };
    window.addEventListener("vault:unauthorized", onUnauthorized);
    return () => window.removeEventListener("vault:unauthorized", onUnauthorized);
  }, [navigate]);
  if (isLoading) return null;
  if (isError) return <Navigate to="/login" replace />;
  return <Outlet />;
}

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "attachments", element: <AttachmentsPage /> },
          { path: "attachments/:id", element: <AttachmentDetailPage /> },
          { path: "cleanup", element: <CleanupPage /> },
          { path: "jobs", element: <JobsPage /> },
          { path: "jobs/:id", element: <JobDetailPage /> },
          { path: "audit", element: <AuditPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster richColors closeButton />
    </QueryClientProvider>
  </StrictMode>,
);
