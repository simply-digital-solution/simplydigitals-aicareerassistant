import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import TargetRolesSection from '../TargetRolesSection'
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
  remote_preference: null,
  employment_type: null,
  salary_floor: null,
  salary_currency: null,
  excluded_companies: null,
  role_fit_json: null,
  seniority_level: null,
  target_industries: JSON.stringify(['Banking & Finance']),
  target_titles: JSON.stringify(['Product Manager', 'Business Analyst']),
  education: null,
  certifications: null,
  phone_number: null,
}

describe('TargetRolesSection', () => {
  let onSaved: () => void

  beforeEach(() => {
    onSaved = vi.fn() as () => void
  })

  it('renders target titles and industries from profile data', () => {
    render(<TargetRolesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Target Roles'))
    expect(screen.getByText('Product Manager')).toBeInTheDocument()
    expect(screen.getByText('Business Analyst')).toBeInTheDocument()
    expect(screen.getByText('Banking & Finance')).toBeInTheDocument()
  })

  it('Save button is disabled when no changes', () => {
    render(<TargetRolesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Target Roles'))
    expect(screen.getByRole('button', { name: /save target roles/i })).toBeDisabled()
  })

  it('adding a title activates Save button', async () => {
    render(<TargetRolesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Target Roles'))
    const inputs = screen.getAllByRole('textbox')
    await userEvent.type(inputs[0], 'Data Analyst{Enter}')
    expect(screen.getByRole('button', { name: /save target roles/i })).not.toBeDisabled()
  })

  it('removing a title activates Save button', () => {
    render(<TargetRolesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Target Roles'))
    fireEvent.click(screen.getAllByText('×')[0])
    expect(screen.getByRole('button', { name: /save target roles/i })).not.toBeDisabled()
  })

  it('Save calls PATCH with updated target_titles and target_industries', async () => {
    const api = await import('../../../api/client')
    render(<TargetRolesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Target Roles'))
    fireEvent.click(screen.getAllByText('×')[0])
    fireEvent.click(screen.getByRole('button', { name: /save target roles/i }))
    await waitFor(() => {
      expect(api.default.patch).toHaveBeenCalledWith('/profile', expect.objectContaining({
        target_titles: expect.any(String),
        target_industries: expect.any(String),
      }))
    })
  })
})
