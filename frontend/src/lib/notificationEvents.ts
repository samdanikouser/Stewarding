/** Tells the bell that notifications were read, acknowledged or arrived, so its count changes at once instead of at the next poll. */
export const NOTIFICATIONS_CHANGED = 'notifications-changed'

export const notificationsChanged = () => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED))
