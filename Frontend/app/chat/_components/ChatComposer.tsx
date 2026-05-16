"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { IconCamera, IconMic, IconNairaFrame, IconSend } from "@/components/confam/icons";

export type PendingPayment = { fileId: number };

type Props = {
  disabled: boolean;
  draft: string;
  onDraftChange: (v: string) => void;
  onSendText: () => void | Promise<void>;
  onProductImage: (file: File) => void | Promise<void>;
  onPaymentImage: (file: File) => void | Promise<void>;
  onVoiceBlob: (blob: Blob) => void | Promise<void>;
  pendingPayment: PendingPayment | null;
  onClearPendingPayment: () => void;
  /** 0–100 while a media file is uploading; null hides the bar. */
  mediaUploadProgress?: number | null;
};

function pickMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
    return "audio/webm;codecs=opus";
  }
  if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
  return undefined;
}

export function ChatComposer({
  disabled,
  draft,
  onDraftChange,
  onSendText,
  onProductImage,
  onPaymentImage,
  onVoiceBlob,
  pendingPayment,
  onClearPendingPayment,
  mediaUploadProgress = null,
}: Props) {
  const productInputRef = useRef<HTMLInputElement | null>(null);
  const paymentInputRef = useRef<HTMLInputElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const recordStartedAtRef = useRef<number | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    setIsMobile(/Android|iPhone|iPad|iPod|Mobi/i.test(navigator.userAgent));
  }, []);

  const stopStream = useCallback((stream: MediaStream | null) => {
    stream?.getTracks().forEach((t) => t.stop());
  }, []);

  useEffect(() => {
    return () => {
      stopStream(mediaRecorderRef.current?.stream ?? null);
    };
  }, [stopStream]);

  const startRecording = async () => {
    setRecordError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mime = pickMime();
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      mediaRecorderRef.current = mr;
      recordStartedAtRef.current = performance.now();
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stopStream(stream);
        const type = mr.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        chunksRef.current = [];
        mediaRecorderRef.current = null;
        const startedAt = recordStartedAtRef.current;
        recordStartedAtRef.current = null;
        setRecording(false);
        const durationMs = startedAt ? performance.now() - startedAt : 0;
        if (blob.size === 0 || durationMs < 300) {
          setRecordError("Hold a little longer — tap again to stop.");
          return;
        }
        await onVoiceBlob(blob);
      };
      mr.start();
      setRecording(true);
    } catch {
      setRecordError("Microphone access is off for this site.");
    }
  };

  const stopRecording = () => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
  };

  const canSend = Boolean(draft.trim()) || Boolean(pendingPayment);

  const toolBtn =
    "grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-mist-line bg-mist-paper text-ink-muted shadow-sm transition active:scale-[95%] disabled:pointer-events-none disabled:opacity-40 hover:border-brand/25 hover:bg-white hover:text-brand md:h-11 md:w-11";

  return (
    <div className="border-t border-mist-line/90 bg-mist-paper/95 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur-xl lg:rounded-b-2xl">
      {mediaUploadProgress != null && mediaUploadProgress < 100 ? (
        <div className="mx-auto mb-2 max-w-3xl px-4 sm:px-6 md:max-w-4xl xl:max-w-5xl">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-mist-line">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-150"
              style={{ width: `${Math.max(2, mediaUploadProgress)}%` }}
            />
          </div>
          <p className="mt-1 text-center text-[10px] font-medium uppercase tracking-wider text-ink-muted">
            Uploading… {mediaUploadProgress}%
          </p>
        </div>
      ) : null}
      {recordError ? (
        <p className="mb-2 px-4 text-center text-xs text-ink-muted sm:px-6">{recordError}</p>
      ) : null}
      {pendingPayment ? (
        <div className="mx-auto mb-2 flex max-w-3xl items-center gap-2 px-3 sm:px-5 md:max-w-4xl md:px-6 xl:max-w-5xl">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-brand/15 bg-brand/[0.06] px-3 py-2 shadow-sm">
            <span className="h-2 w-2 shrink-0 rounded-full bg-brand" aria-hidden />
            <p className="min-w-0 truncate text-xs font-medium text-ink sm:text-sm">
              Screenshot ready — add a note if you want, then send.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold text-ink-muted transition hover:bg-mist hover:text-ink"
            onClick={onClearPendingPayment}
          >
            Remove
          </button>
        </div>
      ) : null}
      <div className="mx-auto max-w-3xl px-3 pb-1 sm:px-5 md:max-w-4xl md:px-6 xl:max-w-5xl">
        <div className="flex items-end gap-1.5 rounded-2xl border border-mist-line bg-white p-1.5 shadow-elev-1 sm:gap-2">
          <input
            ref={productInputRef}
            type="file"
            accept={isMobile ? "image/*" : "image/jpeg,image/png,image/webp"}
            capture={isMobile ? "environment" : undefined}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void onProductImage(f);
            }}
          />
          <input
            ref={paymentInputRef}
            type="file"
            accept="image/*"
            capture={isMobile ? "environment" : undefined}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void onPaymentImage(f);
            }}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => productInputRef.current?.click()}
            className={toolBtn}
            aria-label="Attach photo"
          >
            <IconCamera className="h-[22px] w-[22px]" />
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => {
              if (recording) stopRecording();
              else void startRecording();
            }}
            className={`${toolBtn} ${
              recording ? "border-red-200/80 bg-red-50 text-red-700 hover:border-red-200" : ""
            }`}
            aria-label={recording ? "Stop recording" : "Record voice"}
          >
            <IconMic className="h-[22px] w-[22px]" />
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => paymentInputRef.current?.click()}
            className={toolBtn}
            aria-label="Attach bank screenshot"
          >
            <IconNairaFrame className="h-[22px] w-[22px]" />
          </button>
          <div className="relative min-w-0 flex-1">
            <textarea
              rows={1}
              value={draft}
              disabled={disabled}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (!disabled && canSend) void onSendText();
                }
              }}
              placeholder="Message…"
              className="max-h-36 min-h-[44px] w-full resize-none rounded-xl border-0 bg-transparent px-2 py-2.5 text-[15px] leading-snug text-ink outline-none placeholder:text-ink-muted/70 focus:ring-0 disabled:opacity-50 md:min-h-[48px] md:py-3 md:text-base"
            />
          </div>
          <button
            type="button"
            disabled={disabled || !canSend}
            onClick={() => void onSendText()}
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand text-white shadow-elev-1 transition hover:bg-brand-dark active:scale-[95%] disabled:pointer-events-none disabled:opacity-35 md:h-11 md:w-11"
            aria-label="Send"
          >
            <IconSend className="h-[22px] w-[22px]" />
          </button>
        </div>
      </div>
    </div>
  );
}
