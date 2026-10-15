import { createContext, useContext } from "react";
import type { Schemas } from "./api/client";

export type User = Schemas["UserOut"];

export interface AuthValue {
  user: User | null;
  loading: boolean;
  /** Set when the session probe itself failed (server unreachable), not when signed out. */
  error: unknown;
  retry: () => void;
  isOperator: boolean;
  /** Anonymous read-only public-demo session: every write is rejected by the server. */
  publicDemo: boolean;
  /** Whether this server offers the read-only public demo entry point. */
  demoAvailable: boolean;
  demoLogin: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
