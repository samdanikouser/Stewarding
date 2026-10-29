import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LotScanner } from '@/components/LotScanner'

const decodeQr = vi.hoisted(() => vi.fn())
vi.mock('@/lib/qr', () => ({ decodeQr }))
vi.mock('@/components/ui/modal', () => ({
  Modal: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
}))

const stop = vi.fn()

beforeEach(() => {
  decodeQr.mockReset()
  stop.mockReset()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) },
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 640 })
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 480 })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
    getImageData: () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 }),
  } as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('LotScanner', () => {
  it('reads the label with the decoder when the browser has no detector', async () => {
    decodeQr.mockReturnValue(' POU-261021-01-1 ')
    const onScan = vi.fn()
    render(<LotScanner open onClose={() => {}} onScan={onScan} />)
    await waitFor(() => expect(onScan).toHaveBeenCalledWith('POU-261021-01-1'))
  })

  it('falls back to the decoder when the built-in detector cannot read QR codes', async () => {
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn().mockResolvedValue([]) })
    decodeQr.mockReturnValue('SEA-261021-01')
    const onScan = vi.fn()
    render(<LotScanner open onClose={() => {}} onScan={onScan} />)
    await waitFor(() => expect(onScan).toHaveBeenCalledWith('SEA-261021-01'))
  })

  it('falls back to the decoder when the built-in detector throws', async () => {
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn().mockRejectedValue(new Error('unsupported')) })
    decodeQr.mockReturnValue('SEA-261021-01')
    const onScan = vi.fn()
    render(<LotScanner open onClose={() => {}} onScan={onScan} />)
    await waitFor(() => expect(onScan).toHaveBeenCalledWith('SEA-261021-01'))
  })

  it('uses the built-in detector result when it reads the code', async () => {
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn().mockResolvedValue([{ rawValue: 'POU-261021-01-1-1' }]) })
    const onScan = vi.fn()
    render(<LotScanner open onClose={() => {}} onScan={onScan} />)
    await waitFor(() => expect(onScan).toHaveBeenCalledWith('POU-261021-01-1-1'))
    expect(decodeQr).not.toHaveBeenCalled()
  })

  it('keeps looking until a code appears, and releases the camera when closed', async () => {
    decodeQr.mockReturnValueOnce(null).mockReturnValue('POU-261021-01-1')
    const onScan = vi.fn()
    const { unmount } = render(<LotScanner open onClose={() => {}} onScan={onScan} />)
    await waitFor(() => expect(onScan).toHaveBeenCalledWith('POU-261021-01-1'), { timeout: 2000 })
    expect(decodeQr.mock.calls.length).toBeGreaterThan(1)
    unmount()
    expect(stop).toHaveBeenCalled()
  })

  it('tells the person to type the code when the camera is blocked or needs https', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException('no', 'NotAllowedError')) },
    })
    const { unmount } = render(<LotScanner open onClose={() => {}} onScan={() => {}} />)
    expect(await screen.findByText(/Allow camera access/)).toBeTruthy()
    unmount()
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined })
    render(<LotScanner open onClose={() => {}} onScan={() => {}} />)
    expect(await screen.findByText(/secure \(https\) page/)).toBeTruthy()
  })
})
