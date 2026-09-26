import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, LayoutGroup, motion, useInView, useReducedMotion } from 'motion/react'
import { ar, matches } from '../lib'
import { Img, Phone } from '../ui'

// Fictional studios. Contacts are deliberately fake (zeros, example.com) so
// nothing points at a real business.
const BRANDS = [
  { id: 'raml', name: 'استوديو رمل', mark: 'ر', layout: 'center', bg: '#17120e', ink: '#f3e7d8', accent: '#d9b38c', contact: 'واتساب ٠٥٠ ٠٠٠ ٠٠٠٠' },
  { id: 'najd', name: 'عدسة نجد', mark: 'ن', layout: 'start', bg: '#0d1714', ink: '#e3efe9', accent: '#7fb69e', contact: 'najd@example.com' },
  { id: 'masa', name: 'ضوء المساء', mark: 'ض', layout: 'band', bg: '#1b1012', ink: '#f7e6e2', accent: '#e58f7b', contact: 'example.com/masa' },
] as const

const gallery = matches.slice(0, 9)

export function Brand() {
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const [picked, setPicked] = useState(false) // a manual pick stops the rotation
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.4 })
  const reduce = useReducedMotion()
  const b = BRANDS[i]

  useEffect(() => {
    if (!inView || paused || picked || reduce) return
    const t = setTimeout(() => setI((v) => (v + 1) % BRANDS.length), 3200)
    return () => clearTimeout(t)
  }, [i, inView, paused, picked, reduce])

  const Mark = (
    <motion.span layoutId="brand-mark" className="b-mark" style={{ background: b.accent, color: b.bg }} transition={{ type: 'spring', stiffness: 260, damping: 28 }}>
      {b.mark}
    </motion.span>
  )
  const Name = <motion.span layoutId="brand-name" className="b-name">{b.name}</motion.span>

  return (
    <section className="brand" id="brand">
      <div className="wrap b-grid">
        <div className="b-copy">
          <header className="sec-head">
            <p className="eyebrow">{ar(3, 3)} — علامتك</p>
            <h2><span className="thin">المعرض يحمل</span> <span className="strong">اسمك.</span></h2>
          </header>
          <p className="lede">
            الضيف يفتح صوره ويشوف شعارك، ألوانك، وطريقة التواصل معك — مو شعارنا. كل صورة يحفظها، يحفظ معها اسمك.
          </p>
          <div className="b-tabs" role="tablist" aria-label="أمثلة علامات تجارية وهمية" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
            {BRANDS.map((x, k) => (
              <button key={x.id} role="tab" aria-selected={k === i} className={k === i ? 'on' : ''} onClick={() => { setI(k); setPicked(true) }}>
                {k === i && <motion.span layoutId="tab-pill" className="b-pill" />}
                <span className="b-label">{x.name}</span>
              </button>
            ))}
          </div>
          <p className="note">أسماء الاستوديوهات هنا وهمية، للتوضيح فقط.</p>
        </div>

        <div ref={ref} className="b-stage">
          <Phone className="b-phone">
            <motion.div className={`b-screen is-${b.layout}`} animate={{ backgroundColor: b.bg, color: b.ink }} transition={{ duration: 0.5 }}>
              <LayoutGroup>
                <motion.header layout className="b-head" style={{ borderColor: b.accent }}>
                  {b.layout === 'band' ? (
                    <motion.div layout className="b-band" style={{ background: b.accent }}>{Mark}</motion.div>
                  ) : Mark}
                  {Name}
                  <AnimatePresence mode="popLayout" initial={false}>
                    {b.layout === 'start' && (
                      <motion.span key="c" className="b-contact" initial={{ opacity: 0 }} animate={{ opacity: 0.8 }} exit={{ opacity: 0 }}>{b.contact}</motion.span>
                    )}
                  </AnimatePresence>
                </motion.header>
                <motion.div layout className="b-gallery">
                  {gallery.map((p) => <Img p={p} key={p.n} sizes="100px" />)}
                </motion.div>
                <AnimatePresence mode="popLayout" initial={false}>
                  {b.layout !== 'start' && (
                    <motion.footer key={b.id} layout className="b-foot" style={{ background: b.accent, color: b.bg }} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                      {b.contact}
                    </motion.footer>
                  )}
                </AnimatePresence>
              </LayoutGroup>
            </motion.div>
          </Phone>
        </div>
      </div>
    </section>
  )
}
