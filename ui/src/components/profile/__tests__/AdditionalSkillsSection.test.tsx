import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import AdditionalSkillsSection from '../AdditionalSkillsSection'
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
  years_experience: null,
  skills: null,
  additional_skills: JSON.stringify(['Negotiation', 'Public Speaking']),
  remote_preference: null,
  employment_type: null,
  salary_floor: null,
  salary_currency: null,
  excluded_companies: null,
  role_fit_json: null,
  seniority_level: null,
  target_industries: null,
  target_titles: null,
  education: null,
  certifications: null,
  phone_number: null,
}

describe('AdditionalSkillsSection', () => {
  let onSaved: () => void

  beforeEach(() => {
    onSaved = vi.fn() as () => void
  })

  it('renders additional skills from profile data', () => {
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    expect(screen.getByText('Negotiation')).toBeInTheDocument()
    expect(screen.getByText('Public Speaking')).toBeInTheDocument()
  })

  it('Save button is disabled when no changes', () => {
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    expect(screen.getByRole('button', { name: /save additional skills/i })).toBeDisabled()
  })

  it('adding a skill activates Save button', async () => {
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    const input = screen.getByPlaceholderText('Type a skill and press Enter')
    await userEvent.type(input, 'Mentoring{Enter}')
    expect(screen.getByRole('button', { name: /save additional skills/i })).not.toBeDisabled()
  })

  it('removing a skill activates Save button', () => {
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    fireEvent.click(screen.getAllByText('×')[0])
    expect(screen.getByRole('button', { name: /save additional skills/i })).not.toBeDisabled()
  })

  it('Save calls PATCH with updated additional_skills only', async () => {
    const api = await import('../../../api/client')
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    const input = screen.getByPlaceholderText('Type a skill and press Enter')
    await userEvent.type(input, 'Mentoring{Enter}')
    fireEvent.click(screen.getByRole('button', { name: /save additional skills/i }))
    await waitFor(() => {
      expect(api.default.patch).toHaveBeenCalledWith('/profile', {
        additional_skills: expect.stringContaining('Mentoring'),
      })
    })
  })

  it('calls onSaved after a successful save', async () => {
    render(<AdditionalSkillsSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Additional Skills'))
    const input = screen.getByPlaceholderText('Type a skill and press Enter')
    await userEvent.type(input, 'Mentoring{Enter}')
    fireEvent.click(screen.getByRole('button', { name: /save additional skills/i }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })
})
