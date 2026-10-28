"""Bilingual UI strings (ENG default / Myanmar) for M2 templates.

Render in templates with the `t` tag:  {% load t %} {% t "nav.assets" %}
Language is stored in the session (`lang` = "en" | "my"), default "en".
"""

STRINGS = {
    "app.name": {"en": "IT Asset Manager", "my": "IT Asset Manager"},
    "app.subtitle": {"en": "IT equipment management system", "my": "စက်ပစ္စည်း စီမံခန့်ခွဲမှု စနစ်"},
    "nav.dashboard": {"en": "Dashboard", "my": "ဒသု်််််ုံည"},  # placeholder fixed below
    "nav.assets": {"en": "Assets", "my": "ပိုင်ဆိုင်မှုများ"},
    "nav.people": {"en": "People", "my": "လုပ်သားများ"},
    "nav.sites": {"en": "Sites", "my": "စခန်းများ"},
    "nav.reports": {"en": "Reports", "my": "အစီရင်ခံစာများ"},
    "nav.audit": {"en": "Audit", "my": "စစ်ဆေးရေး"},
    "nav.admin": {"en": "Admin", "my": "Admin"},
    "nav.logout": {"en": "Logout", "my": "ထွက်ရန်"},
    "nav.login": {"en": "Sign in", "my": "ဝင်ရောက်ရန်"},
    "nav.me": {"en": "My assets", "my": "ကိုယ်ပိုင် ပစ္စည်းများ"},
    # employee self-view (design §4.4)
    "me.title": {"en": "My assets", "my": "ကိုယ်ပိုင် ပစ္စည်းများ"},
    "me.no_person": {
        "en": "No linked employee record — contact IT to claim your assets.",
        "my": "ချိတ်ဆက်ထားသော လုပ်သားမှတ်တမ်း မရှိပါ — ပိုင်ဆိုင်မှုအတွက် IT ကို ဆက်သွယ်ပါ။",
    },
    "me.requests": {"en": "My requests", "my": "ကျွန်ုပ်၏ တောင်းဆိုမှုများ"},
    "me.req_id": {"en": "Request", "my": "တောင်းဆိုမှု"},
    "me.created": {"en": "Created", "my": "ဖန်တီးသည့်ရက်"},
    "me.due": {"en": "Due", "my": "ပြန်ရမည့်ရက်"},
    "me.current": {"en": "Current", "my": "လက်ရှိ"},
    "me.request_new": {"en": "+ Request asset", "my": "+ ပစ္စည်း တောင်းဆိုမည်"},
    # employee request form (§6.5 stage ①)
    "req.title": {"en": "Request an asset", "my": "ပစ္စည်း တောင်းဆိုရန်"},
    "req.sub": {
        "en": "Sent to the approval queue (stage ① — approve → procure → receive)",
        "my": "အတည်ပြုစာရင်းသို့ ပို့မည် (အဆင့် ① — အတည်ပြု → ဝယ် → လက်ခံ)",
    },
    "req.submit": {"en": "Submit request", "my": "တောင်းဆိုမှု တင်မည်"},
    # category-specific specification card (§5 catalogue → Asset.attrs)
    "spec.title": {"en": "Specifications", "my": "သတ်မှတ်ချက်များ"},
    # overdue loans page (§14 scan_loans made visible)
    "loans.title": {"en": "Overdue loans", "my": "ပြန်ရန် ကျန်ချိန်ကျော်လွန်သော ပေးအပ်မှုများ"},
    "loans.sub": {
        "en": "Assets checked out past their due date — return or extend",
        "my": "သတ်မှတ်ရက်ကျော်လွန်နေသော ပေးအပ်မှုများ — ပြန်အပ် သို့ ရုံးချိန် တိုးပါ",
    },
    "loans.overdue_by": {"en": "Overdue", "my": "ကျော်လွန်ချိန်"},
    "loans.days_late": {"en": "{n}d late", "my": "{n} ရက် ကျော်"},
    "loans.empty": {
        "en": "No overdue loans — everything is back on time.",
        "my": "ကျော်လွန်နေသော ပေးအပ်မှု မရှိပါ။",
    },
    # request progress stepper (self-view)
    "prog.header": {"en": "Progress", "my": "အဆင့်မြောက်မှု"},
    "prog.approval_wait": {"en": "Awaiting approval", "my": "အတည်ပြုရန် စောင့်ဆိုင်းနေသည်"},
    "prog.approval_wait_n": {
        "en": "Awaiting approval ({cur}/{total})",
        "my": "အတည်ပြုရန် စောင့်ဆိုင်းနေသည် ({cur}/{total})",
    },
    "prog.await_procure": {
        "en": "Approved — awaiting procurement",
        "my": "အတည်ပြုပြီး — ဝယ်ယူရန် စောင့်ဆိုင်း",
    },
    "prog.await_receive": {"en": "Procured — awaiting receipt", "my": "ဝယ်ပြီး — လက်ခူရန် စောင့်ဆိုင်း"},
    "prog.fulfilled": {"en": "Fulfilled", "my": "ပြီးဆုံးပြီ"},
    "prog.rejected": {"en": "Rejected at approval", "my": "အတည်ပြုပွင့်တွင် ငြင်းပယ်ခဲ့သည်"},
    "prog.cancelled": {"en": "Cancelled", "my": "ပယ်ဖျက်ခဲ့သည်"},
    # dashboard
    "dash.title": {"en": "Dashboard", "my": "ဒသ််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််််"},
    "dash.total_assets": {"en": "Total assets", "my": "ပိုင်ဆိုင်မှု စုစုပေါင်း"},
    "dash.by_status": {"en": "By status", "my": "အခြေအနေအလိုက်"},
    "dash.by_condition": {"en": "By condition", "my": "အရည်အသွေးအလိုက်"},
    "dash.by_site": {"en": "By site", "my": "စခန်းအလိုက်"},
    "dash.recent": {"en": "Recently added", "my": "လတ်တလော ထည့်သွင်းခြင်း"},
    "dash.view_all": {"en": "View all", "my": "အားလုံး ကြည့်မည်"},
    # dashboard — mockup KPIs / chart / alerts (docs/itasset-docs/index.html)
    "dash.kpi.alerts": {"en": "Critical alerts", "my": "အရေးကြီး နိုးဆွဲချက်များ"},
    "dash.kpi.attention": {"en": "⚠ Needs attention", "my": "⚠ အာရုံစိုက်ရန် လိုအပ်သည်"},
    "dash.kpi.warranty": {"en": "Warranty expiring", "my": "အာမခံ ကုန်တော့မည့်"},
    "dash.kpi.within30": {"en": "Within 30 days", "my": "၃၀ ရက်အတွင်း"},
    "dash.kpi.active": {"en": "Active assets", "my": "အသုံးပြုနေသော ပစ္စည်းများ"},
    "dash.kpi.assigned": {"en": "{n} assigned", "my": "{n} ခု လက်ခံထားသည်"},
    "dash.kpi.this_month": {"en": "▲ {n} new this month", "my": "▲ ဤလအတွင်း အသစ် {n} ခု"},
    "dash.categories": {"en": "Asset categories", "my": "ပစ္စည်းအမျိုးအစားအလိုက်"},
    "dash.alerts": {"en": "Alerts", "my": "နိုးဆွဲချက်များ"},
    "dash.no_alerts": {
        "en": "All clear — nothing needs attention.",
        "my": "အားလုံး ကောင်းမွန်ပါသည် — ဂရုပြုစရာ မရှိပါ။",
    },
    "dash.others": {"en": "Others", "my": "အခြား"},
    # RAM inventory card (type + speed breakdown from the §5 spec attrs)
    "dash.ram": {"en": "RAM type and speed", "my": "RAM အမျိုးအစားနှင့် အမြန်နှုန်း"},
    "dash.ram.by_type": {"en": "By type", "my": "အမျိုးအစားအလိုက်"},
    "dash.ram.by_speed": {"en": "By speed", "my": "အမြန်နှုန်းအလိုက်"},
    "dash.ram.coverage": {
        "en": "RAM recorded for {n} of {m} assets",
        "my": "RAM မှတ်တမ်း ဖြည့်ထားသည့် ပစ္စည်း {n} / {m} ခု",
    },
    "dash.ram.none": {
        "en": "No RAM details recorded yet — fill them in an asset's Specifications tab.",
        "my": "RAM အသေးစိတ် မှတ်တမ်း မရှိသေးပါ — ပစ္စည်းရဲ့ သတ်မှတ်ချက် စာမျက်နှာမှာ ဖြည့်ပါ။",
    },
    "dash.view_list": {"en": "View list →", "my": "စာရင်း ကြည့်မည် →"},
    "dash.kpi.pending": {"en": "Pending approvals", "my": "အတည်ပြုရန် စောင့်ဆိုင်းနေသည်"},
    "dash.kpi.pending_meta": {
        "en": "Awaiting decision (stage ①)",
        "my": "ဆုံးဖြတ်ရန် စောင့်ဆိုင်းနေသည် (အဆင့် ①)",
    },
    "dash.kpi.overdue": {"en": "Overdue loans", "my": "ပြန်ရန် ကျန်ချိန် ကျော်လွန်"},
    "dash.kpi.overdue_meta": {"en": "Past the due date", "my": "သတ်မှတ်ရက် ကျော်လွန်ပြီ"},
    "alert.overdue_loans": {"en": "{n} loans overdue", "my": "ပြန်ရန် ကျန်ချိန်ကျော်လွန်နေသော {n} ခု"},
    "alert.transfer_exceptions": {
        "en": "{n} transfers in exception",
        "my": "Exception ဖြစ်နေသော ပြောင်းရွှေ့မှု {n} ခု",
    },
    "alert.warranty_soon": {
        "en": "{n} warranties expiring within 7 days",
        "my": "ရက် ၇ အတွင်း အာမခံကုန်မည့် {n} ခု",
    },
    "alert.missing_serial": {
        "en": "{n} assets missing a serial number",
        "my": "Serial နံပါတ် ကွက်နေသော ပစ္စည်း {n} ခု",
    },
    "alert.pending_approvals": {
        "en": "{n} requests awaiting approval",
        "my": "အတည်ပြုရန် စောင့်ဆိုင်းနေသော တောင်းဆိုမှု {n} ခု",
    },
    # assets
    "asset.title": {"en": "Assets", "my": "ပိုင်ဆိုင်မှုများ"},
    "asset.count": {"en": "{n} total", "my": "စုစုပေါင်း {n}"},
    "asset.new": {"en": "+ New asset", "my": "+ အသစ် မှတ်မည်"},
    "asset.edit": {"en": "Edit", "my": "ပြင်ရန်"},
    "asset.delete": {"en": "Delete", "my": "ဖျက်ရန်"},
    "asset.search_ph": {
        "en": "Search tag / serial / hostname / model…",
        "my": "Tag / Serial / Hostname / Model ဖြင့် ရှာမည်…",
    },
    "asset.search_btn": {"en": "Search", "my": "ရှာမည်"},
    "asset.all_statuses": {"en": "All statuses", "my": "အခြေအနေ အားလုံး"},
    "asset.all_warranties": {"en": "Any warranty", "my": "အာမခံ မရွေး"},
    "asset.warranty_le": {"en": "Warranty ≤ {n} days", "my": "အာမခံ {n} ရက်အတွင်း"},
    "asset.missing_serial": {"en": "Missing serial", "my": "Serial ကွက်နေသည်"},
    "asset.clear": {"en": "✕ Clear", "my": "✕ ရှင်းမည်"},
    "asset.tag": {"en": "Tag", "my": "Tag"},
    "asset.category": {"en": "Category", "my": "Category"},
    "asset.model": {"en": "Model", "my": "Model"},
    "asset.site": {"en": "Site", "my": "စခန်း"},
    "asset.status": {"en": "Status", "my": "အခြေအနေ"},
    "asset.details": {"en": "Asset details", "my": "ပိုင်ဆိုင်မှု အသေးစိတ်"},
    # tabbed asset form (create/edit) — buckets in apps.assets.views
    "asset.tab.basics": {"en": "Basics", "my": "အခြေခံ"},
    "asset.tab.specs": {"en": "Specifications", "my": "သတ်မှတ်ချက်များ"},
    "asset.tab.device": {"en": "Device", "my": "စက်ပစ္စည်း"},
    "asset.tab.procurement": {"en": "Procurement", "my": "ဝယ်ယူမှု"},
    "asset.serial": {"en": "Serial", "my": "Serial"},
    "asset.hostname": {"en": "Hostname", "my": "Hostname"},
    "asset.purchase": {"en": "Purchased", "my": "ဝယ်ယူသည်"},
    "asset.cost": {"en": "cost", "my": "ဈေးနှုန်း"},
    "asset.warranty": {"en": "Warranty ends", "my": "အာမခံ ကုန်ဆုံး"},
    "asset.condition": {"en": "Condition", "my": "အခြေအနေ"},
    "asset.actions": {"en": "Actions", "my": "လက်တွေ့ လုပ်ဆောင်ချက်များ"},
    "asset.checkout": {"en": "Check out", "my": "ထုတ်ပေးမည် (Check-out)"},
    "asset.checkin": {"en": "Check in", "my": "ပြန်လည်ရရှိမည် (Check-in)"},
    "asset.pick_holder": {"en": "— Select holder —", "my": "— လက်ခံမည့်သူ ရွေးပါ —"},
    # department-as-holder (Server/NAS/Switch, shared laptops)
    "asset.pick_dept": {"en": "— Select department —", "my": "— ဌာန ရွေးပါ —"},
    "asset.or_dept": {"en": "or", "my": "သို့"},
    "asset.pick_one": {
        "en": "Pick exactly one holder — an employee or a department.",
        "my": "လက်ခံသူ တစ်ဦးတည်း ရွေးပါ — ဝန်ထမ်း သို့မဟုတ် ဌာန။",
    },
    "asset.dept_holder": {"en": "Department", "my": "ဌာန"},
    "asset.dept_abbr": {"en": "dept", "my": "ဌာန"},
    # department detail page (head + department-held assets + members)
    "dept.head": {"en": "Head of department", "my": "ဌာနတာဝန်ခံ"},
    "dept.no_head": {"en": "No head assigned.", "my": "ဌာနတာဝန်ခံ မသတ်မှတ်ရသေးပါ။"},
    "dept.held_now": {"en": "Department-held assets", "my": "ဌာနပိုင် ပစ္စည်းများ"},
    "dept.no_held": {
        "en": "No assets held by this department.",
        "my": "ဤဌာနထံ ပေးအပ်ထားသော ပစ္စည်း မရှိပါ။",
    },
    "dept.members": {"en": "Department members", "my": "ဌာနဝင်များ"},
    "dept.held_by_members": {
        "en": "Held by department members",
        "my": "ဌာနဝင်များ ကိုင်ဆောင်ထားသော ပိုင်ဆိုင်မှုများ",
    },
    "dept.no_member_held": {
        "en": "No assets held by department members.",
        "my": "ဌာနဝင်များ ကိုင်ဆောင်ထားသော ပိုင်ဆိုင်မှု မရှိပါ။",
    },
    "dept.view_assets": {"en": "View assets in list", "my": "ပစ္စည်းစာရင်းတွင် ကြည့်မည်"},
    "nav.departments": {"en": "Departments", "my": "ဌာနများ"},
    "dept.title": {"en": "Departments", "my": "ဌာနများ"},
    "dept.count": {"en": "{n} departments", "my": "ဌာန {n} ခု"},
    "dept.edit_title": {"en": "Edit department", "my": "ဌာန ပြင်ရန်"},
    # bulk department check-out (session 36)
    "bulk.title": {"en": "Bulk check-out", "my": "အစုလိုက် ပေးအပ်မည်"},
    "bulk.sub": {
        "en": "Tick the available assets and assign them all to one department",
        "my": "ရရှိနိုင်သော asset များကို ရွေးပြီး တစ်ခါတည်း ဌာနတစ်ခုထံ ပေးအပ်မည်",
    },
    "bulk.hint": {"en": "{n} available assets", "my": "ရရှိနိုင်သော asset {n} ခု"},
    "bulk.empty": {
        "en": "No available assets here — assigned and in-stock assets are excluded.",
        "my": "ဤနေရာတွင် ရရှိနိုင်သော asset မရှိပါ — assigned နှင့် in-stock asset များ မပါဝင်ပါ။",
    },
    "bulk.selected": {"en": "Check out selected", "my": "ရွေးထားသည်များ ထုတ်ပေးမည်"},
    "bulk.pick_one": {
        "en": "Pick a department and tick at least one asset.",
        "my": "ဌာနတစ်ခု ရွေးပြီး အနည်းဆုံး asset တစ်ခု ရွေးပါ။",
    },
    "bulk.tick_all": {"en": "Tick all shown assets", "my": "ပြသထားသည့် asset အားလုံး ရွေးမည်"},
    "bulk.select_all": {
        "en": "Select all {n} matching this filter",
        "my": "စစ်ထုတ်မှုနှင့် ကိုက်ညီသည့် {n} ခုအားလုံး ရွေးမည်",
    },
    "asset.all_sites": {"en": "All sites", "my": "စခန်း အားလုံး"},
    "asset.history": {"en": "Assignment history", "my": "ပေးအပ်မှု မှတ်တမ်း (Assignments)"},
    "asset.holder": {"en": "Holder", "my": "လက်ခံသူ"},
    "asset.assigned_to": {"en": "Assigned to", "my": "တာဝန်ပေးထားသူ"},
    "asset.parent": {"en": "Parent asset", "my": "မူလ ပစ္စည်း (Parent)"},
    "asset.components": {"en": "Components", "my": "အစိတ်အပိုင်းများ"},
    "asset.no_components": {"en": "No components linked.", "my": "ချိတ်ဆက်ထားသော အစိတ်အပိုင်း မရှိပါ။"},
    "asset.orphan_hint": {
        "en": "Status says Assigned but no holder is recorded — checking out repairs the record.",
        "my": "Assigned အခြေအနေ ဖြစ်နေပေမယ့် လက်ခံသူ မှတ်တမ်း မရှိပါ — check-out လုပ်ခြင်းဖြင့် ပြင်ဆင်နိုင်ပါသည်။",
    },
    "asset.all_depts": {"en": "All departments", "my": "ဌာန အားလုံး"},
    "asset.all_categories": {"en": "All categories", "my": "အမျိုးအစား အားလုံး"},
    "asset.assigned_mine": {"en": "Assigned to me", "my": "ကျွန်တော့်ဆီ ပေးထားသော"},
    "orphan.title": {"en": "Repair assignments", "my": "ပေးအပ်မှု ပြင်ဆင်ရန်"},
    "orphan.sub": {
        "en": (
            "These assets are marked Assigned but the register has no holder "
            "recorded — pick the employee who holds each one."
        ),
        "my": "ဤ asset များသည် Assigned အဖြစ် မှတ်ထားပေမယ့် လက်ခံသူ မှတ်တမ်း မရှိပါ — ကိုင်ဆောင်နေသူ ဝန်ထမ်းကို ရွေးပါ။",
    },
    "orphan.repair": {"en": "Repair", "my": "ပြင်ဆင်မည်"},
    "orphan.empty": {
        "en": "No orphan assignments — every Assigned asset has a holder.",
        "my": "ပေးအပ်မှု ပျောက်နေသည် မရှိပါ — Assigned asset အားလုံးတွင် လက်ခံသူ ရှိပါသည်။",
    },
    "attach.title": {"en": "Attach components", "my": "အစိတ်အပိုင်းများ ချိတ်ဆက်ရန်"},
    "attach.sub": {
        "en": "Tick the components that belong to this workstation",
        "my": "ဤ workstation နဲ့ သက်ဆိုင်သော အစိတ်အပိုင်းများကို ရွေးပါ",
    },
    "attach.hint": {
        "en": "{n} unlinked assets at this site",
        "my": "ဤ site တွင် မချိတ်ရသေးသော asset {n} ခု",
    },
    "attach.empty": {
        "en": (
            "No unlinked assets left here — attach the workstation first, "
            "or clear the category filter."
        ),
        "my": "ဤနေရာတွင် မချိတ်ရသေးသော asset မရှိတော့ပါ — workstation အရင်ချိတ်ပါ သို့မဟုတ် category စစ်ထုတ်မှု ဖျက်ပါ။",
    },
    "attach.selected": {"en": "Attach selected", "my": "ရွေးထားသည်များ ချိတ်မည်"},
    "asset.out_at": {"en": "Out", "my": "ထွက်သည်"},
    "asset.in_at": {"en": "In", "my": "ပြန်ရသည်"},
    "asset.cond_out_in": {"en": "Cond. (out/in)", "my": "အခြေအနေ (ထွက်/ပြန်)"},
    "asset.remarks": {"en": "Remarks", "my": "မှတ်ချက်"},
    "asset.none_yet": {"en": "No records yet.", "my": "မှတ်တမ်း မရှိသေးပါ။"},
    "asset.not_suitable": {
        "en": "This asset is not currently available for check-out/in.",
        "my": "ဤ asset သည် လက်ရှိအခြေအနေတွင် check-out/check-in လုပ်ရန် မသင့်တော်ပါ။",
    },
    "asset.new_title": {"en": "Register new asset", "my": "ပိုင်ဆိုင်မှု အသစ် မှတ်မည်"},
    "asset.edit_title": {"en": "Edit asset", "my": "ပိုင်ဆိုင်မှု ပြင်ရန်"},
    "asset.new_sub": {
        "en": "New assets start as In Stock (§3 step ④)",
        "my": "အသစ် မှတ်လျှင် In Stock အခြေအနေဖြင့် စတင်မည် (§3 အဆင့် ④)",
    },
    "asset.save": {"en": "Save", "my": "သိမ်းမည်"},
    "asset.cancel": {"en": "Cancel", "my": "ပယ်ဖျက်"},
    "asset.delete_q": {"en": "Delete this asset?", "my": "ဖျက်မည်လား?"},
    "asset.delete_warn": {"en": "This cannot be undone.", "my": "ဤလုပ်ဆောင်ချက်ကို ပြန်ရုပ်သတ်၍ မရပါ။"},
    "asset.confirm_delete": {"en": "Delete permanently", "my": "ဖျက်မည် (အတည်ပြု)"},
    "asset.no_delete": {"en": "No", "my": "မဖျက်ဘူး"},
    # people
    "person.title": {"en": "People", "my": "လုပ်သားများ"},
    "person.count": {"en": "{n} people", "my": "စုစုပေါင်း {n} ဦး"},
    "person.new": {"en": "+ New person", "my": "+ လုပ်သား အသစ်"},
    "person.staff_no": {"en": "Staff No", "my": "Staff No"},
    "person.name": {"en": "Name", "my": "နာမည်"},
    "person.dept": {"en": "Department", "my": "ဌာန"},
    "person.detail_title": {"en": "Person", "my": "လုပ်သား"},
    "person.held": {"en": "Assets held", "my": "ထိန်းသိမ်းခဲ့သော ပိုင်ဆိုင်မှုများ"},
    "person.held_now": {"en": "Currently held", "my": "လက်ရှိ ကိုင်ဆောင်ထားသော"},
    "person.no_held": {
        "en": "No assets currently held.",
        "my": "လက်ရှိ ကိုင်ဆောင်ထားသော asset မရှိပါ။",
    },
    "person.new_title": {"en": "New person", "my": "လုပ်သား အသစ်"},
    "person.edit_title": {"en": "Edit person", "my": "လုပ်သား ပြင်ရန်"},
    # sites
    "site.title": {"en": "Sites", "my": "စခန်းများ"},
    "site.count": {"en": "{n} sites", "my": "စုစုပေါင်း {n} ခု"},
    "site.code": {"en": "Code", "my": "Code"},
    "site.people_n": {"en": "People", "my": "လုပ်သား အရေအတွက်"},
    "site.people_at": {"en": "People at this site", "my": "ဤစခန်းရှိ လုပ်သားများ"},
    "site.new_title": {"en": "New site", "my": "စခန်း အသစ်"},
    "site.edit_title": {"en": "Edit site", "my": "စခန်း ပြင်ရန်"},
    # login
    "login.signin": {"en": "Sign in", "my": "ဝင်ရောက်ရန်"},
    "login.username": {"en": "Username", "my": "အသုံးပြုသူအမည်"},
    "login.password": {"en": "Password", "my": "စကားဝှက်"},
    "login.submit": {"en": "Sign in", "my": "ဝင်ရောက်မည်"},
    "login.fail": {
        "en": "Invalid username or password.",
        "my": "အသုံးပြုသူအမည် (သို့) စကားဝှက် မှားယွင်းနေပါသည်။",
    },
    "login.foot": {
        "en": "IT Asset Manager — internal use only",
        "my": "IT Asset Manager — အတွင်းပိုင်း အသုံးပြုမှုသာ",
    },
    # generic
    "common.page": {"en": "Page {n} of {m}", "my": "စာမျက်နှာ {n} / {m}"},
    "common.prev": {"en": "← Prev", "my": "← ရှေ့"},
    "common.next": {"en": "Next →", "my": "နောက် →"},
    "common.empty": {"en": "Nothing here yet.", "my": "မရှိသေးပါ။"},
    # audit (M5)
    "audit.title": {"en": "Activity log", "my": "လှုပ်ရှားမှတ်တမ်း"},
    "audit.sub": {"en": "Who changed what, when (§9)", "my": "ဘယ်သူ ဘာကို ဘယ်အချိန် ပြောင်းလဲခဲ့လဲ (§9)"},
    "audit.all_actions": {"en": "All actions", "my": "လုပ်ဆောင်ချက် အားလုံး"},
    "audit.actor": {"en": "Actor", "my": "ဆောင်ရွက်သူ"},
    "audit.search_ph": {"en": "Search object / details…", "my": "object / details ဖြင့် ရှာမည်…"},
    "audit.when": {"en": "When", "my": "အချိန်"},
    "audit.action": {"en": "Action", "my": "လုပ်ဆောင်ချက်"},
    "audit.object": {"en": "Object", "my": "အရာဝတ္ထု"},
    "audit.details": {"en": "Details", "my": "အသေးစိတ်"},
    "audit.sessions": {"en": "Physical audit", "my": "ရုပ်ပိုင်း စစ်ဆေးမှု"},
    "audit.sessions_sub": {
        "en": "Count assets at a site by scanning tags (§3 audit mode)",
        "my": "စခန်းအလိုက် tag စကင်ပြီး ပိုင်ဆိုင်မှု ရေတွက်ရန် (§3)",
    },
    "audit.start": {"en": "Start audit", "my": "စစ်ဆေးမှု စတင်မည်"},
    "audit.pick_site": {"en": "select site", "my": "စခန်း ရွေးပါ"},
    "audit.status": {"en": "Status", "my": "အခြေအနေ"},
    "audit.started": {"en": "Started", "my": "စတင်သည်"},
    "audit.by": {"en": "By", "my": "ဆောင်ရွက်သူ"},
    "audit.scan": {"en": "Scan", "my": "စကင်မည်"},
    "audit.report_link": {"en": "Report", "my": "အစီရင်ခံစာ"},
    "audit.expected": {"en": "Expected", "my": "ရှိရမည့်အရေအတွက်"},
    "audit.scanned": {"en": "Scanned", "my": "စကင်ပြီး"},
    "audit.close": {"en": "Close & report", "my": "ပိတ်ပြီး အစီရင်ခံမည်"},
    "audit.close_q": {"en": "Close this audit session?", "my": "ဤစစ်ဆေးမှုကို ပိတ်မည်လား?"},
    "audit.scan_hint": {
        "en": "Scan a tag (scanner acts as keyboard — keep focus here)",
        "my": "Tag စကင်ပါ (scanner သည် keyboard အဖြစ် အလုပ်လုပ်သည်)",
    },
    "audit.unknown": {"en": "unknown", "my": "မသိသော tag"},
    "audit.no_scans": {"en": "No scans yet.", "my": "စကင်ထားခြင်း မရှိသေးပါ။"},
    "audit.missing_preview": {"en": "Not yet scanned", "my": "မစကင်ရသေးသူ"},
    "audit.found": {"en": "Found", "my": "တွေ့ရှိ"},
    "audit.missing": {"en": "Missing", "my": "ပျောက်ဆုံး"},
    "audit.unexpected": {"en": "Unexpected", "my": "မမျှော်လင့်ထား"},
    # reports (M7)
    "reports.sub": {
        "en": "Read-only exports over the register (§4)",
        "my": "မှတ်တမ်းပေါ်မှ ဖတ်ရုံသာ export များ (§4)",
    },
    "reports.empty": {
        "en": "No reports registered.",
        "my": "အစီရင်ခံစာ မရှိသေးပါ။",
    },
    "reports.fmt": {"en": "Format", "my": "ပုံစံ"},
    "reports.run": {"en": "Download", "my": " download ပြုလုပ်မည်"},
    # create-in-modal dialog (shared: admin Add links + main-app New buttons)
    "modal.close": {"en": "Close", "my": "ပိတ်မည်"},
    "modal.discard": {
        "en": "Discard unsaved changes?",
        "my": "မသိမ်းရသေးသော ပြင်ဆင်မှုများကို ဖျက်မည်လား?",
    },
    "modal.keep": {"en": "Keep editing", "my": "ဆက်လက်ပြင်မည်"},
    "modal.discard_btn": {"en": "Discard", "my": "ဖျက်မည်"},
}

# fix the two placeholder values properly
STRINGS["nav.dashboard"] = {"en": "Dashboard", "my": "ဒက်ရှ်ဘုတ်"}
STRINGS["dash.title"] = {"en": "Dashboard", "my": "ဒက်ရှ်ဘုတ်"}
