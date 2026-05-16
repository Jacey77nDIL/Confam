"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import type { ConnectedCardDTO } from "@/lib/chat-api";
import {
  CONNECTED_CARD_CHANGED_EVENT,
  emitOpenConnectCardModal,
  executeSquadPayment,
  getConnectedCard,
} from "@/lib/chat-api";

type Meta = Record<string, unknown>;

type Props = {
  messageId: number;
  content: string | null;
  meta: Meta;
};

function parseNairaToKobo(raw: string): number | null {
  const t = raw.replace(/₦|NGN|naira|\s/gi, "").replace(/,/g, "").trim();
  if (!t || !/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const n = Number.parseFloat(t);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n * 100);
}

export function PaymentCard({ messageId, content, meta }: Props) {
  const preview = typeof meta.preview_file_url === "string" ? meta.preview_file_url : null;
  const bank = String(meta.bank_name ?? "—");
  const acct = String(meta.account_number ?? "—");
  const suggestedRaw = meta.suggested_amount != null ? String(meta.suggested_amount) : "";
  const aiName = meta.ai_account_name ? String(meta.ai_account_name) : null;
  const verified = meta.verified_account_name ? String(meta.verified_account_name) : null;
  const highlightBank = meta.name_verification_highlight === "bank_verify";
  const lookup = meta.account_lookup as Record<string, unknown> | undefined;
  const lookupResolved = lookup?.resolved === true;
  const lookupMsg = lookup?.message != null ? String(lookup.message) : null;

  const [card, setCard] = useState<ConnectedCardDTO | null | undefined>(undefined);
  const [amountInput, setAmountInput] = useState(suggestedRaw && suggestedRaw !== "?" ? suggestedRaw : "");
  const [authorizing, setAuthorizing] = useState(false);

  const refreshCard = useCallback(async () => {
    try {
      const c = await getConnectedCard();
      setCard(c);
    } catch {
      setCard(null);
    }
  }, []);

  useEffect(() => {
    void refreshCard();
  }, [refreshCard]);

  useEffect(() => {
    const onChanged = () => void refreshCard();
    window.addEventListener(CONNECTED_CARD_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(CONNECTED_CARD_CHANGED_EVENT, onChanged);
  }, [refreshCard]);

  const amountKobo = useMemo(() => parseNairaToKobo(amountInput), [amountInput]);

  const recipientName = verified || (meta.display_account_name ? String(meta.display_account_name) : aiName || "—");

  const onAuthorize = async () => {
    if (!amountKobo) {
      toast.error("Enter a valid amount in naira.");
      return;
    }
    if (!card?.brand_label && !card?.last4) {
      toast.error("Connect a card first from the header.");
      return;
    }
    setAuthorizing(true);
    try {
      const idem =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `cfm-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const res = await executeSquadPayment({
        amount_kobo: amountKobo,
        recipient_account_number: acct.replace(/\D/g, ""),
        recipient_bank_name: bank !== "—" ? bank : null,
        recipient_account_name: recipientName === "—" ? (aiName || "Recipient") : recipientName,
        idempotency_key: idem,
        assistant_message_id: messageId,
      });
      if (res.success) {
        toast.success(
          res.message ||
            (res.payout_deferred
              ? "Payment complete. Your card was charged; recipient payout will follow manual disbursement."
              : "Payment submitted."),
        );
        void refreshCard();
      } else {
        toast.error(res.message || "Payment could not be completed.");
      }
    } catch {
      toast.error("Network error. Try again.");
    } finally {
      setAuthorizing(false);
    }
  };

  return (
    <div className="space-y-3">
      {preview ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={preview}
          alt="Reference"
          className="max-h-40 w-full max-w-xs rounded-xl object-cover ring-1 ring-black/5 md:max-h-48"
        />
      ) : null}

      <div className="rounded-2xl border border-mist-line bg-white p-4 shadow-card">
        <div className="flex items-start justify-between gap-3 border-b border-mist-line/80 pb-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-muted">Transfer check</p>
            <p className="mt-1 whitespace-pre-wrap text-[15px] font-medium leading-snug text-ink">
              {content || (typeof meta.smart_caption === "string" ? meta.smart_caption : "")}
            </p>
          </div>
          <span className="shrink-0 rounded-full bg-mist px-2.5 py-1 text-[11px] font-semibold text-ink-muted">
            Review
          </span>
        </div>

        <dl className="mt-3 space-y-2.5 text-[13px]">
          <div className="flex justify-between gap-3">
            <dt className="text-ink-muted">Bank</dt>
            <dd className="text-right font-medium text-ink">{bank}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-muted">Account</dt>
            <dd className="text-right font-mono text-[13px] font-semibold tracking-wide text-ink">{acct}</dd>
          </div>
          <div className="flex flex-col gap-1.5 border-t border-mist-line pt-3">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Amount (₦)</dt>
            <dd>
              <input
                type="text"
                inputMode="decimal"
                value={amountInput}
                onChange={(e) => setAmountInput(e.target.value)}
                placeholder={suggestedRaw && suggestedRaw !== "?" ? suggestedRaw : "5000"}
                className="w-full rounded-xl border border-mist-line bg-mist-paper px-3 py-2 text-[15px] font-semibold text-ink outline-none ring-brand/15 focus:border-brand/40 focus:ring-2"
              />
            </dd>
          </div>
          {(aiName || verified) && (
            <div className="border-t border-mist-line pt-3">
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Account name</dt>
              <dd className="mt-1.5 space-y-1.5">
                {verified ? (
                  <p className="flex flex-wrap items-center gap-2">
                    <span
                      className={
                        highlightBank
                          ? "rounded-lg bg-emerald-50 px-2 py-1 text-[14px] font-semibold text-emerald-900 ring-1 ring-emerald-100"
                          : "text-[15px] font-semibold text-ink"
                      }
                    >
                      {verified}
                    </span>
                    {lookupResolved ? (
                      <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-800">
                        Verified
                      </span>
                    ) : null}
                  </p>
                ) : null}
                {aiName && highlightBank ? (
                  <p className="text-[12px] text-ink-muted">
                    From image · <span className="italic">{aiName}</span>
                  </p>
                ) : aiName && !verified ? (
                  <p className="text-[15px] font-medium text-ink">{aiName}</p>
                ) : null}
              </dd>
            </div>
          )}
        </dl>

        <div className="mt-4 rounded-xl border border-mist-line bg-mist-paper px-3 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">Charge</p>
          <p className="mt-1 text-sm font-medium text-ink">
            {card === undefined
              ? "Checking linked card…"
              : card?.brand_label || (card?.last4 ? `Card •••• ${card.last4}` : "No card linked")}
          </p>
        </div>

        {lookupMsg && !lookupResolved ? (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] font-medium text-amber-900 ring-1 ring-amber-100">
            Could not auto-verify the account name. Please double-check bank and digits before paying.
          </p>
        ) : null}

        <button
          type="button"
          disabled={authorizing || card === undefined}
          onClick={() => {
            if (card === undefined) return;
            if (!card) {
              emitOpenConnectCardModal();
              toast.message("Connect a card first", {
                description: "Use the Cards button in the header, or tap again here.",
              });
              return;
            }
            void onAuthorize();
          }}
          className="mt-4 w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white shadow-elev-1 transition hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-45"
        >
          {authorizing
            ? "Authorizing…"
            : card === undefined
              ? "Checking linked card…"
              : !card
                ? "Connect card to pay"
                : "Authorize payment"}
        </button>

        <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
          Money only moves when you tap authorize. Confam uses Squad to verify accounts and process card payments.
        </p>
      </div>
    </div>
  );
}
