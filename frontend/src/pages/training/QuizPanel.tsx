import { CheckCircle2, RotateCcw, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { PlayerLesson } from '@/lib/training'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Quiz {
  pass_mark: number
  attempts: number
  best: number | null
  passed: boolean
  questions: { id: number; text: string; options: string[] }[]
}

interface Result {
  score: number
  passed: boolean
  correct: number
  total: number
  results: boolean[]
  course_completed: boolean
}

/** The questions of a quiz lesson. Passing finishes the lesson; failing can be tried again as often as needed. */
export function QuizPanel({ assignmentId, lesson, onChanged }: { assignmentId: number; lesson: PlayerLesson; onChanged: () => void }) {
  const path = `/training/my/${assignmentId}/lessons/${lesson.id}/quiz`
  const quiz = useApi<Quiz>(path)
  const run = useRun()
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [result, setResult] = useState<Result | null>(null)

  if (!quiz.data) return <p className="text-sm text-ink-muted">Loading the questions...</p>
  const { questions, pass_mark: passMark } = quiz.data
  const answeredAll = questions.every((q) => answers[q.id] !== undefined)

  async function submit() {
    await run(async () => {
      const marked = await api<Result>(path, { body: { answers: questions.map((q) => answers[q.id] ?? null) } })
      setResult(marked)
      onChanged()
      quiz.reload()
    })
  }

  function again() {
    setAnswers({})
    setResult(null)
  }

  return (
    <div className="space-y-5">
      {result ? (
        <div role="status" className={`flex items-start gap-3 rounded-xl p-4 ${result.passed ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger'}`}>
          {result.passed ? <CheckCircle2 aria-hidden className="mt-0.5 h-5 w-5 shrink-0" /> : <XCircle aria-hidden className="mt-0.5 h-5 w-5 shrink-0" />}
          <div>
            <p className="font-semibold">{result.passed ? 'You passed' : 'Not passed yet'}: {result.score}%</p>
            <p className="text-sm">{result.correct} of {result.total} right. You need {passMark}% to pass.{result.course_completed && ' That finishes the course.'}</p>
          </div>
        </div>
      ) : quiz.data.passed ? (
        <p className="rounded-xl bg-ok-soft p-3 text-sm text-ok">You have passed this quiz (best result {quiz.data.best}%). You can take it again whenever you like.</p>
      ) : (
        <p className="text-sm text-ink-muted">Answer every question. You need {passMark}% to pass{quiz.data.attempts > 0 && `, and your best so far is ${quiz.data.best}%`}.</p>
      )}

      <ol className="space-y-5">
        {questions.map((question, index) => (
          <li key={question.id}>
            <fieldset disabled={result !== null} className="space-y-2">
              <legend className="flex items-start gap-2 text-base font-medium">
                <span>{index + 1}. {question.text}</span>
                {result && (result.results[index]
                  ? <CheckCircle2 aria-label="Right" className="mt-0.5 h-5 w-5 shrink-0 text-ok" />
                  : <XCircle aria-label="Wrong" className="mt-0.5 h-5 w-5 shrink-0 text-danger" />)}
              </legend>
              {question.options.map((option, choice) => (
                <label key={choice} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm has-[:checked]:border-brand has-[:checked]:bg-brand-soft has-[:disabled]:cursor-default">
                  <input type="radio" name={`question-${question.id}`} checked={answers[question.id] === choice} onChange={() => setAnswers({ ...answers, [question.id]: choice })} />
                  {option}
                </label>
              ))}
            </fieldset>
          </li>
        ))}
      </ol>

      {result ? (
        !result.passed && <Button variant="outline" onClick={again}><RotateCcw className="h-4 w-4" /> Try again</Button>
      ) : (
        <Button disabled={!answeredAll} onClick={submit}>Submit answers</Button>
      )}
    </div>
  )
}
