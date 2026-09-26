import { useRef } from 'react'
import { motion } from 'motion/react'
import { ar, boxStyle, gsap, matches, others, useGSAP, type Photo } from '../lib'
import { Brackets, Img } from '../ui'

// Two of his among strangers. The "-b" variant is blurred whole-frame except
// his face (baked at build time: no runtime filters on a phone).
const HIS_AT = [5, 14]
const tiles: Photo[] = Array.from({ length: 20 }, (_, i) =>
  HIS_AT.includes(i) ? matches[HIS_AT.indexOf(i) + 3] : others[21 + i],
)

const PROMISES: [string, string][] = [
  ['كل ضيف يشوف صوره هو.', 'وبس. ما فيه رابط للمعرض كامل، ولا صفحة تعرض كل الصور — لأي أحد، ولا حتى لنا كإدارة.'],
  ['نطابق الوجه، ما نتصفّح الصور.', 'السيلفي تُستخدم للمطابقة لحظتها ثم تنمسح. ما تنحفظ على قرص، ولا في سجل.'],
  ['في مناسبات النساء، ولا صورة تطلع قبل ما تنعتمد.', 'الوضع المشدّد يوقف النشر التلقائي بالكامل: كل صورة تمر على المراجعة أول.'],
  ['كل شي ينحذف تلقائياً بعد ', ' من نهاية المناسبة.'],
]

export function Privacy() {
  const root = useRef<HTMLElement>(null)

  // GSAP owns the scroll-linked blur: the sharp wall "loses" every face but his.
  // Default CSS already shows the blurred end state, so no-JS / reduced motion
  // tell the same story.
  useGSAP(() => {
    gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', () => {
      const q = gsap.utils.selector(root)
      const tl = gsap.timeline({
        scrollTrigger: { trigger: q('.p-wall')[0], start: 'top 75%', end: 'center 45%', scrub: 0.5 },
      })
      tl.from(q('.p-blur'), { opacity: 0, duration: 1, stagger: { each: 0.04, from: 'random' } })
        .from(q('.p-you'), { autoAlpha: 0, scale: 1.8, duration: 0.4, stagger: 0.1, ease: 'back.out(2)' }, '-=0.3')
    })
  }, { scope: root })

  return (
    <section className="privacy" id="privacy" ref={root}>
      <div className="wrap">
        <header className="sec-head">
          <p className="eyebrow">{ar(2, 3)} — الخصوصية</p>
          <h2><span className="thin">صورك</span> <span className="strong">لك وحدك.</span></h2>
        </header>
      </div>
      <div className="p-grid wrap">
        <div className="p-wall" aria-hidden>
          {tiles.map((p, i) => (
            <div className="p-tile" key={i}>
              <Img p={p} sizes="(min-width: 900px) 10vw, 22vw" />
              <Img p={p} v="b" className="p-blur" />
              {p.you && (
                <Brackets className="focus p-you" style={boxStyle(p.you)}>
                  <span className="p-tag">أنت</span>
                </Brackets>
              )}
            </div>
          ))}
        </div>
        <ul className="promises">
          {PROMISES.map(([head, body], i) => (
            <motion.li key={i} initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-10% 0px' }} transition={{ duration: 0.5, delay: i * 0.06 }}>
              <span className="num">{ar(i + 1, 2)}</span>
              {i < 3 ? (
                <p><b>{head}</b> {body}</p>
              ) : (
                <p><b>{head}<span className="placeholder" title="مدة الاحتفاظ لم تُحدَّد بعد">[مدة الاحتفاظ]</span>{body}</b> وبيانات الوجه تُعالج على خوادمنا داخل المملكة، بدون أي خدمة خارجية.</p>
              )}
            </motion.li>
          ))}
          <li className="fine">
            ما نقدر نمنع لقطة الشاشة — ونقولها بوضوح. اللي نضمنه: ما أحد يشوف صورة غيره.
          </li>
        </ul>
      </div>
    </section>
  )
}
