"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";

import { IconClose } from "@/components/confam/icons";
import type { ConnectedCardDTO } from "@/lib/chat-api";
import {
  emitConnectedCardChanged,
  finalizeSquadCardVerification,
  getConnectedCard,
  initiateSquadCardVerification,
  removeConnectedCard,
} from "@/lib/chat-api";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function ConnectCardModal({ open, onClose }: Props) {
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<ConnectedCardDTO | null | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCard(undefined);
    (async () => {
      try {
        try {
          const fin = await finalizeSquadCardVerification();
          if (fin.success) emitConnectedCardChanged();
        } catch {
          /* finalize is best-effort */
        }
        const c = await getConnectedCard();
        if (!cancelled) setCard(c);
      } catch {
        if (!cancelled) setCard(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const startCheckout = async () => {
    setBusy(true);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      const returnUrl = `${origin}/chat?card=connected`;
      const res = await initiateSquadCardVerification(returnUrl);
      toast.message("Secure checkout", {
        description: "Complete the short verification in the Squad window.",
      });
      window.location.href = res.checkout_url;
    } catch {
      toast.error("Could not start card verification. Try again.");
      setBusy(false);
    }
  };

  const onRemove = async () => {
    if (!window.confirm("Remove this card from Confam? You can add one again anytime.")) return;
    setBusy(true);
    try {
      await removeConnectedCard();
      setCard(null);
      emitConnectedCardChanged();
      toast.success("Card removed.");
    } catch {
      toast.error("Could not remove card. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-ink/45 backdrop-blur-[2px]"
            onClick={onClose}
          />
          <motion.div
            initial={{ y: 28, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 28, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 32 }}
            className="relative z-10 w-full max-w-md rounded-t-[1.5rem] border border-mist-line bg-white p-6 shadow-elev-2 sm:mx-4 sm:rounded-2xl md:p-8"
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                {card === undefined ? (
                  <>
                    <h2 className="text-lg font-semibold tracking-tight text-ink">Cards</h2>
                    <p className="mt-1.5 text-sm text-ink-muted">Loading…</p>
                  </>
                ) : card ? (
                  <>
                    <h2 className="text-lg font-semibold tracking-tight text-ink">Card on file</h2>
                    <p className="mt-1.5 text-sm font-medium text-ink">
                      {card.brand_label || `${card.card_type ?? "Card"}${card.last4 ? ` •••• ${card.last4}` : ""}`}
                    </p>
                    <p className="mt-2 text-xs leading-relaxed text-ink-muted">
                      Confam only stores a secure token with Squad — not your full card number. The ₦100 check was
                      refunded through Squad as soon as your card was verified; your bank may take a few hours or days
                      to show the credit.
                    </p>
                  </>
                ) : (
                  <>
                    <h2 className="text-lg font-semibold tracking-tight text-ink">Connect debit card</h2>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">
                      A one-time ₦100 check confirms your card (minimum charge required by Squad). We request a full
                      refund from Squad right after verification; your bank may take a few hours or days to post it.
                      Card details stay with Squad — Confam only stores a secure token.
                    </p>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl p-2 text-ink-muted transition hover:bg-mist hover:text-ink"
                aria-label="Close"
              >
                <IconClose />
              </button>
            </div>

            {card === undefined ? null : card ? (
              <div className="flex flex-col gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={onRemove}
                  className="w-full rounded-xl border border-red-200 bg-red-50/80 py-3.5 text-sm font-semibold text-red-800 transition hover:bg-red-50 active:scale-[99%] disabled:opacity-50"
                >
                  {busy ? "Working…" : "Remove card"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void startCheckout()}
                  className="w-full rounded-xl border border-mist-line bg-mist-paper py-3.5 text-sm font-semibold text-ink shadow-sm transition hover:border-brand/20 hover:bg-white active:scale-[99%] disabled:opacity-50"
                >
                  {busy ? "Starting…" : "Use a different card"}
                </button>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  disabled={busy}
                  className="w-full rounded-xl bg-brand py-3.5 text-sm font-semibold text-white shadow-elev-1 transition hover:bg-brand-dark active:scale-[99%] disabled:opacity-50"
                  onClick={() => void startCheckout()}
                >
                  {busy ? "Starting…" : "Continue to secure checkout"}
                </button>
                <p className="mt-4 text-center text-[11px] leading-relaxed text-ink-muted">
                  You will leave this screen briefly to authorize with your bank.
                </p>
              </>
            )}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
