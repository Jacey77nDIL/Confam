"use client";

import type { ReactNode } from "react";
import { Toaster } from "sonner";

import { PwaRegister } from "@/components/pwa-register";
import { AuthProvider } from "@/contexts/auth-context";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <PwaRegister />
      <Toaster
        position="top-center"
        closeButton
        duration={4500}
        toastOptions={{
          classNames: {
            toast:
              "rounded-xl border border-mist-line bg-white text-ink shadow-elev-2 font-sans",
            title: "font-semibold text-ink",
            description: "text-ink-muted text-sm",
            error: "border-red-200/80",
            success: "border-emerald-200/80",
          },
        }}
      />
      {children}
    </AuthProvider>
  );
}
