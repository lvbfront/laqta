import { motion } from 'motion/react'
import { ar, ASSISTANT_URL } from '../lib'
import { Brackets } from '../ui'

type Msg = { me?: boolean; text: string; card?: boolean }
const CHAT: Msg[] = [
  { me: true, text: `عندنا حفل تخرّج يوم الخميس، من ${ar(7)} المغرب لين ${ar(11)}. أبي أحجز التفعيل.` },
  { text: 'أبشر. هذي فترة التفعيل المقترحة:', card: true },
  { me: true, text: 'تمام، أكّد. والحفل نسائي — الصور تطلع للضيوف قبل المراجعة؟' },
  { text: 'لا. في الوضع المشدّد ما تظهر أي صورة قبل ما تنعتمد. تبي أحوّلك لأحد من الفريق عشان التفاصيل؟' },
]

export function Organizers() {
  return (
    <section className="org" id="organizers">
      <div className="wrap o-grid">
        <div className="o-copy">
          <header className="sec-head">
            <p className="eyebrow">{ar(5, 3)} — للمنظّمين</p>
            <h2><span className="thin">تنظّم المناسبة؟</span> <span className="strong">احجز واسأل.</span></h2>
          </header>
          <p className="lede">إذا كنت الجهة المنظّمة، مساعد لقطة يتولّى الحجز معك بالمحادثة:</p>
          <ul className="ticks">
            <li>يحجز فترة التفعيل لمناسبتك، ويعدّلها أو يلغيها.</li>
            <li>يجاوبك عن الباقات والخصوصية من مستندات لقطة.</li>
            <li>ولو احتجت أحد من الفريق، يحوّلك له.</li>
          </ul>
          <p className="note">المساعد مخصّص للمنظّمين. المصوّرون يبدؤون من حسابهم مباشرة.</p>
          <a className="btn ghost" href={ASSISTANT_URL}>اسأل مساعد لقطة</a>
        </div>

        <div className="chat" aria-label="مثال محادثة مع مساعد لقطة">
          <div className="chat-head"><span className="dot" /> مساعد لقطة <small>للمنظّمين</small></div>
          <ol>
            {CHAT.map((m, i) => (
              <motion.li key={i} className={m.me ? 'me' : 'bot'} initial={{ opacity: 0, y: 14, scale: 0.98 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={{ once: true, margin: '-10% 0px' }} transition={{ delay: 0.25 + i * 0.45, duration: 0.35 }}>
                <p>{m.text}</p>
                {m.card && (
                  <Brackets className="slot-card">
                    <span className="slot-label">فترة التفعيل</span>
                    <b>الخميس</b>
                    <span className="slot-time">{ar(7)}:{ar(0, 2)} م — {ar(11)}:{ar(0, 2)} م</span>
                    <span className="slot-state">بانتظار تأكيدك</span>
                  </Brackets>
                )}
              </motion.li>
            ))}
          </ol>
          <p className="chat-foot">مثال توضيحي للمحادثة</p>
        </div>
      </div>
    </section>
  )
}
