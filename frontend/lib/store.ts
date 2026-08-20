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

// ── Intake chat slice ────────────────────────────────────────────────────────
//
// 每个建档前聊天（IntakeAgent）会话的消息/流式状态按 conversation_id 存成一个
// map，而不是像报告问答那样只有"当前一个"——侧栏支持多个会话，且用户可能在
// 一轮回复还没结束时切换到另一个会话。这个 map 存在 store 里而不是
// IntakeChat 组件的本地 state，是为了修复两个真实 bug（2026-07-27）：
// 1. 侧栏 A→B→A 切换时，`app/page.tsx` 会用 `conversationKey` 强制重新挂载
//    IntakeChat——本地 state 之前会随组件销毁而丢失，现在状态活在 store 里，
//    重新挂载后新实例读到的还是同一份数据。
// 2. 请求本身的中断时机也要跟着解绑：正在流式生成时如果组件卸载就 abort()
//    请求，这一轮永远等不到 done、后端也就没有机会落库。abort 函数存在这个
//    文件的模块级 `intakeAbortByKey`（不放进 Zustand state，因为它不需要
//    触发任何渲染），不再挂在组件的 unmount cleanup 上——组件卸载后请求继续
//    在后台跑到 done，正常走后端持久化，重新挂载的组件从 store 里看到最终结果。
//
// 还没被后端分配真实 conversation_id 的"全新会话"用 INTAKE_DRAFT_KEY 占位；
// 拿到真实 id 后用 intakeRenameConversationKey 把这个 slot 平移过去。

export const INTAKE_DRAFT_KEY = '__draft__'

export interface IntakeConversationState {
  messages: ChatMessage[]
  streamingContent: string
  thinkingContent: string
  reasoningDisplayEnabled: boolean
  isStreaming: boolean
  dailyLimitReached: boolean
  dailyLimitMessage: string | null
  /** true 只在命中匿名每日 4 次上限（`code: "login_required"`）时——决定要不要在
   *  限流提示条里额外展示"去登录"按钮，而不是普通的"明日再来"文案。 */
  loginRequired: boolean
  lastFailedMessage: string | null
  /** 是否已经问过一次后端历史（哪怕结果是空历史）——避免每次重新挂载都重新拉取 */
  historyLoaded: boolean
}

export const EMPTY_INTAKE_CONVERSATION_STATE: IntakeConversationState = Object.freeze({
  messages: [],
  streamingContent: '',
  thinkingContent: '',
  reasoningDisplayEnabled: false,
  isStreaming: false,
  dailyLimitReached: false,
  dailyLimitMessage: null,
  loginRequired: false,
  lastFailedMessage: null,
  historyLoaded: false,
})

/** 正在进行的请求的 abort() 函数，按 conversation key 存——模块级、非 Zustand
 *  state，只有组件真的需要主动打断请求时才用得到（目前没有这类场景），
 *  不再绑定组件 unmount。*/
const intakeAbortByKey = new Map<string, () => void>()
export function setIntakeAbort(key: string, abort: (() => void) | null) {
  if (abort) intakeAbortByKey.set(key, abort)
  else intakeAbortByKey.delete(key)
}
export function getIntakeAbort(key: string): (() => void) | null {
  return intakeAbortByKey.get(key) ?? null
}

interface IntakeSlice {
  intakeConversations: Record<string, IntakeConversationState>
  setIntakeHistoryLoaded: (key: string, messages: ChatMessage[]) => void
  intakeAppendUserMessage: (key: string, content: string) => void
  intakeAppendStreamToken: (key: string, token: string) => void
  intakeAppendThinkingToken: (key: string, token: string) => void
  intakeSetReasoningDisplayEnabled: (key: string, enabled: boolean) => void
  intakeCommitStreamingMessage: (key: string) => void
  intakeSetStreaming: (key: string, streaming: boolean) => void
  intakeSetDailyLimit: (key: string, reached: boolean, message?: string, loginRequired?: boolean) => void
  intakeSetLastFailedMessage: (key: string, message: string | null) => void
  /** 草稿会话拿到后端真实 id 后，把它的 state 平移到新 key 下 */
  intakeRenameConversationKey: (oldKey: string, newKey: string) => void
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

// ── UI slice ─────────────────────────────────────────────────────────────────
//
// loginModalOpen 提到 store 里（而不是 app/page.tsx 的本地 state），是因为触发
// 登录弹层的入口不止 SidebarNav 一处——命中匿名每日 4 次上限时 IntakeChat 里的
// "去登录" 按钮也要能直接打开它，不想为此一路多加 prop 透传。

interface UiSlice {
  loginModalOpen: boolean
  setLoginModalOpen: (open: boolean) => void
}

// ── App store ─────────────────────────────────────────────────────────────────

interface AppStore extends ChatSlice, DebugSlice, AuthSlice, IntakeSlice, UiSlice {
  profileId: string | null
  setProfileId: (id: string) => void
  currentTab: PlanType
  setCurrentTab: (tab: PlanType) => void

