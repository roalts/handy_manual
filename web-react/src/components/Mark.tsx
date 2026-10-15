// The Handy Manual mark: a hex nut with an H. Decorative; the name is always next to it in text.

/** Inline SVG, hidden from screen readers; `className` sets its size and place. */
export function Mark({ className = "mark" }: { className?: string }) {
  return (
    <svg aria-hidden className={className} viewBox="0 0 32 32">
      <path className="mark-nut" d="M16 2.2 28 9.1v13.8L16 29.8 4 22.9V9.1Z" />
      <path className="mark-h" d="M11.5 10.5v11M20.5 10.5v11M11.5 16h9" />
    </svg>
  );
}
