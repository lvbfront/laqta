# الطبقة ١ — المواصفات التقنية لمساعد لقطة (assistant)

**الهدف:** مساعد نصي في الترمنال يحجز فترة تفعيل الفعاليات، ويعدّلها ويلغيها، ويجاوب من `laqta-kb.md`، ويحوّل للموظف لما لازم. كل شي ينسجل في CRM بسيط.

**خلصت لما:**
- تقدر تحجز وتعدّل وتلغي من الترمنال.
- تسأل عن الباقات والخصوصية ويجاوب من المستند.
- تطلب خصم فيحوّلك للمبيعات.
- عميل ما يقدر يشوف أو يلمس حجز عميل ثاني.
- كل الاختبارات تمر بدون أي استدعاء LLM، ما عدا حلقة المساعد نفسها.

---

## 0. قرار الحسابات

**حسابات، بس مو حسابات جديدة.** لقطة أصلاً فيها حسابات للمنظمين (`organizations` + `users` + تسجيل دخول + `GET /api/auth/me`). المساعد ما يبني نظام دخول ثاني، يستخدم حسابات لقطة.

**الفصل بين النظامين:**

| | لقطة (المنصة) | المساعد (الـ CRM) |
|---|---|---|
| يملك | **مين أنت:** الحساب، الدخول، الجهة، الفعالية نفسها | **وش صار بيننا:** المحادثات، التذاكر، الحالة التجارية للحجز، المتابعات، الهيكل الإداري للموظفين |
| الربط | `users.id` | `contacts.laqta_user_id` (يقبل فاضي) |

**ليش مو "بس في الداتابيس":** معرفة تاريخ العميل تحتاج تعرف إن المتكلم هو فعلاً صاحب الحساب. لو المساعد يصدّق "أنا أحمد من شركة الريّان" بدون دخول، أي أحد يقدر يلغي حجوزات غيره ويشوف تاريخه.

**٣ أنواع جلسات:**

| النوع | مين | يقدر |
|---|---|---|
| `anonymous` | زائر بدون دخول | يسأل، يفحص التوفر، يترك طلب (باسمه وجواله) |
| `customer` | منظم مسجل دخول | كل ما سبق + يحجز ويعدّل ويلغي **حجوزاته هو فقط**، والمساعد يعرف تاريخه |
| `staff` | موظف في لقطة | أدوات الموظفين (الطبقة ٤) |

**المنظم الجديد بدون حساب:** في الأسبوعين، المساعد يعطيه رابط التسجيل في لقطة. إنشاء حساب من داخل المكالمة مع رمز تحقق (OTP) يكون في v2.

**الصوت لاحقاً:** صوت الويب (الطبقة ٣) يشتغل من صفحة داخل لوحة لقطة، فيورث نفس تسجيل الدخول. الهاتف (v2) رقم المتصل فيه ما يكفي كإثبات، فيحتاج OTP قبل أي فعل حساس.

**في الطبقة ١:** الترمنال ما فيه تسجيل دخول، فنستخدم `DevAuth`: تختار الهوية بـ `--as customer:3`. في الربط الحقيقي، `LaqtaAuth` ياخذ الـ bearer token ويسأل لقطة `GET /api/auth/me`. نفس الواجهة، والمساعد ما يفرق.

---

## 1. هيكل المشروع

```
assistant/
  requirements.txt
  alembic.ini
  alembic/
  policy.yaml                  # كل الأرقام التشغيلية — المصدر الوحيد
  kb/laqta-kb.md
  app/
    config.py                  # إعدادات البيئة + تحميل policy.yaml
    db.py                      # SQLAlchemy engine/session
    models/                    # contacts, staff, interactions, tool_calls,
                               # tickets, bookings, booking_events,
                               # confirmations, kb_chunks, scheduled_actions
    identity/
      identity.py              # Identity dataclass
      dev_auth.py              # --as customer:3
    domain/                    # ⚠️ بدون أي LLM — كود عادي قابل للاختبار
      booking_state.py         # الـ state machine
      availability.py          # قواعد التوفر (دوال pure)
      capacity.py              # قفل السعة في Postgres
      confirmation.py          # رموز التأكيد
      dates/                   # ✍️ تكتبه بنفسك
        intents.py
        resolver.py
        hijri.py
        times.py
    laqta/
      adapter.py               # الواجهة (Protocol)
      mock.py                  # MockLaqta في الذاكرة
    kb/
      chunker.py
      embedder.py
      index.py
      search.py
    tools/
      registry.py              # تسجيل الأدوات + الصلاحيات + التنفيذ + التسجيل
      customer.py
      common.py                # search_kb, resolve_when, check_availability, handoff
    agent/
      system_prompt.md
      context.py               # بلوك "وش نعرف عن هذا العميل"
      session.py
      loop.py                  # حلقة المساعد
      summarize.py             # ملخص المحادثة عند النهاية
    cli/
      chat.py                  # python -m app.cli.chat --as customer:3
      admin.py                 # mark-paid وغيره
  scripts/
    seed.py
    index_kb.py
  tests/
```

