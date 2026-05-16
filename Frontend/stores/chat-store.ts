import { create } from "zustand";

import type { ChatMessageDTO } from "@/lib/chat-api";

type ChatState = {
  sessionId: number | null;
  messages: ChatMessageDTO[];
  busy: boolean;
  error: string | null;
  setSessionId: (id: number | null) => void;
  setMessages: (messages: ChatMessageDTO[]) => void;
  appendPair: (user: ChatMessageDTO, assistant: ChatMessageDTO) => void;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
};

export const useChatStore = create<ChatState>((set) => ({
  sessionId: null,
  messages: [],
  busy: false,
  error: null,
  setSessionId: (id) => set({ sessionId: id }),
  setMessages: (messages) => set({ messages }),
  appendPair: (user, assistant) =>
    set((s) => ({ messages: [...s.messages, user, assistant] })),
  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
}));
