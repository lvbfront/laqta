# Camera day: Sony ZV-E10 → Laqta

Goal: the photographer's ZV-E10 sends shots to this Mac, laqta_agent uploads them, and a guest's selfie finds them, all on a phone hotspot.

**Model not yet confirmed.** The original ZV-E10 and the ZV-E10 II have different menus. Both are covered below; step 0 of the checklist tells them apart.

Sources are Sony's official help guides and Sony's Imaging Edge support site. Short names used below:

| Short name | URL |
|---|---|
| **[E10]** ZV-E10 Help Guide | https://helpguide.sony.net/ilc/2070/v1/en/ (PDF: https://helpguide.sony.net/ilc/2070/v1/en/print.pdf; "p.N" = PDF page) |
| **[E10-PCR]** E10 "Operating the camera from a computer (PC Remote Function)" | https://helpguide.sony.net/ilc/2070/v1/en/contents/TP0002392805.html |
| **[E10II]** ZV-E10M2 Help Guide | https://helpguide.sony.net/ilc/2430/v1/en/ (PDF: …/2430/v1/en/print.pdf) |
| **[IED-CONN]** Imaging Edge "Connecting the camera to the computer" | https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/4_1_connection.php |
| **[IED-PANEL]** Imaging Edge "Operation panel" | https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/4_3_panels.php |
| **[IED-SHOOT]** Imaging Edge "Remote Shooting" | https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/4_5_remote.php |
| **[IED-FAQ]** Imaging Edge FAQ | https://support.d-imaging.sony.co.jp/app/imagingedge/en/faqs/ |
| **[IED-ENV]** Recommended environment | https://support.d-imaging.sony.co.jp/www/disoft/int/pcenv/en/contents/index.html |
| **[IED-DEV]** Supported devices | https://support.d-imaging.sony.co.jp/app/imagingedge/en/devices/ |

## Answers (verified vs not)

