import { useState } from 'react'

export default function TagInput({
  tags,
  onChange,
  placeholder,
  colorCls = 'bg-indigo-50 text-indigo-700',
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  colorCls?: string
}) {
  const [input, setInput] = useState('')

  const addTag = () => {
    const val = input.trim()
    const isDupe = tags.some(t => t.toLowerCase() === val.toLowerCase())
    if (val && !isDupe) onChange([...tags, val])
    setInput('')
  }

  const removeTag = (index: number) => onChange(tags.filter((_, i) => i !== index))

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag() }
    else if (e.key === 'Backspace' && !input && tags.length > 0) onChange(tags.slice(0, -1))
  }

  return (
    <div className="flex flex-wrap gap-1.5 border border-gray-300 rounded-lg px-3 py-2 min-h-[42px] focus-within:ring-2 focus-within:ring-indigo-400">
      {tags.map((tag, i) => (
        <span key={i} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${colorCls}`}>
          {tag}
          <button type="button" onClick={() => removeTag(i)} className="opacity-60 hover:opacity-100 leading-none">×</button>
        </span>
      ))}
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={addTag}
        placeholder={placeholder}
        className="flex-1 min-w-[120px] outline-none text-sm bg-transparent"
      />
    </div>
  )
}
