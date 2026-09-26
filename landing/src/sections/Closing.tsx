import { motion, useInView, useReducedMotion } from 'motion/react'
import { useRef } from 'react'
import { ar, ASSISTANT_URL, SIGNUP_URL } from '../lib'
import { Brackets } from '../ui'

const PLANS = [
  {
    who: 'للمصوّرين',
    kind: 'اشتراك',
    points: ['معرض يحمل اسمك وشعارك وطريقة التواصل معك', 'رفع مباشر أثناء المناسبة', 'كل ضيف يلقى صوره بالوجه'],
    cta: ['ابدأ أول مناسبة مجاناً', SIGNUP_URL],
  },
  {
    who: 'للمنظّمين',
    kind: 'لكل مناسبة',
    points: ['حجز فترة التفعيل عبر مساعد لقطة', 'وضع خصوصية مشدّد لمناسبات النساء', 'حذف تلقائي بعد مدة الاحتفاظ'],
    cta: ['اسأل مساعد لقطة', ASSISTANT_URL],
  },
] as const

const FAQ: [string, string][] = [
  ['هل تنحفظ صورة السيلفي؟', 'لا. تُستخدم للمطابقة لحظتها ثم تنمسح. ما تنكتب على قرص، ولا تنحفظ في ملف أو سجل.'],
  ['يقدر أحد يتصفّح كل صور المناسبة؟', 'لا، ولا أي دور في النظام. المراجِع يشوف الصور اللي تنتظر الاعتماد فقط، وكل ضيف يشوف الصور اللي هو فيها فقط.'],
  ['وين تنعالج بيانات الوجه؟', 'على خوادمنا، بدون أي خدمة خارجية للتعرّف على الوجوه. وبيانات الوجه ما تطلع من المملكة.'],
  ['كم تبقى الصور؟', 'تنحذف تلقائياً بعد [مدة الاحتفاظ] من نهاية المناسبة.'],
  ['أحتاج كاميرا معيّنة؟', 'لا. ترفع من مجلد على جهازك عبر برنامج لقطة، أو مباشرة عبر FTP إذا كانت كاميرتك تدعمه.'],
]

function Placeholdered({ text }: { text: string }) {
  const [a, b] = text.split('[مدة الاحتفاظ]')
  return b === undefined ? <>{text}</> : <>{a}<span className="placeholder" title="مدة الاحتفاظ لم تُحدَّد بعد">[مدة الاحتفاظ]</span>{b}</>
}

export function Closing() {
  const ctaRef = useRef<HTMLDivElement>(null)
  const seen = useInView(ctaRef, { once: true, amount: 0.6 })
  const reduce = useReducedMotion()

  return (
    <>
      <section className="pricing" id="pricing">
        <div className="wrap">
          <header className="sec-head">
            <p className="eyebrow">{ar(6, 3)} — الأسعار</p>
            <h2><span className="thin">الأسعار</span> <span className="strong">قريباً.</span></h2>
          </header>
          <div className="plans">
            {PLANS.map((p) => (
              <motion.article className="plan" key={p.who} whileHover={{ y: -4 }} transition={{ type: 'spring', stiffness: 300, damping: 24 }}>
                <p className="plan-who">{p.who}</p>
                <p className="plan-kind">{p.kind}</p>
                <Brackets className="plan-price"><span>قريباً</span></Brackets>
                <ul className="ticks">{p.points.map((x) => <li key={x}>{x}</li>)}</ul>
                <a className="btn ghost" href={p.cta[1]}>{p.cta[0]}</a>
              </motion.article>
            ))}
          </div>
        </div>
      </section>

      <section className="faq" id="faq">
        <div className="wrap faq-grid">
          <header className="sec-head">
            <p className="eyebrow">{ar(7, 3)} — أسئلة</p>
            <h2><span className="thin">أسئلة</span> <span className="strong">متكررة.</span></h2>
          </header>
          <div>
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>{q}</summary>
                <p><Placeholdered text={a} /></p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="final" id="start">
        <div ref={ctaRef} className="final-inner wrap">
          <Brackets className="final-frame">
            <h2><span className="thin">المناسبة الجاية…</span> <span className="strong">لقيناك.</span></h2>
          </Brackets>
          <p className="lede">أول مناسبة علينا. ارفع، وخلّ كل ضيف يلقى صوره.</p>
          <motion.a className="btn" href={SIGNUP_URL} whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>ابدأ أول مناسبة مجاناً</motion.a>
        </div>
        {!reduce && (
          <motion.div className="flash" aria-hidden initial={{ opacity: 0 }} animate={seen ? { opacity: [0, 0.92, 0] } : { opacity: 0 }} transition={{ duration: 0.55, times: [0, 0.12, 1], ease: 'easeOut' }} />
        )}
      </section>

      <footer className="foot wrap">
        <span className="logo">لقطة</span>
        <p>الصور في هذه الصفحة توضيحية من Unsplash. الأسماء والمحادثات أمثلة.</p>
      </footer>
    </>
  )
}
