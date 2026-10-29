import { api } from '@/lib/api'

export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

/** An iPhone only offers push to an app opened from the Home Screen. */
export const needsHomeScreen = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) && !(navigator as Navigator & { standalone?: boolean }).standalone && !pushSupported()

function keyBytes(base64Url: string): Uint8Array<ArrayBuffer> {
  const raw = atob(base64Url.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(base64Url.length / 4) * 4, '='))
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration()
  return registration ? registration.pushManager.getSubscription() : null
}

export async function enablePush(): Promise<void> {
  if ((await Notification.requestPermission()) !== 'granted') throw new Error('Alerts are blocked for this site. Allow notifications in the browser settings, then try again')
  const { public_key } = await api<{ public_key: string | null }>('/push/key')
  if (!public_key) throw new Error('Push alerts are not set up on the server yet')
  const registration = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready
  const subscription = (await registration.pushManager.getSubscription())
    ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) })
  const { endpoint, keys } = subscription.toJSON()
  await api('/push/subscribe', { body: { endpoint, keys } })
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription()
  if (!subscription) return
  await api('/push/unsubscribe', { body: { endpoint: subscription.endpoint } })
  await subscription.unsubscribe()
}
