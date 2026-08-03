import os
import sys
import time
import shutil
from playwright.sync_api import sync_playwright

def record_live_e2e_video():
    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"
    target_url = "https://bears.ceoloide.com"
    video_dir = os.path.abspath("scratch/videos")
    os.makedirs(video_dir, exist_ok=True)

    print(f"\n=======================================================")
    print(f"🎬 RECORDING LIVE E2E TEST VIDEO ON: {target_url}")
    print(f"=======================================================\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 720},
            record_video_dir=video_dir,
            record_video_size={"width": 1280, "height": 720}
        )
        page = context.new_page()

        # Step 1: Open live web application
        print("[1/4] Navigating to https://bears.ceoloide.com...")
        page.goto(target_url, wait_until="networkidle")
        time.sleep(2.0)

        # Logout if logged in
        if page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").count() > 0:
            print("[Info] Active session detected. Logging out first to record full login flow...")
            page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").first.click()
            time.sleep(2.5)

        # Step 2: Fill login form
        print(f"[2/4] Entering email ({email}) and password...")
        page.locator("input[type='text'], input[placeholder*='mail']").first.fill(email)
        time.sleep(0.5)
        page.locator("input[type='password']").first.fill(pwd)
        time.sleep(1.0)

        # Step 3: Submit login form
        print("[3/4] Submitting credentials...")
        start_t = time.time()
        page.locator("button[type='submit']").first.click()

        # Step 4: Monitor progress & wait for Dashboard
        print("[4/4] Monitoring verification interstitial & progress steps...")
        dashboard_reached = False

        for sec in range(60):
            time.sleep(1.0)
            elapsed = round(time.time() - start_t, 1)
            body_text = page.locator("body").inner_text().replace("\n", " ")

            if sec % 3 == 0 or "Extraction Control Panel" in body_text:
                print(f"  [{elapsed}s] {body_text[:120]}...")

            if "Extraction Control Panel" in body_text or "Extracted Media Library" in body_text or page.locator("button:has-text('Log Out')").count() > 0:
                dashboard_reached = True
                print(f"\n🎉 SUCCESS: Live Dashboard reached after {elapsed}s!")
                time.sleep(3.0) # Pause so video captures completed dashboard view
                break

        video_path = page.video.path() if page.video else None
        context.close()
        browser.close()

        if video_path and os.path.exists(video_path):
            final_video_name = "e2e_auth_recording.webm"
            final_video_path = os.path.abspath(os.path.join("scratch", final_video_name))
            shutil.copy(video_path, final_video_path)
            print(f"\n🎥 Video recording saved to: {final_video_path}")
            
            # Copy to artifact dir for markdown embedding
            artifact_dir = "/home/antigravity/.gemini/antigravity/brain/80dadb55-5c00-4f16-ae32-f27dced4cd5f"
            if os.path.exists(artifact_dir):
                art_video_path = os.path.join(artifact_dir, final_video_name)
                shutil.copy(final_video_path, art_video_path)
                print(f"Copied video to artifact directory: {art_video_path}")
                
            return final_video_path

    return None

if __name__ == "__main__":
    record_live_e2e_video()
