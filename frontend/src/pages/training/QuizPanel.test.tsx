import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PlayerLesson } from '@/lib/training'
import { ToastProvider } from '@/lib/toast'
import { QuizPanel } from '@/pages/training/QuizPanel'

const mocks = vi.hoisted(() => ({ api: vi.fn(), reload: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/useApi', () => ({
  useApi: () => ({ reload: mocks.reload, data: {
    pass_mark: 80, attempts: 0, best: null, passed: false,
    questions: [{ id: 1, text: 'Safe fridge temperature?', options: ['Below 5 C', '10 C'] }, { id: 2, text: 'Raw chicken goes...', options: ['Above', 'Below'] }],
  } }),
}))

const lesson: PlayerLesson = { id: 9, title: 'Check yourself', kind: 'quiz', body: null, external_url: null, media: null, completed: false, position_seconds: 0, questions: 2 }

describe('QuizPanel', () => {
  beforeEach(() => {
    mocks.api.mockReset()
    mocks.reload.mockReset()
  })

  it('needs every question answered before it can be submitted, and sends the answers in order', async () => {
    mocks.api.mockResolvedValue({ score: 100, passed: true, correct: 2, total: 2, results: [true, true], course_completed: true })
    const changed = vi.fn()
    render(<ToastProvider><QuizPanel assignmentId={3} lesson={lesson} onChanged={changed} /></ToastProvider>)
    const submit = screen.getByRole('button', { name: 'Submit answers' }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('Below 5 C'))
    expect(submit.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('Below'))
    expect(submit.disabled).toBe(false)
    fireEvent.click(submit)
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/training/my/3/lessons/9/quiz', { body: { answers: [0, 1] } }))
    expect(await screen.findByText(/You passed: 100%/)).toBeTruthy()
    expect(screen.getByText(/That finishes the course/)).toBeTruthy()
    expect(changed).toHaveBeenCalled()
  })

  it('marks wrong answers without revealing the right ones, and offers another go', async () => {
    mocks.api.mockResolvedValue({ score: 50, passed: false, correct: 1, total: 2, results: [true, false], course_completed: false })
    render(<ToastProvider><QuizPanel assignmentId={3} lesson={lesson} onChanged={vi.fn()} /></ToastProvider>)
    fireEvent.click(screen.getByLabelText('Below 5 C'))
    fireEvent.click(screen.getByLabelText('Above'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit answers' }))
    expect(await screen.findByText(/Not passed yet: 50%/)).toBeTruthy()
    expect(screen.getByLabelText('Right')).toBeTruthy()
    expect(screen.getByLabelText('Wrong')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
    expect((screen.getByRole('button', { name: 'Submit answers' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Below 5 C') as HTMLInputElement).checked).toBe(false)
  })
})
