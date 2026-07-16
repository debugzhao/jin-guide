import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatMessage, DebugEvent, DebugNodeState, DebugRunFilter, PlanType } from '@/types'

const uuidv4 = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)

// ── Auth slice ────────────────────────────────────────────────────────────────

export interface CurrentUser {
  user_id: string
  email: string
  role: string
  email_verified: boolean
}

interface AuthSlice {
  user: CurrentUser | null
  /** True once an api.me() probe has completed (success or failure) — avoids
   *  flashing the "登录" button before we know the real session state. */
  authChecked: boolean
  setUser: (user: CurrentUser | null) => void
  clearUser: () => void
}

// ── Chat slice ────────────────────────────────────────────────────────────────

interface ChatSlice {
  activeReportId: string | null
  messages: ChatMessage[]
  streamingContent: string
  isStreaming: boolean
  dailyLimitReached: boolean
  dailyLimitMessage: string | null
  /** Last failed user message, kept around so the "重试" button can resend it */
  lastFailedMessage: string | null

  /** 切换到另一份报告的对话时重置消息列表；同一份报告内重复调用是 no-op */
  setActiveReport: (reportId: string) => void
  /** Initialise or replace messages (e.g. after loading history from API) */
  setChatMessages: (messages: ChatMessage[]) => void
  appendUserMessage: (content: string) => void
  /** Called on each SSE token event */
  appendStreamToken: (token: string) => void
  /** Called on SSE done — commits the streaming message */
  commitStreamingMessage: (citations?: { source_id: string; text: string }[]) => void
  setDailyLimitReached: (reached: boolean, message?: string) => void
  setLastFailedMessage: (message: string | null) => void
  clearChat: () => void
}

// ── Debug slice (Admin Debug Console — /admin/debug only) ──────────────────────

/** The 7 real LangGraph nodes (HITL/profile_agent/deliver removed in v1.1 — see CLAUDE.md) */
export const DEBUG_NODE_NAMES = [
  'data_resolver',
  'retrieval_agent',
  'policy_rule_agent',
  'recommendation',
  'risk',
  'report',
  'reflection',
] as const

function initialNodeStates(): Record<string, DebugNodeState> {
  return Object.fromEntries(DEBUG_NODE_NAMES.map((n) => [n, { status: 'pending' as const }]))
}

const DEBUG_EVENTS_CAP = 1000

interface DebugSlice {
  selectedRunId: string | null
  isLiveFollowing: boolean
  debugRunFilter: DebugRunFilter
  nodeStates: Record<string, DebugNodeState>
  debugEvents: DebugEvent[]
  timelineFilter: 'all' | 'node' | 'tool' | 'error'
  isAutoScroll: boolean

  setSelectedRunId: (runId: string | null) => void
  setIsLiveFollowing: (live: boolean) => void
  setDebugRunFilter: (filter: DebugRunFilter) => void
  /** Feed one parsed SSE debug event in; updates nodeStates + appends to debugEvents */
  applyDebugEvent: (type: string, data: Record<string, unknown>) => void
  /** Mark any node still "running" as failed — called on debug:stream_end when run.status === 'failed' */
  markRunningNodesFailed: () => void
  resetDebugState: () => void
  setTimelineFilter: (filter: DebugSlice['timelineFilter']) => void
  setAutoScroll: (auto: boolean) => void
}

// ── App store ─────────────────────────────────────────────────────────────────

interface AppStore extends ChatSlice, DebugSlice, AuthSlice {
  profileId: string | null
  setProfileId: (id: string) => void
  currentTab: PlanType
  setCurrentTab: (tab: PlanType) => void

  /** 当前建档前聊天（IntakeAgent）会话 id；null = 全新对话，不拉历史。不持久化——
   *  每次全新打开 `/` 都应该是空白对话，历史通过侧栏会话列表点选恢复。 */
  currentIntakeConversationId: string | null
  setCurrentIntakeConversationId: (id: string | null) => void
  /** 侧栏会话列表的重新拉取信号：新建会话产生新 id、或一轮对话完成更新了
   *  updated_at 排序时递增，触发侧栏重新 fetch，避免跨组件传函数式 refetch。 */
  conversationListVersion: number
  bumpConversationListVersion: () => void
}

