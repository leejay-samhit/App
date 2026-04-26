import React, { createContext, useContext, useEffect, useState, ReactNode } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, setAuthToken } from "./api";

export type User = {
  id: string;
  name: string;
  email: string;
  role: "user" | "admin";
  referral_code: string;
  referred_by: string | null;
  wallet_balance: number;
  total_earned: number;
  registration_paid: boolean;
  direct_referrals_count: number;
  payouts_received: number;
  upi_id: string | null;
  bank_account: string | null;
  ifsc: string | null;
  account_holder: string | null;
  phone?: string | null;
};

type AuthState = {
  user: User | null | undefined; // undefined = checking, null = not auth
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (data: { name: string; email: string; password: string; phone?: string; referral_code?: string }) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setSession: (token: string, user: User) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    try {
      const { data } = await api.get<User>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
      await setAuthToken(null);
    }
  };

  useEffect(() => {
    (async () => {
      const token = await AsyncStorage.getItem("auth_token");
      if (!token) {
        setUser(null);
        return;
      }
      await refresh();
    })();
  }, []);

  const login = async (email: string, password: string) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      await setAuthToken(data.token);
      setUser(data.user);
      return data.user as User;
    } finally {
      setLoading(false);
    }
  };

  const register = async (payload: any) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/register", payload);
      await setAuthToken(data.token);
      setUser(data.user);
      return data.user as User;
    } finally {
      setLoading(false);
    }
  };

  const setSession = async (token: string, u: User) => {
    await setAuthToken(token);
    setUser(u);
  };

  const logout = async () => {
    await setAuthToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh, setSession }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
};
