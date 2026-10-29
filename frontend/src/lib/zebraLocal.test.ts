import { afterEach, describe, expect, it, vi } from 'vitest'
import { findLocalZebra, printOnLocalZebra } from '@/lib/zebraLocal'

const respond = (body: unknown, ok = true) => ({ ok, text: async () => (typeof body === 'string' ? body : JSON.stringify(body)), json: async () => body }) as Response
const zebra = { uid: 'abc', name: 'ZDesigner ZD421-203dpi ZPL', connection: 'driver', deviceType: 'printer' }

afterEach(() => vi.unstubAllGlobals())

describe('Zebra Browser Print client', () => {
  it("finds the computer's default Zebra", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(zebra))
    vi.stubGlobal('fetch', fetchMock)
    expect(await findLocalZebra()).toEqual({ base: 'http://127.0.0.1:9100', printer: zebra })
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:9100/default?type=printer', expect.anything())
  })

  it('falls back to the first available printer when there is no default', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => (url.includes('/default') ? respond('') : respond({ printer: [zebra] }))))
    expect((await findLocalZebra())?.printer.uid).toBe('abc')
  })

  it('tries the secure address when the plain one is blocked, and gives up quietly when the helper is not running', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => {
      if (url.startsWith('http://')) throw new TypeError('blocked')
      return respond(zebra)
    }))
    expect((await findLocalZebra())?.base).toBe('https://127.0.0.1:9101')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection refused')))
    expect(await findLocalZebra()).toBeNull()
  })

  it('sends the label text and the device as plain JSON, and reports a refusal', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond('', true))
    vi.stubGlobal('fetch', fetchMock)
    await printOnLocalZebra({ base: 'http://127.0.0.1:9100', printer: zebra }, '^XA^XZ')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:9100/write')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ device: zebra, data: '^XA^XZ' })
    expect(init.headers).toBeUndefined()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond('Printer is offline', false)))
    await expect(printOnLocalZebra({ base: 'http://127.0.0.1:9100', printer: zebra }, '^XA^XZ')).rejects.toThrow('Printer is offline')
  })
})
