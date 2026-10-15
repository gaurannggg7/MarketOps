/**
 * MarketStream: a small external store owning one WebSocket at a time.
 *
 * - React subscribes through useSyncExternalStore with selectors (see useMarket.ts), so a tick
 *   only re-renders components whose selected value changed.
 * - Grid code can subscribe to quote batches directly (onQuotes) and apply AG Grid transactions
 *   without React rendering at all.
 * - Reconnects use exponential backoff with full jitter and a ceiling. Every new attempt first
 *   detaches and closes the previous socket and clears pending timers, so listeners never pile up.
 */
import { CloseCode, parseServerMessage } from "./protocol";
import { applyMessage, initialStreamState, markSuspect, type Quote, type StreamState } from "./reducer";

export interface SocketLike {
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason?: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  close(code?: number, reason?: string): void;
  send?(data: string): void;
}

export interface StreamOptions {
  url: () => string;
  createSocket?: (url: string) => SocketLike;
  random?: () => number;
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
  /** Resubscribe quickly after a deliberate resync (gap/epoch/server request). */
  resyncDelayMs?: number;
  /**
   * Split-origin deployments: fetch a single-use stream ticket (cookie-authenticated REST call)
   * before each connection and send it as the first message. Undefined = cookie auth.
   */
  getTicket?: () => Promise<string>;
}

export type QuoteListener = (changed: readonly Quote[], kind: "snapshot" | "delta") => void;

export class MarketStream {
  private state: StreamState = initialStreamState();
  private readonly listeners = new Set<() => void>();
  private readonly quoteListeners = new Set<QuoteListener>();
  private socket: SocketLike | null = null;
  private timer: unknown = null;
  private attempt = 0;
  private running = false;
  private readonly opts: Required<Omit<StreamOptions, "getTicket">> & Pick<StreamOptions, "getTicket">;
  /** Incremented on every connect/stop so late ticket responses for old attempts are ignored. */
  private generation = 0;
  /** Wall-clock ms for which the next reconnect is scheduled (for UI countdowns). */
  nextRetryAt: number | null = null;
  /** Number of sockets created; useful to verify no duplicate connections in tests. */
  socketsCreated = 0;

  constructor(options: StreamOptions) {
    this.opts = {
      createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
      random: Math.random,
      now: Date.now,
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
      baseDelayMs: 500,
      maxDelayMs: 15_000,
      resyncDelayMs: 150,
      ...options,
    };
  }

  // ---- external store API -----------------------------------------------------------------
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getState = (): StreamState => this.state;

  onQuotes(listener: QuoteListener): () => void {
    this.quoteListeners.add(listener);
    return () => this.quoteListeners.delete(listener);
  }

  private setState(next: StreamState): void {
    this.state = next;
    for (const l of this.listeners) l();
  }

  // ---- lifecycle ----------------------------------------------------------------------------
  start(): void {
    if (this.running) return;
    this.running = true;
    this.attempt = 0;
    this.connect();
  }

  /** Stop and release everything (logout, unmount). Safe to call repeatedly. */
  stop(): void {
    this.running = false;
    this.generation += 1;
    this.clearTimer();
    this.detachSocket(1000, "client stop");
    this.nextRetryAt = null;
    this.setState({ ...initialStreamState(), stats: this.state.stats, status: "idle" });
  }

  /** Force a fresh snapshot (used by the UI "Resync now" control). */
  resyncNow(): void {
    if (!this.running) return;
    this.clearTimer();
    this.detachSocket(1000, "manual resync");
    this.setState(markSuspect(this.state, "resyncing", "manual"));
    this.connect();
  }

  get isRunning(): boolean {
    return this.running;
  }

