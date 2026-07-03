import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatMessage, DebugEvent, DebugNodeState, DebugRunFilter, PlanType } from '@/types'

const uuidv4 = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)

interface AssessFormData {
  province?: string
  batch?: string
  score?: number
  rank?: number
  subjects?: string[]
  gender?: string
  hasPhysicalLimits?: boolean
}

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
  isChatPanelOpen: boolean
  activeReportId: string | null
  messages: ChatMessage[]
  streamingContent: string
  isStreaming: boolean
  dailyLimitReached: boolean
  dailyLimitMessage: string | null
  /** Last failed user message, kept around so the "重试" button can resend it */
  lastFailedMessage: string | null

  openChatPanel: (reportId: string) => void
  closeChatPanel: () => void
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
  /** Controls the homepage-triggered debug drawer — open to any visitor, no role check. */
  isDebugDrawerOpen: boolean
  selectedRunId: string | null
  isLiveFollowing: boolean
  debugRunFilter: DebugRunFilter
  nodeStates: Record<string, DebugNodeState>
  debugEvents: DebugEvent[]
  timelineFilter: 'all' | 'node' | 'tool' | 'error'
  isAutoScroll: boolean

  openDebugDrawer: () => void
  closeDebugDrawer: () => void
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
  wizardStep: number
  setWizardStep: (step: number) => void
  assessFormData: AssessFormData
  setAssessFormData: (data: AssessFormData) => void
}

export const useAppStore = create<AppStore>()(
  persist(
    (set, get) => ({
      // ── base store ──
      profileId: null,
      setProfileId: (id) => set({ profileId: id }),
      currentTab: 'balanced',
      setCurrentTab: (tab) => set({ currentTab: tab }),
      wizardStep: 1,
      setWizardStep: (step) => set({ wizardStep: step }),
      assessFormData: {},
      setAssessFormData: (data) => set({ assessFormData: data }),

      // ── chat slice ──
      isChatPanelOpen: false,
      activeReportId: null,
      messages: [],
      streamingContent: '',
      isStreaming: false,
      dailyLimitReached: false,
      dailyLimitMessage: null,
      lastFailedMessage: null,

      openChatPanel: (reportId) => {
        const { activeReportId } = get()
        // Reset messages when switching reports
        if (activeReportId !== reportId) {
          set({ messages: [], streamingContent: '', activeReportId: reportId })
        }
        set({ isChatPanelOpen: true })
      },

      closeChatPanel: () => set({ isChatPanelOpen: false }),

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
      isDebugDrawerOpen: false,
      selectedRunId: null,
      isLiveFollowing: true,
      debugRunFilter: {},
      nodeStates: initialNodeStates(),
      debugEvents: [],
      timelineFilter: 'all',
      isAutoScroll: true,

      openDebugDrawer: () => set({ isDebugDrawerOpen: true }),
      closeDebugDrawer: () => set({ isDebugDrawerOpen: false }),

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
        wizardStep: state.wizardStep,
        assessFormData: state.assessFormData,
      }),
    }
  )
)
