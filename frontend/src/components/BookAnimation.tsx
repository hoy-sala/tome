// Animated Tome book mark. Same book shape as <TomeMark>, split into
// left-page / right-page / spine so the pages can move independently.
// Stroke = currentColor, so it themes via text-* utilities (e.g. text-primary).
// Motion is driven by CSS classes in index.css (.book-anim--{variant}).
import { cn } from '@/lib/utils'

export type BookAnimationVariant = 'levitate' | 'refresh' | 'send' | 'riffle'

interface Props {
  variant: BookAnimationVariant
  className?: string
  strokeWidth?: number
  /** Set false to freeze the animation (e.g. only play while loading). */
  playing?: boolean
}

const LEFT = 'M4 18 Q 4 14 8 14 L 28 18 Q 32 19 32 22 L 32 52 Q 32 50 28 49 L 8 49 Q 4 49 4 46 Z'
const RIGHT = 'M60 18 Q 60 14 56 14 L 36 18 Q 32 19 32 22 L 32 52 Q 32 50 36 49 L 56 49 Q 60 49 60 46 Z'

export function BookAnimation({ variant, className, strokeWidth = 6, playing = true }: Props) {
  const wrapper = cn('book-anim', `book-anim--${variant}`, playing && 'is-playing', className)
  const sw = strokeWidth

  if (variant === 'riffle') {
    return (
      <span className={wrapper} aria-hidden="true">
        <svg viewBox="0 1 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
          <line className="spine" x1="32" y1="20" x2="32" y2="52" strokeWidth={sw} strokeLinecap="round" />
          <path className="pg" d={RIGHT} strokeWidth={sw} strokeLinejoin="round" />
          <path className="pg" d={RIGHT} strokeWidth={sw} strokeLinejoin="round" />
          <path className="pg" d={RIGHT} strokeWidth={sw} strokeLinejoin="round" />
          <path className="pg" d={RIGHT} strokeWidth={sw} strokeLinejoin="round" />
          <path className="left-page" d={LEFT} strokeWidth={sw} strokeLinejoin="round" />
        </svg>
      </span>
    )
  }

  return (
    <span className={wrapper} aria-hidden="true">
      <svg viewBox="0 1 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
        {variant === 'levitate' && <ellipse className="ba-shadow" cx="32" cy="58" rx="18" ry="3" />}
        <g className="book">
          <path className="left-page" d={LEFT} strokeWidth={sw} strokeLinejoin="round" />
          <path className="right-page" d={RIGHT} strokeWidth={sw} strokeLinejoin="round" />
          <line className="spine" x1="32" y1="22" x2="32" y2="52" strokeWidth={sw} strokeLinecap="round" />
        </g>
      </svg>
    </span>
  )
}
