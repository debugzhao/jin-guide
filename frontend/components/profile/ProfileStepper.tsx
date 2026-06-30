'use client'

import { cn } from '@/lib/utils'
import { Check } from 'lucide-react'

interface Step {
  label: string
  required?: boolean
}

interface ProfileStepperProps {
  steps: Step[]
  currentStep: number
}

export default function ProfileStepper({ steps, currentStep }: ProfileStepperProps) {
  const progress = ((currentStep - 1) / (steps.length - 1)) * 100

  return (
    <div className="bg-white border-b border-[#E2E8F0] px-4 py-3">
      {/* Progress bar */}
      <div className="relative h-1.5 bg-[#E2E8F0] rounded-full mb-3">
        <div
          className="absolute left-0 top-0 h-full bg-[#0D9488] rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
      {/* Step info */}
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs text-[#64748B]">
            步骤 {currentStep}/{steps.length}
          </span>
          <h2 className="text-sm font-semibold text-[#0F172A] mt-0.5">
            {steps[currentStep - 1]?.label}
          </h2>
        </div>
        {steps[currentStep - 1]?.required !== false && (
          <span className="text-xs text-[#1E40AF] bg-[#EFF6FF] px-2 py-0.5 rounded-tag">
            {steps[currentStep - 1]?.required ? '必填' : '建议填写'}
          </span>
        )}
      </div>
      {/* Step dots */}
      <div className="flex items-center gap-1 mt-2">
        {steps.map((_, idx) => {
          const stepNum = idx + 1
          const isCompleted = stepNum < currentStep
          const isCurrent = stepNum === currentStep
          return (
            <div
              key={idx}
              className={cn(
                'flex items-center justify-center rounded-full transition-all',
                isCompleted && 'w-4 h-4 bg-[#0D9488]',
                isCurrent && 'w-4 h-4 bg-[#1E40AF]',
                !isCompleted && !isCurrent && 'w-3 h-3 bg-[#E2E8F0]'
              )}
            >
              {isCompleted && <Check className="w-2.5 h-2.5 text-white" />}
              {isCurrent && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