| Question | Answer | Source |
|---|---|---|
| Does Imaging Edge Desktop (Remote) run on this Mac? | **Yes.** Mac requirement is "macOS 14/macOS 15/macOS 26"; this Mac runs macOS 26.5.1. The installed `/Applications/Imaging Edge/Remote.app` (`com.sony.Remote`) is a universal binary (`x86_64 arm64`), so it runs natively on Apple Silicon, without Rosetta. | [IED-ENV]; `lipo -archs` on the installed app |
| Is it installed? | **Yes** (2026-10-06): Imaging Edge Desktop 1.2.02, with Remote at `/Applications/Imaging Edge/Remote.app`, allowed under Privacy & Security → Local Network. | checked on this Mac |
| Do both cameras support Remote over Wi-Fi? | **Yes.** Both the ZV-E10 and ZV-E10M2 are listed with Remote Shooting over USB ✓ and Wi-Fi ✓ (no wired LAN). | [IED-DEV] (E-mount table) |
| macOS 26 caveat | Sony: "Using the Remote function with a **USB connection may not operate correctly** on systems running this version of macOS." This weakens the USB fallback on this Mac. | [IED-FAQ] "Remote cannot recognize the camera" |
| macOS permission | On macOS 15+, Remote must be allowed under **System Settings → Privacy & Security → Local Network**, or it won't find the camera. If it's already on, toggle it off and on. | [IED-CONN], [IED-FAQ] |
| **When the photographer presses the camera's own shutter button during PC Remote, is the photo transferred to the Mac?** | **Unverified.** Sony's pages only describe shooting by clicking the Photo button in Remote ([IED-SHOOT]); none says what happens with the body's shutter button. **Test this first on the day (checklist step 7).** | none |
| Setting for where stills are saved | **ZV-E10:** MENU → (Network) → [PC Remote Function] → [Still Img. Save Dest.] = [PC Only] / [PC+Camera] / [Camera Only]. **ZV-E10 II:** MENU → (Network) → [Cnct./Remote Sht.] → [Remote Shoot Setting] → [Still Img. Save Dest.] = [Destination Only] / [Dest.+Camera] / [Camera Only]. | [E10-PCR]; [E10II] p.496 |
| What to choose | **PC+Camera** (E10) / **Dest.+Camera** (E10 II): the SD card keeps a backup, which is the SD-copy fallback below. Sony notes that with these options and no card in the camera, "the shutter will not be released", so **put a card in**. Never choose Camera Only: as the name says, nothing is saved to the Mac (Sony also notes those shots don't appear under [Remote shots] in Viewer). | [E10-PCR] Note; [E10II] p.496; [IED-SHOOT] Hint |
| Where Imaging Edge saves files | Remote's **Image Save Settings panel** sets the destination folder ("Save in") and an optional file-name prefix. Sony's own FAQ uses this folder as a hot folder for Capture One and Lightroom, which is exactly our pattern. **Default folder: unverified.** Sony doesn't document it, and Remote stores no save folder until a camera has connected (checked: its preferences hold none yet). The Remote binary contains the string `Pictures`, which suggests a folder under `~/Pictures`, but that's an inference. Don't rely on the default; set it explicitly. | [IED-PANEL]; [IED-FAQ] "external programs" |
| How to point it at our folder | In Remote, set **Save in** to **`/Users/awb/Pictures/laqta-inbox`** (already created). In the agent, choose **the same folder** when it asks. The agent watches subfolders too, so it doesn't matter if Remote creates a dated subfolder inside it (tested). **Don't** choose `~/Pictures` itself: the agent would also upload any other JPEGs already in there. | `agent/tests/test_watcher_scenarios.py` |
| File format | **JPEG only.** ZV-E10: [File Format] = [JPEG] ([E10] p.124). **ZV-E10 II: also set [JPEG/HEIF Switch] = [JPEG]** ([E10II] p.259). The agent uploads only `.jpg`/`.jpeg` (`agent/laqta_agent/config.py:29`), so **HEIF shots would be silently ignored**. If the photographer insists on RAW+JPEG: the agent skips `.ARW` (tested), but use [RAW+J PC Save Img] = [JPEG Only] ([E10-PCR]) so RAW doesn't clog the Wi-Fi. | cited |
| Which size | [JPEG Image Size] = **L: 24M (6000×4000)** at 3:2 ([E10] p.126). Quality: Fine. "PC Save Image Size" can send a **2M** JPEG instead of the original, but only in PC+Camera ([E10-PCR]; E10 II: [Save Image Size], p.496). 2M transfers faster, but guests would download a 2 MP file and small faces in group shots get fewer pixels. Use 2M only if Original is too slow. | cited |
| How long one shot takes over Wi-Fi | **Unverified.** Sony publishes no figure. Measure it on the day: `scripts/camera_check` prints when each file lands, relative to the shot. Locally, the landed → uploaded hop measured 1.3–2 s (mostly the agent's 1 s × 2 stability check). | measure |
| FTP transfer? | **No, on either model.** The ZV-E10 help guide (589 pages) never mentions FTP. The ZV-E10 II guide's only match is a URL path `…/di/sftp/…` on a page about RTMPS streaming encryption, not an FTP feature. | [E10] and [E10II] full text |
| Wi-Fi band | **ZV-E10: 2.4 GHz only** (IEEE 802.11 b/g/n, [E10] p.581). ZV-E10 II: 2.4/5 GHz on "models supporting 5 GHz", 2.4 GHz on others ([E10II] pp.544–545). **The hotspot must offer 2.4 GHz.** | cited |

## Connecting on a phone hotspot (primary route)

**Before you start, on the phone:** turn the hotspot on with a WPA2/WPA3 password; Sony strongly recommends WPA2 or WPA3 ([E10-PCR] Note; [E10II] p.442). Make sure it offers **2.4 GHz**. On an iPhone, Apple's "Maximize Compatibility" switch does this. That's an Apple setting, **not from Sony's docs; unverified on the phone you'll use.**

### ZV-E10 (original), from [E10-PCR] and [IED-CONN]
1. MENU → (Network) → [Smartphone Connect] → [Smartphone Connection] → **[Off]** (Sony: do this beforehand).
2. MENU → (Network) → [Wi-Fi Settings] → **[Access Point Set.]** → pick the hotspot SSID → enter the password → [OK] ([E10] "Access Point Set.", https://helpguide.sony.net/ilc/2070/v1/en/contents/TP0001117109.html). [WPS Push] is the alternative; whether phones support WPS is **unverified**, so use Access Point Set.
3. MENU → (Network) → [PC Remote Function] → [PC Remote Cnct Method] → **[Wi-Fi Access Point]**, then [PC Remote] → **[On]**.
4. Join the Mac to the **same hotspot**.
5. Wait for **"Connected via Wi-Fi."** on the camera, then [PC Remote Function] → **[Pairing]**.
6. On the Mac, launch **Remote**, double-click the camera in the Device selection window ([Refresh] if it's missing), and follow Remote's pairing messages. Select **[OK]** on the camera's pairing confirmation screen.

Pairing info is deleted if the camera is initialized ([E10-PCR]).

### ZV-E10 II, from [E10II] p.510 and [IED-CONN]
1. Make sure the camera is not connected to a smartphone ([E10II] p.510).
2. MENU → (Network) → [Wi-Fi] → [Wi-Fi Connect] → **[On]**. If the hotspot isn't found, use [Access Point Set.] ([E10II] p.442).
3. MENU → (Network) → [Cnct./Remote Sht.] → [Remote Shoot Function] → [Remote Shooting] → **[On]**.
4. Select **[Access Authen. Info]** to show the username, password and fingerprint. If no prompt appears: [Network Option] → [Access Authen. Settings] → [Access Authen.] → [On], then [Access Authen. Info].
5. Join the Mac to the same hotspot. Launch Remote, double-click the camera, enter the username and password, check that the fingerprint matches the camera, then click **[Connect]**.

### If they can't see each other (in this order)
1. Smartphone connection is **off** on the camera ([E10-PCR]; [E10II] p.510).
2. Remote is allowed under **Privacy & Security → Local Network**. Toggle it off and on ([IED-FAQ]).
3. Click **[Refresh]** in Remote's device list ([IED-CONN]).
4. Quit any other camera or cloud-storage app, wait about 1 minute, and relaunch Remote ([IED-FAQ]).
5. Hotspot is on **2.4 GHz** (ZV-E10 is 2.4 GHz only, [E10] p.581).
6. Both devices are on the same network:
   - Camera: [Display Wi-Fi Info.]. On the ZV-E10 the IP only shows once PC Remote over an access point is connected ([E10] p.337); on the ZV-E10 II it shows when Wi-Fi Connect is On (p.447).
   - Mac: run `ipconfig getifaddr en0`. The first three numbers should match.
   - Run `ping <camera IP>` from the Mac. If ping fails while both are joined, the hotspot may isolate its clients. That's **unverified, not from Sony**; try another phone, or fall back.
7. Re-pair (E10), or re-enter the access authentication info (E10 II).

## Laqta settings for the hotspot

- **Photographer-side only (camera → Mac → upload):** nothing to change. Everything uses `localhost`.
- **Guest selfie: do it on the Mac**, at `http://localhost:3000/e/<qr_token>` in the Mac's own browser (uses the Mac's webcam).
- **A phone on the hotspot can't run the guest flow in dev.** Postgres, Redis and MinIO are bound to `127.0.0.1` (`docker-compose.yml`), so nothing on the hotspot can reach them. Gallery images are presigned MinIO URLs that the guest's browser loads directly from MinIO, so a phone would get broken images. Separately, phone browsers only open the camera on `https://` or `localhost`. Testing from a phone needs either images served through the API or an HTTPS setup; neither is built.
- **What the hotspot can reach:** only the API (`:8000`) and the web dev server (`:3000`). Postgres, Redis, MinIO and FTPS are bound to `127.0.0.1` (`docker-compose.yml`); `scripts/health_check` checks this from the Mac's LAN IP. Still, use **your own** hotspot, not venue Wi-Fi.

## Fallbacks, ranked

1. **Wi-Fi Direct.** The camera becomes the access point. ZV-E10: [PC Remote Cnct Method] = [Wi-Fi Direct], then [Wi-Fi Direct Info.] shows the SSID and password; join the Mac to it ([E10-PCR]). E10 II: [Remote Shoot Function] → [Wi-Fi Direct Info.] ([E10II] p.510).
   - The Mac **loses internet** while joined. That's fine today, since everything runs on localhost, and the agent and the stack keep working.
   - At a real event it means no uploads to a cloud server, and guest phones can't reach the Mac.
   - The agent's red "no internet" banner may show, because it checks the API URL. With `LAQTA_API_URL=http://localhost:8000` it should stay green; **unverified with the camera.**
2. **USB PC Remote.**
   - ZV-E10: [PC Remote Cnct Method] = [USB], with the USB-C cable ([E10-PCR]).
   - E10 II: plug in and choose [Remote Shoot (PC Remote)] on the camera ([E10II] p.510).
   - Same Remote app and save folder. **Sony warns USB Remote may not work correctly on macOS 26** ([IED-FAQ]). If it misbehaves: restart the Mac, and turn off background items under **General → Login Items & Extensions** (Sony's suggestion).
3. **SD card copy.** Shoot to the card (Camera Only), then use a card reader to copy the card's `DCIM` folder into `~/Pictures/laqta-inbox`.
   - The agent handles nested folders, skips `.ARW`, and won't upload a file twice even if the copy is repeated (all tested).
   - This isn't live, but it can't fail on networking.

## Checklist for the day

**Before leaving home** (done today unless noted):

```bash
scripts/health_check                              # ALL CHECKS PASSED
scripts/.venv/bin/python scripts/e2e_smoke        # E2E SMOKE: PASS
```

Imaging Edge Remote is installed and allowed under Local Network, and `/Users/awb/Pictures/laqta-inbox` exists.

| # | Step | Success looks like | If it fails |
|---|---|---|---|
| 0 | **Identify the model.** Look at the name on the body, and check whether MENU → (Network) has **[PC Remote Function]** (original) or **[Cnct./Remote Sht.]** (II). | You know which section to follow. | — |
| 1 | Start the stack (docs/RUN_LOCAL.md §2–3), then run `scripts/health_check`. | `ALL CHECKS PASSED` | Fix the first FAIL line; the most common cause is Docker Desktop not running. |
| 2 | Dashboard → create a **standard** event (auto-publish), then click **Pair camera agent**. | 6-character code | Strict events hide every photo until a moderator approves it. Use standard for this test. |
| 3 | Start the agent GUI (RUN_LOCAL §4), enter the code, choose `/Users/awb/Pictures/laqta-inbox`. In another terminal: `python3 scripts/camera_check`. | Agent shows "Connected"; camera_check prints "Watching …" | Wrong folder: camera_check reads the GUI agent's folder from its settings. |
| 4 | Camera: File Format = **JPEG** (E10 II: JPEG/HEIF Switch = **JPEG**), size L, Fine. Save Dest = **PC+Camera** / **Dest.+Camera**. Card inserted. | — | Without a card, the shutter won't release ([E10-PCR]). |
| 5 | Connect over the hotspot (section above). Remote → Image Save Settings → **Save in = `/Users/awb/Pictures/laqta-inbox`**. | Live view in Remote; Save in shows that path | "If they can't see each other" list above. |
| 6 | **Test shot from Remote's Photo button.** Photograph a person (you) facing the camera, face clearly visible. | camera_check prints, in order: **landed** → **picked up** → **uploaded** → **server received** → **processed** "N face(s)" with N ≥ 1 → **guest-visible** | See the hop table below. |
| 7 | **Test shot from the camera's own shutter button.** This answers the unverified question. | Same lines as step 6 | If nothing "lands": the body button doesn't transfer in this mode. Shoot from Remote, or rely on the card and SD copy. **Write down the answer.** |
| 8 | Burst: 10 quick shots. | 10 × guest-visible, nothing failed | Note the slowest "landed" delay: that's the Wi-Fi transfer time Sony doesn't document. |
| 9 | **Guest selfie:** on the Mac browser open `http://localhost:3000/e/<qr_token>` (QR token from the dashboard), tick consent, take the selfie. | Gallery shows the step-6/7/8 photos you're in | `no_face_detected` / `selfie_too_blurry`: better light, hold still. Zero matches: check step 6 showed faces ≥ 1. If it still fails, **stop and tell me. Don't change the threshold.** |

### What each camera_check hop means, and what to try

| Hop | Timestamp comes from | If it never appears |
|---|---|---|
| **landed** | file mtime when first seen | Remote's Save in folder ≠ inbox; Save Dest = Camera Only; HEIF format (`.HIF`, shown as "not a JPEG"). |
| **picked up** | agent queue `created_at` (file stable, hashed and queued) | Agent not running or watching another folder. A JPEG that never ends with the JPEG end-of-image marker is held back on purpose (a half-written file). |
| **uploaded** | agent queue `updated_at` at status done (no dedicated "uploaded" timestamp exists in the code) | `UPLOAD FAILED` lines show the error. Check `curl localhost:8000/health`. "authentication failed" means re-pair. |
| **server received** | `photos.created_at` | "same content was uploaded earlier": a duplicate, which is fine. |
| **processed** | **No timestamp in the code** (`photos` has no processed_at; `faces.created_at` is the job's *start*). camera_check prints when it *saw* `status=ready`. | `docker compose logs worker`. "0 face(s)": the face is too small (<40 px) or blurry; move closer. |
| **guest-visible** | **No timestamp in the code** (`published` has no time unless a moderator acted). Shown when seen. | "unpublished": strict event, so approve it in the moderation page. |
