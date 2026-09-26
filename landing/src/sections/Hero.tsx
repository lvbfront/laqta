import { useEffect, useRef } from 'react'
import { animate, motion, useReducedMotion } from 'motion/react'
import { photos, SIGNUP_URL } from '../lib'
import { Brackets, Img } from '../ui'

// Wall order: interleave so the demo guest's photos don't cluster.
const wall = photos.map((_, i) => photos[(i * 17) % photos.length])

export function Hero() {
  const wallRef = useRef<HTMLDivElement>(null)
  const boxRef = useRef<HTMLSpanElement>(null)
  const reduce = useReducedMotion()

  // Motion owns the roaming focus box. It lives inside the drifting wall, so it
  // drifts with the photos; each hop picks a face that's currently on screen.
  useEffect(() => {
    const wallEl = wallRef.current, box = boxRef.current
    if (!wallEl || !box) return
    let alive = true, timer = 0
    const hop = async () => {
      if (!alive) return
      const tiles = [...wallEl.querySelectorAll<HTMLElement>('.hero-tile')]
      const vw = innerWidth, vh = innerHeight
      const visible = tiles.filter((t) => {
        const r = t.getBoundingClientRect()
        return r.left > 16 && r.right < vw - 16 && r.top > 72 && r.bottom < vh * 0.62
      })
      const pool = visible.length ? visible : tiles
      const tile = pool[Math.floor(Math.random() * pool.length)]
      const p = wall[+tile.dataset.i!]
      const [fx, fy, fw, fh] = p.faces[0] ?? p.you!
      const pad = 0.35
      const target = {
        x: tile.offsetLeft + Math.max(0, fx - fw * pad) * tile.offsetWidth,
        y: tile.offsetTop + Math.max(0, fy - fh * pad) * tile.offsetHeight,
        width: fw * (1 + pad * 2) * tile.offsetWidth,
        height: fh * (1 + pad * 2) * tile.offsetHeight,
      }
      if (reduce) {
        Object.assign(box.style, { transform: `translate(${target.x}px, ${target.y}px)`, width: `${target.width}px`, height: `${target.height}px`, opacity: '1' })
        return
      }
      await animate(box, { opacity: 0.35 }, { duration: 0.15 })
      await animate(box, target, { type: 'spring', stiffness: 120, damping: 20 })
      await animate(box, { opacity: 1, scale: [1.12, 1] }, { duration: 0.25 })
      timer = window.setTimeout(hop, 1400)
    }
    timer = window.setTimeout(hop, 900)
    return () => { alive = false; clearTimeout(timer) }
  }, [reduce])

  return (
    <section className="hero" id="top">
      <div className="hero-wall" ref={wallRef} aria-hidden>
        {wall.map((p, i) => (
          <div className="hero-tile" data-i={i} key={i}>
            <Img p={p} eager={i < 24} sizes="(min-width: 900px) 14vw, 30vw" />
          </div>
        ))}
        <span ref={boxRef} className="hero-box"><Brackets className="focus" /></span>
      </div>
      <div className="hero-shade" aria-hidden />
      <div className="hero-copy wrap">
        <motion.p className="eyebrow" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          لقطة — توزيع صور المناسبات بالوجه
        </motion.p>
        <motion.h1 initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35, duration: 0.7, ease: [0.2, 0.7, 0.2, 1] }}>
          <span className="thin">كل ضيف يلقى صوره… بوجهه،</span>{' '}
          <span className="strong">وباسمك أنت</span>
        </motion.h1>
        <motion.p className="lede" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}>
          ترفع الصور أثناء المناسبة، الضيف يمسح الكود ويلتقط سيلفي، ويوصله اللي هو فيه بس — في معرض يحمل اسمك.
        </motion.p>
        <motion.a className="btn" href={SIGNUP_URL} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.75 }} whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>
          ابدأ أول مناسبة مجاناً
        </motion.a>
      </div>
    </section>
  )
}
