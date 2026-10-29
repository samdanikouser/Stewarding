/** The code part of a scanned QR text, which is a link ending in /scan/<code> or the bare code. */
export function scanCode(text: string): string {
  const match = text.trim().match(/\/scan\/([^/?#\s]+)/)
  return match ? match[1] : text.trim()
}
