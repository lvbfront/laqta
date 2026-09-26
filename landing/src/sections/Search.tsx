import { useRef } from 'react'
import { useReducedMotion } from 'motion/react'
import { ar, boxStyle, DIR, gsap, matches, others, posIn, useGSAP, type Photo } from '../lib'
import { Brackets, Img, Phone } from '../ui'

const COUNT = 43
// 30 tiles: 9 of his spread through 21 strangers. Same set on every breakpoint;
// CSS reflows it 5×6 on phones and 10×3 on desktop.
const MATCH_AT = [2, 6, 9, 13, 16, 19, 23, 26, 28]
const flying = matches.slice(0, 9)
const tiles: Photo[] = []
{
  let m = 0, o = 0
  for (let i = 0; i < 30; i++) tiles.push(MATCH_AT.includes(i) ? flying[m++] : others[o++])
}
const DECOYS = [0, 4, 11, 17, 21, 25] // strangers the scanner glances at and rejects

const STEPS = [
  'الضيف يلتقط سيلفي. تبقى في الذاكرة لحظة المطابقة، ثم تنمسح.',
  'نقارن وجهه بوجوه كل صور المناسبة.',
  'كل صورة ما هو فيها… تبتعد.',
  'وصلت صوره. هو بس.',
]

function Title() {
  return (
    <header className="sec-head">
      <p className="eyebrow">{ar(1, 3)} — البحث</p>
      <h2><span className="thin">سيلفي وحدة…</span> <span className="strong">لقيناك.</span></h2>
    </header>
  )
}

function Gallery({ slotted }: { slotted: boolean }) {
  // `slotted`: the first 9 cells are empty targets the flying tiles land on.
  return (
    <>
      <div className="gal-head">
        <span className="gal-avatar">{!slotted && <img src="/photos/selfie.webp" alt="" width={36} height={36} />}</span>
        <Brackets className="gal-title">
          <b className="gal-count">{ar(slotted ? 0 : COUNT)}</b> صورة لك
        </Brackets>
      </div>
      <div className="gal-grid">
        {flying.map((p, i) =>
          slotted ? <span className="gal-slot" data-slot={i} key={i} /> : <Img p={p} key={i} sizes="90px" />,
        )}
        <Img p={matches[9]} sizes="90px" />
        <span className="gal-more">{ar(COUNT - matches.length)} صورة ثانية</span>
      </div>
    </>
  )
}

function Wall({ dimmed }: { dimmed?: boolean }) {
  return (
    <div className="s-wall">
      {tiles.map((p, i) => (
        <div className={`s-tile${p.you ? ' is-match' : ''}${dimmed && !p.you ? ' is-dim' : ''}`} data-i={i} key={i}>
          <Img p={p} sizes="(min-width: 900px) 9vw, 18vw" />
          {p.you && <span className="wash" />}
          {p.you && <Brackets className="focus lock" style={boxStyle(p.you, 0.6)} />}
          {DECOYS.includes(i) && p.faces[0] && <Brackets className="focus decoy" style={boxStyle(p.faces[0])} />}
        </div>
      ))}
    </div>
  )
}