**البيئة:** المساعد يشتغل على جهازك مباشرة بـ venv، مثل Next.js في لقطة، ويتصل بنفس حاوية Postgres على المنفذ 5433، لكن بقاعدة بيانات منفصلة:

```bash
docker compose exec postgres createdb -U <POSTGRES_USER> assistant
docker compose exec postgres psql -U <POSTGRES_USER> -d assistant -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

⚠️ الـ extension ينفعل لكل قاعدة بيانات لحالها، فتفعيله في قاعدة لقطة ما يكفي.

**المكتبات:**
```
sqlalchemy>=2.0  alembic  psycopg[binary]  pgvector  pydantic>=2  pyyaml
anthropic  sentence-transformers  hijridate  pytest
```
(`hijridate` هي البديل الرسمي لـ `hijri-converter` اللي صارت deprecated، وتستخدم تقويم أم القرى.)

---

## 2. policy.yaml — المصدر الوحيد للأرقام

```yaml
timezone: Asia/Riyadh

lead_time_hours:
  remote: 48
  onsite: 168              # 7 أيام

max_event_days: 3
upload_opens_before_hours: 2
upload_closes_after_hours: 24
free_reschedule_before_hours: 48

payment_deadline:
  after_tentative_hours: 72
  before_start_hours: 24   # أيهما أقرب

refunds:                   # حسب الوقت المتبقي قبل البداية
  - {min_hours_before: 168, percent: 100}
  - {min_hours_before: 48,  percent: 50}
  - {min_hours_before: 0,   percent: 0}

onsite:
  cities: [jeddah, riyadh, dammam]
  max_events_per_city_per_day: 2
  included_in: [premium]
  addon_for: [standard]

packages:
  starter:  {max_guests: 300,  max_photos: 2000,  seats: 1,    retention_days: 14}
  standard: {max_guests: 1000, max_photos: 10000, seats: 3,    retention_days: 30}
  premium:  {max_guests: null, max_photos: null,  seats: null, retention_days: 90}

strict_mode:
  retention_days: 7
  default_match_mode: code
  forbidden_addons: [extended_retention]

confirmation_ttl_minutes: 10
```

**قاعدة:** أي رقم يظهر في الكود لازم يجي من هنا. إذا تغيّر رقم، غيّره هنا وفي `laqta-kb.md`.

---

## 3. قاعدة البيانات

```sql
contacts(
  id, laqta_user_id UNIQUE NULL, laqta_org_id NULL,
  name, phone NULL, email NULL, org_name NULL,
  source,                      -- chat | voice | staff
  created_at)

staff(
  id, laqta_user_id UNIQUE NULL,
  name, email, team,           -- sales | ops | support | privacy
  manager_id NULL REFERENCES staff(id),
  active BOOL)

interactions(                  -- جلسة محادثة وحدة
  id, contact_id NULL, staff_id NULL,
  channel,                     -- chat | voice
  identity_kind,               -- anonymous | customer | staff
  started_at, ended_at,
  transcript JSONB,
  summary TEXT NULL,           -- ملخص ٢–٣ أسطر يولّد في النهاية
  outcome NULL)                -- booked | answered | handed_off | abandoned ...

tool_calls(                    -- كل استدعاء أداة — ذهب للتقييم والتصحيح
  id, interaction_id, user_turn INT, name, args JSONB, result JSONB,
  ok BOOL, latency_ms INT, created_at)

tickets(
  id, contact_id NULL, interaction_id,
  team, assignee_staff_id NULL,
  priority,                    -- normal | urgent | privacy
  reason_code,                 -- discount | premium_quote | long_event | late_change
                               -- | complaint | live_issue | legal | unknown_question | wants_human
  summary TEXT,
  status,                      -- open | acknowledged | resolved
  due_at, created_at, acknowledged_at NULL, resolved_at NULL)

bookings(
  id UUID, contact_id, laqta_org_id, laqta_event_id NULL,
  status,                      -- tentative | confirmed | live | ended | cancelled
  event_name, city, venue,
  starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ,
  expected_guests, photographers,
  match_mode,                  -- face | code | sequential | both  (نفس قيم لقطة)
  strict_mode BOOL,
  package, addons JSONB, onsite_support BOOL,
  payment_due_at,
  version INT,                 -- optimistic locking
  created_at, updated_at)

booking_events(                -- سجل كل انتقال حالة
  id, booking_id, from_status, to_status, trigger, actor, reason, at)

confirmations(                 -- انظر القسم 8
  id UUID, interaction_id, action, params JSONB, params_hash,
  prepared_at_user_turn INT, expires_at, used_at NULL)

