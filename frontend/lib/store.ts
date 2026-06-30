import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PlanType } from '@/types'

interface AssessFormData {
  province?: string
  batch?: string
  score?: number
  rank?: number
  subjects?: string[]
  gender?: string
  hasPhysicalLimits?: boolean
}

interface AppStore {
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
    (set) => ({
      profileId: null,
      setProfileId: (id) => set({ profileId: id }),
      currentTab: 'balanced',
      setCurrentTab: (tab) => set({ currentTab: tab }),
      wizardStep: 1,
      setWizardStep: (step) => set({ wizardStep: step }),
      assessFormData: {},
      setAssessFormData: (data) => set({ assessFormData: data }),
    }),
    {
      name: 'wenjin-store',
    }
  )
)
