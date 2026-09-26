# landing — Laqta marketing page

Arabic, RTL-first landing page for Laqta. Vite + React + TypeScript, GSAP
(ScrollTrigger) for everything tied to scroll position, Motion
(`motion/react`) for enter/exit, hover, layout transitions and the phone UI.
No library ever animates an element the other one owns.

```bash
cd landing
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production build into dist/
npm run preview    # serve dist/
```

## Sections

| # | Section | Animated by |
|---|---------|-------------|
| 1 | Hero — drifting photo wall, roaming focus box | CSS keyframes (drift), Motion (box, copy) |
| 2 | The search — pinned sequence (`src/sections/Search.tsx`) | GSAP + ScrollTrigger |
| 3 | Privacy — same wall, every face blurred except his | GSAP (scroll-linked blur), Motion (promises) |
| 4 | Your brand — phone gallery re-skins across 3 fictional studios | Motion (`layoutId`, `layout`) |
| 5 | How it works — contact sheet, 3 frames; two modes: live QR, and after-the-event link («قريباً») | Motion |
| 6 | For organizers — activation window + مساعد لقطة chat | Motion |
| 7 | Pricing «قريباً», FAQ (native `<details>`), final CTA with shutter flash | Motion |

Every sequence has a reduced-motion version: section 2 swaps the pin for a
three-frame storyboard, section 3 renders already blurred, the hero wall stops,
the brand phone stops auto-rotating, and Motion drops transforms globally
(`MotionConfig reducedMotion="user"`).

## References

- **seemecreative.com** — used: photo-led layouts, editorial grids, mixed-weight
  headlines (as weight + colour, not outline text), corner-bracket labels (built
  as a CSS component, `Brackets` in `src/ui.tsx`), small numbered labels, the
  "develop-in" fade.
- **techredux.co — not used.** The site renders almost entirely into a WebGL
  canvas that showed only a background grid in the test browser, so its scroll
  storytelling could not be seen. Pacing was taken from the GSAP ScrollTrigger
  docs instead.

## Placeholders to fill

- `SIGNUP_URL` and `ASSISTANT_URL` in `src/lib.ts` point at on-page anchors.
- «[مدة الاحتفاظ]» (retention period) appears in section 3, the organizer
  pricing card and the FAQ, styled as a visible placeholder. No number was
  invented.
- «٤٣ صورة لك» is the demo count from the brief, not a statistic.

## Photos

`public/photos/` holds 61 Unsplash photos (Unsplash License), all men only,
each checked by eye, sharp and blurred. They are cropped to 4:5, re-encoded to
WebP at 320/640px with no EXIF, plus a blurred 320px variant per photo.
`src/data/photos.json` carries normalised face boxes.

They were produced by `scripts/prep_photos.py`, which runs the same local
InsightFace `buffalo_l` pack as the product. The demo guest is one real man
who appears in 13 photos of a single Unsplash shoot (by eightysixmedia), found
and confirmed by embedding similarity, so the focus boxes land on his actual
face. The blurred variants blur the whole frame and restore only his face,
because the detector misses small and turned faces and the privacy section
can't leak one.

Photographers: 24ameer, 256p, ahmadossayli, al_kaium, alkhnaifer1991, antreinas, aranprime, bahr_splash, c_vara, chriscreations__, coleito, eightysixmedia, heathamilla, iamjhunelle, jakobnoahrosen, jakobowens1, jentheodore, jeremiahdelmar, kouki_walims, lanceplaine, levimeirclancy, manuelfigueroa, mjphotography05, moninak, mrgreatheart, nischalm, numaninsari, olivialu10, paupattersonphotography_, rizsam, royalfoto, rumanamin, sambalye, sammyswae, shalom_ej, shotbyriki, stewardesign, the_gallery, xodusdigitals — all on unsplash.com.

## Dev-only switches

`src/dev.ts` is stripped from production builds.

- `?rm=1` emulates `prefers-reduced-motion` (patches `matchMedia` + mirrors the
  CSS block) for testing without changing the OS setting.
- `?shot=1` sets Motion's `skipAnimations`, for screenshots from a
  background tab.
- `window.__ST` is ScrollTrigger, for driving scroll states from the console.

`screenshots/` has every section at 390px and 1440px.
