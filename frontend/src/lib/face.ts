import type * as FaceApi from '@vladmandic/face-api'

/** Where the model weights are served from; they are copied from the face-api package into public/models. */
const MODEL_URL = '/models'

let loading: Promise<typeof FaceApi> | null = null

/** Loads the face library and the three small models once, only when a camera screen needs them. */
export function loadFaceModels(): Promise<typeof FaceApi> {
  loading ??= import('@vladmandic/face-api').then(async (faceapi) => {
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODEL_URL),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
    ])
    return faceapi
  })
  loading.catch(() => { loading = null })
  return loading
}

export type Step = 'turn_left' | 'turn_right'

export const STEP_TEXT: Record<Step, string> = {
  turn_left: 'Turn your head slowly to your left',
  turn_right: 'Turn your head slowly to your right',
}

const TURN_LEFT_AT = 0.62
const TURN_RIGHT_AT = 0.38
const CENTRE = [0.44, 0.56] as const

/**
 * Where the nose sits between the two ends of the jaw, from the 68 landmark points: about 0.5 facing the camera,
 * higher when the person turns to their own left (the camera image is not mirrored, so their left is its right).
 */
export function yawRatio(points: { x: number }[]): number {
  return (points[30].x - points[0].x) / (points[16].x - points[0].x)
}

/** A step is finished once the turn was reached and the head has come back to the middle. */
export function advance(step: Step, ratio: number, turned: boolean): { turned: boolean; done: boolean } {
  if (!turned) return { turned: step === 'turn_left' ? ratio >= TURN_LEFT_AT : ratio <= TURN_RIGHT_AT, done: false }
  const back = ratio >= CENTRE[0] && ratio <= CENTRE[1]
  return { turned: !back, done: back }
}

/** The current video frame as a small JPEG, base64 without the data-URL prefix. */
export function snapshotOf(video: HTMLVideoElement): string {
  const scale = Math.min(1, 320 / (video.videoWidth || 320))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round((video.videoWidth || 320) * scale)
  canvas.height = Math.round((video.videoHeight || 240) * scale)
  canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.7).split(',')[1]
}

/** Straight-line distance between two face templates; smaller means more alike. */
export function faceDistance(a: ArrayLike<number>, b: ArrayLike<number>): number {
  let sum = 0
  for (let i = 0; i < a.length; i++) sum += (a[i] - b[i]) ** 2
  return Math.sqrt(sum)
}

/** The mean of several templates of the same face, which is steadier than a single frame. */
export function averageFace(faces: ArrayLike<number>[]): number[] {
  return Array.from(faces[0], (_, i) => faces.reduce((sum, f) => sum + f[i], 0) / faces.length)
}
