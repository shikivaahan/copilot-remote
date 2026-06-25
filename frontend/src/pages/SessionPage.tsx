import { useParams } from "react-router-dom";
import { useRequireAuth } from "@/hooks/useRequireAuth";

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
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
      data-testid="session-placeholder"
    >
      <h1 className="text-base font-semibold tracking-tight">Session</h1>
      <p className="mt-2 break-all text-sm text-neutral-400">
        Session id: <span className="text-neutral-200">{id}</span>
      </p>
      <p className="mt-6 text-sm text-neutral-500">
        Terminal, mobile keyboard, and live status panel arrive in Phase 7.
      </p>
    </section>
  );
}
