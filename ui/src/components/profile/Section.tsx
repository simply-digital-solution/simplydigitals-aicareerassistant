import { useState } from 'react'

export default function Section({
  title,
  subtitle,
  badge,
  defaultOpen = false,
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
      <div className="flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors">
        <button
          type="button"
          onClick={() => setOpen(v => !v)}
          className="flex items-center gap-3 min-w-0 flex-1 text-left"
        >
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900">{title}</span>
              {badge}
            </div>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
        </button>
        <div className="flex items-center gap-2 shrink-0 ml-3">
          {actions}
          <button
            type="button"
            onClick={() => setOpen(v => !v)}
            className="text-gray-400 text-xs pl-2 cursor-pointer"
          >
            {open ? '▲' : '▼'}
          </button>
        </div>
      </div>
      {open && <div className="px-5 pb-5 space-y-4 border-t border-gray-100">{children}</div>}
    </div>
  )
}
