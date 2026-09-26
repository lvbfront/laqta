import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ar, boxStyle, matches, others, type Photo } from '../lib'
import { Brackets, Img } from '../ui'

/** Decorative QR-like mark. Deliberately not a real code: nothing to scan. */
function QrMark() {
  const N = 21, cells: [number, number][] = []
  let s = 7
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647)
  const finder = (x: number, y: number) => x < 7 && y < 7
  for (let y = 0; y < N; y++)
    for (let x = 0; x < N; x++)
      if (!finder(x, y) && !finder(N - 1 - x, y) && !finder(x, N - 1 - y) && rnd() > 0.52) cells.push([x, y])
  const Finder = ({ x, y }: { x: number; y: number }) => (
    <g transform={`translate(${x} ${y})`}>
      <rect width="7" height="7" fill="currentColor" /><rect x="1" y="1" width="5" height="5" fill="var(--paper)" /><rect x="2" y="2" width="3" height="3" fill="currentColor" />
    </g>
  )
  return (
    <svg viewBox={`-1 -1 ${N + 2} ${N + 2}`} className="qr" aria-hidden>
      <rect x="-1" y="-1" width={N + 2} height={N + 2} fill="var(--paper)" />
      {cells.map(([x, y]) => <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="currentColor" />)}
      <Finder x={0} y={0} /><Finder x={N - 7} y={0} /><Finder x={0} y={N - 7} />
    </svg>
  )
}

const guest = matches[2]

type Step = { verb: string; who: string; body: string; art: ReactNode }

function Upload({ picks, fill }: { picks: Photo[]; fill: number }) {
  return (
    <div className="h-upload">
      {picks.map((p, i) => <Img p={p} key={i} sizes="120px" className={`h-u${i}`} />)}
      {/* In-view is watched on the track: the fill starts at scaleX(0), which has no area to intersect. */}
      <motion.span className="h-bar" initial="off" whileInView="on" viewport={{ once: true }}>
        <motion.i variants={{ off: { scaleX: 0 }, on: { scaleX: fill } }} transition={{ duration: 1.4, ease: 'easeOut', delay: 0.3 }} />
      </motion.span>
    </div>
  )
}

function Found() {
  return (
    <div className="h-found">
      <Img p={guest} sizes="200px" />
      <Brackets className="focus" style={boxStyle(guest.you!)} />
      <svg className="h-pencil" style={boxStyle(guest.you!, 1.3)} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        <motion.path d="M50 6 C 80 6, 96 26, 94 52 C 92 80, 70 95, 46 94 C 20 93, 5 74, 6 48 C 7 24, 26 8, 56 9" initial={{ pathLength: 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: 0.9, delay: 0.5, ease: 'easeInOut' }} />
      </svg>
    </div>
  )
}

/** One link in a chat bubble. Deliberately no real URL. */
function LinkBubble() {
  return (
    <div className="h-link">
      <p>صور المناسبة جاهزة. افتح الرابط والتقط سيلفي:</p>
      <Brackets className="h-link-chip"><span>رابط الألبوم</span></Brackets>
    </div>
  )
}

const MODES: { id: string; label: string; soon?: boolean; steps: Step[] }[] = [
  {
    id: 'live',
    label: 'مباشر أثناء المناسبة',
    steps: [
      {
        verb: 'ارفع',
        who: 'المصوّر',
        body: 'ارفع الصور أول بأول أثناء المناسبة — من مجلد على جهازك عبر برنامج لقطة، أو مباشرة من الكاميرا عبر FTP.',
        art: <Upload picks={[others[3], others[8], others[12]]} fill={0.72} />,
      },
      {
        verb: 'يمسح الكود',
        who: 'الضيف',
        body: 'على الطاولة أو في الدعوة. يوافق على الشروط، ويلتقط سيلفي من المتصفح — بدون تحميل تطبيق.',
        art: <Brackets className="h-qr"><QrMark /></Brackets>,
      },
      {
        verb: 'يلقى صوره',
        who: 'الضيف',
        body: 'يوصله معرض فيه الصور اللي هو فيها بس، باسمك وشعارك. وكل ما رفعت صور جديدة فيها وجهه، تنضاف له.',
        art: <Found />,
      },
    ],
  },
  {
    id: 'link',
    label: 'بعد المناسبة برابط',
    soon: true,
    steps: [
      {
        verb: 'ارفع بعد المناسبة',
        who: 'المصوّر',
        body: 'في آخر اليوم، ترفع كل صور المناسبة دفعة وحدة.',
        art: <Upload picks={[others[20], others[25], others[30]]} fill={1} />,
      },
      {
        verb: 'أرسل رابط واحد',
        who: 'المصوّر',
        body: 'رابط واحد لكل الضيوف — في قروب واتساب أو رسالة. بدون كود على الطاولة.',
        art: <LinkBubble />,
      },
      {
        verb: 'يلقى ألبومه',
        who: 'الضيف',
        body: 'يفتح الرابط ويلتقط سيلفي، ويتكوّن له ألبوم فيه الصور اللي هو فيها بس.',
        art: <Found />,
      },
    ],
  },
]

export function How() {
  const [m, setM] = useState(0)
  const mode = MODES[m]
  return (
    <section className="how" id="how">
      <div className="wrap">
        <header className="sec-head">
          <p className="eyebrow">{ar(4, 3)} — الطريقة</p>
          <h2><span className="thin">ثلاث لقطات.</span> <span className="strong">بس.</span></h2>
        </header>
        <div className="b-tabs h-tabs" role="tablist" aria-label="طريقة التسليم">
          {MODES.map((x, k) => (
            <button key={x.id} role="tab" aria-selected={k === m} aria-controls="how-sheet" className={k === m ? 'on' : ''} onClick={() => setM(k)}>
              {k === m && <motion.span layoutId="mode-pill" className="b-pill" />}
              <span className="b-label">{x.label}{x.soon && <small className="soon">قريباً</small>}</span>
            </button>
          ))}
        </div>
        <AnimatePresence mode="wait" initial={false}>
          {mode.soon && (
            <motion.p key="soon" className="h-soon" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              قريباً — هذا الوضع قيد التطوير، وما هو متاح حالياً.
            </motion.p>
          )}
        </AnimatePresence>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.ol id="how-sheet" role="tabpanel" className={`sheet wrap${mode.soon ? ' is-soon' : ''}`} key={mode.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
          {mode.steps.map((s, i) => (
            <motion.li className="frame" key={i} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-15% 0px' }} transition={{ duration: 0.55, delay: i * 0.12 }}>
              <div className="frame-art">{s.art}</div>
              <div className="frame-meta">
                <span className="frame-no">{ar(i + 1, 3)}</span>
                <span className="frame-who">{mode.soon && <b className="soon">قريباً</b>}{s.who}</span>
              </div>
              <h3>{s.verb}</h3>
              <p>{s.body}</p>
            </motion.li>
          ))}
        </motion.ol>
      </AnimatePresence>
    </section>
  )
}
