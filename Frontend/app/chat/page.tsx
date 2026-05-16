"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { ConnectCardModal } from "@/app/chat/_components/ConnectCardModal";
import { ChatComposer, type PendingPayment } from "@/app/chat/_components/ChatComposer";
import { ChatNavbar } from "@/app/chat/_components/ChatNavbar";
import { MessageList } from "@/app/chat/_components/MessageList";
import { ChatLoadingSkeleton } from "@/components/confam/skeleton";
import { useAuth } from "@/contexts/auth-context";
import { extractApiError } from "@/lib/api";
import * as chatApi from "@/lib/chat-api";
import { useChatStore } from "@/stores/chat-store";
import { useLocationStore } from "@/stores/location-store";

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center text-gray-500">
          Loading secure chat...
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  );
}

function ChatContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, logout } = useAuth();
  const [cardOpen, setCardOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [pendingPayment, setPendingPayment] = useState<PendingPayment | null>(null);
  const [mediaUploadProgress, setMediaUploadProgress] = useState<number | null>(null);

  const sessionId = useChatStore((s) => s.sessionId);
  const messages = useChatStore((s) => s.messages);
  const setSessionId = useChatStore((s) => s.setSessionId);
  const setMessages = useChatStore((s) => s.setMessages);
  const appendPair = useChatStore((s) => s.appendPair);
  const busy = useChatStore((s) => s.busy);
  const setBusy = useChatStore((s) => s.setBusy);
  const requestLocation = useLocationStore((s) => s.requestLocation);

  useEffect(() => {
    if (!loading && !user) router.replace("/?login=1");
  }, [loading, user, router]);

  useEffect(() => {
    if (searchParams.get("card") !== "connected") return;
    let cancelled = false;
    (async () => {
      for (let i = 0; i < 20; i++) {
        if (cancelled) return;
        try {
          const fin = await chatApi.finalizeSquadCardVerification();
          if (fin.success) {
            chatApi.emitConnectedCardChanged();
            if (!cancelled) {
              toast.success("Card connected successfully.");
              router.replace("/chat");
            }
            return;
          }
          const c = await chatApi.getConnectedCard();
          if (c) {
            chatApi.emitConnectedCardChanged();
            if (!cancelled) {
              toast.success("Card connected successfully.");
              router.replace("/chat");
            }
            return;
          }
        } catch {
          /* keep polling — webhook may lag */
        }
        await new Promise((r) => setTimeout(r, 600));
      }
      if (!cancelled) {
        toast.message("Card link finishing up", {
          description: "Open Cards in a moment if your card does not appear yet.",
        });
        router.replace("/chat");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchParams, router]);

  useEffect(() => {
    const open = () => setCardOpen(true);
    window.addEventListener(chatApi.OPEN_CONNECT_CARD_MODAL_EVENT, open);
    return () => window.removeEventListener(chatApi.OPEN_CONNECT_CARD_MODAL_EVENT, open);
  }, []);

  useEffect(() => {
    if (!user) return;
    requestLocation();
  }, [user, requestLocation]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        setBusy(true);
        const sid = await chatApi.bootstrapSession();
        if (cancelled) return;
        setSessionId(sid);
        const ms = await chatApi.listMessages(sid);
        if (cancelled) return;
        setMessages(ms);
      } catch (e) {
        if (!cancelled) toast.error(extractApiError(e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, setBusy, setMessages, setSessionId]);

  const applyTurn = (t: chatApi.TurnResultDTO) => {
    appendPair(t.user_message, t.assistant_message);
  };

  const refreshUntilResolved = async (sid: number, assistantId: number) => {
    const started = Date.now();
    while (Date.now() - started < 60_000) {
      await new Promise((r) => setTimeout(r, 900));
      try {
        const ms = await chatApi.listMessages(sid);
        setMessages(ms);
        const a = ms.find((m) => m.id === assistantId);
        if (a && a.content && a.content !== "Processing…") return;
      } catch {
        return;
      }
    }
    toast.message("Still processing", {
      description: "Pull to refresh your messages if this takes a while.",
    });
  };

  const handleSendText = async () => {
    if (!sessionId) return;
    if (!draft.trim() && !pendingPayment) return;
    try {
      setBusy(true);
      if (pendingPayment) {
        const text = draft.trim() || null;
        const turn = await chatApi.sendPayment(sessionId, pendingPayment.fileId, { text });
        setPendingPayment(null);
        setDraft("");
        applyTurn(turn);
        toast.success("Details captured");
        return;
      }
      const turn = await chatApi.sendText(sessionId, draft.trim());
      setDraft("");
      applyTurn(turn);
    } catch (e) {
      toast.error(extractApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleProductImage = async (file: File) => {
    if (!sessionId) return;
    try {
      setBusy(true);
      setMediaUploadProgress(0);
      const up = await chatApi.uploadChatFile(file, {
        kind: "chat_image",
        onProgress: (p) => setMediaUploadProgress(p),
      });
      setMediaUploadProgress(null);
      const caption = draft.trim() || null;
      const turn = await chatApi.sendImage(sessionId, up.id, caption);
      setDraft("");
      applyTurn(turn);
      void refreshUntilResolved(sessionId, turn.assistant_message.id);
    } catch (e) {
      toast.error(extractApiError(e));
    } finally {
      setMediaUploadProgress(null);
      setBusy(false);
    }
  };

  const handlePaymentImage = async (file: File) => {
    if (!sessionId) return;
    try {
      setBusy(true);
      setMediaUploadProgress(0);
      const up = await chatApi.uploadChatFile(file, {
        kind: "payment_image",
        onProgress: (p) => setMediaUploadProgress(p),
      });
      setMediaUploadProgress(null);
      setPendingPayment({ fileId: up.id });
      toast.success("Screenshot attached", {
        description: "Add a note if needed, then send.",
      });
    } catch (e) {
      toast.error(extractApiError(e));
    } finally {
      setMediaUploadProgress(null);
      setBusy(false);
    }
  };

  const handleVoiceBlob = async (blob: Blob) => {
    if (!sessionId) return;
    try {
      setBusy(true);
      const ext = blob.type.includes("mp4") ? "m4a" : "webm";
      const file = new File([blob], `voice.${ext}`, {
        type: blob.type || "audio/webm",
      });
      setMediaUploadProgress(0);
      const up = await chatApi.uploadChatFile(file, {
        kind: "voice_note",
        onProgress: (p) => setMediaUploadProgress(p),
      });
      setMediaUploadProgress(null);
      const turn = await chatApi.sendVoice(sessionId, up.id);
      applyTurn(turn);
      void refreshUntilResolved(sessionId, turn.assistant_message.id);
    } catch (e) {
      toast.error(extractApiError(e));
    } finally {
      setMediaUploadProgress(null);
      setBusy(false);
    }
  };

  if (loading || !user) {
    return <ChatLoadingSkeleton />;
  }

  return (
    <div className="min-h-[100dvh] bg-mist lg:flex lg:min-h-[100dvh] lg:items-center lg:justify-center lg:px-5 lg:py-8">
      <div
        className="mx-auto flex h-[100dvh] w-full max-w-lg flex-col overflow-hidden bg-white shadow-elev-2 sm:max-w-2xl md:max-w-3xl lg:h-[min(100dvh,calc(100dvh-2.5rem))] lg:max-h-[calc(100dvh-2.5rem)] lg:max-w-4xl lg:rounded-2xl lg:ring-1 lg:ring-mist-line xl:max-w-5xl"
        role="application"
        aria-label="Confam"
      >
        <ChatNavbar
          onConnectCard={() => setCardOpen(true)}
          onSignOut={() => logout()}
        />
        <MessageList messages={messages} />
        {busy ? (
          <div className="pointer-events-none fixed bottom-[5.5rem] left-1/2 z-30 -translate-x-1/2 rounded-full border border-mist-line bg-white/95 px-4 py-1.5 text-xs font-medium text-ink shadow-elev-1 sm:bottom-24 md:text-sm lg:bottom-10">
            Working…
          </div>
        ) : null}
        <ChatComposer
          disabled={busy || !sessionId}
          draft={draft}
          onDraftChange={setDraft}
          onSendText={handleSendText}
          onProductImage={handleProductImage}
          onPaymentImage={handlePaymentImage}
          onVoiceBlob={handleVoiceBlob}
          pendingPayment={pendingPayment}
          onClearPendingPayment={() => setPendingPayment(null)}
          mediaUploadProgress={mediaUploadProgress}
        />
        <ConnectCardModal open={cardOpen} onClose={() => setCardOpen(false)} />
      </div>
    </div>
  );
}
