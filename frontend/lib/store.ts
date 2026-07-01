import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatMessage, PlanType } from '@/types'

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

// ── Chat slice ────────────────────────────────────────────────────────────────

interface ChatSlice {
  isChatPanelOpen: boolean
  activeReportId: string | null
  messages: ChatMessage[]
  streamingContent: string
  isStreaming: boolean
  dailyLimitReached: boolean

  openChatPanel: (reportId: string) => void
  closeChatPanel: () => void
  /** Initialise or replace messages (e.g. after loading history from API) */
  setChatMessages: (messages: ChatMessage[]) => void
  appendUserMessage: (content: string) => void
  /** Called on each SSE token event */
  appendStreamToken: (token: string) => void
  /** Called on SSE done — commits the streaming message */
  commitStreamingMessage: (citations?: { source_id: string; text: string }[]) => void
  setDailyLimitReached: (reached: boolean) => void
  clearChat: () => void
}

// ── App store ─────────────────────────────────────────────────────────────────

interface AppStore extends ChatSlice {
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

      setDailyLimitReached: (reached) => set({ dailyLimitReached: reached }),

      clearChat: () =>
        set({ messages: [], streamingContent: '', isStreaming: false, dailyLimitReached: false }),
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
