"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Bilingual, Lang } from "./types";

const ar = {
  app: "البلاسي ون",
  tagline: "شغّل محلّك من مكان واحد، بدون تعقيد.",
  login: "تسجيل الدخول", logout: "خروج", signup: "إنشاء حساب جديد", email: "البريد الإلكتروني", password: "كلمة المرور",
  password_hint: "١٢ حرفًا على الأقل", business_name: "اسم المحل", have_account: "عندك حساب؟", no_account: "لسه ماعندكش حساب؟",
  nav_today: "اليوم", nav_sales: "المبيعات", nav_inventory: "المخزون", nav_money: "الفلوس والحسابات", nav_settings: "الإدارة والإعدادات",
  welcome: "أهلًا", loading: "لحظة…", retry: "حاول تاني", next: "التالي", back: "رجوع", yes: "نعم", no: "لا", continue: "متابعة",
  connect_title: "اربط نظام أودو", connect_sub: "المنصة تعمل فوق أودو. اكتب بيانات الاتصال مرة واحدة وسنحفظها مشفّرة.",
  conn_name: "اسم الاتصال", conn_url: "عنوان أودو", conn_db: "اسم قاعدة البيانات", conn_login: "اسم المستخدم", conn_secret: "مفتاح API أو كلمة المرور",
  conn_secret_hint: "لا يظهر أبدًا في المتصفح بعد الحفظ", connect_btn: "اتصال وفحص", connecting: "نتحقق من الاتصال…",
  setup_title: "نجهّز محلّك", setup_sub: "جاوب على أسئلة بسيطة وسنجهّز لك خطة إعداد تراجعها قبل أي تغيير.",
  question_of: "سؤال", build_plan: "جهّز الخطة", building: "نقرأ أودو ونجهّز الخطة…",
  plan_title: "خطة الإعداد", plan_sub: "هذا ما سيتم عمله. لن يتغير شيء قبل موافقتك.",
  to_add: "سيتم إضافته", already_ok: "جاهز بالفعل", needs_attention: "يحتاج انتباهك",
  risk_low: "خطورة منخفضة", risk_medium: "خطورة متوسطة", risk_high: "خطورة عالية",
  approve: "أوافق على الخطة", approved: "تمت الموافقة", approvals_needed: "الموافقات المطلوبة",
  run: "ابدأ الإعداد", running: "جارٍ الإعداد…", export: "تنزيل الخطة",
  backup_note: "ننصح بعمل نسخة احتياطية لقاعدة أودو قبل البدء. الإعداد يضيف فقط ولا يعدّل أو يحذف شيئًا موجودًا.",
  confirm_run: "تأكيد وبدء الإعداد", cancel: "إلغاء",
  st_executing: "جارٍ التنفيذ", st_succeeded: "تم وتم التحقق", st_needs_review: "يحتاج مراجعة", st_failed: "فشل", st_skipped: "تم تخطيه", st_manual_required: "يدوي",
  done_title: "المحل جاهز للتشغيل", done_sub: "تحققنا من كل خطوة من أودو مباشرة.",
  review_title: "الإعداد يحتاج مراجعة", failed_title: "توقف الإعداد",
  rerun_hint: "يمكنك إعادة التشغيل بأمان: الخطوات المنتهية لا تتكرر.",
  nothing_to_do: "لا يوجد ما يحتاج تغييرًا. كل شيء جاهز.",
  today_title: "اليوم", today_sub: "نظرة سريعة على حالة محلّك",
  card_connection: "الاتصال بأودو", card_ready: "جاهزية النظام", card_setup: "الإعداد", ok: "سليم", problem: "به مشكلة",
  checked: "آخر فحص", issues: "ملاحظات", no_issues: "لا توجد مشاكل مانعة", blocking: "مشاكل مانعة",
  next_step: "الخطوة التالية", go_setup: "ابدأ إعداد المحل", go_connect: "اربط أودو", go_plan: "راجع الخطة", all_set: "كل شيء جاهز",
  kpi_sales: "مبيعات اليوم", kpi_cash: "النقدية بالخزنة", kpi_stock: "أصناف قاربت على النفاد", kpi_payables: "مستحق للموردين",
  kpi_na: "يتوفر بعد تفعيل شاشة البيع. لن نعرض أرقامًا غير موثّقة.",
  soon_title: "قيد البناء", soon_sales: "شاشة البيع السريع بالباركود والميزان", soon_inventory: "المنتجات والمخزون والجرد والمشتريات", soon_money: "الخزنة والمصروفات وحسابات الموردين والعملاء",
  soon_sub: "تُبنى في المرحلة القادمة فوق الإعداد الذي أنجزته.",
  settings_conn: "اتصال أودو", settings_setup: "إعداد المحل", settings_plans: "خطط الإعداد السابقة",
  err_network: "تعذّر الوصول للخادم. تحقق من الاتصال.", err_generic: "حدث خطأ غير متوقع.", err_ref: "رقم مرجعي",
  err_invalid_credentials: "البريد أو كلمة المرور غير صحيحة.", err_rate_limited: "محاولات كثيرة، انتظر قليلًا ثم حاول.",
  err_email_taken: "هذا البريد مسجّل بالفعل.", err_validation: "راجع البيانات المدخلة.",
  err_unsafe_url: "هذا العنوان غير مسموح به لأسباب أمنية.", err_odoo_unavailable: "تعذّر الاتصال بأودو بهذه البيانات. راجع العنوان والقاعدة والمفتاح.",
  err_name_taken: "يوجد اتصال بهذا الاسم.", err_forbidden: "ليست لديك صلاحية لهذا الإجراء.", err_plan_drift: "تغيّر أودو منذ مراجعة الخطة. جهّز خطة جديدة.",
  err_plan_not_applicable: "الخطة بها تعارضات أو اختيارات غير مدعومة.", err_nothing_to_apply: "لا يوجد ما يحتاج تغييرًا.", err_approval_role: "دورك لا يسمح بالموافقة على هذه الخطة.",
  lang_switch: "English",
  v_grocery: "بقالة / ميني ماركت", v_bookstore: "مكتبة", v_shoes: "محل أحذية", v_clothing: "محل ملابس", v_general: "تجارة عامة",
  p_cash: "نقدًا", p_card: "بطاقة", p_wallet: "محفظة إلكترونية", p_bank_transfer: "تحويل بنكي",
  role_owner: "المالك", role_accountant: "المحاسب",
  nav_menu: "القائمة الرئيسية",
  impact_install_module: "يضيف قوائم وبيانات هذا التطبيق إلى أودو.", recovery_install_module: "يمكن إلغاء التطبيق من أودو، لكن بياناته قد تُفقد. خذ نسخة احتياطية أولًا.",
  impact_enable_feature: "يفعّل إعدادًا في أودو. المنتجات الحالية لا تتأثر.", recovery_enable_feature: "يمكن إيقاف الإعداد من أودو إن لم تعتمد عليه بيانات.",
  impact_ensure_journal: "يضيف دفترًا واحدًا وحسابه.", recovery_ensure_journal: "يمكن أرشفة الدفتر إن لم تُسجَّل عليه قيود.",
  impact_ensure_pos_payment_method: "يضيف طريقة دفع لنقطة البيع.", recovery_ensure_pos_payment_method: "يمكن أرشفتها إن لم تُستخدم.",
  impact_ensure_pos_config: "ينشئ نقطة بيع واحدة ويربطها بطرق الدفع.", recovery_ensure_pos_config: "يمكن أرشفة نقطة البيع إن لم تُفتح عليها جلسات.",
  impact_load_chart_of_accounts: "يحمّل دليل الحسابات القياسي للدولة. خطوة مالية تُنفَّذ يدويًا مع المحاسب.", recovery_load_chart_of_accounts: "لا رجوع عنها بعد ترحيل القيود.",
  note_accounting: "دليل الحسابات والضرائب الحالية تبقى كما هي. راجعها مع محاسبك.",
  note_pos: "إعداد نقطة البيع الحالي يبقى كما هو؛ أي نقص يظهر في فحص الجاهزية.",
  note_barcode: "باركود الميزان مدعوم في أودو أصلًا، وسنولّد لك أكواد الميزان للمنتجات.",
  conflict_multi_branch: "تعدد الفروع غير مدعوم بعد. ابدأ بفرع واحد.", conflict_weighing_with_variants: "الأصناف الموزونة مع المقاسات والألوان غير مدعومة.",
  conflict_no_weight_barcode_rule: "لا توجد قاعدة باركود وزن في أودو. راجع إعداد الباركود يدويًا قبل استخدام الميزان.", conflict_incompatible_environment: "نسخة أودو هذه غير معتمدة بعد، فلا يمكن تطبيق خطة عليها.",
  blocked_generic: "غير متاح الآن",
} as const;

