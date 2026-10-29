import jsQR from 'jsqr'

export interface Frame {
  data: Uint8ClampedArray
  width: number
  height: number
}

/** The text of the QR code in a camera frame, or null when there is none; light-on-dark codes are tried too. */
export function decodeQr(frame: Frame): string | null {
  return jsQR(frame.data, frame.width, frame.height, { inversionAttempts: 'attemptBoth' })?.data ?? null
}