  private connect(): void {
    if (!this.running) return;
    this.clearTimer();
    this.detachSocket(1000, "replaced");
    this.nextRetryAt = null;
    const statusBefore = this.state.status;
    this.setState({
      ...this.state,
      status: statusBefore === "resyncing" ? "resyncing" : "connecting",
      dataSuspect: true,
    });
    const generation = ++this.generation;
    const getTicket = this.opts.getTicket;
    if (!getTicket) {
      this.openSocket(null);
      return;
    }
    getTicket().then(
      (ticket) => {
        if (this.running && generation === this.generation) this.openSocket(ticket);
      },
      () => {
        // Backend asleep/unreachable (e.g. a free-tier cold start): back off and retry.
        if (!this.running || generation !== this.generation) return;
        this.attempt += 1;
        this.schedule(this.backoffDelay(this.attempt), "reconnecting");
      },
    );
  }

  private openSocket(ticket: string | null): void {
    const socket = this.opts.createSocket(this.opts.url());
    this.socketsCreated += 1;
    this.socket = socket;
    if (ticket !== null) {
      socket.onopen = () => {
        if (this.socket === socket) socket.send?.(JSON.stringify({ type: "auth", ticket }));
      };
    }
    socket.onmessage = (ev) => {
      if (this.socket !== socket) return;
      this.handleMessage(ev.data);
    };
    socket.onclose = (ev) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.handleClose(ev.code);
    };
    socket.onerror = () => {
      /* onclose follows and drives reconnection */
    };
  }

  private handleMessage(data: unknown): void {
    const msg = parseServerMessage(data);
    if (!msg) return;
    const { state, outcome } = applyMessage(this.state, msg, this.opts.now());
    this.setState(state);
    switch (outcome.kind) {
      case "snapshot":
        this.attempt = 0;
        for (const l of this.quoteListeners) l(outcome.changed, "snapshot");
        break;
      case "applied":
        for (const l of this.quoteListeners) l(outcome.changed, "delta");
        break;
      case "resync":
        // Do not keep applying an incomplete stream: drop this socket and resubscribe.
        this.detachSocket(1000, `client resync: ${outcome.reason}`);
        this.schedule(this.opts.resyncDelayMs, "resyncing");
        break;
      default:
        break;
    }
  }

  private handleClose(code: number): void {
    if (!this.running) return;
    if (code === CloseCode.LOGGED_OUT || code === CloseCode.UNAUTHENTICATED) {
      this.running = false;
      this.setState(markSuspect(this.state, "offline", code === CloseCode.LOGGED_OUT ? "logged_out" : "unauthenticated"));
      return;
    }
    if (code === CloseCode.RESYNC || code === CloseCode.SCENARIO_DISCONNECT) {
      this.schedule(this.opts.resyncDelayMs, "resyncing");
      return;
    }
    this.attempt += 1;
    this.schedule(this.backoffDelay(this.attempt), "reconnecting");
  }

  /** Exponential backoff with full jitter: random in [base/2, min(max, base·2^(n-1))]. */
  backoffDelay(attempt: number): number {
    const ceiling = Math.min(this.opts.maxDelayMs, this.opts.baseDelayMs * 2 ** Math.max(0, attempt - 1));
    const floor = this.opts.baseDelayMs / 2;
    return Math.round(floor + this.opts.random() * Math.max(0, ceiling - floor));
  }

  private schedule(delayMs: number, status: "reconnecting" | "resyncing"): void {
    if (!this.running) return;
    this.clearTimer();
    this.nextRetryAt = this.opts.now() + delayMs;
    this.setState(markSuspect(this.state, status, null));
    this.timer = this.opts.setTimer(() => {
      this.timer = null;
      this.connect();
    }, delayMs);
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      this.opts.clearTimer(this.timer);
      this.timer = null;
    }
  }

  private detachSocket(code: number, reason: string): void {
    const socket = this.socket;
    if (!socket) return;
    this.socket = null;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    try {
      socket.close(code, reason);
    } catch {
      /* already closed */
    }
  }
}

/** Build-time override for split-origin hosting, e.g. wss://marketops-api-hy19.onrender.com/ws/market. */
export const configuredStreamUrl: string | undefined = (import.meta.env.VITE_STREAM_URL as string | undefined) || undefined;

export function defaultStreamUrl(): string {
  if (configuredStreamUrl) return configuredStreamUrl;
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss:" : "ws:"}//${host}/ws/market`;
}