type Key = keyof typeof ar;
const en: Record<Key, string> = {
  app: "Elblasy One", tagline: "Run your shop from one simple place.",
  login: "Sign in", logout: "Sign out", signup: "Create account", email: "Email", password: "Password",
  password_hint: "At least 12 characters", business_name: "Shop name", have_account: "Have an account?", no_account: "No account yet?",
  nav_today: "Today", nav_sales: "Sales", nav_inventory: "Inventory", nav_money: "Money & Accounts", nav_settings: "Management & Settings",
  welcome: "Welcome", loading: "One moment…", retry: "Try again", next: "Next", back: "Back", yes: "Yes", no: "No", continue: "Continue",
  connect_title: "Connect your Odoo", connect_sub: "The platform runs on top of Odoo. Enter the connection details once; they are stored encrypted.",
  conn_name: "Connection name", conn_url: "Odoo address", conn_db: "Database name", conn_login: "Username", conn_secret: "API key or password",
  conn_secret_hint: "Never shown in the browser after saving", connect_btn: "Connect & check", connecting: "Checking the connection…",
  setup_title: "Let's set up your shop", setup_sub: "Answer a few simple questions and we'll prepare a plan you review before anything changes.",
  question_of: "Question", build_plan: "Build my plan", building: "Reading Odoo and preparing the plan…",
  plan_title: "Setup plan", plan_sub: "This is what will be done. Nothing changes before you approve.",
  to_add: "Will be added", already_ok: "Already in place", needs_attention: "Needs your attention",
  risk_low: "Low risk", risk_medium: "Medium risk", risk_high: "High risk",
  approve: "Approve this plan", approved: "Approved", approvals_needed: "Approvals required",
  run: "Start setup", running: "Setting up…", export: "Download plan",
  backup_note: "We recommend backing up the Odoo database first. Setup only adds; it never edits or deletes existing things.",
  confirm_run: "Confirm & start", cancel: "Cancel",
  st_executing: "In progress", st_succeeded: "Done & verified", st_needs_review: "Needs review", st_failed: "Failed", st_skipped: "Skipped", st_manual_required: "Manual",
  done_title: "Your shop is ready", done_sub: "Every step was verified directly from Odoo.",
  review_title: "Setup needs review", failed_title: "Setup stopped",
  rerun_hint: "You can safely run it again: finished steps are not repeated.",
  nothing_to_do: "Nothing needs changing. Everything is ready.",
  today_title: "Today", today_sub: "A quick look at your shop",
  card_connection: "Odoo connection", card_ready: "System readiness", card_setup: "Setup", ok: "Healthy", problem: "Has a problem",
  checked: "Last checked", issues: "Findings", no_issues: "No blocking issues", blocking: "Blocking issues",
  next_step: "Next step", go_setup: "Set up my shop", go_connect: "Connect Odoo", go_plan: "Review the plan", all_set: "All set",
  kpi_sales: "Today's sales", kpi_cash: "Cash in drawer", kpi_stock: "Items running low", kpi_payables: "Owed to suppliers",
  kpi_na: "Available once the sales screen is live. We won't show unverified numbers.",
  soon_title: "Under construction", soon_sales: "Fast sales with barcode and scale", soon_inventory: "Products, stock, counts and purchasing", soon_money: "Cash drawer, expenses, supplier and customer accounts",
  soon_sub: "Built next, on top of the setup you just finished.",
  settings_conn: "Odoo connection", settings_setup: "Shop setup", settings_plans: "Previous setup plans",
  err_network: "Can't reach the server. Check your connection.", err_generic: "Something unexpected happened.", err_ref: "Reference",
  err_invalid_credentials: "Wrong email or password.", err_rate_limited: "Too many attempts. Please wait and try again.",
  err_email_taken: "This email is already registered.", err_validation: "Please check the entered data.",
  err_unsafe_url: "This address is not allowed for security reasons.", err_odoo_unavailable: "Couldn't connect to Odoo with these details. Check the address, database and key.",
  err_name_taken: "A connection with this name exists.", err_forbidden: "You don't have permission for this action.", err_plan_drift: "Odoo changed since the plan was reviewed. Build a new plan.",
  err_plan_not_applicable: "The plan has conflicts or unsupported choices.", err_nothing_to_apply: "Nothing needs changing.", err_approval_role: "Your role cannot approve this plan.",
  lang_switch: "العربية",
  v_grocery: "Grocery / mini-market", v_bookstore: "Bookstore", v_shoes: "Shoe store", v_clothing: "Clothing store", v_general: "General trading",
  p_cash: "Cash", p_card: "Card", p_wallet: "E-wallet", p_bank_transfer: "Bank transfer",
  role_owner: "Owner", role_accountant: "Accountant",
  nav_menu: "Main menu",
  impact_install_module: "Adds this app's menus and data to Odoo.", recovery_install_module: "The app can be uninstalled in Odoo, but its data may be lost. Back up first.",
  impact_enable_feature: "Turns on a setting in Odoo. Existing products are unaffected.", recovery_enable_feature: "The setting can be turned off in Odoo if no data depends on it.",
  impact_ensure_journal: "Adds one journal and its account.", recovery_ensure_journal: "The journal can be archived if it has no entries.",
  impact_ensure_pos_payment_method: "Adds a payment method for the point of sale.", recovery_ensure_pos_payment_method: "Can be archived if unused.",
  impact_ensure_pos_config: "Creates one point of sale and attaches the payment methods.", recovery_ensure_pos_config: "The point of sale can be archived if it has no sessions.",
  impact_load_chart_of_accounts: "Loads the country's standard chart of accounts. A financial step done manually with your accountant.", recovery_load_chart_of_accounts: "Cannot be undone once entries are posted.",
  note_accounting: "Your existing chart of accounts and taxes are kept as they are. Review them with your accountant.",
  note_pos: "Your existing point-of-sale setup is kept as it is; gaps show up in the readiness scan.",
  note_barcode: "Weighing-scale barcodes are supported natively in Odoo, and we'll generate scale codes for your products.",
  conflict_multi_branch: "Multiple branches aren't supported yet. Start with one.", conflict_weighing_with_variants: "Weighed items with sizes/colours are not supported.",
  conflict_no_weight_barcode_rule: "No weight-barcode rule exists in Odoo. Review the barcode setup manually before using a scale.", conflict_incompatible_environment: "This Odoo version isn't verified yet, so no plan can be applied.",
  blocked_generic: "Not available right now",
};

