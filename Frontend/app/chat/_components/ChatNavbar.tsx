"use client";

import { LogoLink } from "@/components/confam/Logo";

type Props = {
  onConnectCard: () => void;
  onSignOut: () => void;
};

export function ChatNavbar({ onConnectCard, onSignOut }: Props) {
  return (
    <header className="sticky top-0 z-20 border-b border-mist-line/90 bg-white/90 px-3 py-2.5 backdrop-blur-xl sm:px-5 md:px-6 lg:rounded-t-2xl">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
        <LogoLink size="md" className="min-w-0 py-1" />
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onConnectCard}
            className="rounded-full border border-mist-line bg-mist-paper px-3 py-2 text-xs font-semibold text-ink shadow-sm transition hover:border-brand/20 hover:bg-white sm:px-4 sm:text-[13px]"
          >
            Cards
          </button>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded-full px-3 py-2 text-xs font-semibold text-ink-muted transition hover:bg-mist sm:text-[13px]"
          >
            <span className="sm:hidden">Exit</span>
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
      <p className="mx-auto mt-0.5 max-w-5xl truncate px-0.5 text-[11px] font-medium tracking-wide text-ink-muted sm:text-xs">
        Assistant · markets & transfers
      </p>
    </header>
  );
}