  /** 当前建档前聊天（IntakeAgent）会话 id；null = 全新对话（未发过消息）。持久化——
   *  刷新页面后应该回到刷新前正在看的会话，而不是变成看不出是哪条历史（见
   *  上面 IntakeSlice 的说明）；"新建对话"会显式把它设回 null。 */
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

      // ── intake chat slice ──
      intakeConversations: {},

      setIntakeHistoryLoaded: (key, messages) =>
        set((s) => ({
          intakeConversations: {
            ...s.intakeConversations,
            [key]: {
              ...(s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE),
              messages,
              historyLoaded: true,
            },
          },
        })),

      intakeAppendUserMessage: (key, content) => {
        const msg: ChatMessage = {
          id: uuidv4(),
          role: 'user',
          content,
          citations: [],
          created_at: new Date().toISOString(),
        }
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: {
                ...prev,
                messages: [...prev.messages, msg],
                isStreaming: true,
                streamingContent: '',
                thinkingContent: '',
                historyLoaded: true,
              },
            },
          }
        })
      },

      intakeAppendStreamToken: (key, token) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: { ...prev, streamingContent: prev.streamingContent + token },
            },
          }
        }),

      intakeAppendThinkingToken: (key, token) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          if (!prev.reasoningDisplayEnabled) return {}
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: { ...prev, thinkingContent: prev.thinkingContent + token },
            },
          }
        }),

      intakeSetReasoningDisplayEnabled: (key, enabled) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: {
                ...prev,
                reasoningDisplayEnabled: enabled,
                thinkingContent: enabled ? prev.thinkingContent : '',
              },
            },
          }
        }),

      intakeCommitStreamingMessage: (key) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          if (!prev.streamingContent) {
            return {
              intakeConversations: {
                ...s.intakeConversations,
                [key]: { ...prev, isStreaming: false },
              },
            }
          }
          const msg: ChatMessage = {
            id: uuidv4(),
            role: 'assistant',
            content: prev.streamingContent,
            thinking: prev.reasoningDisplayEnabled ? prev.thinkingContent || undefined : undefined,
            citations: [],
            created_at: new Date().toISOString(),
          }
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: {
                ...prev,
                messages: [...prev.messages, msg],
                streamingContent: '',
                thinkingContent: '',
                isStreaming: false,
              },
            },
          }
        }),

      intakeSetStreaming: (key, streaming) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return { intakeConversations: { ...s.intakeConversations, [key]: { ...prev, isStreaming: streaming } } }
        }),

      intakeSetDailyLimit: (key, reached, message, loginRequired) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return {
            intakeConversations: {
              ...s.intakeConversations,
              [key]: {
                ...prev,
                dailyLimitReached: reached,
                dailyLimitMessage: reached ? message ?? null : null,
                loginRequired: reached ? !!loginRequired : false,
              },
            },
          }
        }),

      intakeSetLastFailedMessage: (key, message) =>
        set((s) => {
          const prev = s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE
          return { intakeConversations: { ...s.intakeConversations, [key]: { ...prev, lastFailedMessage: message } } }
        }),

      intakeRenameConversationKey: (oldKey, newKey) =>
        set((s) => {
          if (oldKey === newKey || !s.intakeConversations[oldKey]) return {}
          const { [oldKey]: moved, ...rest } = s.intakeConversations
          return { intakeConversations: { ...rest, [newKey]: moved } }
        }),

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

      // ── ui slice ──
      loginModalOpen: false,
      setLoginModalOpen: (open) => set({ loginModalOpen: open }),

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
      // Don't persist streaming state or chat messages — load from API on mount.
      // currentIntakeConversationId IS persisted so a browser refresh reopens the
      // same conversation instead of losing track of it (see bug报告 2026-07-27):
      // the messages themselves are safely in Postgres/Redis already — the only
      // thing a refresh used to lose was "which conversation was I even looking at".
      partialize: (state) => ({
        profileId: state.profileId,
        currentTab: state.currentTab,
        currentIntakeConversationId: state.currentIntakeConversationId,
      }),
    }
  )
)