export const useAppStore = create<AppStore>()(
  persist(
    (set, get) => ({
      // ── base store ──
      profileId: null,
      setProfileId: (id) => set({ profileId: id }),
      currentTab: 'balanced',
      setCurrentTab: (tab) => set({ currentTab: tab }),

      currentIntakeConversationId: null,
      setCurrentIntakeConversationId: (id) => set({ currentIntakeConversationId: id }),
      conversationListVersion: 0,
      bumpConversationListVersion: () =>
        set((s) => ({ conversationListVersion: s.conversationListVersion + 1 })),

      // ── chat slice ──
      activeReportId: null,
      messages: [],
      streamingContent: '',
      isStreaming: false,
      dailyLimitReached: false,
      dailyLimitMessage: null,
      lastFailedMessage: null,

      setActiveReport: (reportId) => {
        const { activeReportId } = get()
        if (activeReportId !== reportId) {
          set({ messages: [], streamingContent: '', activeReportId: reportId })
        }
      },

      setChatMessages: (messages) => set({ messages }),

      appendUserMessage: (content) => {
        const msg: ChatMessage = {
          id: uuidv4(),
          role: 'user',
          content,
          citations: [],
          created_at: new Date().toISOString(),
        }
        set((s) => ({ messages: [...s.messages, msg], isStreaming: true, streamingContent: '' }))
      },

      appendStreamToken: (token) => {
        set((s) => ({ streamingContent: s.streamingContent + token }))
      },

      commitStreamingMessage: (citations = []) => {
        const { streamingContent } = get()
        if (!streamingContent) {
          set({ isStreaming: false })
          return
        }
        const msg: ChatMessage = {
          id: uuidv4(),
          role: 'assistant',
          content: streamingContent,
          citations,
          created_at: new Date().toISOString(),
        }
        set((s) => ({
          messages: [...s.messages, msg],
          streamingContent: '',
          isStreaming: false,
        }))
      },

      setDailyLimitReached: (reached, message) =>
        set({ dailyLimitReached: reached, dailyLimitMessage: reached ? message ?? null : null }),

      setLastFailedMessage: (message) => set({ lastFailedMessage: message }),

      clearChat: () =>
        set({
          messages: [],
          streamingContent: '',
          isStreaming: false,
          dailyLimitReached: false,
          dailyLimitMessage: null,
          lastFailedMessage: null,
        }),

      // ── auth slice ──
      user: null,
      authChecked: false,
      setUser: (user) => set({ user, authChecked: true }),
      clearUser: () => set({ user: null, authChecked: true }),

      // ── debug slice ──
      selectedRunId: null,
      isLiveFollowing: true,
      debugRunFilter: {},
      nodeStates: initialNodeStates(),
      debugEvents: [],
      timelineFilter: 'all',
      isAutoScroll: true,

      setSelectedRunId: (runId) =>
        set({ selectedRunId: runId, nodeStates: initialNodeStates(), debugEvents: [] }),

      setIsLiveFollowing: (live) => set({ isLiveFollowing: live }),

      setDebugRunFilter: (filter) => set({ debugRunFilter: filter }),

      applyDebugEvent: (type, data) => {
        const event: DebugEvent = {
          id: uuidv4(),
          type,
          ts: typeof data.ts === 'number' ? data.ts : Date.now() / 1000,
          node: typeof data.node === 'string' ? data.node : undefined,
          raw: data,
        }

        set((s) => {
          const nodeStates = { ...s.nodeStates }
          const node = event.node

          if (node) {
            const prev = nodeStates[node] ?? { status: 'pending' as const }
            if (type === 'node_started') {
              nodeStates[node] = {
                ...prev,
                status: 'running',
                iteration: typeof data.iteration === 'number' ? data.iteration : prev.iteration,
              }
            } else if (type === 'node_completed') {
              nodeStates[node] = {
                ...prev,
                // A prior `degraded` event for this node wins over the generic "completed"
                // status the graph wrapper always sends on node exit.
                status: prev.status === 'degraded' ? 'degraded' : 'completed',
                latencyMs: typeof data.latency_ms === 'number' ? data.latency_ms : prev.latencyMs,
              }
            } else if (type === 'degraded') {
              nodeStates[node] = { ...prev, status: 'degraded' }
            }
          }

          // reflection_iteration doesn't carry a `node` field — target it explicitly.
          if (type === 'reflection_iteration' && typeof data.iteration === 'number') {
            const prev = nodeStates['reflection'] ?? { status: 'pending' as const }
            nodeStates['reflection'] = { ...prev, iteration: data.iteration }
          }

          return {
            nodeStates,
            debugEvents: [...s.debugEvents, event].slice(-DEBUG_EVENTS_CAP),
          }
        })
      },

      markRunningNodesFailed: () => {
        set((s) => {
          const nodeStates = { ...s.nodeStates }
          for (const [name, node] of Object.entries(nodeStates)) {
            if (node.status === 'running') {
              nodeStates[name] = { ...node, status: 'failed' }
            }
          }
          return { nodeStates }
        })
      },

      resetDebugState: () =>
        set({ nodeStates: initialNodeStates(), debugEvents: [], isAutoScroll: true }),

      setTimelineFilter: (filter) => set({ timelineFilter: filter }),

      setAutoScroll: (auto) => set({ isAutoScroll: auto }),
    }),
    {
      name: 'wenjin-store',
      // Don't persist streaming state or chat messages — load from API on mount
      partialize: (state) => ({
        profileId: state.profileId,
        currentTab: state.currentTab,
      }),
    }
  )
)