kb_chunks(
  id, section_title, audience, content, content_hash,
  embedding VECTOR(1024))      -- BGE-M3

scheduled_actions(             -- للطبقة ٤، بس سوّ الجدول الحين
  id, kind, subject_type, subject_id, run_at,
  idempotency_key UNIQUE, status, attempts, last_error, executed_at)
```

**ملاحظات:**
- كل الأوقات `TIMESTAMPTZ` وتنخزن UTC، وتتحول لتوقيت الرياض فقط عند العرض.
- `bookings` تملك **الحالة التجارية** (مبدئي، مدفوع، الباقة). **فترة التفعيل الفعلية** تملكها فعالية لقطة (`laqta_event_id`). في v2 ممكن تنتقل الحالة التجارية للقطة لما تبنون الدفع هناك.

**الـ seed:**
- ٤ فرق، لكل فريق مدير وموظفين اثنين (أسماء وهمية).
- ٣ منظمين، كل واحد له حساب في `MockLaqta` وسجل في `contacts`.
- حجز موجود مسبقاً بدعم ميداني في جدة، عشان تختبر امتلاء السعة.

---

## 4. الهوية والصلاحيات

```python
@dataclass(frozen=True)
class Identity:
    kind: Literal["anonymous", "customer", "staff"]
    contact_id: int | None = None
    staff_id: int | None = None
    laqta_user_id: int | None = None
    laqta_org_id: int | None = None
```

- `DevAuth.parse("customer:3")` ترجع هوية العميل رقم ٣. `anon` ترجع `anonymous`.
- **الصلاحيات في طبقتين:**
  1. قائمة الأدوات اللي تنرسل للنموذج تتفلتر حسب `identity.kind`. العميل ما يشوف أدوات الموظفين أصلاً.
  2. كل أداة تتحقق مرة ثانية وقت التنفيذ. عميل يطلب حجز عميل ثاني يطلع له `not_found`، مو `forbidden`، **نفس نمط لقطة ضد الـ enumeration** (404 للمورد اللي ما يخصك).

---

## 5. الـ state machine للحجز

**حالة `draft` ما تنحفظ.** المسودة تعيش في رمز التأكيد (القسم 8). أول حالة محفوظة هي `tentative`.

| من | الحدث (trigger) | إلى | الشرط (guard) |
|---|---|---|---|
| — | `confirm_booking` | `tentative` | التوفر OK وقت التنفيذ تحت القفل |
| `tentative` | `mark_paid` (موظف) | `confirmed` | — |
| `tentative` | `payment_expired` (الساعة) | `cancelled` | `now >= payment_due_at` |
| `tentative` / `confirmed` | `cancel` (عميل) | `cancelled` | قبل `live` |
| `tentative` / `confirmed` | `reschedule` | نفس الحالة | `now <= starts_at - 48h` والموعد الجديد متاح |
| `confirmed` | `window_open` (الساعة) | `live` | `now >= starts_at - 2h` |
| `live` | `window_close` (الساعة) | `ended` | `now >= ends_at + 24h` |

**أي انتقال مو في الجدول يطلع `InvalidTransition`.** مثلاً `reschedule` على `live`، أو `window_open` على `tentative` (الحجز غير المدفوع ما يتفعّل أبداً).

```python
TRANSITIONS: dict[tuple[Status, Trigger], Transition] = {
    (Status.TENTATIVE, Trigger.MARK_PAID): Transition(to=Status.CONFIRMED),
    (Status.TENTATIVE, Trigger.CANCEL):    Transition(to=Status.CANCELLED, guard=before_live),
    # ...
}

def apply(booking, trigger, *, now, policy, actor, reason=None) -> Booking:
    t = TRANSITIONS.get((booking.status, trigger))
    if t is None:
        raise InvalidTransition(booking.status, trigger)
    if t.guard and not t.guard(booking, now, policy):
        raise GuardFailed(trigger, t.guard.__name__)
    # يسجل booking_events ويزيد version
```

**الوقت دائماً معامل (`now`)، ما تستدعي `datetime.now()` داخل الـ domain أبداً.** هذا اللي يخلي الـ fake clock في الطبقة ٤ ممكن. الانتقالات الزمنية (`window_open`، `payment_expired`) في الطبقة ١ تختبرها بتمرير `now`، والـ worker اللي يشغلها تلقائياً يجي في الطبقة ٤.

---

## 6. التوفر وقفل السعة

### القواعد، دالة pure بدون قاعدة بيانات

```python
def check(req: AvailabilityRequest, *, now: datetime,
          onsite_counts: dict[date, int], policy: Policy) -> AvailabilityResult
