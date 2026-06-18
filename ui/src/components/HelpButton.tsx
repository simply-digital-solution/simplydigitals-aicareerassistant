import { useEffect, useRef, useState } from 'react'

const SUPPORT_EMAIL = 'pandiri.vasu@gmail.com'
const WHATSAPP_NUMBER = '6590673055'

function ContactModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ name: '', email: '', message: '' })

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault()
    const subject = encodeURIComponent('AI Career Assistant Support')
    const body = encodeURIComponent(
      `Name: ${form.name}\nEmail: ${form.email}\n\n${form.message}`
    )
    window.location.href = `mailto:${SUPPORT_EMAIL}?subject=${subject}&body=${body}`
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-end sm:items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Send us a message</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSend} className="space-y-3">
          <input
            required
            type="text"
            placeholder="Your name"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <input
            required
            type="email"
            placeholder="Your email"
            value={form.email}
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <textarea
            required
            placeholder="Describe your issue…"
            value={form.message}
            onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
            rows={4}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
          <button
            type="submit"
            className="w-full bg-indigo-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            Send via Email
          </button>
        </form>
      </div>
    </div>
  )
}

export default function HelpButton() {
  const [open, setOpen] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  // Close panel when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <>
      {showForm && (
        <ContactModal onClose={() => setShowForm(false)} />
      )}

      <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2" ref={panelRef}>

        {/* Contact options panel */}
        {open && (
          <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-4 w-56 mb-1 animate-fade-in">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Contact Support
            </p>

            <div className="space-y-2">
              {/* Email */}
              <a
                href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('AI Career Assistant Support')}`}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-gray-50 transition-colors group"
                onClick={() => setOpen(false)}
              >
                <span className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800">Email us</p>
                  <p className="text-xs text-gray-400 truncate">{SUPPORT_EMAIL}</p>
                </div>
              </a>

              {/* Contact form */}
              <button
                onClick={() => { setShowForm(true); setOpen(false) }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-gray-50 transition-colors text-left"
              >
                <span className="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-800">Contact form</p>
                  <p className="text-xs text-gray-400">Fill in details</p>
                </div>
              </button>

              {/* WhatsApp */}
              <a
                href={`https://wa.me/${WHATSAPP_NUMBER}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-gray-50 transition-colors"
                onClick={() => setOpen(false)}
              >
                <span className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-green-600" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                    <path d="M12 0C5.373 0 0 5.373 0 12c0 2.125.557 4.118 1.529 5.845L.057 23.571a.5.5 0 00.608.67l5.896-1.539A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.907 0-3.693-.528-5.218-1.443l-.374-.223-3.875 1.011 1.026-3.762-.244-.386A9.96 9.96 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
                  </svg>
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-800">WhatsApp</p>
                  <p className="text-xs text-gray-400">+65 9067 3055</p>
                </div>
              </a>
            </div>
          </div>
        )}

        {/* Floating help button */}
        <button
          onClick={() => setOpen(v => !v)}
          className={`w-12 h-12 rounded-full shadow-lg flex items-center justify-center transition-all ${
            open
              ? 'bg-gray-700 text-white rotate-45'
              : 'bg-indigo-600 text-white hover:bg-indigo-700 hover:shadow-xl'
          }`}
          aria-label="Help and support"
        >
          {open ? (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          )}
        </button>
      </div>
    </>
  )
}
