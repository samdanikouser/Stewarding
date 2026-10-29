// Shows a push alert from the server and opens the right page when it is tapped.
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {}
  event.waitUntil(self.registration.showNotification(data.title || 'Plato', {
    body: data.body || '',
    tag: data.tag,
    icon: '/icon-192.png',
    badge: '/favicon-32.png',
    data: { link: data.link || '/tasks' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const link = event.notification.data?.link || '/tasks'
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((open) => {
    const here = open.find((c) => 'focus' in c)
    if (here) return here.navigate(link).then((c) => c && c.focus())
    return self.clients.openWindow(link)
  }))
})
