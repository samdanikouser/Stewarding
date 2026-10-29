import { QrCode } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LotScanner } from '@/components/LotScanner'
import { Button } from '@/components/ui/button'
import { scanCode } from '@/lib/scan'

/** Opens the camera to read the QR code posted at a monitoring point or location, then goes to that place's form. */
export function ScanButton() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}><QrCode aria-hidden className="mr-2 h-4 w-4" />Scan QR</Button>
      <LotScanner open={open} title="Scan the QR code" what="place" onClose={() => setOpen(false)}
        onScan={(text) => { setOpen(false); navigate(`/scan/${scanCode(text)}`) }} />
    </>
  )
}
