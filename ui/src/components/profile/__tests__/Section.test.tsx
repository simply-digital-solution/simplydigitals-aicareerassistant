import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Section from '../Section'

describe('Section', () => {
  it('renders title and children when open', () => {
    render(<Section title="Resume" defaultOpen={true}><p>Content here</p></Section>)
    expect(screen.getByText('Resume')).toBeInTheDocument()
    expect(screen.getByText('Content here')).toBeInTheDocument()
  })

  it('starts open when defaultOpen=true', () => {
    render(<Section title="Resume" defaultOpen={true}><p>Content</p></Section>)
    expect(screen.getByText('Content')).toBeInTheDocument()
  })

  it('starts closed when defaultOpen=false', () => {
    render(<Section title="Resume" defaultOpen={false}><p>Content</p></Section>)
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
  })

  it('toggles open when header button is clicked', () => {
    render(<Section title="Resume" defaultOpen={false}><p>Content</p></Section>)
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Content')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
  })

  it('action button clicks do not toggle the section', () => {
    const action = <button type="button" data-testid="action">Action</button>
    render(<Section title="Resume" defaultOpen={true} actions={action}><p>Content</p></Section>)
    expect(screen.getByText('Content')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('action'))
    expect(screen.getByText('Content')).toBeInTheDocument()
  })
})
