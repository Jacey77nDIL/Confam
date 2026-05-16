import api from "@/lib/api";
import { useLocationStore } from "@/stores/location-store";

export type ChatSessionDTO = {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessageDTO = {
  id: number;
  role: string;
  msg_type: string;
  content: string | null;
  transcript: string | null;
  ocr_payload: Record<string, unknown> | null;
  payment_metadata?: Record<string, unknown> | null;
  file_id: number | null;
  file_url: string | null;
  created_at: string;
};

export type TurnResultDTO = {
  user_message: ChatMessageDTO;
  assistant_message: ChatMessageDTO;
};

export type UploadedFileDTO = {
  id: number;
  mime_type: string | null;
  original_name: string | null;
  file_url: string | null;
  file_type: string;
};

export type UploadKind = "chat_image" | "payment_image" | "voice_note" | "avatar";

function geoFields(): { latitude?: number; longitude?: number } {
  const c = useLocationStore.getState().coords;
  if (!c) return {};
  return { latitude: c.latitude, longitude: c.longitude };
}

export async function listSessions(): Promise<ChatSessionDTO[]> {
  const { data } = await api.get<ChatSessionDTO[]>("/chat/sessions");
  return data;
}

export async function createSession(title?: string): Promise<ChatSessionDTO> {
  const { data } = await api.post<ChatSessionDTO>("/chat/sessions", {
    title: title ?? "New chat",
  });
  return data;
}

export async function bootstrapSession(): Promise<number> {
  const sessions = await listSessions();
  if (sessions.length) return sessions[0].id;
  const created = await createSession();
  return created.id;
}

export async function listMessages(sessionId: number): Promise<ChatMessageDTO[]> {
  const { data } = await api.get<ChatMessageDTO[]>(
    `/chat/sessions/${sessionId}/messages`,
  );
  return data;
}

export async function uploadChatFile(
  file: File,
  opts?: {
    kind?: UploadKind;
    onProgress?: (percent: number) => void;
  },
): Promise<UploadedFileDTO> {
  const form = new FormData();
  form.append("upload", file);
  const params = opts?.kind ? { kind: opts.kind } : {};
  const { data } = await api.post<UploadedFileDTO>("/chat/files", form, {
    params,
    onUploadProgress: (ev) => {
      if (opts?.onProgress && ev.total) {
        opts.onProgress(Math.round((ev.loaded * 100) / ev.total));
      }
    },
  });
  return data;
}

export async function sendText(sessionId: number, text: string): Promise<TurnResultDTO> {
  const { data } = await api.post<TurnResultDTO>(
    `/chat/sessions/${sessionId}/messages/text`,
    { text, ...geoFields() },
  );
  return data;
}

export async function sendImage(
  sessionId: number,
  fileId: number,
  caption?: string | null,
): Promise<TurnResultDTO> {
  const { data } = await api.post<TurnResultDTO>(
    `/chat/sessions/${sessionId}/messages/image`,
    { file_id: fileId, caption: caption ?? null, ...geoFields() },
  );
  return data;
}

export async function sendVoice(sessionId: number, fileId: number): Promise<TurnResultDTO> {
  const { data } = await api.post<TurnResultDTO>(
    `/chat/sessions/${sessionId}/messages/voice`,
    { file_id: fileId, ...geoFields() },
  );
  return data;
}

export async function sendPayment(
  sessionId: number,
  fileId: number,
  opts?: { text?: string | null },
): Promise<TurnResultDTO> {
  const { data } = await api.post<TurnResultDTO>(
    `/chat/sessions/${sessionId}/messages/payment`,
    {
      file_id: fileId,
      text: opts?.text ?? null,
      ...geoFields(),
    },
  );
  return data;
}

export type CardVerificationInitDTO = {
  checkout_url: string;
  transaction_ref: string;
  message: string;
};

export async function initiateSquadCardVerification(returnUrl: string): Promise<CardVerificationInitDTO> {
  const { data } = await api.post<CardVerificationInitDTO>(
    "/integrations/squad/card-verification/initiate",
    { return_url: returnUrl },
  );
  return data;
}

export type ConnectedCardDTO = {
  status: string;
  card_type: string | null;
  masked_pan: string | null;
  last4: string | null;
  brand_label: string | null;
};

export async function finalizeSquadCardVerification(): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post<{ success: boolean; message: string }>(
    "/integrations/squad/card-verification/finalize",
  );
  return data;
}

export async function getConnectedCard(): Promise<ConnectedCardDTO | null> {
  const { data } = await api.get<ConnectedCardDTO | null>("/integrations/squad/connected-card");
  return data;
}

export async function removeConnectedCard(): Promise<void> {
  await api.delete("/integrations/squad/connected-card");
}

/** Dispatch after connect/remove so in-chat payment UI refetches card state. */
export const CONNECTED_CARD_CHANGED_EVENT = "confam:connected-card-changed";

/** Open the Squad card linking modal from anywhere (e.g. in-chat payment block). */
export const OPEN_CONNECT_CARD_MODAL_EVENT = "confam:open-connect-card-modal";

export function emitConnectedCardChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(CONNECTED_CARD_CHANGED_EVENT));
  }
}

export function emitOpenConnectCardModal(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(OPEN_CONNECT_CARD_MODAL_EVENT));
  }
}

export type PaymentExecuteDTO = {
  success: boolean;
  message: string;
  transaction_id: number | null;
  duplicate?: boolean;
  /** True when the card charge succeeded but bank payout is deferred (collection-only). */
  payout_deferred?: boolean;
};

export async function executeSquadPayment(body: {
  amount_kobo: number;
  recipient_account_number: string;
  recipient_bank_name?: string | null;
  recipient_account_name: string;
  idempotency_key: string;
  assistant_message_id?: number | null;
}): Promise<PaymentExecuteDTO> {
  const { data } = await api.post<PaymentExecuteDTO>("/integrations/squad/payments/execute", body);
  return data;
}
