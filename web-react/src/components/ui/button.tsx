import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

// Graphite: pill buttons, accent fill for the main action, soft fill for the others.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-full border text-base font-semibold leading-tight text-center whitespace-normal transition-colors touch-manipulation cursor-pointer disabled:cursor-not-allowed disabled:opacity-55 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "border-transparent bg-destructive text-paper hover:bg-destructive/90",
        outline: "border-control-line bg-background text-foreground hover:bg-accent",
        secondary: "border-transparent bg-secondary text-foreground hover:bg-line",
        ghost: "border-transparent bg-transparent text-inherit hover:bg-accent",
        link: "border-transparent text-link underline underline-offset-4",
      },
      // Every size keeps the 44 px minimum tap target.
      size: {
        default: "min-h-tap min-w-tap px-5 py-2",
        xs: "min-h-tap min-w-tap px-2.5 py-1 text-sm",
        sm: "min-h-tap min-w-tap px-3.5 py-1.5 text-[15px]",
        lg: "min-h-tap min-w-tap px-6 py-2.5",
        icon: "size-tap",
        "icon-xs": "size-tap",
        "icon-sm": "size-tap",
        "icon-lg": "size-12",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

/** Pill button in the Graphite variants; `asChild` styles its child element instead of rendering a button. */
function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