```

الترتيب، وأول قاعدة تفشل ترجع سببها:
1. `in_past`: البداية قبل `now`
2. `end_before_start`
3. `too_long`: أكثر من `max_event_days`، والحل تحويل للمبيعات
4. `lead_time`: أقل من 48 ساعة، أو 168 مع الدعم الميداني
5. `onsite_city_unsupported`
6. `onsite_full`: أي يوم من أيام الفعالية وصل الحد
7. `guests_exceed_package`: مع اقتراح الباقة المناسبة

إذا فشل بسبب `lead_time` أو `onsite_full`، ترجع `suggestions`: أقرب ٣ أيام متاحة بنفس الأوقات، تبحث لقدام حتى ٣٠ يوم.

**رسالة الرفض للنموذج ما فيها أرقام السعة.** ترجع `onsite_full` بس، بدون "٢ من ٢". النموذج ما يقدر يسرّب رقم ما شافه.

### القفل

مشكلة: عميلين في نفس اللحظة يحجزون آخر مكان دعم ميداني في جدة يوم ١٧. `SELECT ... FOR UPDATE` على الحجوزات الموجودة **ما يكفي**، لأنه يقفل الصفوف الموجودة بس، والحجز الجديد صف ما انوجد لسا (phantom). الحل: advisory lock على المفتاح نفسه:

```python
def lock_onsite_days(session, city: str, days: list[date]) -> None:
    for d in sorted(days):  # ترتيب ثابت يمنع الـ deadlock بين فعاليتين متعددة الأيام
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"onsite:{city}:{d.isoformat()}"},
        )
```

القفل ينفك تلقائياً مع نهاية الـ transaction. التسلسل داخل `confirm_booking`: ابدأ transaction، ثم اقفل، ثم عدّ الحجوزات، ثم `check()`، ثم أنشئ الحجز، ثم استدعِ الـ adapter، ثم commit.

### اختبار السباق

- الإعداد: حجز ميداني موجود في جدة يوم X، والحد ٢.
- ٥ threads تحاول تحجز نفس اليوم في نفس اللحظة.
- المتوقع: **واحد بالضبط** ينجح، والأربعة يطلع لهم `onsite_full`.
- لازم يشتغل على Postgres الحقيقي، مو SQLite.
- هذا اختبار الـ race من الخطة الأصلية، رجع بشكل جديد.

---

## 7. محلّل التواريخ ✍️ (اكتبه بنفسك)

**المبدأ:** النموذج ما يكتب تاريخ أبداً. يطلع **وصف منظم** (intent)، وكودك يحسب التاريخ.

### الـ intents (pydantic)

```python
# التاريخ
{"kind": "relative_day", "offset": 1}                                  # بكرة
{"kind": "relative_weekday", "weekday": "thu", "which": "next"}         # الخميس الجاي
{"kind": "absolute", "calendar": "gregorian", "month": 11, "day": 17}   # ١٧ نوفمبر
{"kind": "absolute", "calendar": "hijri", "month": 6, "day": 1}         # ١ جمادى الآخرة
{"kind": "day_only", "day": 17}                                         # "يوم ١٧" بدون شهر
{"kind": "event_anchored", "anchor": "eid_fitr", "offset": 2}           # ثالث يوم العيد
{"kind": "unclear", "raw": "..."}

# الوقت
{"kind": "clock", "hour": 8, "minute": 0, "period": "pm" | "am" | "unspecified"}
{"kind": "prayer", "prayer": "maghrib", "offset_minutes": 30}           # بعد المغرب بنص ساعة
{"kind": "part_of_day", "part": "morning" | "afternoon" | "evening" | "late_night"}
```

### المخرجات

```python
ResolvedWhen(start: datetime, end: datetime,        # timezone-aware, Asia/Riyadh
             gregorian_text: str, hijri_text: str,  # "الخميس ١٧ سبتمبر ٢٠٢٦" / "٦ ربيع الثاني ١٤٤٨"
             assumptions: list[str])                # ["افترضت ٨ مساءً", "النهاية بعد منتصف الليل"]
