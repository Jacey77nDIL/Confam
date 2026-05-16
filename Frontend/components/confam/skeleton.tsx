export function SkeletonLine({ className = "" }: { className?: string }) {
  return (
    <div
      className={`relative overflow-hidden rounded-md bg-mist-line/80 ${className}`}
      aria-hidden
    >
      <div className="animate-shimmer absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/50 to-transparent" />
    </div>
  );
}

export function ChatLoadingSkeleton() {
  return (
    <div className="flex min-h-[100dvh] flex-col bg-mist">
      <header className="border-b border-mist-line/90 bg-white/90 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div className="flex items-center gap-3">
            <SkeletonLine className="h-10 w-10 rounded-xl" />
            <div className="space-y-2">
              <SkeletonLine className="h-3.5 w-24" />
              <SkeletonLine className="h-2.5 w-32" />
            </div>
          </div>
          <SkeletonLine className="h-9 w-28 rounded-full" />
        </div>
      </header>
      <div className="flex flex-1 flex-col gap-4 px-4 py-8">
        <div className="mx-auto w-full max-w-2xl space-y-4">
          <SkeletonLine className="ml-auto h-16 w-[72%] rounded-2xl rounded-br-md" />
          <SkeletonLine className="h-24 w-[88%] rounded-2xl rounded-bl-md" />
          <SkeletonLine className="ml-auto h-12 w-[55%] rounded-2xl rounded-br-md" />
        </div>
      </div>
      <div className="border-t border-mist-line/90 bg-white/95 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <SkeletonLine className="mx-auto h-14 max-w-2xl rounded-2xl" />
      </div>
    </div>
  );
}
