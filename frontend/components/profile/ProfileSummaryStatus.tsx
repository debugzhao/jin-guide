interface ProfileSummaryStatusProps {
  hasPreferences: boolean
  reportVersion: 'basic' | 'preference_updated'
}

/**
 * 「档案摘要」状态卡片 —— summary-row 表格状展示基础信息/偏好/报告状态
 * （docs/wenjin-agent-prototype.html 第 1119-1125 行）。
 */
export default function ProfileSummaryStatus({ hasPreferences, reportVersion }: ProfileSummaryStatusProps) {
  return (
    <div className="wj-glass-card rounded-2xl rounded-tl-sm px-4 py-3 max-w-[96%]">
      <div className="text-xs text-[#9CA3C4] mb-1">档案摘要</div>
      <div className="flex justify-between gap-2.5 text-xs text-[#9CA3C4] py-2 border-b border-dashed border-white/10">
        <span>基础建档信息</span>
        <strong className="text-[#8FE0B7] font-medium">完整，可渲染</strong>
      </div>
      <div className="flex justify-between gap-2.5 text-xs text-[#9CA3C4] py-2 border-b border-dashed border-white/10">
        <span>城市/专业/学费偏好</span>
        <strong className="text-[#F1F5F9] font-medium">{hasPreferences ? '已补充' : '等待用户自然输入'}</strong>
      </div>
      <div className="flex justify-between gap-2.5 text-xs text-[#9CA3C4] py-2">
        <span>右侧报告状态</span>
        <strong className="text-[#F1F5F9] font-medium">{reportVersion === 'basic' ? '基础版' : '偏好更新版'}</strong>
      </div>
      <p className="text-xs text-[#6B7280] mt-2">
        基础信息确认后，右侧会立即出现志愿报告；之后补充城市、专业、学费偏好，我会更新同一份报告。
      </p>
    </div>
  )
}