# أو
Ambiguous(candidates: list[date], question_ar: str)
```

### القواعد

- **"الجاي":** أقرب يوم بهذا الاسم بعد اليوم، ما يشمل اليوم نفسه. **"اللي بعده":** زائد ٧. أي حالة فيها احتمال، تنضاف لـ `assumptions`.
- **`day_only`: غامض دائماً.** "يوم ١٧" ممكن يكون ١٧ ميلادي أو ١٧ هجري، فترجع `Ambiguous` بالاثنين.
- **الأعياد:** عيد الفطر = ١ شوال، والأضحى = ١٠ ذي الحجة. تحسبها من `hijridate` مباشرة، بدون جدول يدوي. الموعد الفعلي ممكن يختلف يوم برؤية الهلال، فأضف ذلك دائماً لـ `assumptions`. "بعد العيد" بدون رقم يوم = `Ambiguous`.
- **اليوم الوطني (٢٣ سبتمبر) ويوم التأسيس (٢٢ فبراير):** تواريخ ميلادية ثابتة.
- **الوقت بدون صباح/مساء:** لا تخمّن بصمت. خذ الافتراض الأرجح (١–٦ = مساءً، ٧–١١ حسب نوع الفعالية)، وأضفه لـ `assumptions`.
- **الصلاة:** في الطبقة ١ جدول تقريبي لكل مدينة وشهر، مع `assumptions += ["الوقت تقريبي"]`. الحساب الدقيق بطريقة أم القرى تحسين لاحق.
- **النهاية قبل البداية** (زواج من ٩ الليل إلى ٢): النهاية في اليوم اللي بعده، وتنضاف للـ assumptions.
- **أسماء الشهور الهجرية بالعربي:** `hijridate` فيها `month_name("ar")`.

### أمثلة اختبار حقيقية

المرجع: الجمعة ١١ سبتمبر ٢٠٢٦ = ٢٩ ربيع الأول ١٤٤٨. محسوبة بـ `hijridate`:

| الكلام | intent | النتيجة |
|---|---|---|
| بكرة | relative_day +1 | السبت 2026-09-12 |
| بعد بكرة | relative_day +2 | الأحد 2026-09-13 |
| الخميس الجاي | thu, next | 2026-09-17 |
| الخميس اللي بعده | thu, after_next | 2026-09-24 |
| الجمعة الجاية (واليوم جمعة) | fri, next | 2026-09-18، مو اليوم |
| ١٥ ربيع الثاني | hijri 4/15 | السبت 2026-09-26 |
| ١ جمادى الآخرة | hijri 6/1 | 2026-11-11 |
| ١٧ نوفمبر | gregorian 11/17 | الثلاثاء 2026-11-17 = ٧ جمادى الآخرة |
| يوم ١٧ | day_only 17 | **غامض:** 2026-09-17 (ميلادي) أو 2026-09-28 (١٧ ربيع الثاني) |
| اليوم الوطني | national_day | الأربعاء 2026-09-23 |
| ثالث يوم العيد | eid_fitr +2 | 2027-03-11 تقريباً، مع ملاحظة الرؤية |
| بعد العيد | eid_fitr, بدون offset | **غامض:** اسأل عن اليوم بالضبط |
| أمس | relative_day −1 | يرفضها `check()` بسبب `in_past` |

المطلوب ١٠٠+ حالة. هذي بداية.

### النموذج كيف يستخدمه

الأداة `resolve_when` تاخذ الـ intents وترجع `when_id`، وهو معرف للنتيجة محفوظ في الجلسة، مع النص الميلادي والهجري. **كل أدوات الحجز تاخذ `when_id` وليس تاريخ.** بهذي الطريقة أي تاريخ يوصل للحجز لازم يكون مر على الـ resolver، والنموذج ما يقدر يمرر تاريخ حسبه بنفسه.

---

## 8. التأكيد الإجباري

في التعليمات نقول للنموذج "أكّد قبل ما تحجز"، **بس ما نعتمد على التعليمات.** الكود يفرضها:

1. `prepare_booking(when_id, details)` تتحقق من كل شي (التوفر، الباقة، الوضع المشدد) **بدون أي تغيير**، وترجع `confirmation_id` + `summary_ar` (الملخص اللي يقراه على العميل).
2. النموذج يقرا الملخص، والعميل يرد.
3. `confirm_action(confirmation_id)`، والكود يتحقق:
   - الرمز موجود ويخص هذي الجلسة
   - ما انتهى (١٠ دقايق) وما انستخدم
   - **جات رسالة جديدة من العميل بعد `prepare`**: `current_user_turn > prepared_at_user_turn`
   - يعيد فحص التوفر تحت القفل، لأن الوضع ممكن تغيّر
4. بعدها بس ينفّذ.

نفس الشي لـ `prepare_reschedule` و`prepare_cancel`، وكلها تنتهي بـ `confirm_action` واحدة. **يعني فيه أداة وحدة بس تسوي side effects.** هذا يسهّل التقييم ويسهّل الشرح في المقابلة.

**حدود هذا الضمان، وقلها بصراحة في `EVAL.md`:** الكود يضمن إن العميل **أُعطي فرصة يرد**. ما يضمن إن رده كان "إيه" وليس "لا". هذا يقيسه `confirmation_violations` في الطبقة ٢.

---

## 9. الـ LaqtaAdapter

```python
class LaqtaAdapter(Protocol):
    def get_user(self, user_id: int) -> LaqtaUser: ...
    def create_event(self, *, idempotency_key: str, org_id: int, name_ar: str,
                     starts_at: datetime, ends_at: datetime,
                     match_mode: str, privacy_mode: str) -> LaqtaEvent: ...
    def update_event_window(self, event_id: int, starts_at, ends_at) -> LaqtaEvent: ...
    def cancel_event(self, event_id: int) -> None: ...
    def get_event(self, event_id: int) -> LaqtaEvent: ...
