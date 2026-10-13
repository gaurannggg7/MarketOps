import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, type ReactNode } from "react";
import { api, call, onUnauthorized, setCsrfToken } from "../lib/api/client";
import { AuthContext, type AuthValue } from "../lib/auth";

const ME_KEY = ["auth", "me"] as const;

async function fetchMe() {
  // /auth/session answers 200 even when signed out, so a cold load logs no 401s.
  const state = await call(api.GET("/api/v1/auth/session"));
  setCsrfToken(state.session?.csrf_token ?? null);
  return state.session?.user ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ME_KEY, queryFn: fetchMe, retry: false, staleTime: 60_000 });
  const { refetch } = me;

  useEffect(() => {
    // Any 401 from the API means the session expired or was revoked: drop to the login screen.
    onUnauthorized(() => {
      setCsrfToken(null);
      queryClient.setQueryData(ME_KEY, null);
    });
    return () => onUnauthorized(null);
  }, [queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await call(api.POST("/api/v1/auth/login", { body: { email, password } }));
      setCsrfToken(session.csrf_token);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData(ME_KEY, session.user);
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await call(api.POST("/api/v1/auth/logout"));
    } finally {
      setCsrfToken(null);
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
    }
  }, [queryClient]);

  const value = useMemo<AuthValue>(
    () => ({
      user: me.data ?? null,
      loading: me.isPending,
      error: me.isError ? me.error : null,
      retry: () => void refetch(),
      isOperator: me.data?.role === "OPERATOR",
      login,
      logout,
    }),
    [me.data, me.isPending, me.isError, me.error, refetch, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
