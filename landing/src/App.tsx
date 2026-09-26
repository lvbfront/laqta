import { useEffect } from 'react'
import { MotionConfig } from 'motion/react'
import { ar, ScrollTrigger, SIGNUP_URL } from './lib'
import { Hero } from './sections/Hero'
import { Search } from './sections/Search'
import { Privacy } from './sections/Privacy'
import { Brand } from './sections/Brand'
import { How } from './sections/How'
import { Organizers } from './sections/Organizers'
import { Closing } from './sections/Closing'

const NAV = [
  ['search', 'البحث'],
  ['privacy', 'الخصوصية'],
  ['brand', 'علامتك'],
  ['how', 'الطريقة'],
  ['organizers', 'للمنظّمين'],
  ['pricing', 'الأسعار'],
]

export default function App() {
  // Webfont swap changes line heights; re-measure pins once fonts settle.
  useEffect(() => { document.fonts.ready.then(() => ScrollTrigger.refresh()) }, [])

  return (
    <MotionConfig reducedMotion="user">
      <nav className="nav">
        <a className="logo" href="#top">لقطة</a>
        <ol>
          {NAV.map(([id, label], i) => (
            <li key={id}><a href={`#${id}`}><span>{ar(i + 1, 3)}</span>{label}</a></li>
          ))}
        </ol>
        <a className="btn small" href={SIGNUP_URL}>ابدأ مجاناً</a>
      </nav>
      <main>
        <Hero />
        <Search />
        <Privacy />
        <Brand />
        <How />
        <Organizers />
        <Closing />
      </main>
    </MotionConfig>
  )
}
