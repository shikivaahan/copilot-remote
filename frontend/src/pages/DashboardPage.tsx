import { useRequireAuth } from "@/hooks/useRequireAuth";

export default function DashboardPage() {
  const user = useRequireAuth();
  if (!user) {
    return (
      <div className="p-4 text-neutral-400" role="status">
        Loading…
      </div>
    );
  }

  return (
    <section
      className="rounded-lg border border-neutral-800 bg-neutral-900 p-6"
      data-testid="dashboard-placeholder"
    >
      <h1 className="text-base font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-2 text-sm text-neutral-400">
        Welcome, <span className="text-neutral-200">@{user.username}</span>.
      </p>
      <p className="mt-6 text-sm text-neutral-500">
        Session list, create-session form, and live status indicators land in
        Phase 7.
      </p>
    </section>
  );
}