```

- **الأسماء والقيم نفس لقطة بالضبط** (`name_ar`، `match_mode` = face | code | sequential | both، `privacy_mode` = standard | strict)، عشان النسخة الحقيقية في v2 تكون مجرد طبقة HTTP رفيعة.
- `strict_mode=True` يتحول إلى `privacy_mode="strict"`، ولقطة أصلاً تجبر `auto_publish=false` في هذي الحالة.
- `idempotency_key = booking.id`. لو انستدعت مرتين بنفس المفتاح، ترجع نفس الفعالية وما تسوي ثانية.
- `MockLaqta`: dicts في الذاكرة + قائمة استدعاءات عشان الاختبارات تتأكد وش انطلب.

---

## 10. الأدوات

### شكل النتيجة

```json
{"ok": true,  "data": { ... }}
{"ok": false, "error": "lead_time", "detail": "أقل مهلة للحجز بدعم ميداني ٧ أيام",
 "suggestions": ["2026-09-20", "2026-09-21", "2026-09-22"]}
```

- **الرفض التجاري = `ok: false` كبيانات عادية.** النموذج يتعامل معه ويقترح بديل.
- **`is_error: true` في الـ tool_result فقط للأعطال** (exception في الكود).
- أخطاء التحقق من المدخلات (pydantic) ترجع `ok: false` مع التفاصيل، عشان النموذج يصحح نفسه.

### القائمة

| الأداة | anonymous | customer | side effect |
|---|---|---|---|
| `search_kb(query)` | ✓ | ✓ | لا |
| `resolve_when(date, start_time, end_time, days)` | ✓ | ✓ | لا |
| `check_availability(when_id, city, onsite_support)` | ✓ | ✓ | لا |
| `get_my_bookings()` | | ✓ | لا |
| `prepare_booking(when_id, details)` | | ✓ | لا |
| `prepare_reschedule(booking_id, when_id)` | | ✓ | لا |
| `prepare_cancel(booking_id)` (ترجع نسبة الاسترداد) | | ✓ | لا |
| `confirm_action(confirmation_id)` | | ✓ | **نعم** |
| `handoff_to_staff(reason_code, summary, urgent, contact_name?, contact_phone?)` | ✓ | ✓ | **نعم** (تذكرة) |

**الـ handoff للزائر:** `contact_name` و`contact_phone` إجبارية للـ anonymous، والكود يتحقق. التذكرة تتوجه للفريق حسب `reason_code` (من قسم "متى يحوّل" في الـ KB)، وتنعطى للموظف الأقل تذاكر مفتوحة في الفريق. `due_at` من جدول أوقات الاستجابة.

### التسجيل

```python
@tool(name="check_availability", roles={"anonymous", "customer"})
def check_availability(ctx: ToolContext, inp: CheckAvailabilityInput) -> dict: ...
```

- الـ schema تطلع من الـ pydantic model تلقائياً (`model_json_schema()`).
- **وصف كل أداة مهم مثل الكود:** متى تستخدمها، ومتى لا. مثلاً وصف `prepare_booking` يقول: "لا تستدعها قبل ما تجمع كل الحقول المطلوبة وتستخدم `resolve_when`".
- `registry.execute()` يتحقق من الدور مرة ثانية، ويسجل كل استدعاء في `tool_calls` مع الوقت.

---

## 11. الـ RAG

1. **التقطيع (`chunker.py`):** قسّم على `^## `، واقرأ `<!-- audience: x -->`، وتجاهل التعليق اللي في أول الملف. **حط العنوان في بداية كل قطعة** ("القسم: الباقات\n...")، لأنه يحسّن البحث.
2. **الـ embeddings (`embedder.py`):**
   ```python
   model = SentenceTransformer("BAAI/bge-m3")          # ~2GB أول تحميل، يشتغل على CPU
   vecs = model.encode(texts, normalize_embeddings=True)  # 1024 بُعد
   ```
3. **الفهرسة (`scripts/index_kb.py`):** upsert حسب `content_hash`، وتحذف الأقسام اللي انشالت من الملف. تشغيلها مرتين = نفس النتيجة.
4. **البحث (`search.py`):**
   ```sql
   SELECT section_title, content, 1 - (embedding <=> :q) AS score
   FROM kb_chunks
   WHERE audience = ANY(:allowed)        -- customer/anonymous: {public} | staff: {public, internal}
   ORDER BY embedding <=> :q
   LIMIT 3;
   ```
   إذا أعلى score أقل من حد معيّن، ترجع `{"ok": true, "data": {"results": [], "note": "no_relevant_section"}}`، والتعليمات تقول: نتيجة فاضية = handoff.
