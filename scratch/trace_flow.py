import os
import sys
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath("./user_data")
TRACE_OUTPUT = os.path.abspath("./scratch/trace.zip")

os.makedirs("./scratch", exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)

print("=" * 60)
print("Starting Interactive Playwright Diagnostic Trace Session")
print("=" * 60)
print(f"User Data Directory: {USER_DATA_DIR}")
print(f"Trace Output:        {TRACE_OUTPUT}")
print("-" * 60)
print("INSTRUCTIONS:")
print("1. A Chrome browser window will open.")
print("2. Log in to Bright Horizons / Family Info Center if prompted.")
print("3. Perform any MFA steps and navigate to Byron's My Bright Day feed.")
print("4. Click timeframe links, scroll the feed, or inspect elements.")
print("5. When finished, return to this terminal and press ENTER.")
print("=" * 60)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1280, "height": 800}
    )
    
    # Enable comprehensive tracing (screenshots, DOM snapshots, network requests)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://familyinfocenter.brighthorizons.com/home")
    
    try:
        input("\n>>> Press ENTER after completing your session interactions... <<<\n")
    except KeyboardInterrupt:
        print("\nSession interrupted.")
    finally:
        print("Stopping trace and saving trace archive...")
        context.tracing.stop(path=TRACE_OUTPUT)
        context.close()
        print(f"Trace successfully saved to: {TRACE_OUTPUT}")
