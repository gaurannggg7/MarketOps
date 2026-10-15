import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, type ReactNode } from "react";
import { api, call, isWaking, onUnauthorized, setCsrfToken } from "../lib/api/client";
import { AuthContext, type AuthValue, type User } from "../lib/auth";

const ME_KEY = ["auth", "me"] as const;

interface Probe {
  user: User | null;
  publicDemo: boolean;
  demoAvailable: boolean;
}

async function fetchMe(): Promise<Probe> {
  // /auth/session answers 200 even when signed out, so a cold load logs no 401s.
  const state = await call(api.GET("/api/v1/auth/session"));
  setCsrfToken(state.session?.csrf_token ?? null);
  return {
    user: state.session?.user ?? null,
    publicDemo: state.session?.public_demo ?? false,
    demoAvailable: state.demo_available,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ME_KEY,
    queryFn: fetchMe,
    // A sleeping free-tier backend answers 502/503/504 (or nothing) for ~1-2 minutes while it
    // wakes: keep retrying for up to 3 minutes; any other error is shown immediately.
    retry: (count, error) => isWaking(error) && count < 36,
    retryDelay: 5000,
    staleTime: 60_000,
  });
  const { refetch } = me;

  useEffect(() => {
    // Any 401 from the API means the session expired or was revoked: drop to the login screen.
    onUnauthorized(() => {
      setCsrfToken(null);
      queryClient.setQueryData<Probe>(ME_KEY, (old) => ({ user: null, publicDemo: false, demoAvailable: old?.demoAvailable ?? false }));
    });
    return () => onUnauthorized(null);
  }, [queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await call(api.POST("/api/v1/auth/login", { body: { email, password } }));
      setCsrfToken(session.csrf_token);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData<Probe>(ME_KEY, (old) => ({ user: session.user, publicDemo: false, demoAvailable: old?.demoAvailable ?? false }));
    },
    [queryClient],
  );

  const demoLogin = useCallback(async () => {
    const session = await call(api.POST("/api/v1/auth/demo"));
    setCsrfToken(session.csrf_token);
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
    queryClient.setQueryData<Probe>(ME_KEY, { user: session.user, publicDemo: true, demoAvailable: true });
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      await call(api.POST("/api/v1/auth/logout"));
    } finally {
      setCsrfToken(null);
      queryClient.clear();
      await queryClient.invalidateQueries({ queryKey: ME_KEY });
    }
  }, [queryClient]);

  const value = useMemo<AuthValue>(
    () => ({
      user: me.data?.user ?? null,
      publicDemo: me.data?.publicDemo ?? false,
      demoAvailable: me.data?.demoAvailable ?? false,
      demoLogin,
      loading: me.isPending,
      error: me.isError ? me.error : null,
      retry: () => void refetch(),
      isOperator: me.data?.user?.role === "OPERATOR" && !me.data.publicDemo,
      login,
      logout,
    }),
    [me.data, me.isPending, me.isError, me.error, refetch, login, logout, demoLogin],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
