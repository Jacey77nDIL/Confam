"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import api, { extractApiError } from "@/lib/api";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/auth-storage";

export type AuthUser = {
  id: number;
  full_name: string;
  email: string;
  created_at: string;
};

type AuthContextValue = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  message: string | null;
  clearFeedback: () => void;
  login: (email: string, password: string) => Promise<void>;
  signup: (fullName: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const router = useRouter();

  const clearFeedback = useCallback(() => {
    setError(null);
    setMessage(null);
  }, []);

  const refreshUser = useCallback(async () => {
    const stored = getAccessToken();
    if (!stored) {
      setUser(null);
      setToken(null);
      setLoading(false);
      return;
    }
    setToken(stored);
    try {
      const { data } = await api.get<AuthUser>("/auth/me");
      setUser(data);
    } catch {
      clearAccessToken();
      setUser(null);
      setToken(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      clearFeedback();
      try {
        const { data } = await api.post<{
          access_token: string;
          token_type: string;
        }>("/auth/login", { email, password });
        setAccessToken(data.access_token);
        setToken(data.access_token);
        const { data: me } = await api.get<AuthUser>("/auth/me");
        setUser(me);
        setMessage("Signed in successfully.");
      } catch (e) {
        setError(extractApiError(e));
        throw e;
      }
    },
    [clearFeedback],
  );

  const signup = useCallback(
    async (fullName: string, email: string, password: string) => {
      clearFeedback();
      try {
        const { data } = await api.post<{
          access_token: string;
          token_type: string;
        }>("/auth/signup", {
          full_name: fullName,
          email,
          password,
        });
        setAccessToken(data.access_token);
        setToken(data.access_token);
        const { data: me } = await api.get<AuthUser>("/auth/me");
        setUser(me);
        setMessage("Account created. Welcome to Confam.");
      } catch (e) {
        setError(extractApiError(e));
        throw e;
      }
    },
    [clearFeedback],
  );

  const logout = useCallback(() => {
    clearAccessToken();
    setUser(null);
    setToken(null);
    clearFeedback();
    router.push("/");
  }, [clearFeedback, router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      error,
      message,
      clearFeedback,
      login,
      signup,
      logout,
      refreshUser,
    }),
    [
      user,
      token,
      loading,
      error,
      message,
      clearFeedback,
      login,
      signup,
      logout,
      refreshUser,
    ],
  );

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
