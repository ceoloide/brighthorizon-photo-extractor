import json, os, sys
from backend.database import TenantStorage
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
ts = TenantStorage(email)

payload_json = {
  "cookies": "_ga=GA1.1.298394350.1782168137; OptanonAlertBoxClosed=2026-06-22T22:42:17.934Z; _gcl_au=1.1.512019037.1782168145; _twpid=tw.1782168145228.347824097898148442; _tt_enable_cookie=1; _ttp=01KVRQZKBZWKVW0MFS0V4GS2F6_.tt.1; _fbp=fb.1.1782168145318.7493401512029410; _pendo_visitorId.3527651379=_PENDO_T_ge0uCTe1zOD; _pendo_accountId.3527651379=ACCOUNT-UNIQUE-ID; _pendo___sg__.672bb382-89e6-484c-6825-cb518fd863d2=%7B%7D; _hjSessionUser_1090331=eyJpZCI6IjVkODBmNzEwLTQyMmYtNTg5MC04MWRkLTk3NTIwYjJhOTJmMiIsImNyZWF0ZWQiOjE3ODIxNjgxNDUzNTksImV4aXN0aW5nIjp0cnVlfQ==; rxVisitorgzqynqn8=1785172716105066R6J609C0LQP4MPPU2MCOA66NCVOHN; dtCookiegzqynqn8=v_4_srv_14_sn_03F968B9C523E674B22125CEF0FD06E8_app-3Afd9b92690dc9025c_1_app-3A1ff8de0de16aa49b_1_ol_0_perc_100000_mul_1_rcs-3Acss_0; _fs_dwell_passed=c4905f90-c819-478d-a96d-cdbd8bcb8c4a; auth0.5VIzhuWNKxFc9etVvp5fonr2tlbBEZae.is.authenticated=true; dtSagzqynqn8=-; OptanonConsent=isGpcEnabled=0&datestamp=Thu+Jul+30+2026+15%3A06%3A52+GMT%2B0200+(Central+European+Summer+Time)&version=202605.1.0&browserGpcFlag=0&isIABGlobal=false&hosts=&consentId=6085d58f-6f26-4a85-b584-e5e8d41f3ad0&interactionCount=1&isAnonUser=1&prevHadToken=0&landingPath=NotLandingPage&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1&crTime=1782168137725&AwaitingReconsent=false&geolocation=US%3BNY&isDntEnabled=0; _ga_0EY7LSHQSZ=GS2.1.s1785416036$o9$g1$t1785416812$j8$l0$h0; fs_lua=1.1785416812081; fs_uid=#o-1TY88M-na1#012ef0f2-a6ec-4e59-9099-5da1c1602c5e:c4905f90-c819-478d-a96d-cdbd8bcb8c4a:1785416034394::7#1a493750###/1790784911; rxvtgzqynqn8=1785418614238|1785416033730; dtPCgzqynqn8=14$416812007_926h-vVRMFMDAPAEUPBTKLSAJQQVDEOQVMWTLB-0e0",
  "storage": "{\"_pendo_meta.a3b7f593-81ca-427f-4066-2f251770e28a\":\"{\\\"ttl\\\":1794056036328,\\\"value\\\":935454988}\",\"_fs_uid\":\"#o-1TY88M-na1#012ef0f2-a6ec-4e59-9099-5da1c1602c5e:c4905f90-c819-478d-a96d-cdbd8bcb8c4a:1785416034394::7#1a493750###/1790784911\"}"
}

cookie_str = payload_json["cookies"]
storage_dict = json.loads(payload_json["storage"])

formatted_cookies = []
for pair in cookie_str.split(";"):
    if "=" in pair:
        k, v = pair.strip().split("=", 1)
        formatted_cookies.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": ".brighthorizons.com",
            "path": "/"
        })

ls_items = []
for k, v in storage_dict.items():
    ls_items.append({"name": k, "value": v})

origin_obj = {
    "origin": "https://familyinfocenter.brighthorizons.com",
    "localStorage": ls_items
}

playwright_state = {
    "cookies": formatted_cookies,
    "origins": [origin_obj]
}

state_file = os.path.join(ts.user_data_dir, "storage_state.json")
with open(state_file, "w") as f:
    json.dump(playwright_state, f, indent=2)

print(f"✓ Saved storage_state.json for {email} with {len(formatted_cookies)} cookies and {len(ls_items)} LocalStorage keys.")
