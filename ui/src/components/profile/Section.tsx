import { useState } from 'react'

export default function Section({
  title,
  subtitle,
  badge,
  defaultOpen = true,
  actions,
  children,
}: {
  title: string
  subtitle?: string
  badge?: React.ReactNode
  defaultOpen?: boolean
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900">{title}</span>
              {badge}
            </div>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
          {actions}
          <span className="text-gray-400 text-xs pl-2">{open ? '▲' : '▼'}</span>
        </div>
      </button>
      {open && <div className="px-5 pb-5 space-y-4 border-t border-gray-100">{children}</div>}
    </div>
  )
}
