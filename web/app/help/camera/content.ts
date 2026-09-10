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

export interface HelpContent {
  pageTitle: string;
  intro: {
    heading: string;
    paragraphs: string[];
  };
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
  vendorsHeading: string;
  vendors: VendorInfo[];
  stepsHeading: string;
  steps: HelpStep[];
  troubleshootingHeading: string;
  troubleshooting: HelpQA[];
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
    intro: {
      heading: "قبل أن تبدأ: هناك برنامجان، وأنت بحاجة لكليهما",
      paragraphs: [
        "هذه هي الفكرة الوحيدة التي يجب أن تفهمها قبل كل شيء، لأن معظم المشاكل سببها الخلط بينهما:",
        "١) برنامج كاميرتك (من Canon أو Nikon أو Sony أو Fujifilm) — وظيفته الوحيدة أن يحفظ كل صورة تلتقطها في مجلد على جهاز الكمبيوتر، لحظة التقاطها. هذا البرنامج لا علاقة له بلقطة إطلاقًا.",
        "٢) وكيل لقطة (Laqta Agent) — برنامجنا نحن، ووظيفته الوحيدة أن يراقب ذلك المجلد بالتحديد، وما إن تظهر فيه صورة جديدة حتى يرفعها تلقائيًا إلى لقطة خلال ثوانٍ.",
        "وكيل لقطة لا يتحدث مع الكاميرا أبدًا، ولا يعرف حتى أن لديك كاميرا — كل ما يفعله هو مراقبة مجلد. لذلك أهم خطوة في هذا الدليل كله هي: تأكد أن البرنامجين يشيران إلى نفس المجلد بالضبط.",
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
      body: 'ميزة "Connect to EOS Utility" التي تظهر في قائمة اتصال الكاميرا (اتصال Wi-Fi مباشر بين الكاميرا وبرنامج EOS Utility) شيء مختلف تمامًا عن "FTP الكاميرا" الذي قد تراه في قوائم بعض الكاميرات الاحترافية. هذا الدليل يتحدث فقط عن EOS Utility عبر كابل USB — وليس عن أي إعداد FTP في الكاميرا نفسها.',
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
  },
  en: {
    pageTitle: "Connecting your camera to Laqta",
    intro: {
      heading: "Before you start: there are two separate pieces of software, and you need both",
      paragraphs: [
        "This is the single most important thing to understand first, because almost every problem people run into comes from mixing these two up:",
        "1) Your camera's tethering software (from Canon, Nikon, Sony, or Fujifilm) — its only job is to save every photo you take into a folder on your computer, the instant you take it. This software has nothing to do with Laqta.",
        "2) Laqta Agent — our software. Its only job is to watch that exact folder, and the moment a new photo appears in it, upload it to Laqta automatically within seconds.",
        "Laqta Agent never talks to your camera at all — it doesn't even know you have one. All it does is watch a folder. So the single most important step in this whole guide is: make sure both programs are pointed at the exact same folder.",
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
      body: 'The "Connect to EOS Utility" feature in your camera\'s connection menu (a direct Wi-Fi link between the camera and the EOS Utility software) is completely different from "camera FTP", which some professional camera bodies also offer. This guide only covers EOS Utility over a USB cable -- not any FTP setting on the camera itself.',
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
  },
};
