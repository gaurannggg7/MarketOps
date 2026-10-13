import { createContext, useContext } from "react";
import type { Schemas } from "./api/client";

export type User = Schemas["UserOut"];

export interface AuthValue {
  user: User | null;
  loading: boolean;
  isOperator: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
