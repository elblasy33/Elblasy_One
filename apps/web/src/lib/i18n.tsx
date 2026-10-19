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
  pos_title: "الكاشير", pos_no_config: "لا توجد نقطة بيع مضبوطة بعد", pos_no_config_sub: "أكمل إعداد المحل أولًا لتُجهَّز نقطة البيع.", pos_go_setup: "إعداد المحل",
  pos_open_title: "افتح الخزنة", pos_open_sub: "اكتب النقدية التي في الدرج الآن لبدء الوردية.", pos_opening_cash: "النقدية الافتتاحية", pos_open_btn: "فتح الخزنة",
  pos_scan: "امسح الباركود أو ابحث باسم المنتج", pos_not_found: "لم نجد هذا الباركود", pos_empty_cart: "السلة فارغة. امسح منتجًا أو اختر من القائمة.",
  pos_total: "الإجمالي", pos_tax: "منها ضريبة", pos_pay: "ادفع", pos_clear: "تفريغ السلة", pos_qty: "الكمية", pos_discount: "خصم %", pos_stock_low: "المتاح",
  pay_title: "الدفع", pay_method: "طريقة الدفع", pay_tendered: "المبلغ المدفوع", pay_exact: "بالضبط", pay_change: "الباقي للعميل", pay_confirm: "تأكيد البيع", pay_short: "المبلغ أقل من الإجمالي",
  sale_done: "تم البيع", sale_verified: "وتحقّقنا منه في أودو", sale_new: "بيع جديد", sale_print: "طباعة الإيصال", sale_stock_late: "المخزون سيُخصم عند إغلاق الخزنة.",
  rcpt_ref: "رقم الإيصال", rcpt_cashier: "الكاشير", rcpt_paid: "المدفوع", rcpt_change: "الباقي", rcpt_thanks: "شكرًا لزيارتكم",
  close_title: "إغلاق الخزنة", close_sub: "عُدّ النقدية في الدرج واكتب المبلغ. سنقارنه بما يتوقعه النظام.", close_counted: "النقدية المعدودة", close_btn: "إغلاق الخزنة", close_open: "الخزنة مفتوحة منذ",
  close_expected: "المتوقع", close_diff: "الفرق", close_balanced: "الخزنة مطابقة", close_posted: "تم ترحيل القيود المحاسبية في أودو.", close_diff_warn: "يوجد فرق في الخزنة. سُجّل في سجل التدقيق.",
  hist_title: "مبيعات الوردية", hist_none: "لا مبيعات في هذه الوردية بعد", hist_items: "صنف", refund: "مرتجع", refund_confirm: "استرجاع كامل لهذا البيع", refunded: "تم الاسترجاع", refund_method_note: "يُرد المبلغ نقدًا.",
  tab_register: "البيع", tab_history: "المبيعات",
  kpi_sales_net: "صافي مبيعات اليوم", kpi_cash_net: "النقدية المحصّلة اليوم", kpi_def: "التعريف", kpi_orders: "طلب",
  err_price_changed: "تغيّر السعر منذ عرض الإجمالي. راجع السلة ثم أعد المحاولة.", err_no_open_session: "الخزنة مغلقة. افتحها أولًا.", err_sales_rejected: "رفض أودو العملية.",
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
  prod_title: "المنتجات", prod_search: "ابحث بالاسم أو الباركود", prod_add: "منتج جديد", prod_import: "استيراد من ملف", prod_none: "لا توجد منتجات بعد", prod_none_sub: "أضف أول منتج أو استورد قائمتك دفعة واحدة.",
  prod_found: "منتج", prod_price: "السعر", prod_cost: "التكلفة", prod_stock: "في المخزن", prod_by_weight: "بالوزن", prod_variants: "نوع/مقاس", prod_lot: "صلاحية/دفعات",
  prod_prev: "السابق", prod_next: "التالي", prod_no_stock_info: "غير متابَع",
  np_title: "منتج جديد", np_name: "اسم المنتج", np_price: "سعر البيع", np_cost: "سعر الشراء (التكلفة)", np_category: "التصنيف (اختياري)", np_sku: "كود داخلي (اختياري)",
  np_barcode: "الباركود", np_bc_type: "اكتبه", np_bc_auto: "ولّد تلقائيًا", np_bc_scale: "كود ميزان تلقائي", np_bc_none: "بدون باركود",
  np_weight: "يُباع بالوزن (كيلو)", np_weight_hint: "سيُحفظ بكود الميزان ليقرأه الكاشير مباشرة.",
  np_variants: "له مقاسات أو ألوان", np_attr_name: "الخاصية", np_attr_values: "القيم (افصل بفاصلة)", np_add_attr: "إضافة خاصية", np_preset_shoes: "مقاسات أحذية ٣٦–٤٦", np_preset_clothes: "مقاسات ملابس S–XXL", np_variants_total: "عدد التركيبات",
  np_lot: "يتبع الصلاحية والدفعات", np_pos: "يظهر في شاشة البيع", np_made: "منتج مصنّع عندي",
  np_save: "حفظ المنتج", np_saved: "تم حفظ المنتج", np_verified: "وتحقّقنا منه في أودو", np_another: "إضافة منتج آخر", np_to_recipe: "حدّد مكوّناته", np_to_list: "عرض المنتجات",
  np_retry_note: "إن انقطع الاتصال أعد الضغط، لن يُكرَّر المنتج.", np_unknown: "ربما تم الحفظ. اضغط حفظ مرة أخرى بأمان ولن يتكرر المنتج.",
  rc_title: "مكوّنات المنتج المصنّع", rc_yield: "الكمية الناتجة", rc_add: "أضف مكوّنًا", rc_qty: "الكمية", rc_save: "حفظ الوصفة", rc_saved: "تم حفظ الوصفة", rc_pick: "اختر المنتج المصنّع", rc_search: "ابحث عن مكوّن",
  im_title: "استيراد المنتجات", im_sub: "الصق ملف CSV أو اختره. سنراجعه أولًا ولن نُنشئ شيئًا قبل موافقتك.", im_template: "تنزيل نموذج", im_choose: "اختر ملفًا", im_paste: "أو الصق المحتوى هنا",
  im_check: "راجع الملف", im_rows: "صفوف", im_valid: "سليمة", im_invalid: "بها مشكلات", im_commit: "أنشئ الصفوف السليمة", im_done: "تم الاستيراد", im_created: "تم إنشاؤها", im_skipped: "تم تخطيها", im_limit: "حتى ١٠٠ صف في المرة الواحدة.", im_row: "صف",
  err_product_rejected: "رفض أودو المنتج.", err_idempotency_conflict: "تم استخدام هذا الطلب لبيانات مختلفة. حدّث الصفحة.", err_outcome_unknown: "ربما تم الحفظ. اضغط حفظ مرة أخرى بأمان.", err_in_progress: "العملية ما زالت جارية، انتظر لحظة.",
  err_verification_failed: "تعذّر التأكد من المنتج في أودو. راجعه قبل المتابعة.", err_recipe_rejected: "رفض أودو الوصفة.", err_verification_unavailable: "تم الحفظ لكن تعذّر التحقق. اضغط حفظ مرة أخرى بأمان.",
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
  pos_title: "Register", pos_no_config: "No point of sale is set up yet", pos_no_config_sub: "Finish the shop setup first so a point of sale gets created.", pos_go_setup: "Shop setup",
  pos_open_title: "Open the register", pos_open_sub: "Enter the cash currently in the drawer to start the shift.", pos_opening_cash: "Opening cash", pos_open_btn: "Open register",
  pos_scan: "Scan a barcode or search by product name", pos_not_found: "Barcode not found", pos_empty_cart: "The cart is empty. Scan a product or pick from the list.",
  pos_total: "Total", pos_tax: "of which tax", pos_pay: "Pay", pos_clear: "Clear cart", pos_qty: "Qty", pos_discount: "Discount %", pos_stock_low: "In stock",
  pay_title: "Payment", pay_method: "Payment method", pay_tendered: "Amount paid", pay_exact: "Exact", pay_change: "Change due", pay_confirm: "Confirm sale", pay_short: "Amount is less than the total",
  sale_done: "Sale complete", sale_verified: "and verified in Odoo", sale_new: "New sale", sale_print: "Print receipt", sale_stock_late: "Stock will be deducted when the register is closed.",
  rcpt_ref: "Receipt no.", rcpt_cashier: "Cashier", rcpt_paid: "Paid", rcpt_change: "Change", rcpt_thanks: "Thank you for shopping with us",
  close_title: "Close the register", close_sub: "Count the cash in the drawer and enter it. We'll compare it with what the system expects.", close_counted: "Counted cash", close_btn: "Close register", close_open: "Register open since",
  close_expected: "Expected", close_diff: "Difference", close_balanced: "The register balances", close_posted: "Accounting entries were posted in Odoo.", close_diff_warn: "There is a cash difference. It was recorded in the audit log.",
  hist_title: "This shift's sales", hist_none: "No sales in this shift yet", hist_items: "items", refund: "Refund", refund_confirm: "Fully refund this sale", refunded: "Refunded", refund_method_note: "The amount is paid back in cash.",
  tab_register: "Sell", tab_history: "Sales",
  kpi_sales_net: "Net sales today", kpi_cash_net: "Cash collected today", kpi_def: "Definition", kpi_orders: "orders",
  err_price_changed: "The price changed since the total was shown. Review the cart and try again.", err_no_open_session: "The register is closed. Open it first.", err_sales_rejected: "Odoo rejected the operation.",
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
  prod_title: "Products", prod_search: "Search by name or barcode", prod_add: "New product", prod_import: "Import from file", prod_none: "No products yet", prod_none_sub: "Add your first product or import your list in one go.",
  prod_found: "products", prod_price: "Price", prod_cost: "Cost", prod_stock: "In stock", prod_by_weight: "By weight", prod_variants: "variants", prod_lot: "Expiry/lots",
  prod_prev: "Previous", prod_next: "Next", prod_no_stock_info: "Not tracked",
  np_title: "New product", np_name: "Product name", np_price: "Selling price", np_cost: "Purchase price (cost)", np_category: "Category (optional)", np_sku: "Internal code (optional)",
  np_barcode: "Barcode", np_bc_type: "Type it", np_bc_auto: "Generate", np_bc_scale: "Auto scale code", np_bc_none: "No barcode",
  np_weight: "Sold by weight (kg)", np_weight_hint: "Saved with a scale code so the cashier can scan it directly.",
  np_variants: "Has sizes or colours", np_attr_name: "Attribute", np_attr_values: "Values (comma-separated)", np_add_attr: "Add attribute", np_preset_shoes: "Shoe sizes 36–46", np_preset_clothes: "Clothing sizes S–XXL", np_variants_total: "Combinations",
  np_lot: "Track expiry & lots", np_pos: "Show on the sales screen", np_made: "I make this product",
  np_save: "Save product", np_saved: "Product saved", np_verified: "and verified in Odoo", np_another: "Add another", np_to_recipe: "Set its ingredients", np_to_list: "View products",
  np_retry_note: "If the connection drops, press again: the product won't be duplicated.", np_unknown: "It may have been saved. Press save again safely; it won't be duplicated.",
  rc_title: "Ingredients of a made product", rc_yield: "Quantity produced", rc_add: "Add ingredient", rc_qty: "Quantity", rc_save: "Save recipe", rc_saved: "Recipe saved", rc_pick: "Pick the made product", rc_search: "Search an ingredient",
  im_title: "Import products", im_sub: "Paste a CSV or choose a file. We check it first and create nothing until you confirm.", im_template: "Download template", im_choose: "Choose a file", im_paste: "or paste the content here",
  im_check: "Check the file", im_rows: "rows", im_valid: "valid", im_invalid: "with problems", im_commit: "Create the valid rows", im_done: "Import finished", im_created: "created", im_skipped: "skipped", im_limit: "Up to 100 rows at a time.", im_row: "Row",
  err_product_rejected: "Odoo rejected the product.", err_idempotency_conflict: "This request was used with different data. Refresh the page.", err_outcome_unknown: "It may have been saved. Press save again safely.", err_in_progress: "Still running, wait a moment.",
  err_verification_failed: "Couldn't confirm the product in Odoo. Check it before continuing.", err_recipe_rejected: "Odoo rejected the recipe.", err_verification_unavailable: "Saved, but couldn't verify. Press save again safely.",
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
