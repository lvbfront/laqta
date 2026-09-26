"""One-off: turn Unsplash sources into the landing page's photo set.

Detects faces with the same local buffalo_l pack the product uses, crops every
photo to 4:5 around its faces, writes 320/640px WebP (cv2 writes no EXIF, so no
GPS survives), writes a whole-frame-blurred 320px copy with only the demo
guest's face kept sharp for the privacy section, and emits src/data/photos.json with normalised face boxes.

Run from a venv with insightface/onnxruntime/opencv (see api/requirements.txt):
  python scripts/prep_photos.py <sources_dir> <manifest.json>
manifest: {"matches": [id...], "anchor": [id, face_index], "others": [id...], "credits": {id: user}}
"""
import json, sys, cv2, numpy as np
from pathlib import Path
from insightface.app import FaceAnalysis

src, manifest = Path(sys.argv[1]), json.load(open(sys.argv[2]))
out = Path(__file__).resolve().parent.parent / 'public' / 'photos'
out.mkdir(parents=True, exist_ok=True)
app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'], providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))

def faces(im):
    return [f for f in app.get(im) if f.det_score > 0.6]

ak, ai = manifest['anchor']
anchor = faces(cv2.imread(str(src / f'{ak}.jpg')))[ai].normed_embedding

def crop45(im, focus):
    h, w = im.shape[:2]
    if w / h > 0.8:
        cw, ch = int(h * 0.8), h
    else:
        cw, ch = w, int(w / 0.8)
    fx, fy = focus
    x0 = int(min(max(fx * w - cw / 2, 0), w - cw))
    y0 = int(min(max(fy * h - ch * 0.4, 0), h - ch))
    return x0, y0, cw, ch

records, selfie = [], None
for pid in manifest['matches'] + manifest['others']:
    im = cv2.imread(str(src / f'{pid}.jpg'))
    H, W = im.shape[:2]
    fs = faces(im)
    if not fs:
        continue
    you = None
    if pid in manifest['matches']:
        sims = [float(f.normed_embedding @ anchor) for f in fs]
        best = int(np.argmax(sims))
        if sims[best] < 0.4 or (fs[best].bbox[2] - fs[best].bbox[0]) / W < 0.035:
            print('skip weak match', pid); continue
        you = best
    focus_face = fs[you] if you is not None else max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]))
    b = focus_face.bbox
    x0, y0, cw, ch = crop45(im, ((b[0] + b[2]) / 2 / W, (b[1] + b[3]) / 2 / H))
    boxes, you_box = [], None
    for i, f in enumerate(fs):
        fx0, fy0, fx1, fy1 = f.bbox
        cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
        if not (x0 <= cx < x0 + cw and y0 <= cy < y0 + ch):
            continue
        box = [round(float(v), 4) for v in ((fx0 - x0) / cw, (fy0 - y0) / ch, (fx1 - fx0) / cw, (fy1 - fy0) / ch)]
        if i == you:
            you_box = box
        else:
            boxes.append(box)
    crop = im[y0:y0 + ch, x0:x0 + cw]
    n = len(records)
    for size, tag in ((320, 's'), (640, 'm')):
        r = cv2.resize(crop, (size, int(size * 1.25)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out / f'{n:02d}-{tag}.webp'), r, [cv2.IMWRITE_WEBP_QUALITY, 72])
    small = cv2.resize(crop, (320, 400), interpolation=cv2.INTER_AREA)
    # Blur the whole frame — the detector misses small and turned faces, and a
    # privacy promise can't leak one. In his photos, restore only his face.
    blurred = cv2.GaussianBlur(small, (0, 0), 9)
    if you_box:
        x, y, w, h = you_box
        pad = 0.45
        bx0, by0 = max(int((x - w * pad) * 320), 0), max(int((y - h * pad) * 400), 0)
        bx1, by1 = min(int((x + w * (1 + pad)) * 320), 320), min(int((y + h * (1 + pad)) * 400), 400)
        blurred[by0:by1, bx0:bx1] = small[by0:by1, bx0:bx1]
    cv2.imwrite(str(out / f'{n:02d}-b.webp'), blurred, [cv2.IMWRITE_WEBP_QUALITY, 72])
    rec = {'n': n, 'faces': boxes, 'credit': manifest['credits'].get(pid, ''), 'unsplash': pid}
    if you_box:
        rec['you'] = you_box
        fw = focus_face.bbox[2] - focus_face.bbox[0]
        if selfie is None or fw > selfie[0]:
            selfie = (fw, im, focus_face.bbox)
    records.append(rec)

# The demo "selfie": a square crop of his largest face. Marketing asset only.
_, im, b = selfie
cx, cy, s = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]) * 2.2
x0, y0 = int(max(cx - s / 2, 0)), int(max(cy - s * 0.45, 0))
sq = im[y0:y0 + int(s), x0:x0 + int(s)]
cv2.imwrite(str(out / 'selfie.webp'), cv2.resize(sq, (360, 360), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_WEBP_QUALITY, 78])

dest = out.parent.parent / 'src' / 'data' / 'photos.json'
dest.parent.mkdir(parents=True, exist_ok=True)
json.dump(records, open(dest, 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(records), 'photos,', sum('you' in r for r in records), 'matches')
