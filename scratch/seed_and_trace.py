import os
import sys
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath("./user_data")
TRACE_OUTPUT = os.path.abspath("./scratch/trace.zip")

os.makedirs("./scratch", exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)

print("=" * 60)
print("Starting System-Chrome Seeding & Trace Session")
print("=" * 60)
print(f"Chrome Binary:     /usr/bin/google-chrome")
print(f"User Data Dir:     {USER_DATA_DIR}")
print(f"Trace Archive:     {TRACE_OUTPUT}")
print("-" * 60)
print("INSTRUCTIONS:")
print("1. Real Google Chrome will open.")
print("2. Log into Bright Horizons / Family Info Center.")
print("3. Perform MFA / Turnstile if prompted (real Chrome bypasses Turnstile).")
print("4. Navigate to Byron's My Bright Day feed, select timeframes, scroll feed.")
print("5. When finished, press ENTER in the terminal.")
print("=" * 60)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        executable_path="/usr/bin/google-chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1280, "height": 800}
    )
    
    # Start tracing
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://familyinfocenter.brighthorizons.com/home")
    
    try:
        input("\n>>> Press ENTER in terminal after completing your session interactions... <<<\n")
    except KeyboardInterrupt:
        print("\nSession interrupted.")
    finally:
        print("Stopping trace and saving session profile...")
        context.tracing.stop(path=TRACE_OUTPUT)
        context.close()
        print(f"Session seeded in {USER_DATA_DIR}")
        print(f"Trace saved to {TRACE_OUTPUT}")
