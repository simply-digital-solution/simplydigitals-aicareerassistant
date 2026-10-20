import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import SkillsSection from '../SkillsSection'
import type { ProfileData } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: {
    patch: vi.fn().mockResolvedValue({}),
  },
}))

const baseData: ProfileData = {
  resume_text: null,
  resume_obj: null,
  linkedin_url: null,
  full_name: null,
  target_locations: null,
  years_experience: 5,
  skills: JSON.stringify(['Python', 'SQL']),
  remote_preference: null,
  employment_type: null,
  salary_floor: null,
  salary_currency: null,
  excluded_companies: null,
  role_fit_json: null,
  seniority_level: 'Senior',
  target_industries: null,
  target_titles: null,
  education: null,
  certifications: null,
  phone_number: null,
}

describe('SkillsSection', () => {
  let onSaved: () => void

  beforeEach(() => {
    onSaved = vi.fn() as () => void
  })

  it('renders skills from profile data', () => {
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('SQL')).toBeInTheDocument()
  })

  it('Save button is disabled when no changes', () => {
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    expect(screen.getByRole('button', { name: /save skills/i })).toBeDisabled()
  })

  it('adding a skill activates Save button', async () => {
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    const input = screen.getByPlaceholderText('Type a skill and press Enter')
    await userEvent.type(input, 'React{Enter}')
    expect(screen.getByRole('button', { name: /save skills/i })).not.toBeDisabled()
  })

  it('removing a skill activates Save button', () => {
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    fireEvent.click(screen.getAllByText('×')[0])
    expect(screen.getByRole('button', { name: /save skills/i })).not.toBeDisabled()
  })

  it('Save calls PATCH with updated skills and years_experience', async () => {
    const api = await import('../../../api/client')
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    const input = screen.getByPlaceholderText('Type a skill and press Enter')
    await userEvent.type(input, 'React{Enter}')
    fireEvent.click(screen.getByRole('button', { name: /save skills/i }))
    await waitFor(() => {
      expect(api.default.patch).toHaveBeenCalledWith('/profile', expect.objectContaining({
        skills: expect.stringContaining('React'),
        years_experience: 5,
      }))
    })
  })

  it('seniority level is shown read-only', () => {
    render(<SkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Skills'))
    expect(screen.getByText('Senior')).toBeInTheDocument()
    const seniorityEl = screen.getByText('Senior')
    expect(seniorityEl.tagName).not.toBe('INPUT')
    expect(seniorityEl.tagName).not.toBe('SELECT')
  })
})
