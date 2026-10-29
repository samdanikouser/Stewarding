/** Zebra Browser Print runs on the computer a USB or driver-installed Zebra is plugged into and listens on these local addresses. */
const BASES = ['http://127.0.0.1:9100', 'https://127.0.0.1:9101']

export interface LocalPrinter {
  uid: string
  name: string
  connection?: string
  deviceType?: string
  [key: string]: unknown
}

export interface LocalHelper {
  base: string
  printer: LocalPrinter
}

async function ask(base: string, path: string, init?: RequestInit): Promise<Response> {
  const control = new AbortController()
  const timer = setTimeout(() => control.abort(), 1500)
  try {
    return await fetch(`${base}${path}`, { ...init, signal: control.signal })
  } finally {
    clearTimeout(timer)
  }
}

/** The helper and this computer's default Zebra, or null when the helper is not running or has no printer. */
export async function findLocalZebra(): Promise<LocalHelper | null> {
  for (const base of BASES) {
    try {
      const chosen = await ask(base, '/default?type=printer')
      const text = chosen.ok ? (await chosen.text()).trim() : ''
      if (text) {
        const printer = JSON.parse(text) as LocalPrinter
        if (printer?.uid) return { base, printer }
      }
      const listed = await ask(base, '/available')
      const first = listed.ok ? ((await listed.json()) as { printer?: LocalPrinter[] }).printer?.[0] : undefined
      if (first?.uid) return { base, printer: first }
    } catch {
      continue
    }
  }
  return null
}

/** Sends ZPL to the printer through the helper; the body is plain text so the browser needs no pre-flight check. */
export async function printOnLocalZebra(found: LocalHelper, zpl: string): Promise<void> {
  const response = await ask(found.base, '/write', { method: 'POST', body: JSON.stringify({ device: found.printer, data: zpl }) })
  if (!response.ok) throw new Error((await response.text()) || 'The printer did not accept the labels')
}
