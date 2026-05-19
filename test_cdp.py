"""Test connecting to real Chrome via CDP to bypass Cloudflare on dramaday.me."""
import subprocess
import time
import os
from pathlib import Path

def get_chrome_path():
    """Get Chrome executable path."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

def main():
    chrome_path = get_chrome_path()
    if not chrome_path:
        print("Chrome not found!")
        return
    
    print(f"Chrome: {chrome_path}")
    
    # Launch Chrome with remote debugging
    user_data_dir = Path(os.environ.get("TEMP", ".")) / "dramaday-chrome-profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    
    port = 9223  # Use different port to avoid conflicts
    
    print(f"Launching Chrome with --remote-debugging-port={port}...")
    proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://dramaday.me/"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for Chrome to start
    time.sleep(3)
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as pw:
            print("Connecting to Chrome via CDP...")
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            
            # Wait for Cloudflare challenge to solve
            print("Waiting for Cloudflare challenge to solve...")
            for i in range(30):
                title = page.title()
                print(f"  [{i*2}s] Title: {title}")
                if 'Just a moment' not in title:
                    print(f"Challenge solved after {i*2} seconds!")
                    break
                time.sleep(2)
            
            # Extract cookies
            cookies = context.cookies()
            print("\nCookies:")
            cf_clearance = None
            for c in cookies:
                name = c.get('name', '')
                val = c.get('value', '')
                print(f"  {name}: {val[:50]}...")
                if name == 'cf_clearance':
                    cf_clearance = val
            
            if cf_clearance:
                print(f"\n[OK] cf_clearance obtained: {cf_clearance[:30]}...")
                
                # Now try to access drama page with the cookie
                print("\nNavigating to drama page...")
                try:
                    page.goto('https://dramaday.me/sold-out-on-you/', wait_until='domcontentloaded', timeout=30000)
                except Exception as e:
                    print(f"Navigation error (expected): {e}")
                    # Wait a bit and try again
                    time.sleep(2)
                    page.goto('https://dramaday.me/sold-out-on-you/', wait_until='domcontentloaded', timeout=30000)
                
                time.sleep(2)
                
                content = page.content()
                print(f"Drama page length: {len(content)}")
                print('Has download table:', 'supsystic-table' in content or 'exe.io' in content)
                print('Title:', page.title()[:50])
            else:
                print("\n[FAIL] No cf_clearance cookie found")
            
            browser.close()
    
    finally:
        proc.terminate()
        print("\nChrome closed.")

if __name__ == '__main__':
    main()
