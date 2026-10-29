import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand active:translate-y-px disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-brand text-brand-ink shadow-sm hover:bg-brand-deep',
        outline: 'border border-border-strong bg-surface shadow-xs hover:bg-surface-muted',
        ghost: 'hover:bg-surface-muted',
        danger: 'bg-danger text-danger-ink shadow-sm hover:bg-danger/90',
      },
      size: { default: 'h-10 px-4 pointer-coarse:h-11', sm: 'h-8 px-3 pointer-coarse:h-10', icon: 'h-10 w-10 pointer-coarse:h-11 pointer-coarse:w-11' },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export function Button({ className, variant, size, asChild, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
