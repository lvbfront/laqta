import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'
import data from './data/photos.json'

gsap.registerPlugin(ScrollTrigger, useGSAP)
// Mobile address-bar show/hide resizes the viewport; don't re-layout pins for it.
ScrollTrigger.config({ ignoreMobileResize: true })

export { gsap, ScrollTrigger, useGSAP }

/** Box = [x, y, w, h], fractions of the 4:5 photo. */
export type Box = [number, number, number, number]
export type Photo = { n: number; faces: Box[]; you?: Box; credit: string; unsplash: string }
export const photos = data as Photo[]
export const matches = photos.filter((p) => p.you)
export const others = photos.filter((p) => !p.you)

export const src = (p: Photo, v: 's' | 'm' | 'b' = 's') => `/photos/${String(p.n).padStart(2, '0')}-${v}.webp`

const AR = '٠١٢٣٤٥٦٧٨٩'
/** Latin digits → Arabic-Indic. `ar(1, 3)` → «٠٠١». */
export const ar = (v: number | string, pad = 0) =>
  String(v).padStart(pad, '0').replace(/\d/g, (d) => AR[+d])

/** Horizontal sign for GSAP x values: the page is RTL, so "forward" is −x. */
export const DIR = () => (document.documentElement.dir === 'rtl' ? -1 : 1)

/** Layout position of `el` inside `root`, ignoring transforms (unlike getBoundingClientRect). */
export function posIn(el: HTMLElement, root: HTMLElement) {
  let x = 0, y = 0, n: HTMLElement | null = el
  while (n && n !== root) {
    x += n.offsetLeft
    y += n.offsetTop
    n = n.offsetParent as HTMLElement | null
  }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight }
}

/** Face box → CSS percentages, grown by `pad` of its size on each side (faces
 *  are tight crops; brackets need air) and clamped into the photo.
 *  Physical `left` on purpose: photos are never mirrored, so neither are faces. */
export const boxStyle = ([x, y, w, h]: Box, pad = 0.4) => {
  const x0 = Math.max(0, x - w * pad), y0 = Math.max(0, y - h * pad)
  const x1 = Math.min(1, x + w * (1 + pad)), y1 = Math.min(1, y + h * (1 + pad))
  return { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }
}

// Placeholders the brief says must not be invented.
export const SIGNUP_URL = '#start'
export const ASSISTANT_URL = '#organizers'

// Dev-only handle for driving/inspecting scroll states from the console.
if (import.meta.env.DEV) Object.assign(window, { __ST: ScrollTrigger })
