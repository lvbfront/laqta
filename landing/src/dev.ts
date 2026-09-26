import { MotionGlobalConfig } from 'motion/react'

// Dev only: `?rm=1` emulates prefers-reduced-motion for testing, since the OS
// setting can't be flipped from a test harness. Stripped from production builds.
if (import.meta.env.DEV && new URLSearchParams(location.search).has('rm')) {
  const real = window.matchMedia.bind(window)
  window.matchMedia = (q: string) => {
    if (!q.includes('prefers-reduced-motion')) return real(q)
    const matches = !q.includes('no-preference')
    return { ...real(q), matches, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} } as MediaQueryList
  }
  // Mirror the CSS `@media (prefers-reduced-motion: reduce)` block.
  document.head.insertAdjacentHTML('beforeend', '<style>.hero-wall{animation:none!important}.hero-box{opacity:1!important}</style>')
}
// Dev only: `?shot=1` jumps every Motion animation to its end state, for
// screenshots taken from a background (rAF-throttled) browser tab.
if (import.meta.env.DEV && new URLSearchParams(location.search).has('shot')) {
  MotionGlobalConfig.skipAnimations = true
}

