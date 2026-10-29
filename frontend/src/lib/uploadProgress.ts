import { ApiError, tokenStore } from '@/lib/api'

/** Sends one file to the API and reports how much has gone, because a large video takes a while and the person needs to see it moving. */
export function uploadWithProgress<T>(path: string, file: File, onProgress: (percent: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    const request = new XMLHttpRequest()
    request.open('POST', `/api${path}`)
    const token = tokenStore.get()
    if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((100 * event.loaded) / event.total))
    }
    request.onerror = () => reject(new ApiError(0, 'The upload was interrupted. Check the connection and try again'))
    request.onload = () => {
      let parsed: { detail?: unknown } | null = null
      try {
        parsed = JSON.parse(request.responseText)
      } catch {
        parsed = null
      }
      if (request.status >= 200 && request.status < 300) return resolve(parsed as T)
      const message = typeof parsed?.detail === 'string' ? parsed.detail
        : request.status === 413 ? 'The file is too large for the server'
        : 'The upload was refused'
      reject(new ApiError(request.status, message, parsed?.detail))
    }
    request.send(form)
  })
}
