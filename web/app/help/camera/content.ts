export interface VendorInfo {
  brand: string;
  software: string;
  url: string;
  urlLabel: string;
  note?: string;
}

export interface HelpStep {
  title: string;
  body: string;
}

export interface HelpQA {
  question: string;
  answer: string;
}

export interface WirelessTip {
  title: string;
  body: string;
}

export interface HelpContent {
  pageTitle: string;

  // Both paths, presented as equally valid choices based on shooting
  // style -- neither is the "main" one or a fallback for the other.
  pathsOverview: {
    heading: string;
    body: string;
    agentTitle: string;
    agentBody: string;
    ftpTitle: string;
    ftpBody: string;
  };

  selector: {
    heading: string;
    placeholder: string;
    noResults: string;
    notListedLabel: string;
    verdictFtpTitle: string;
    verdictFtpBody: string;
    verdictAgentTitle: string;
    verdictAgentBody: string;
    verdictNotListedBody: string;
    firmwareNote: string;
    changeCamera: string;
  };

  tabs: { agent: string; ftp: string };

  // --- Agent path ---
  agentIntro: { heading: string; paragraphs: string[] };
  diagram: {
    camera: string;
    usbCable: string;
    tetheringSoftware: string;
    folder: string;
    watches: string;
    agent: string;
    uploads: string;
    laqta: string;
  };
  usbNote: { title: string; body: string };
  eosWarning: { title: string; body: string };
  wireless: {
    heading: string;
    apWarningTitle: string;
    apWarningBody: string;
    correctSetupTitle: string;
    correctSetupBody: string;
    tips: WirelessTip[];
    coverageTestTitle: string;
    coverageTestBody: string;
  };
  vendorsHeading: string;
  vendors: VendorInfo[];
  stepsHeading: string;
  steps: HelpStep[];
  troubleshootingHeading: string;
  troubleshooting: HelpQA[];

  // --- Camera FTP path ---
  ftpIntro: { heading: string; paragraphs: string[] };
  ftpStepsHeading: string;
  ftpSteps: HelpStep[];
  ftpTroubleshootingHeading: string;
  ftpTroubleshooting: HelpQA[];

  // --- Download ---
  downloadHeading: string;
  downloadMac: string;
  downloadWindows: string;
  downloadWindowsUnavailable: string;
  downloadSource: string;
}

// Root official domains only -- not deep-linked support-article paths,
// which move over time and this content has no way to keep verified.
// Each vendor note tells the reader exactly what to search for once
// they're on the brand's own site.
const VENDORS_AR: VendorInfo[] = [
  {
    brand: "Canon",
    software: "EOS Utility",
    url: "https://www.canon.com/",
    urlLabel: "الموقع الرسمي لكانون",
    note: 'ابحث في قسم الدعم/التنزيلات عن اسم كاميرتك، ثم "EOS Utility".',
  },
  {
    brand: "Nikon",
    software: "NX Tether",
    url: "https://www.nikon.com/",
    urlLabel: "الموقع الرسمي لنيكون",
    note: 'ابحث عن "NX Tether" في مركز التنزيلات.',
  },
  {
    brand: "Sony",
    software: "Imaging Edge Remote",
    url: "https://www.sony.com/",
    urlLabel: "الموقع الرسمي لسوني",
    note: 'ابحث عن "Imaging Edge" — Remote هو الجزء المسؤول عن التصوير عن بُعد وحفظ الصور مباشرة.',
  },
  {
    brand: "Fujifilm",
    software: "X Acquire",
    url: "https://www.fujifilm.com/",
    urlLabel: "الموقع الرسمي لفوجي فيلم",
    note: 'ابحث عن "X Acquire" ضمن برامج كاميرات سلسلة X.',
  },
];

const VENDORS_EN: VendorInfo[] = [
  {
    brand: "Canon",
    software: "EOS Utility",
    url: "https://www.canon.com/",
    urlLabel: "Canon's official site",
    note: 'Search the support/downloads section for your camera model, then "EOS Utility".',
  },
  {
    brand: "Nikon",
    software: "NX Tether",
    url: "https://www.nikon.com/",
    urlLabel: "Nikon's official site",
    note: 'Search the download center for "NX Tether".',
  },
  {
    brand: "Sony",
    software: "Imaging Edge Remote",
    url: "https://www.sony.com/",
    urlLabel: "Sony's official site",
    note: '"Imaging Edge" is the suite; Remote is the part that shoots and saves photos live.',
  },
  {
    brand: "Fujifilm",
    software: "X Acquire",
    url: "https://www.fujifilm.com/",
    urlLabel: "Fujifilm's official site",
    note: 'Search for "X Acquire" under X-series camera software.',
  },
];

