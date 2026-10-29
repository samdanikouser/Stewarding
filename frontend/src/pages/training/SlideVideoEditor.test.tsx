import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdminLesson } from '@/lib/training'
import { ToastProvider } from '@/lib/toast'
import { SlideVideoEditor } from '@/pages/training/SlideVideoEditor'

const mocks = vi.hoisted(() => ({ api: vi.fn(), typed: false, status: null as string | null, slides: [] as unknown[] }))
vi.mock('@/lib/api', () => ({ api: mocks.api, tokenStore: { get: () => 'token' } }))
vi.mock('@/lib/useApi', () => ({
  useApi: (path: string) => {
    if (path === '/training/voice') return { data: { typed: mocks.typed }, reload: vi.fn() }
    const lesson: AdminLesson = {
      id: 7, position: 0, title: 'Fridge temperatures', kind: 'video', body: null, external_url: null, media: null, questions: [],
      slides: mocks.slides as AdminLesson['slides'], video: { status: mocks.status as AdminLesson['video']['status'], error: null },
    }
    return { data: { id: 1, title: 'Cold Storage Safety', lesson_list: [lesson] }, reload: vi.fn() }
  },
}))

const open = () => render(<ToastProvider><SlideVideoEditor courseId={1} lessonId={7} onClose={vi.fn()} onChanged={vi.fn()} /></ToastProvider>)

describe('SlideVideoEditor', () => {
  beforeEach(() => {
    mocks.api.mockReset()
    mocks.typed = false
    mocks.status = null
    mocks.slides = []
  })

  it('starts with one slide named after the lesson, and says when typed voice-over is not available', () => {
    open()
    expect((screen.getByLabelText('Slide title') as HTMLInputElement).value).toBe('Fridge temperatures')
    expect((screen.getByLabelText(/Type what is said/) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText(/Not set up on this server yet/)).toBeTruthy()
    expect((screen.getByLabelText(/Upload a recording/) as HTMLInputElement).disabled).toBe(false)
  })

  it('offers typed voice-over once the server has a voice', () => {
    mocks.typed = true
    open()
    expect((screen.getByLabelText(/Type what is said/) as HTMLInputElement).disabled).toBe(false)
    expect(screen.queryByText(/Not set up on this server yet/)).toBeNull()
  })

  it('saves the slides with the points split one per line, then makes the video', async () => {
    mocks.api.mockResolvedValue({ slides: [{ id: 'abc123abc123', title: 'Fridge temperatures', bullets: ['Below 5', 'Log it'], narration: null, voice: 'none', seconds: 6, image: null, audio: null }] })
    open()
    fireEvent.change(screen.getByLabelText('Points (one per line)'), { target: { value: 'Below 5\n\n  Log it  ' } })
    fireEvent.click(screen.getByRole('button', { name: /Make the video/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Make it without sound/ }))   // no voice-over was chosen, so it asks first
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/training/lessons/7/render', { method: 'POST' }))
    expect(mocks.api).toHaveBeenNthCalledWith(1, '/training/lessons/7/slides', {
      method: 'PUT', body: { slides: [{ id: null, title: 'Fridge temperatures', bullets: ['Below 5', 'Log it'], narration: null, voice: 'none', seconds: 6 }] },
    })
  })

  it('adds slides and can choose a recording for one of them', () => {
    open()
    fireEvent.click(screen.getByRole('button', { name: /Add slide/ }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect((screen.getByLabelText('Slide title') as HTMLInputElement).value).toBe('')
    fireEvent.click(screen.getByLabelText(/Upload a recording/))
    expect(screen.getByRole('button', { name: /Choose a recording/ })).toBeTruthy()
  })

  it('shows that the video is being made and holds the form still until it is done', () => {
    mocks.status = 'rendering'
    mocks.slides = [{ id: 'abc123abc123', title: 'One', bullets: [], narration: null, voice: 'none', seconds: 6, image: null, audio: null }]
    open()
    expect(screen.getByText(/Being made/)).toBeTruthy()
    expect((screen.getByRole('button', { name: /Make the video/ }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Slide title') as HTMLInputElement).closest('fieldset')?.disabled).toBe(true)
  })
})

describe('SlideVideoEditor sound', () => {
  beforeEach(() => {
    mocks.api.mockReset()
    mocks.typed = false
    mocks.status = null
    mocks.slides = []
  })

  it('says how many slides have a voice-over', () => {
    mocks.slides = [
      { id: 'aaaaaaaaaaaa', title: 'One', bullets: [], narration: null, voice: 'none', seconds: 6, image: null, audio: null },
      { id: 'bbbbbbbbbbbb', title: 'Two', bullets: [], narration: null, voice: 'upload', seconds: 6, image: null, audio: 'voice.wav' },
    ]
    open()
    expect(screen.getByText(/Voice-over on 1 of 2 slides/)).toBeTruthy()
  })

  it('asks before making a video that would have no sound, and does nothing if the answer is no', async () => {
    mocks.slides = [{ id: 'aaaaaaaaaaaa', title: 'One', bullets: [], narration: null, voice: 'none', seconds: 6, image: null, audio: null }]
    open()
    expect(screen.getByText(/No slide has a voice-over yet/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Make the video/ }))
    expect(await screen.findByText(/the video will be silent/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(mocks.api).not.toHaveBeenCalled()
  })
})

describe('SlideVideoEditor long points', () => {
  it('cuts a point over 160 characters into shorter ones instead of sending one the server refuses', async () => {
    mocks.api.mockReset()
    mocks.slides = []
    mocks.api.mockResolvedValue({ slides: [] })
    open()
    fireEvent.change(screen.getByLabelText('Points (one per line)'), { target: { value: 'word '.repeat(70) } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Save slides' })[0])
    await waitFor(() => expect(mocks.api).toHaveBeenCalled())
    const sent = (mocks.api.mock.calls[0][1] as { body: { slides: { bullets: string[] }[] } }).body.slides[0].bullets
    expect(sent.length).toBeGreaterThan(1)
    expect(sent.every((b) => b.length <= 160)).toBe(true)
  })
})
