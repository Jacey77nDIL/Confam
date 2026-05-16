"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";

import type { ChatMessageDTO } from "@/lib/chat-api";
import { PaymentCard } from "@/app/chat/_components/PaymentCard";

type Props = {
  messages: ChatMessageDTO[];
};

function isPaymentIntentMessage(m: ChatMessageDTO): boolean {
  const meta = m.payment_metadata;
  if (!meta || typeof meta !== "object") return false;
  const o = meta as Record<string, unknown>;
  const flag = o.is_payment_intent;
  if (flag === true || flag === "true" || flag === 1) return true;
  const mode = o.mode;
  if (
    (mode === "saved_recipient" || mode === "payment_screenshot" || mode === "product_image") &&
    (o.account_number != null || o.bank_name != null)
  ) {
    return true;
  }
  return false;
}

function Bubble({ m }: { m: ChatMessageDTO }) {
  const isUser = m.role === "user";
  const widthCap = isUser
    ? "max-w-[min(90%,22rem)] sm:max-w-md"
    : "max-w-[min(94%,28rem)] sm:max-w-xl md:max-w-2xl";

  const shell = `${widthCap} rounded-[1.25rem] px-3.5 py-2.5 text-[15px] leading-relaxed shadow-card md:px-4 md:py-3 md:text-[15px] ${
    isUser
      ? "rounded-br-md bg-brand text-white"
      : "rounded-bl-md border border-mist-line bg-white text-ink"
  }`;

  const renderBody = () => {
    if (m.msg_type === "voice") {
      return (
        <div className="space-y-2.5">
          <p className={`text-[10px] font-semibold uppercase tracking-[0.12em] ${isUser ? "text-white/70" : "text-ink-muted"}`}>
            Voice
          </p>
          {m.file_url ? (
            <audio
              controls
              className={`w-full max-w-[260px] rounded-lg ${isUser ? "opacity-95" : ""}`}
              src={m.file_url}
            >
              <track kind="captions" />
            </audio>
          ) : null}
          {m.transcript ? (
            <p className={`text-[13px] leading-snug ${isUser ? "text-white/90" : "text-ink-muted"}`}>
              <span className={`font-medium ${isUser ? "text-white" : "text-ink"}`}>Transcript · </span>
              {m.transcript}
            </p>
          ) : null}
        </div>
      );
    }

    if (m.msg_type === "image") {
      return (
        <div className="space-y-2.5">
          {m.file_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={m.file_url}
              alt="Attachment"
              className="max-h-52 w-full max-w-xs rounded-xl object-cover ring-1 ring-black/5 md:max-h-60"
            />
          ) : null}
          {m.content ? (
            <p className={isUser ? "text-white/95" : "text-ink"}>{m.content}</p>
          ) : (
            <p className={isUser ? "text-white/75" : "text-ink-muted"}>Photo</p>
          )}
        </div>
      );
    }

    if (m.msg_type === "payment_image") {
      const payload = m.ocr_payload as Record<string, unknown> | null;
      const err =
        payload && typeof payload.extraction_error === "string"
          ? payload.extraction_error
          : null;
      const parsed =
        payload && payload.parsed_json && typeof payload.parsed_json === "object"
          ? (payload.parsed_json as Record<string, unknown>)
          : null;
      return (
        <div className="space-y-2.5">
          {m.file_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={m.file_url}
              alt="Bank screenshot"
              className="max-h-44 w-full max-w-xs rounded-xl object-cover ring-1 ring-black/5 md:max-h-52"
            />
          ) : null}
          {payload ? (
            <div
              className={`rounded-xl border px-3 py-2.5 text-[13px] leading-snug ${
                isUser
                  ? "border-white/20 bg-white/10 text-white"
                  : "border-mist-line bg-mist-paper text-ink"
              }`}
            >
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] opacity-80">Extracted</p>
              <p className="mt-1.5 font-medium">Bank · {String(payload.bank_name || parsed?.bank_name || "—")}</p>
              <p className="font-mono text-[13px] tracking-wide">Acct · {String(payload.account_number || parsed?.account_number || "—")}</p>
              <p>Name · {String(payload.account_name || parsed?.account_name || "—")}</p>
              {err ? (
                <p className={`mt-2 text-[12px] font-medium ${isUser ? "text-amber-100" : "text-amber-800"}`}>
                  {err}
                </p>
              ) : null}
            </div>
          ) : null}
          {m.content && isUser ? (
            <p className="text-[13px] text-white/85">{m.content}</p>
          ) : null}
        </div>
      );
    }

    if (!isUser && isPaymentIntentMessage(m)) {
      return (
        <PaymentCard messageId={m.id} content={m.content} meta={m.payment_metadata as Record<string, unknown>} />
      );
    }

    return <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{m.content || ""}</p>;
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div className={shell}>{renderBody()}</div>
    </motion.div>
  );
}

export function MessageList({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-mist px-3 py-4 pb-28 sm:px-5 sm:py-5 md:px-6 md:py-6 lg:pb-32">
      <div className="mx-auto w-full max-w-3xl space-y-3 lg:max-w-4xl xl:max-w-5xl">
        {messages.length === 0 ? (
          <div className="mx-auto mt-10 max-w-md rounded-2xl border border-mist-line bg-white px-5 py-8 text-center shadow-card sm:mt-14 sm:px-8">
            <p className="text-sm font-semibold text-ink">Start here</p>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">
              Ask for a price range, attach a product photo, record a voice note, or add a bank screenshot — then send.
            </p>
          </div>
        ) : null}
        {messages.map((m) => (
          <Bubble key={m.id} m={m} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
