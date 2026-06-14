import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect } from 'vitest'
import TagInput from '../TagInput'

describe('TagInput', () => {
  it('renders existing tags', () => {
    render(<TagInput tags={['React', 'TypeScript']} onChange={() => {}} />)
    expect(screen.getByText('React')).toBeInTheDocument()
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
  })

  it('adds a tag on Enter key', async () => {
    const onChange = vi.fn()
    render(<TagInput tags={[]} onChange={onChange} placeholder="Add skill" />)
    const input = screen.getByPlaceholderText('Add skill')
    await userEvent.type(input, 'Python{Enter}')
    expect(onChange).toHaveBeenCalledWith(['Python'])
  })

  it('adds a tag on comma key', async () => {
    const onChange = vi.fn()
    render(<TagInput tags={[]} onChange={onChange} placeholder="Add skill" />)
    const input = screen.getByPlaceholderText('Add skill')
    await userEvent.type(input, 'Python,')
    expect(onChange).toHaveBeenCalledWith(['Python'])
  })

  it('does not add duplicate tags (case-insensitive)', async () => {
    const onChange = vi.fn()
    render(<TagInput tags={['Python']} onChange={onChange} placeholder="Add skill" />)
    const input = screen.getByPlaceholderText('Add skill')
    await userEvent.type(input, 'python{Enter}')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('removes a tag when × is clicked', () => {
    const onChange = vi.fn()
    render(<TagInput tags={['React', 'TypeScript']} onChange={onChange} />)
    const removeButtons = screen.getAllByText('×')
    fireEvent.click(removeButtons[0])
    expect(onChange).toHaveBeenCalledWith(['TypeScript'])
  })

  it('calls onChange with updated array on every change', async () => {
    const onChange = vi.fn()
    render(<TagInput tags={['React']} onChange={onChange} placeholder="Add skill" />)
    const input = screen.getByPlaceholderText('Add skill')
    await userEvent.type(input, 'Vue{Enter}')
    expect(onChange).toHaveBeenCalledWith(['React', 'Vue'])
  })
})
