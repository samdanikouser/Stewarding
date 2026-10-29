import { tokenStore } from '@/lib/api'

/** Fetches an authenticated file and saves it; returns false when the server refuses. */
export async function downloadFile(path: string, fallbackName: string): Promise<boolean> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${tokenStore.get()}` } })
  if (!response.ok) return false
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = response.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] ?? fallbackName
  link.click()
  URL.revokeObjectURL(url)
  return true
}

/** An authenticated text file, such as ZPL label data; throws when the server refuses. */
export async function fetchText(path: string): Promise<string> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${tokenStore.get()}` } })
  if (!response.ok) throw new Error('Could not make the labels')
  return response.text()
}

/** Opens an authenticated PDF in a new tab to read or print; the tab opens first so it is not blocked as a pop-up. */
export async function openPdf(path: string): Promise<boolean> {
  const tab = window.open('', '_blank')
  const response = await fetch(path, { headers: { Authorization: `Bearer ${tokenStore.get()}` } })
  if (!response.ok) {
    tab?.close()
    return false
  }
  const url = URL.createObjectURL(await response.blob())
  if (tab) tab.location.href = url
  else window.location.href = url
  setTimeout(() => URL.revokeObjectURL(url), 120_000)
  return true
}