5. **اختبار الاسترجاع (`tests/kb_questions.yaml`):** ٢٠ سؤال، وكل سؤال معه القسم الصحيح. قِس hit@1 وhit@3، واستخدمه عشان تختار الحد. وضمنها أسئلة داخلية ("كم فعالية تغطون باليوم؟") تتأكد إن العميل **ما يرجع له أبداً** قسم `internal`.

(٢٠ قطعة بس، فما تحتاج index على العمود. الـ HNSW موجود في لقطة لو احتجته.)

---

## 12. حلقة المساعد

### الكود

```python
def run_turn(session: Session, user_text: str) -> str:
    session.user_turn += 1
    session.messages.append({"role": "user", "content": user_text})

    for _ in range(MAX_STEPS):  # 8 — حماية من اللف اللانهائي
        resp = client.messages.create(
            model=settings.agent_model,             # "claude-sonnet-5"
            max_tokens=1024,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},   # الجزء الثابت يتخزن
                {"type": "text", "text": session.context_block},  # يتغير لكل عميل
            ],
            tools=registry.schemas_for(session.identity),
            messages=session.messages,
        )
        session.messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = registry.execute(block.name, block.input, ctx=session.tool_ctx())
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(out, ensure_ascii=False),
                    "is_error": out.get("_exception", False),
                })
        session.messages.append({"role": "user", "content": results})

    return FALLBACK_MESSAGE  # "خلني أحوّلك لأحد من الفريق" + يفتح تذكرة
```

**ليش نكتب الحلقة بيدنا** بدل الـ tool runner الجاهز في الـ SDK: نحتاج نتحكم في التحقق من الدور، والتسجيل، وعدّاد رسائل العميل اللي يعتمد عليه التأكيد. وتفهم كل سطر، وهذا مهم للمقابلة.

### بلوك السياق (`context.py`)

يتولّد بداية كل جلسة، وصغير (أقل من ٣٠٠ token):
```
اليوم: الجمعة ١١ سبتمبر ٢٠٢٦ = ٢٩ ربيع الأول ١٤٤٨، الساعة ١٤:٠٥ بتوقيت الرياض
المتكلم: عميل مسجل — أحمد العتيبي، شركة الريّان للفعاليات
حجوزاته: [#a3f2 "ملتقى الريّان" ١٧ سبتمبر، جدة، مبدئي، الدفع قبل ١٤ سبتمبر]
تذاكر مفتوحة: [#42 طلب خصم — مع المبيعات منذ ٩ سبتمبر]
آخر تواصل: ٩ سبتمبر — حجز مبدئي لملتقى الريّان وطلب خصم فتحوّل للمبيعات.
```

**التاريخ والوقت هنا مهمين جداً.** النموذج ما يعرف تاريخ اليوم إلا منك. هذا اللي يخلي المساعد "يعرف تاريخ المستخدم" اللي كنت تبيه، وبدون ما يحتاج أداة بحث في كل محادثة.

### الملخص في النهاية (`summarize.py`)

عند `/end` أو انتهاء الجلسة: Haiku يكتب ملخص ٢–٣ أسطر ويحدد `outcome`، وينحفظ في `interactions.summary`. هذا اللي يظهر في "آخر تواصل" المرة الجاية.

### التعليمات (`system_prompt.md`) — مسودة

```
You are the Laqta assistant (مساعد لقطة). Laqta is a Saudi event-photo delivery platform.
Speak Saudi Arabic: polite, warm, short sentences. One question at a time.

HARD RULES
- Never state a price, policy, deadline, or date that did not come from a tool result
  or search_kb in THIS conversation. If search_kb returns nothing relevant, use
  handoff_to_staff. Never guess.
- Never compute dates yourself. Always call resolve_when. Read back both the
  Gregorian and Hijri dates, plus any assumptions it returns.
- If resolve_when returns ambiguous, ask the customer its question. Do not pick one.
- Booking/reschedule/cancel: collect every required field, call prepare_*, read the
  summary back in full, then wait. Call confirm_action only after the customer
  clearly agrees in a NEW message.
- Never offer, promise, or hint at discounts. Discount requests → handoff (reason: discount).
- Never reveal capacity numbers or internal rules. If a date is full, say it is not
  available and offer the suggestions from the tool.
- Anonymous visitors cannot book. Offer the registration link, answer questions,
  or take their name + phone for a handoff.

REQUIRED BOOKING FIELDS
event name, date + start/end time (via resolve_when), city, venue, expected guests,
number of photographers, match mode, whether it is a women's event / strict mode,
package and add-ons.
If the event is a women's event, explain strict mode and suggest code matching.

HANDOFF when: discount, premium quote, event > 3 days, change within 48h,
extending a live event, complaint, live technical issue (urgent), legal/data request,
unknown question, or the customer asks for a person.
```

التعليمات بالإنجليزي والرد بالسعودي طريقة شائعة وتشتغل. تقدر تجرب نسخة عربية بعدين وتقارن في التقييم.

