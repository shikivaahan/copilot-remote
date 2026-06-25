import { Outlet } from "react-router-dom";
import clsx from "clsx";
import { useAuth } from "@/auth/useAuth";

export default function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen w-full bg-neutral-950 text-neutral-100 font-mono">
      <header className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
        <div
          className={clsx(
            "mx-auto flex max-w-screen-md items-center justify-between px-4 py-3",
            "sm:px-6",
          )}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-base font-semibold tracking-tight">
              Copilot Remote
            </span>
            {user && (
              <span className="text-xs text-neutral-500">
                @{user.username}
              </span>
            )}
          </div>
          {user && (
            <button
              type="button"
              onClick={() => {
                void logout();
              }}
              className={clsx(
                "rounded border border-neutral-700 px-3 py-1 text-xs",
                "text-neutral-200 hover:bg-neutral-800 active:bg-neutral-700",
                "transition-colors",
              )}
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <main
        className={clsx(
          "mx-auto w-full max-w-screen-md px-4 py-4",
          "sm:px-6 sm:py-6",
        )}
      >
        <Outlet />
      </main>
    </div>
  );
}