const dict = { ar, en } as const;
export type TKey = Key;

interface Ctx { lang: Lang; dir: "rtl" | "ltr"; t: (k: TKey) => string; tr: (b: Bilingual | undefined) => string; setLang: (l: Lang) => void }
const LangCtx = createContext<Ctx | null>(null);

export function LangProvider({ initial, children }: { initial: Lang; children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    document.cookie = `lang=${l}; path=/; max-age=31536000; samesite=lax`;
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);
  const value = useMemo<Ctx>(
    () => ({
      lang, dir: lang === "ar" ? "rtl" : "ltr", setLang,
      t: (k) => dict[lang][k],
      tr: (b) => (b ? b[lang] : ""),
    }),
    [lang, setLang],
  );
  return <LangCtx.Provider value={value}>{children}</LangCtx.Provider>;
}

export function useLang(): Ctx {
  const c = useContext(LangCtx);
  if (!c) throw new Error("LangProvider missing");
  return c;
}

/** Maps API error codes to friendly text; falls back to a generic message plus the reference id. */
/** Localised text for a keyed API message; falls back to the API's own (English) text. */
export function keyed(t: (k: TKey) => string, prefix: string, id: string, fallback: string): string {
  const key = `${prefix}_${id}` as TKey;
  return key in ar ? t(key) : fallback;
}

export function errorText(t: (k: TKey) => string, code: string): string {
  const key = `err_${code}` as TKey;
  return key in ar ? t(key) : t("err_generic");
}
