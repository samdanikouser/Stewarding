import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { PNG } from 'pngjs'
import { describe, expect, it } from 'vitest'
import { decodeQr, type Frame } from '@/lib/qr'

const LABELS: [string, string][] = [
  ['label-1.png', 'POU-261021-01-1'],
  ['label-2.png', 'SEA-261021-01'],
  ['label-3.png', 'POU-261021-01-1-1'],
]

function load(name: string): Frame {
  const png = PNG.sync.read(readFileSync(join(__dirname, '../test-fixtures/qr', name)))
  return { data: new Uint8ClampedArray(png.data), width: png.width, height: png.height }
}

const gray = (f: Frame, i: number) => (f.data[i] + f.data[i + 1] + f.data[i + 2]) / 3

function make(width: number, height: number, fill: (x: number, y: number) => number): Frame {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      data[i] = data[i + 1] = data[i + 2] = fill(x, y)
      data[i + 3] = 255
    }
  }
  return { data, width, height }
}

function scale(f: Frame, factor: number): Frame {
  const w = Math.round(f.width * factor)
  const h = Math.round(f.height * factor)
  return make(w, h, (x, y) => gray(f, (Math.min(f.height - 1, Math.floor(y / factor)) * f.width + Math.min(f.width - 1, Math.floor(x / factor))) * 4))
}

function rotate(f: Frame, degrees: number): Frame {
  const rad = (degrees * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const w = Math.ceil(Math.abs(f.width * cos) + Math.abs(f.height * sin))
  const h = Math.ceil(Math.abs(f.width * sin) + Math.abs(f.height * cos))
  return make(w, h, (x, y) => {
    const dx = x - w / 2
    const dy = y - h / 2
    const sx = Math.round(dx * cos + dy * sin + f.width / 2)
    const sy = Math.round(-dx * sin + dy * cos + f.height / 2)
    return sx < 0 || sy < 0 || sx >= f.width || sy >= f.height ? 255 : gray(f, (sy * f.width + sx) * 4)
  })
}

function blur(f: Frame, radius: number): Frame {
  return make(f.width, f.height, (x, y) => {
    let sum = 0
    let n = 0
    for (let dy = -radius; dy <= radius; dy++) {
      for (let dx = -radius; dx <= radius; dx++) {
        const sx = Math.min(f.width - 1, Math.max(0, x + dx))
        const sy = Math.min(f.height - 1, Math.max(0, y + dy))
        sum += gray(f, (sy * f.width + sx) * 4)
        n++
      }
    }
    return sum / n
  })
}

function noise(f: Frame, amount: number): Frame {
  let seed = 12345
  const random = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296 - 0.5
  return make(f.width, f.height, (x, y) => gray(f, (y * f.width + x) * 4) + random() * amount)
}

function dim(f: Frame): Frame {
  return make(f.width, f.height, (x, y) => 60 + gray(f, (y * f.width + x) * 4) * 0.25)
}

describe('QR decoding of printed labels', () => {
  describe.each(LABELS)('%s', (name, code) => {
    const frame = load(name)

    it('reads the code from the clean label', () => {
      expect(decodeQr(frame)).toBe(code)
    })

    it.each([0.6, 0.8, 1.5])('reads it at %sx size', (factor) => {
      expect(decodeQr(scale(frame, factor))).toBe(code)
    })

    it.each([-20, -8, 12, 30])('reads it tilted by %s degrees', (degrees) => {
      expect(decodeQr(rotate(frame, degrees))).toBe(code)
    })

    it('reads it slightly out of focus', () => {
      expect(decodeQr(blur(frame, 1))).toBe(code)
    })

    it('reads it with camera noise', () => {
      expect(decodeQr(noise(frame, 60))).toBe(code)
    })

    it('reads it in dim light', () => {
      expect(decodeQr(dim(frame))).toBe(code)
    })
  })

  it('returns null for a frame with no code', () => {
    expect(decodeQr(make(300, 200, () => 200))).toBeNull()
  })
})
