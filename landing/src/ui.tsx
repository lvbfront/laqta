import type { CSSProperties, ReactNode } from 'react'
import { src, type Photo } from './lib'

/** Viewfinder corners: four bordered spans on a wrapper, positioned with
 *  logical insets so they mirror in RTL. Empty = a focus box. */
export function Brackets({ children, className = '', style }: { children?: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <span className={`bk ${className}`} style={style}>
      <i className="bk-ss" /><i className="bk-se" /><i className="bk-es" /><i className="bk-ee" />
      {children}
    </span>
  )
}

/** A 4:5 photo. Sized by CSS aspect-ratio so nothing shifts while it loads. */
export function Img({ p, v = 's', eager, sizes = '160px', className = '' }: { p: Photo; v?: 's' | 'b'; eager?: boolean; sizes?: string; className?: string }) {
  return (
    <img
      className={`ph ${className}`}
      src={src(p, v)}
      srcSet={v === 's' ? `${src(p, 's')} 320w, ${src(p, 'm')} 640w` : undefined}
      sizes={v === 's' ? sizes : undefined}
      width={320}
      height={400}
      alt=""
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      draggable={false}
    />
  )
}

export function Phone({ children, className = '', style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <div className={`phone ${className}`} style={style}>
      <div className="phone-screen">
        <span className="phone-notch" aria-hidden />
        {children}
      </div>
    </div>
  )
}