export const CONTENT: Record<"ar" | "en", HelpContent> = {
  ar: {
    pageTitle: "توصيل الكاميرا بلقطة",

    pathsOverview: {
      heading: "طريقتان، وكلتاهما مدعومتان بالكامل",
      body: "هناك طريقتان لرفع الصور إلى لقطة تلقائيًا أثناء الحدث. أيّهما تختار يعتمد فقط على أسلوب تصويرك، وليس على أن إحداهما «أفضل» من الأخرى:",
      agentTitle: "وكيل لقطة (جهاز كمبيوتر)",
      agentBody:
        "مناسب لموقع تصوير ثابت — بوث تصوير فردي، جلسات صور بترتيب معيّن، أو أي إعداد لا يتحرك فيه المصوّر كثيرًا بعيدًا عن مكانه. يحتاج جهاز كمبيوتر محمول بجانب الكاميرا طوال الوقت.",
      ftpTitle: "FTP الكاميرا (بلا كمبيوتر)",
      ftpBody:
        "مناسب لمصوّر يتنقل داخل القاعة أو الحدث. إذا كانت كاميرتك تدعم FTP المدمج، يمكنك التصوير من أي مكان دون حمل كمبيوتر محمول إطلاقًا، باستخدام نقطة اتصال جوال (5G) فقط.",
    },

    selector: {
      heading: "لست متأكدًا أيّهما يناسبك؟ اختر كاميرتك",
      placeholder: "اكتب اسم الشركة أو الطراز، مثل: Canon R5",
      noResults: "لا توجد نتائج مطابقة",
      notListedLabel: "لا أجد كاميرتي في القائمة",
      verdictFtpTitle: "✅ كاميرتك تدعم FTP المدمج",
      verdictFtpBody: "يمكنك التصوير من أي مكان في الحدث دون حمل كمبيوتر محمول، باستخدام نقطة اتصال جوال. اطّلع على طريقة FTP أدناه.",
      verdictAgentTitle: "💻 كاميرتك تحتاج جهاز كمبيوتر قريب",
      verdictAgentBody: "كاميرتك (حسب معلوماتنا) لا تملك FTP مدمجًا، لذا استخدم وكيل لقطة عبر جهاز كمبيوتر بجانب الكاميرا. اطّلع على طريقة الوكيل أدناه.",
      verdictNotListedBody:
        "لا مشكلة — طريقة وكيل لقطة تعمل مع أي كاميرا تقريبًا (طالما لديها برنامج تصوير مرتبط بالكمبيوتر من الشركة المصنّعة)، لذا هذا هو الخيار الآمن الافتراضي. إذا كنت تعرف أن كاميرتك تدعم FTP مدمجًا، يمكنك تجربة طريقة FTP مباشرة.",
      firmwareNote:
        "ملاحظة: بعض الشركات المصنّعة تضيف دعم FTP لكاميرات موجودة عبر تحديث البرامج الثابتة (firmware). إذا لم تجد كاميرتك في القائمة أو كانت مصنّفة «بلا FTP مدمج»، تحقّق من قائمة الشبكة/الاتصال في كاميرتك نفسها — فقد تجد خيار «نقل FTP» غير مذكور هنا بعد.",
      changeCamera: "تغيير الكاميرا",
    },

    tabs: { agent: "وكيل لقطة (موقع ثابت)", ftp: "FTP الكاميرا (تنقّل)" },

    agentIntro: {
      heading: "قبل أن تبدأ: هناك برنامجان، وأنت بحاجة لكليهما",
      paragraphs: [
        "هذه هي الفكرة الوحيدة التي يجب أن تفهمها قبل كل شيء في طريقة الوكيل، لأن معظم المشاكل سببها الخلط بينهما:",
        "١) برنامج كاميرتك (من Canon أو Nikon أو Sony أو Fujifilm) — وظيفته الوحيدة أن يحفظ كل صورة تلتقطها في مجلد على جهاز الكمبيوتر، لحظة التقاطها. هذا البرنامج لا علاقة له بلقطة إطلاقًا.",
        "٢) وكيل لقطة (Laqta Agent) — برنامجنا نحن، ووظيفته الوحيدة أن يراقب ذلك المجلد بالتحديد، وما إن تظهر فيه صورة جديدة حتى يرفعها تلقائيًا إلى لقطة خلال ثوانٍ.",
        "وكيل لقطة لا يتحدث مع الكاميرا أبدًا، ولا يعرف حتى أن لديك كاميرا — كل ما يفعله هو مراقبة مجلد. لذلك أهم خطوة في هذا القسم كله هي: تأكد أن البرنامجين يشيران إلى نفس المجلد بالضبط.",
      ],
    },
    diagram: {
      camera: "الكاميرا",
      usbCable: "كابل USB",
      tetheringSoftware: "برنامج الكاميرا (من الشركة المصنّعة)",
      folder: "مجلد على الكمبيوتر",
      watches: "يراقب",
      agent: "وكيل لقطة",
      uploads: "يرفع تلقائيًا",
      laqta: "لقطة",
    },
    usbNote: {
      title: "التوصيل الافتراضي: كابل USB",
      body: "وصّل الكاميرا بالكمبيوتر بكابل USB — هذا هو الأسلوب الموصى به دائمًا، خصوصًا يوم الحدث، لأنه الأكثر استقرارًا وسرعة. بعض أجسام الكاميرات تدعم التوصيل اللاسلكي (Wi-Fi) كبديل اختياري، لكن لا يُنصح به كخيار أساسي إلا إذا لم يكن أمامك خيار آخر.",
    },
    eosWarning: {
      title: "ملاحظة مهمة لمستخدمي Canon",
      body: 'ميزة "Connect to EOS Utility" التي تظهر في قائمة اتصال الكاميرا (اتصال Wi-Fi مباشر بين الكاميرا وبرنامج EOS Utility) شيء مختلف تمامًا عن "FTP الكاميرا" الذي قد تراه في قوائم بعض الكاميرات الاحترافية (انظر تبويب FTP أعلاه إن كنت تبحث عن ذلك). هذا القسم يتحدث فقط عن EOS Utility عبر كابل USB.',
    },
    wireless: {
      heading: "الاتصال اللاسلكي (بديل عن كابل USB)",
      apWarningTitle: "⚠️ تحذير مهم: لا تستخدم نقطة اتصال الكاميرا نفسها (وضع Access Point)",
      apWarningBody:
        'كثير من الكاميرات توفّر وضعًا تُنشئ فيه شبكة Wi-Fi خاصة بها (Access Point) لتتصل بها مباشرة من جهاز آخر. لا تستخدم هذا الوضع مع وكيل لقطة: إذا انضم الكمبيوتر إلى شبكة الكاميرا هذه، فلن يعود لديه أي اتصال بالإنترنت على الإطلاق — لأن شبكة الكاميرا معزولة تمامًا عن الإنترنت. سيستمر وكيل لقطة في رصد الصور الجديدة وإضافتها لقائمة الانتظار، لكنه لن يتمكن من رفع أي منها أبدًا، وقد لا تلاحظ المشكلة فورًا إن لم تراقب الشاشة. هذا هو الخطأ الأكثر شيوعًا في الاتصال اللاسلكي، وتحديدًا ما يظهر له وكيل لقطة الآن تحذيرًا واضحًا على الشاشة (انظر أدناه).',
      correctSetupTitle: "الإعداد الصحيح",
      correctSetupBody:
        "يجب أن تنضم الكاميرا والكمبيوتر كلاهما إلى نفس نقطة اتصال خارجية — نقطة اتصال جوال (هاتف) أو راوتر سفر (travel router) — وليس أن ينضم أحدهما إلى الآخر مباشرة. بهذه الطريقة يحصل الكمبيوتر على اتصال إنترنت حقيقي، بينما يبقى قادرًا على التواصل مع الكاميرا عبر نفس الشبكة المحلية.",
      tips: [
        {
          title: "ضع نقطة الاتصال في مكان مركزي ومرتفع",
          body: "كلما كانت نقطة الاتصال أقرب لمنتصف القاعة وأعلى ارتفاعًا (على طاولة أو رف، لا على الأرض)، كانت التغطية أفضل وأكثر تجانسًا في كل الاتجاهات.",
        },
        {
          title: "توقّع نطاق تغطية ١٠-٢٠ مترًا داخل المبنى",
          body: "هذا نطاق واقعي للاتصال اللاسلكي داخل قاعة عادية، ويتأثر بالجدران والحشود والتداخل مع شبكات أخرى. لا تفترض تغطية كاملة للقاعة دون اختبار فعلي (انظر اختبار التغطية أدناه).",
        },
        {
          title: "صوّر بحجم JPEG صغير أو متوسط فقط",
          body: "الملفات الكبيرة (JPEG بأقصى دقة، أو RAW) تستغرق وقتًا أطول بكثير للنقل لاسلكيًا مقارنة بكابل USB، مما قد يسبب تراكمًا في قائمة الانتظار. اضبط حجم الصورة في الكاميرا على صغير أو متوسط عند التصوير اللاسلكي.",
        },
        {
          title: "عطّل إيقاف التشغيل التلقائي للكاميرا",
          body: "معظم الكاميرات تدخل في وضع سكون أو تُغلق تلقائيًا بعد بضع دقائق من عدم الاستخدام، مما يقطع الاتصال اللاسلكي ويتطلب إعادة الاتصال يدويًا. عطّل هذا الإعداد (أو اضبطه على أطول مدة ممكنة) من قائمة إعدادات الطاقة في الكاميرا طوال فترة الحدث.",
        },
        {
          title: "أحضر بطاريات احتياطية",
          body: "يستهلك الاتصال اللاسلكي طاقة البطارية بشكل أسرع بكثير من التصوير العادي أو التوصيل بكابل USB (الذي يشحن الكاميرا أثناء الاستخدام في كثير من الأجسام). لا تعتمد على بطارية واحدة ليوم كامل من التصوير اللاسلكي.",
        },
      ],
      coverageTestTitle: "اختبار التغطية قبل الحدث",
      coverageTestBody:
        "لا تكتشف حدود التغطية اللاسلكية لأول مرة أثناء الحدث نفسه. قبل يوم الحدث بوقت كافٍ، اذهب إلى موقع التصوير وامشِ في كل أنحاء القاعة، والتقط صورة تجريبية كل بضعة أمتار أثناء تحركك، وراقب عداد «تم الرفع» في نافذة وكيل لقطة على الكمبيوتر (اطلب من شخص آخر مراقبته إن كنت تتحرك بالكاميرا بعيدًا عن الجهاز). علّم أي منطقة يتوقف فيها العداد عن الزيادة — هذه هي الحدود الفعلية لتغطيتك، ومن الأفضل معرفتها الآن والتخطيط حولها (نقل نقطة الاتصال، أو تجنّب التصوير من تلك الزاوية) بدلاً من اكتشافها فجأة أثناء الحدث.",
    },
    vendorsHeading: "١. ثبّت برنامج كاميرتك",
    vendors: VENDORS_AR,
    stepsHeading: "الخطوات كاملة، من الصفر",
    steps: [
      {
        title: "ثبّت برنامج الكاميرا الخاص بعلامتك التجارية",
        body: "نزّل وثبّت البرنامج المناسب لعلامة كاميرتك من الروابط أعلاه (Canon EOS Utility، Nikon NX Tether، Sony Imaging Edge Remote، أو Fujifilm X Acquire).",
      },
      {
        title: "وصّل الكاميرا بكابل USB وشغّلها",
        body: "استخدم كابل USB الأصلي أو كابلاً يدعم نقل البيانات (بعض الكابلات الرخيصة تُستخدم للشحن فقط ولا تنقل بيانات). شغّل الكاميرا بعد التوصيل.",
      },
      {
        title: "اضبط مجلد الحفظ على مجلد جديد وفارغ",
        body: 'في إعدادات برنامج الكاميرا، غيّر "مجلد الحفظ" (Save Destination / Transfer Destination) إلى مجلد جديد تنشئه خصيصًا لهذا الحدث، مثل: سطح المكتب ← صور_الحدث.',
      },
      {
        title: "التقط صورة تجريبية وتأكد من وصولها للمجلد",
        body: "التقط صورة واحدة، ثم افتح ذلك المجلد في جهاز الكمبيوتر وتأكد من ظهور ملف الصورة فيه فورًا. لا تكمل الخطوة التالية قبل التأكد من هذا.",
      },
      {
        title: "ثبّت وكيل لقطة وأدخل رمز الاقتران",
        body: "ثبّت تطبيق وكيل لقطة (Laqta Agent)، وعند فتحه أول مرة سيطلب منك رمزًا من ٦ خانات — احصل عليه من منظّم الحدث (يظهر له في لوحة التحكم عند الضغط على زر «ربط وكيل التصوير»)، وأدخله.",
      },
      {
        title: "اختر نفس المجلد بالضبط",
        body: "بعد الاقتران، سيطلب منك وكيل لقطة اختيار المجلد الذي سيراقبه — اختر نفس المجلد الذي ضبطته في الخطوة ٣، وليس مجلدًا آخر.",
      },
      {
        title: "التقط صورة أخرى وراقب العداد",
        body: 'التقط صورة جديدة بالكاميرا، وراقب نافذة وكيل لقطة — يجب أن ترى عداد "تم الرفع" يزداد خلال ثوانٍ قليلة. إذا زاد العداد، فكل شيء يعمل بشكل صحيح.',
      },
    ],
    troubleshootingHeading: "المشاكل الشائعة وحلولها",
    troubleshooting: [
      {
        question: "الصورة لا تظهر في المجلد بعد التقاطها",
        answer:
          "هذه مشكلة في برنامج الكاميرا نفسه، وليست في وكيل لقطة — فالوكيل لا يمكنه رفع صورة لم تصل إلى المجلد أصلاً. تحقق من: الكابل موصول بإحكام من الطرفين، الكاميرا في وضع التصوير الفعلي (وليست في وضع الاستعراض فقط)، إعداد «مجلد الحفظ» في البرنامج ما زال يشير للمجلد الصحيح، وأن برنامج الكاميرا ما زال يعمل ومتصلاً (بعض البرامج تقطع الاتصال تلقائيًا بعد فترة خمول طويلة — أغلقه وأعد فتحه).",
      },
      {
        question: "برنامج الكاميرا لا يكتشف الكاميرا أصلاً",
        answer:
          "جرّب بالترتيب: (١) كابل USB آخر — كابلات الشحن الرخيصة كثيرًا ما لا تنقل بيانات. (٢) منفذ USB آخر على الكمبيوتر مباشرة، وليس عبر موزّع (hub). (٣) تأكد أن وضع اتصال USB في قائمة الكاميرا نفسها مضبوط على «PC connection» أو «PTP»، وليس «تخزين كتلي» (Mass Storage / MTP قد لا يعمل مع بعض البرامج). (٤) أغلق برنامج الكاميرا وأعد فتحه. (٥) تأكد من تثبيت أحدث تعريفات (drivers) الكاميرا من موقع الشركة المصنّعة.",
      },
      {
        question: "وكيل لقطة يظهر «غير متصل»",
        answer:
          "هذا يعني فقط عدم وجود اتصال إنترنت في تلك اللحظة على جهاز الكمبيوتر — وليس مشكلة في برنامج الكاميرا أو في الصور نفسها. لا داعي للقلق: الصور تبقى محفوظة في طابور الانتظار داخل الجهاز، وسيُعاد رفعها تلقائيًا بمجرد عودة الاتصال، دون أي إجراء إضافي منك. تحقق من اتصال الواي فاي أو شبكة الإنترنت على الكمبيوتر نفسه.",
      },
      {
        question: "صوّرت قبل ربط الوكيل — هل ستضيع تلك الصور؟",
        answer:
          "لا. بمجرد اختيار المجلد بعد إدخال رمز الاقتران، يقوم وكيل لقطة تلقائيًا بفحص المجلد بالكامل، لا الصور الجديدة فقط — فيجد كل الصور الموجودة مسبقًا فيه ويبدأ برفعها. لا تحتاج لفعل شيء إضافي، لكن تأكد أنك اخترت نفس المجلد الذي كانت الصور تُحفظ فيه.",
      },
      {
        question: "كيف أشغّل فحص نهاية الحدث (للتأكد من رفع كل شيء)؟",
        answer:
          'في أي وقت، اضغط زر «فحص المجلد وإعادة رفع الصور القديمة» في نافذة وكيل لقطة. هذا يعيد فحص المجلد بالكامل من جديد — مفيد بشكل خاص في نهاية الحدث للتأكد من عدم تفويت أي صورة، خصوصًا إذا كان الوكيل مغلقًا لفترة أثناء التصوير.',
      },
    ],

    ftpIntro: {
      heading: "طريقة FTP: التصوير بلا كمبيوتر محمول",
      paragraphs: [
        "إذا كانت كاميرتك تدعم FTP مدمجًا (تحقق أعلاه إن لم تكن متأكدًا)، يمكنها إرسال كل صورة مباشرة إلى لقطة بنفسها، فور التقاطها — دون حاجة لأي جهاز كمبيوتر أو برنامج وسيط. هذا يعني أنك تستطيع التنقل بحرية في أي مكان بالحدث، طالما لديك اتصال إنترنت (عادةً عبر نقطة اتصال جوال 5G).",
        "كل حدث له بيانات دخول FTP خاصة به (خادم، منفذ، اسم مستخدم، كلمة مرور) يحصل عليها منظّم الحدث من لوحة التحكم بالضغط على زر «بيانات FTP» في بطاقة الحدث.",
      ],
    },
    ftpStepsHeading: "خطوات إعداد FTP على الكاميرا",
    ftpSteps: [
      {
        title: "احصل على بيانات FTP من منظّم الحدث",
        body: "اطلب من منظّم الحدث الضغط على زر «بيانات FTP» في بطاقة الحدث بلوحة التحكم — سيحصل على: الخادم (Host)، المنفذ (Port)، اسم المستخدم، وكلمة المرور. كلمة المرور تظهر مرة واحدة فقط، فتأكد من نسخها بدقة.",
      },
      {
        title: "افتح قائمة الشبكة/FTP في كاميرتك",
        body: "في قائمة إعدادات كاميرتك، ابحث عن قسم باسم «الشبكة» (Network) أو «الاتصال» (Connection)، ثم عن خيار «إعدادات نقل FTP» (FTP Transfer Settings). يختلف الاسم والمكان قليلًا حسب الشركة المصنّعة — راجع دليل كاميرتك إن لم تجده.",
      },
      {
        title: "أدخل الخادم والمنفذ",
        body: "أدخل قيمتي الخادم (Host) والمنفذ (Port) كما وردتا من المنظّم، بالضبط دون أي تعديل أو مسافات إضافية.",
      },
      {
        title: "فعّل FTPS (وليس FTP العادي)",
        body: "اختر وضع الاتصال «FTPS» أو «FTP over TLS» أو «Explicit FTPS» — وليس «FTP» العادي غير المشفّر. إذا ظهرت رسالة تحذير حول شهادة أمان غير موثوقة، هذا متوقع (نستخدم شهادة تطوير محلية)؛ اختر المتابعة/القبول.",
      },
      {
        title: "أدخل اسم المستخدم وكلمة المرور",
        body: "أدخلهما بدقة تامة (حساسان لحالة الأحرف). احفظ إعداد الاتصال.",
      },
      {
        title: "اختبر الاتصال إن توفر خيار لذلك",
        body: "بعض الكاميرات توفر زر «اختبار الاتصال» (Connection Test) ضمن إعدادات FTP — استخدمه للتأكد قبل بدء التصوير الفعلي.",
      },
      {
        title: "التقط صورة تجريبية وتأكد من الرفع",
        body: "التقط صورة، وراقب مؤشر النقل على شاشة الكاميرا (عادة رمز أو رسالة صغيرة تشير لنجاح الإرسال). إذا نجح، افتح لوحة تحكم لقطة وتأكد من ظهور الصورة في قائمة صور الحدث.",
      },
    ],
    ftpTroubleshootingHeading: "المشاكل الشائعة في FTP وحلولها",
    ftpTroubleshooting: [
      {
        question: "الكاميرا تقول «فشل الاتصال» (Connection Failed)",
        answer:
          "تحقق أولاً من أن الكاميرا متصلة فعليًا بالإنترنت (إشارة نقطة الاتصال الجوال قوية، وليست مجرد مفعّلة). ثم تأكد من: الخادم والمنفذ مُدخلان بالضبط دون أخطاء إملائية، ووضع الاتصال مضبوط على FTPS وليس FTP العادي.",
      },
      {
        question: "الاتصال ينجح لكن نقل الصور يفشل أو يتوقف (Timeout)",
        answer:
          "غالبًا سبب ذلك إعداد «الوضع السلبي» (Passive Mode) — تأكد من تفعيله إن وُجد كخيار منفصل في قائمة FTP بالكاميرا. إذا استمرت المشكلة، تواصل مع منظّم الحدث للتأكد من أن الشبكة التي يعمل عليها الخادم تسمح بنطاق منافذ النقل السلبي.",
      },
      {
        question: "الكاميرا تقول أن الصورة أُرسلت، لكنها لا تظهر في لقطة",
        answer:
          "تحقق من منظّم الحدث أن الحدث لا يزال نشطًا وأن بيانات FTP لم تُلغَ. إن كان الحدث من نوع «صارم»، فالصور لا تظهر لأحد قبل موافقة أحد المشرفين عليها من صفحة المراجعة — هذا سلوك متوقع وليس خطأ.",
      },
      {
        question: "بيانات الدخول توقفت عن العمل أثناء الحدث",
        answer:
          "يمكن لمنظّم الحدث إلغاء بيانات دخول أي وقت من لوحة التحكم (مثلاً عند فقدان جهاز). اطلب منه إصدار بيانات دخول جديدة من نفس بطاقة الحدث — يمكن إصدار أكثر من مجموعة بيانات لنفس الحدث.",
      },
      {
        question: "هل يمكن أن تفقد الاتصال أثناء التنقل داخل القاعة؟",
        answer:
          "نعم، وهذا الفرق الأساسي بين هذه الطريقة وطريقة الوكيل: الاعتماد على نقطة اتصال جوال يعني أن قوة الإشارة قد تختلف من مكان لآخر بالقاعة. هذا ليس عطلاً — إذا انقطع الاتصال مؤقتًا، أعد المحاولة بعد التأكد من عودة الإشارة. لموقع تصوير ثابت لا يتحرك، يوفّر الوكيل عبر جهاز كمبيوتر اتصالًا أكثر استقرارًا عادةً.",
      },
    ],

    downloadHeading: "تنزيل وكيل لقطة",
    downloadMac: "تنزيل لـ macOS",
    downloadWindows: "تنزيل لـ Windows",
    downloadWindowsUnavailable: "نسخة Windows الجاهزة للتنزيل غير متوفرة بعد — راجع ملف agent/README.md للتشغيل من الكود المصدري في هذه الأثناء.",
    downloadSource: "أو شغّله من الكود المصدري (للمطوّرين) — راجع agent/README.md",
  },

  en: {
    pageTitle: "Connecting your camera to Laqta",

    pathsOverview: {
      heading: "Two ways, both fully supported",
      body: "There are two ways to get photos into Laqta automatically during your event. Which one to use depends only on how you shoot, not on one being \"better\" than the other:",
      agentTitle: "Laqta Agent (a computer)",
      agentBody:
        "Best for a stationary shooting setup — a solo photo booth, seated portraits taken in sequence, or any setup where the photographer doesn't move far from their spot. Needs a laptop next to the camera the whole time.",
      ftpTitle: "Camera FTP (no computer)",
      ftpBody:
        "Best for a photographer moving around the venue. If your camera has built-in FTP, you can shoot from anywhere without carrying a laptop at all, using only a mobile hotspot (5G).",
    },

    selector: {
      heading: "Not sure which fits you? Pick your camera",
      placeholder: "Type your brand or model, e.g. Canon R5",
      noResults: "No matching cameras",
      notListedLabel: "I don't see my camera",
      verdictFtpTitle: "✅ Your camera has built-in FTP",
      verdictFtpBody: "You can shoot from anywhere at the event without a laptop, using a mobile hotspot. See the FTP path below.",
      verdictAgentTitle: "💻 Your camera needs a nearby computer",
      verdictAgentBody: "As far as we know, your camera doesn't have built-in FTP, so use Laqta Agent with a laptop next to the camera. See the agent path below.",
      verdictNotListedBody:
        "No problem -- the Laqta Agent path works with almost any camera (as long as it has a manufacturer tethering program), so it's the safe default. If you know your camera has built-in FTP, you can try the FTP path directly instead.",
      firmwareNote:
        "Note: some manufacturers add FTP support to existing cameras via a firmware update. If you don't see your camera listed, or it's marked as no built-in FTP, check your camera's own network/connection menu -- it may have an \"FTP transfer\" option not reflected here yet.",
      changeCamera: "Change camera",
    },

    tabs: { agent: "Laqta Agent (stationary)", ftp: "Camera FTP (mobile)" },

    agentIntro: {
      heading: "Before you start: there are two separate pieces of software, and you need both",
      paragraphs: [
        "This is the single most important thing to understand first for the agent path, because almost every problem people run into comes from mixing these two up:",
        "1) Your camera's tethering software (from Canon, Nikon, Sony, or Fujifilm) — its only job is to save every photo you take into a folder on your computer, the instant you take it. This software has nothing to do with Laqta.",
        "2) Laqta Agent — our software. Its only job is to watch that exact folder, and the moment a new photo appears in it, upload it to Laqta automatically within seconds.",
        "Laqta Agent never talks to your camera at all — it doesn't even know you have one. All it does is watch a folder. So the single most important step in this whole section is: make sure both programs are pointed at the exact same folder.",
      ],
    },
    diagram: {
      camera: "Camera",
      usbCable: "USB cable",
      tetheringSoftware: "Camera software (from the manufacturer)",
      folder: "A folder on your computer",
      watches: "watches",
      agent: "Laqta Agent",
      uploads: "uploads automatically",
      laqta: "Laqta",
    },
    usbNote: {
      title: "The default: a USB cable",
      body: "Connect your camera to the computer with a USB cable -- this is always the recommended path, especially on event day, because it's the most stable and fastest option. Some camera bodies support wireless (Wi-Fi) tethering as an optional alternative, but it isn't recommended as your main connection unless you have no other choice.",
    },
    eosWarning: {
      title: "Important note for Canon users",
      body: 'The "Connect to EOS Utility" feature in your camera\'s connection menu (a direct Wi-Fi link between the camera and the EOS Utility software) is completely different from "camera FTP", which some professional camera bodies also offer (see the FTP tab above if that\'s what you\'re looking for). This section only covers EOS Utility over a USB cable.',
    },
    wireless: {
      heading: "Wireless tethering (an alternative to USB)",
      apWarningTitle: "⚠️ Important warning: do NOT use the camera's own access point mode",
      apWarningBody:
        "Many cameras offer a mode where the camera creates its own Wi-Fi network (Access Point mode) that another device connects to directly. Don't use this mode with Laqta Agent: if the computer joins the camera's own network, it loses its internet connection entirely -- the camera's network is completely isolated from the internet. Laqta Agent will keep detecting new photos and queuing them, but it will never be able to upload any of them, and you may not notice right away if you're not watching the screen. This is the single most common wireless-tethering mistake, and it's exactly what Laqta Agent's offline warning banner now exists to catch immediately (see below).",
      correctSetupTitle: "The correct setup",
      correctSetupBody:
        "Both the camera and the computer must join the same external hotspot -- a mobile phone hotspot or a travel router -- not join each other directly. This way the computer gets a real internet connection, while still being able to reach the camera over the same local network.",
      tips: [
        {
          title: "Place the hotspot centrally and elevated",
          body: "The closer the hotspot is to the center of the venue, and the higher it's placed (on a table or shelf, not the floor), the more even and reliable the coverage in every direction.",
        },
        {
          title: "Expect 10-20m of indoor range",
          body: "That's a realistic range for wireless tethering inside an ordinary venue, affected by walls, crowds, and interference from other networks. Don't assume full-venue coverage without actually testing it (see the coverage test below).",
        },
        {
          title: "Shoot small or medium JPEG only",
          body: "Large files (full-resolution JPEG, or RAW) take much longer to transfer wirelessly than over USB, which can cause the upload queue to back up. Set the camera's image size to small or medium specifically for wireless shooting.",
        },
        {
          title: "Disable the camera's auto power-off",
          body: "Most cameras sleep or power off automatically after a few minutes of inactivity, which drops the wireless connection and requires manually reconnecting. Turn this off (or set it to the longest available duration) in the camera's power settings for the whole event.",
        },
        {
          title: "Bring spare batteries",
          body: "Wireless tethering drains the battery much faster than normal shooting or a USB connection (which charges the camera during use on many bodies). Don't rely on a single battery for a full day of wireless shooting.",
        },
      ],
      coverageTestTitle: "Test coverage before the event",
      coverageTestBody:
        "Don't discover the limits of your wireless coverage for the first time during the actual event. With enough time before the event, go to the venue and walk through the whole space, taking a test shot every few metres as you go, while watching the \"Uploaded\" counter in the Laqta Agent window on the computer (ask someone else to watch it if you're moving away from the machine with the camera). Mark any area where the counter stops increasing -- that's your actual coverage boundary, and it's much better to know it now and plan around it (move the hotspot, or avoid shooting from that spot) than to discover it suddenly during the event.",
    },
    vendorsHeading: "1. Install your camera's software",
    vendors: VENDORS_EN,
    stepsHeading: "The full steps, from zero",
    steps: [
      {
        title: "Install your camera brand's tethering software",
        body: "Download and install the right software for your camera brand from the links above (Canon EOS Utility, Nikon NX Tether, Sony Imaging Edge Remote, or Fujifilm X Acquire).",
      },
      {
        title: "Connect the camera with a USB cable and turn it on",
        body: "Use the original cable, or one that supports data transfer (some cheap cables are charge-only and carry no data). Turn the camera on after connecting it.",
      },
      {
        title: "Set the save destination to a new, empty folder",
        body: 'In the camera software\'s settings, change the "Save Destination" / "Transfer Destination" to a new folder you create specifically for this event, e.g. Desktop → EventPhotos.',
      },
      {
        title: "Take one test shot and confirm it reaches the folder",
        body: "Take a single photo, then open that folder on your computer and confirm the file appears there immediately. Don't move on to the next step until you've confirmed this.",
      },
      {
        title: "Install Laqta Agent and enter the pairing code",
        body: "Install the Laqta Agent app. The first time you open it, it will ask for a 6-character code -- get this from the event organizer (they see it on the dashboard after clicking \"Pair camera agent\"), and enter it.",
      },
      {
        title: "Choose the exact same folder",
        body: "After pairing, Laqta Agent will ask you to choose the folder it should watch -- choose the same folder you set in step 3, not a different one.",
      },
      {
        title: "Take another shot and watch the counter",
        body: 'Take a new photo with your camera and watch the Laqta Agent window -- the "Uploaded" counter should go up within a few seconds. If it does, everything is working correctly.',
      },
    ],
    troubleshootingHeading: "Common problems and fixes",
    troubleshooting: [
      {
        question: "The photo doesn't appear in the folder after I take it",
        answer:
          "This is a problem with the camera software itself, not Laqta Agent -- the agent can't upload a photo that never reached the folder in the first place. Check: the cable is firmly connected on both ends, the camera is actually in shooting mode (not just review/playback), the \"save destination\" setting in the software still points at the right folder, and the camera software is still running and connected (some tethering apps disconnect automatically after a long idle period -- close and reopen it).",
      },
      {
        question: "The tethering software doesn't detect the camera at all",
        answer:
          "Try, in order: (1) a different USB cable -- cheap charging-only cables often carry no data. (2) A different USB port, plugged directly into the computer, not through a hub. (3) Check that the USB connection mode in the camera's own menu is set to \"PC connection\" or \"PTP\", not \"Mass Storage\" (some software doesn't work with mass-storage/MTP mode). (4) Close and reopen the camera software. (5) Make sure you have the latest camera drivers installed from the manufacturer's site.",
      },
      {
        question: 'Laqta Agent shows "Offline"',
        answer:
          "This just means there's no internet connection on the computer at that moment -- it's not a problem with the camera software or the photos themselves. Don't worry: photos stay safely queued on the machine and will be uploaded automatically the moment the connection comes back, with no extra action needed from you. Check the computer's WiFi or network connection.",
      },
      {
        question: "I took photos before pairing the agent -- are they lost?",
        answer:
          "No. As soon as you choose the folder right after entering the pairing code, Laqta Agent automatically scans the entire folder, not just new photos from then on -- it finds every photo already sitting there and starts uploading them. You don't need to do anything extra, just make sure you pick the same folder the photos were already saved into.",
      },
      {
        question: "How do I run the end-of-event catch-up upload?",
        answer:
          'At any time, click "Scan folder and upload older photos" in the Laqta Agent window. This re-scans the whole folder from scratch -- especially useful at the end of the event to make sure nothing was missed, particularly if the agent was closed for a while during shooting.',
      },
    ],

    ftpIntro: {
      heading: "The FTP path: shoot with no laptop",
      paragraphs: [
        "If your camera has built-in FTP (check above if you're not sure), it can send every photo straight to Laqta by itself, the instant it's taken -- no computer or middleman software needed. That means you're free to move around anywhere at the event, as long as you have internet access (usually via a mobile 5G hotspot).",
        'Each event has its own FTP credentials (host, port, username, password) that the event organizer gets from the dashboard by clicking "FTP credentials" on the event card.',
      ],
    },
    ftpStepsHeading: "Setting up FTP on your camera",
    ftpSteps: [
      {
        title: "Get FTP credentials from the event organizer",
        body: 'Ask the organizer to click "FTP credentials" on the event card in the dashboard -- they\'ll get a host, port, username, and password. The password is shown only once, so make sure it\'s copied accurately.',
      },
      {
        title: "Open the network/FTP menu on your camera",
        body: 'In your camera\'s settings menu, look for a "Network" or "Connection" section, then an "FTP Transfer Settings" option. The exact name and location varies by manufacturer -- check your camera\'s manual if you can\'t find it.',
      },
      {
        title: "Enter the host and port",
        body: "Enter the host and port exactly as given by the organizer, with no extra spaces or typos.",
      },
      {
        title: "Turn on FTPS (not plain FTP)",
        body: 'Choose "FTPS", "FTP over TLS", or "Explicit FTPS" as the connection mode -- not plain, unencrypted "FTP". If you see a warning about an untrusted security certificate, that\'s expected (we use a local development certificate); choose to continue/accept.',
      },
      {
        title: "Enter the username and password",
        body: "Enter them exactly (they're case-sensitive). Save the connection settings.",
      },
      {
        title: "Test the connection if your camera offers it",
        body: 'Some cameras have a "Connection Test" option within the FTP settings -- use it to confirm everything works before you start shooting for real.',
      },
      {
        title: "Take a test shot and confirm the upload",
        body: "Take a photo and watch the transfer indicator on your camera's screen (usually a small icon or message confirming a successful send). If it succeeds, open the Laqta dashboard and confirm the photo appears in that event's photo list.",
      },
    ],
    ftpTroubleshootingHeading: "Common FTP problems and fixes",
    ftpTroubleshooting: [
      {
        question: '"Connection Failed" on the camera',
        answer:
          "First confirm the camera actually has internet access (the hotspot has real signal, not just power). Then check: the host and port are entered exactly right, with no typos, and the connection mode is set to FTPS, not plain FTP.",
      },
      {
        question: "Connection succeeds but the transfer fails or times out",
        answer:
          'This is usually a "Passive Mode" setting -- make sure it\'s turned on if your camera\'s FTP menu offers it as a separate option. If the problem continues, check with the event organizer that the network the server runs on allows the passive transfer port range through.',
      },
      {
        question: "The camera says the photo sent, but it doesn't show up in Laqta",
        answer:
          "Check with the organizer that the event is still active and the FTP credentials weren't revoked. If it's a \"strict\" privacy event, photos don't show up for anyone until a moderator approves them on the review page -- that's expected behavior, not a bug.",
      },
      {
        question: "The credentials stopped working mid-event",
        answer:
          "An organizer can revoke credentials at any time from the dashboard (e.g. if a device was lost). Ask them to issue a fresh set from the same event card -- more than one credential set can exist for the same event at once.",
      },
      {
        question: "Can the connection drop while I'm moving around the venue?",
        answer:
          "Yes -- and this is the core tradeoff versus the agent path: relying on a mobile hotspot means signal strength can vary from spot to spot in the venue. That's not a malfunction -- if the connection drops briefly, just retry once signal is back. For a fixed shooting spot that doesn't move, the agent over a laptop usually gives a more consistently stable connection.",
      },
    ],

    downloadHeading: "Download Laqta Agent",
    downloadMac: "Download for macOS",
    downloadWindows: "Download for Windows",
    downloadWindowsUnavailable: "A ready-to-run Windows build isn't available yet -- see agent/README.md to run it from source in the meantime.",
    downloadSource: "Or run it from source (for developers) -- see agent/README.md",
  },
};
