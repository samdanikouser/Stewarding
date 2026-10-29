import { describe, expect, it } from 'vitest'
import { advance, averageFace, faceDistance, yawRatio } from '@/lib/face'

describe('face templates', () => {
  it('measures the straight-line distance between two templates', () => {
    expect(faceDistance([0, 0, 0], [3, 4, 0])).toBe(5)
    expect(faceDistance([1, 2], [1, 2])).toBe(0)
  })

  it('averages several frames of the same face into one steadier template', () => {
    expect(averageFace([[0, 10], [2, 20], [4, 30]])).toEqual([2, 20])
  })

  it('keeps a lone frame as it is', () => {
    expect(averageFace([[1.5, -2]])).toEqual([1.5, -2])
  })
})

const jaw = (nose: number) => Array.from({ length: 68 }, (_, i) => ({ x: i === 0 ? 100 : i === 16 ? 200 : i === 30 ? nose : 150 }))

describe('yawRatio', () => {
  it('is about one half facing the camera and rises when the nose moves toward the right of the image', () => {
    expect(yawRatio(jaw(150))).toBeCloseTo(0.5)
    expect(yawRatio(jaw(170))).toBeCloseTo(0.7)
    expect(yawRatio(jaw(130))).toBeCloseTo(0.3)
  })
})

describe('advance', () => {
  it('needs the turn first, then the head back in the middle, before a step is done', () => {
    let state = advance('turn_left', 0.5, false)
    expect(state).toEqual({ turned: false, done: false })
    state = advance('turn_left', 0.7, state.turned)
    expect(state).toEqual({ turned: true, done: false })
    state = advance('turn_left', 0.6, state.turned)
    expect(state).toEqual({ turned: true, done: false })
    expect(advance('turn_left', 0.5, state.turned)).toEqual({ turned: false, done: true })
  })

  it('counts a turn only in the direction that was asked for', () => {
    expect(advance('turn_left', 0.3, false).turned).toBe(false)
    expect(advance('turn_right', 0.7, false).turned).toBe(false)
    expect(advance('turn_right', 0.3, false).turned).toBe(true)
  })

  it('does not finish a step by staying in the middle', () => {
    expect(advance('turn_right', 0.5, false).done).toBe(false)
  })
})