---

## 13. واجهة الترمنال

```bash
python -m app.cli.chat --as customer:1     # عميل مسجل
python -m app.cli.chat --as anon           # زائر
python -m app.cli.admin mark-paid <booking_id>
```

أوامر داخل المحادثة:
- `/debug`: تشغيل أو إيقاف عرض كل استدعاء أداة ونتيجته
- `/end`: إنهاء الجلسة وتوليد الملخص
- `/ctx`: عرض بلوك السياق الحالي

---

## 14. الاختبارات

كلها بدون LLM، ما عدا الأخيرة:

- `test_state_machine.py`: كل انتقال مسموح ينجح، **وكل انتقال ممنوع يطلع خطأ**.
- `test_availability.py`: كل قاعدة لحالها، والاقتراحات.
- `test_capacity_race.py`: ٥ threads على Postgres الحقيقي.
- `test_dates_*.py`: ١٠٠+ حالة ✍️
- `test_confirmation.py`: تأكيد في نفس الرسالة ← يرفض. بعد رسالة جديدة ← يقبل. منتهي ← يرفض. من جلسة ثانية ← يرفض. الموعد امتلأ بين prepare وconfirm ← يرفض.
- `test_scoping.py`: العميل أ يطلب حجز العميل ب ← `not_found`. الزائر يستدعي `prepare_booking` ← مرفوض حتى لو تجاوز فلتر القائمة.
- `test_handoff.py`: كل `reason_code` يروح للفريق الصح، والزائر بدون جوال ← مرفوض.
- `test_kb_retrieval.py`: hit@3 فوق الحد، والـ internal ما يطلع للعميل أبداً.
- `test_mock_laqta.py`: نفس idempotency key ← نفس الفعالية.
- `test_agent_smoke.py` (`@pytest.mark.llm`، ما يشتغل افتراضياً): ٣ محادثات قصيرة مع API حقيقي. هذي بذرة الطبقة ٢.

---

## 15. ترتيب الشغل

| اليوم | الشغل | مين يكتب |
|---|---|---|
| ١ | الهيكل، قاعدة البيانات، migrations، `policy.yaml`، الـ seed، `Identity` + `DevAuth` | Claude Code |
| ٢ | الـ state machine، `availability.check()`، القفل، اختبار السباق | Claude Code، وأنت تراجع كل guard |
| ٣ | محلّل التواريخ + ١٠٠ اختبار | **أنت** |
| ٤ | `MockLaqta`، التأكيد، الأدوات، الـ RAG + اختبار الاسترجاع | Claude Code |
| ٥ | حلقة المساعد، التعليمات، السياق، الملخص، الترمنال. جرّب ١٠ سيناريوهات بيدك واكتب كل غلطة | الاثنين |

قائمة الأغلاط من اليوم ٥ هي أول نسخة من تصنيف الأخطاء (failure taxonomy). احتفظ فيها.

---

## 16. برومبت Claude Code (الأيام ١، ٢، ٤)

> I'm building `assistant/`, a new service inside my Laqta repo: a text (later voice) assistant that books event activation windows on Laqta, answers questions from a knowledge base via RAG, and hands off to staff. Read `assistant/layer1-spec.md` fully before doing anything — it is the source of truth. Also read the repo's root `CLAUDE.md` for the existing Laqta conventions.
>
> **Constraints:**
> - Do not modify anything outside `assistant/`. The assistant talks to Laqta only through `app/laqta/adapter.py`; use `MockLaqta` for everything in this phase.
> - Same stack as Laqta: Python 3.11, SQLAlchemy 2.0, Alembic, Postgres 16 + pgvector, pytest. Separate database `assistant` in the existing Postgres container (host port 5433).
> - `app/domain/` must contain zero LLM calls and must never call `datetime.now()` — time is always passed in as `now`.
> - Every number comes from `policy.yaml`. No magic numbers in code.
> - **Do not implement `app/domain/dates/`.** Create only the pydantic intent models and a `resolve()` function signature that raises `NotImplementedError`. I will write the resolver myself.
> - Capacity locking uses `pg_advisory_xact_lock` as described in section 6, and the race test must run against real Postgres.
> - Only `confirm_action` and `handoff_to_staff` may cause side effects, and `confirm_action` must enforce the rules in section 8.
>
> **Work in this order, and stop for my review after each step:**
> 1. Project skeleton, config, models, first Alembic migration, seed script. (spec §1–4)
> 2. Booking state machine with full transition tests. (§5)
> 3. Availability rules, capacity lock, race test. (§6)
> 4. `MockLaqta`, confirmation tokens, tool registry and tools with tests. (§8–10)
> 5. KB chunker, embedder, index script, search, retrieval test. (§11)
>
> Show me the test output at each step. Do not start the agent loop — I'll do that with you after the resolver is done.
