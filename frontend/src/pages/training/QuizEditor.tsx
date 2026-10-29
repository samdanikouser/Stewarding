import { Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { api } from '@/lib/api'
import type { AdminLesson, AdminQuestion } from '@/lib/training'
import { useRun } from '@/lib/toast'

type Draft = Omit<AdminQuestion, 'id'> & { key: number }

let counter = 0
const blank = (): Draft => ({ key: ++counter, text: '', options: ['', ''], correct: 0 })

/** Writes the questions of a quiz lesson: each has a few answers and one marked as right. */
export function QuizEditor({ lesson, onClose, onSaved }: { lesson: AdminLesson; onClose: () => void; onSaved: () => void }) {
  const run = useRun()
  const [questions, setQuestions] = useState<Draft[]>(() => (lesson.questions.length ? lesson.questions.map((q) => ({ key: ++counter, text: q.text, options: [...q.options], correct: q.correct })) : [blank()]))

  const change = (key: number, patch: Partial<Draft>) => setQuestions((all) => all.map((q) => (q.key === key ? { ...q, ...patch } : q)))
  const ready = questions.length > 0 && questions.every((q) => q.text.trim().length >= 2 && q.options.length >= 2 && q.options.every((o) => o.trim()))

  async function save() {
    const body = { questions: questions.map((q) => ({ text: q.text, options: q.options, correct: q.correct })) }
    if (await run(() => api(`/training/lessons/${lesson.id}/questions`, { method: 'PUT', body }), 'Questions saved')) onSaved()
  }

  return (
    <Modal open size="xl" title={`Quiz: ${lesson.title}`} description="Give each question two to six answers and mark the right one." onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={!ready} onClick={save}>Save questions</Button>
      </>}>
      <div className="space-y-5">
        {questions.map((question, index) => (
          <fieldset key={question.key} className="space-y-3 rounded-xl border border-border bg-surface p-4">
            <div className="flex items-start gap-2">
              <span className="mt-2 text-sm font-semibold text-ink-muted">{index + 1}.</span>
              <Input aria-label={`Question ${index + 1}`} placeholder="Write the question" maxLength={500} value={question.text} onChange={(e) => change(question.key, { text: e.target.value })} />
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove question ${index + 1}`} onClick={() => setQuestions((all) => all.filter((q) => q.key !== question.key))}><Trash2 className="h-4 w-4" /></Button>
            </div>
            <div className="space-y-2 pl-6">
              {question.options.map((option, choice) => (
                <div key={choice} className="flex items-center gap-2">
                  <input type="radio" aria-label={`Answer ${choice + 1} of question ${index + 1} is the right one`} name={`right-${question.key}`} checked={question.correct === choice} onChange={() => change(question.key, { correct: choice })} />
                  <Input aria-label={`Answer ${choice + 1} of question ${index + 1}`} placeholder={`Answer ${choice + 1}`} maxLength={200} value={option}
                    onChange={(e) => change(question.key, { options: question.options.map((o, i) => (i === choice ? e.target.value : o)) })} />
                  {question.options.length > 2 && (
                    <Button type="button" variant="ghost" size="icon" aria-label={`Remove answer ${choice + 1}`}
                      onClick={() => change(question.key, { options: question.options.filter((_, i) => i !== choice), correct: question.correct === choice ? 0 : question.correct > choice ? question.correct - 1 : question.correct })}><X className="h-4 w-4" /></Button>
                  )}
                </div>
              ))}
              {question.options.length < 6 && (
                <Button type="button" size="sm" variant="outline" onClick={() => change(question.key, { options: [...question.options, ''] })}><Plus className="h-3.5 w-3.5" /> Add an answer</Button>
              )}
            </div>
          </fieldset>
        ))}
        <Button type="button" variant="outline" onClick={() => setQuestions((all) => [...all, blank()])}><Plus className="h-4 w-4" /> Add a question</Button>
      </div>
    </Modal>
  )
}
