import type { PreferenceEntry } from './PreferenceComposer'

interface Props {
  entry: PreferenceEntry
}

/**
 * 「推荐偏好」卡片 —— 识别到城市/专业/学费类自由文本后展示
 * （docs/wenjin-agent-prototype.html preferenceFormHtml()，第 1579-1619 行）。
 * 未命中偏好意图时展示普通确认文案（同文件 sendConversation() 的 else 分支）。
 */
export default function PreferenceCard({ entry }: Props) {
  if (!entry.matched) {
    return (
      <div className="wj-glass-card rounded-2xl rounded-tl-sm px-4 py-3 max-w-[96%] space-y-1">
        <div className="text-xs text-[#9CA3C4]">问津助手</div>
        <p className="text-sm text-[#F1F5F9]">
          我会继续按当前基础档案维护右侧报告。你也可以补充城市、专业或学费偏好，我会渲染偏好卡并更新右侧报告。
        </p>
      </div>
    )
  }

  return (
    <div className="wj-glass-card rounded-2xl rounded-tl-sm px-4 py-3 max-w-[96%] space-y-3">
      <div className="text-xs text-[#9CA3C4]">问津助手</div>
      <p className="text-sm text-[#F1F5F9]">
        我识别到你在补充城市、专业或学费偏好。下面这张偏好卡不会改变基础建档，只会让推荐报告更精细。
      </p>
      <div className="bg-white/[0.03] border border-white/10 rounded-lg p-3.5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm text-[#F1F5F9]">推荐偏好</strong>
          <span className="text-xs px-2 py-0.5 rounded-tag bg-[rgba(167,139,250,0.14)] text-[#A78BFA] border border-[rgba(167,139,250,0.35)]">
            按需生成
          </span>
        </div>
        <p className="text-xs text-[#9CA3C4]">来自你的输入：{entry.text}</p>
      </div>
      <p className="text-xs text-[#6B7280]">
        偏好卡重新生成方案需要经过确认后调用局部重新生成（即将支持，敬请期待）。
      </p>
    </div>
  )
}
