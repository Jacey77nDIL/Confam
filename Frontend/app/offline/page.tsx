import Link from "next/link";

export default function OfflinePage() {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 bg-mist px-6 text-center">
      <div className="rounded-2xl border border-mist-line bg-white px-8 py-10 shadow-card">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">Offline</p>
        <h1 className="mt-2 text-xl font-semibold tracking-tight text-ink">You&apos;re offline</h1>
        <p className="mt-3 max-w-xs text-sm leading-relaxed text-ink-muted">
          Reconnect to load prices and messages. Cached screens may still open briefly.
        </p>
        <Link
          href="/chat"
          className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-brand py-3 text-sm font-semibold text-white shadow-elev-1 transition hover:bg-brand-dark"
        >
          Try again
        </Link>
      </div>
    </div>
  );
}