function Pinned() {
  const root = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    const stage = root.current!
    const q = gsap.utils.selector(stage)
    const matchTiles = q('.s-tile.is-match') as HTMLElement[]
    const strangers = q('.s-tile:not(.is-match)') as HTMLElement[]
    const slots = q('.gal-slot') as HTMLElement[]
    const selfie = q('.s-selfie')[0] as HTMLElement
    const avatar = q('.gal-avatar')[0] as HTMLElement
    const counter = q('.gal-count')[0] as HTMLElement
    const captions = q('.s-cap')

    // Flight vectors from layout positions (transform-free), recomputed on refresh.
    const fly = (i: number) => {
      const a = posIn(matchTiles[i], stage), b = posIn(slots[i], stage)
      return { x: b.x + b.w / 2 - (a.x + a.w / 2), y: b.y + b.h / 2 - (a.y + a.h / 2), s: b.w / a.w }
    }
    const toAvatar = () => {
      const a = posIn(selfie, stage), b = posIn(avatar, stage)
      return { x: b.x + b.w / 2 - (a.x + a.w / 2), y: b.y + b.h / 2 - (a.y + a.h / 2), s: b.w / a.w }
    }
    const rand = gsap.utils.random(-1, 1, 0.01, true)
    const n = { v: 0 }

    gsap.set(captions.slice(1), { autoAlpha: 0 })
    const tl = gsap.timeline({
      defaults: { ease: 'power2.out' },
      scrollTrigger: {
        trigger: stage,
        pin: true,
        start: 'top top',
        end: () => `+=${innerHeight * (innerWidth < 700 ? 3.2 : 3.6)}`,
        scrub: 0.6,
        invalidateOnRefresh: true,
      },
    })

    // 1 · selfie
    tl.from(selfie, { autoAlpha: 0, scale: 0.7, duration: 1 })
      .from(q('.s-scan'), { yPercent: -100, duration: 1, ease: 'none' }, '<0.3')
      .to(q('.s-scan'), { autoAlpha: 0, duration: 0.3 })
      // 2 · scanning: glance at strangers, then lock onto him
      .addLabel('scan')
      .to(captions[0], { autoAlpha: 0, duration: 0.3 }, 'scan')
      .to(captions[1], { autoAlpha: 1, duration: 0.3 }, 'scan+=0.2')
      .fromTo(q('.decoy'), { autoAlpha: 0, scale: 1.8 }, { autoAlpha: 1, scale: 1, duration: 0.35, stagger: 0.12 }, 'scan')
      .to(q('.decoy'), { autoAlpha: 0, duration: 0.2, stagger: 0.12 }, 'scan+=0.4')
      .fromTo(q('.lock'), { autoAlpha: 0, scale: 2.2 }, { autoAlpha: 1, scale: 1, duration: 0.5, stagger: 0.14, ease: 'back.out(2)' }, 'scan+=0.9')
      // 3 · strangers dim, then fall away
      .addLabel('drop')
      .to(captions[1], { autoAlpha: 0, duration: 0.3 }, 'drop')
      .to(captions[2], { autoAlpha: 1, duration: 0.3 }, 'drop+=0.2')
      .to(strangers, { opacity: 0.22, duration: 0.5, stagger: { each: 0.015, from: 'random' } }, 'drop')
      .to(strangers, {
        y: () => innerHeight * (0.35 + Math.random() * 0.4),
        x: () => rand() * 40 * DIR(),
        rotation: () => rand() * 10,
        autoAlpha: 0,
        duration: 1.2,
        ease: 'power2.in',
        stagger: { each: 0.03, from: 'random' },
      }, 'drop+=0.6')
      // 4 · phone arrives, his photos fly in as washed-out ghosts and develop
      .addLabel('fly', '-=0.5')
      .to(captions[2], { autoAlpha: 0, duration: 0.3 }, 'fly')
      .to(captions[3], { autoAlpha: 1, duration: 0.3 }, 'fly+=0.2')
      .from(q('.s-phone'), { autoAlpha: 0, y: 60, scale: 0.94, duration: 0.8 }, 'fly')
      .to(selfie, { x: () => toAvatar().x, y: () => toAvatar().y, scale: () => toAvatar().s, duration: 1, ease: 'power3.inOut' }, 'fly+=0.3')
      .to(q('.lock'), { autoAlpha: 0, duration: 0.3 }, 'fly+=0.4')
      .to(q('.wash'), { opacity: 0.78, duration: 0.3 }, 'fly+=0.4')
    matchTiles.forEach((t, i) => {
      tl.to(t, { x: () => fly(i).x, y: () => fly(i).y, scale: () => fly(i).s, duration: 1, ease: 'power3.inOut' }, `fly+=${0.5 + i * 0.08}`)
    })
    tl.addLabel('land')
      .to(q('.wash'), { opacity: 0, duration: 0.9, stagger: 0.1, ease: 'power1.inOut' }, 'land-=0.2')
      .to(n, { v: COUNT, duration: 1.2, ease: 'power1.out', onUpdate: () => { counter.textContent = ar(Math.round(n.v)) } }, 'land-=0.4')
      .from(q('.gal-title .bk-ss, .gal-title .bk-se, .gal-title .bk-es, .gal-title .bk-ee'), { autoAlpha: 0, scale: 0.4, duration: 0.4, stagger: 0.05 }, 'land')
      .to({}, { duration: 0.6 }) // hold the finished gallery before unpinning
  }, { scope: root })

  return (
    <div className="s-stage" ref={root}>
      <Title />
      <div className="s-field">
        <Wall />
        <Brackets className="s-selfie">
          <img src="/photos/selfie.webp" alt="سيلفي الضيف" width={180} height={180} />
          <span className="s-scan" aria-hidden />
        </Brackets>
      </div>
      <Phone className="s-phone"><Gallery slotted /></Phone>
      <ol className="s-caps">
        {STEPS.map((s, i) => <li className="s-cap" key={i}><b>{ar(i + 1)}</b>{s}</li>)}
      </ol>
    </div>
  )
}

/** prefers-reduced-motion: the same story as three still frames. */
function Static() {
  return (
    <div className="s-static wrap">
      <Title />
      <ol className="s-frames">
        <li>
          <Brackets className="s-selfie is-static"><img src="/photos/selfie.webp" alt="سيلفي الضيف" width={180} height={180} /></Brackets>
          <p><b>{ar(1)}</b>{STEPS[0]}</p>
        </li>
        <li>
          <Wall dimmed />
          <p><b>{ar(2)}</b>{STEPS[1]} {STEPS[2]}</p>
        </li>
        <li>
          <Phone className="s-phone is-static"><Gallery slotted={false} /></Phone>
          <p><b>{ar(3)}</b>{STEPS[3]}</p>
        </li>
      </ol>
    </div>
  )
}

export function Search() {
  const reduce = useReducedMotion()
  return (
    <section className="search" id="search" aria-label="كيف نلقى صورك">
      {reduce ? <Static /> : <Pinned />}
    </section>
  )
}
