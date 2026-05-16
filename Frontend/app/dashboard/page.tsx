"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function DashboardRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/chat");
  }, [router]);
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-mist px-6 text-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-mist-line border-t-brand" aria-hidden />
      <p className="text-sm font-medium text-ink-muted">Opening assistant…</p>
    </div>
  );
}
