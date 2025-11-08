"""
Session Manager - Handles browser session persistence
Saves and loads cookies/storage so we don't need to log in every time
Supports persistent browser contexts and cookie import from existing browsers
"""
import json
from pathlib import Path
from playwright.sync_api import BrowserContext
from typing import Optional, Tuple
import os
import platform
import sqlite3
import shutil


class SessionManager:
    """Manages browser session state (cookies, storage)"""
    
    def __init__(self, base_dir: str = "sessions", profiles_dir: str = "browser_profiles"):
        """
        Initialize session manager.
        
        Args:
            base_dir: Base directory for storing session files
            profiles_dir: Base directory for persistent browser profiles
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
    
    def get_session_path(self, app_name: str) -> Path:
        """
        Get the path to session file for an app.
        
        Args:
            app_name: Name of the application (e.g., "Asana", "Notion")
        
        Returns:
            Path to session file
        """
        # Sanitize app name for filename
        safe_name = app_name.lower().replace(" ", "_")
        return self.base_dir / f"{safe_name}_session.json"
    
    def get_profile_path(self, app_name: str) -> Path:
        """
        Get the path to persistent browser profile for an app.
        
        Args:
            app_name: Name of the application
        
        Returns:
            Path to browser profile directory
        """
        safe_name = app_name.lower().replace(" ", "_")
        return self.profiles_dir / f"{safe_name}_profile"
    
    def save_session(self, context: BrowserContext, app_name: str) -> bool:
        """
        Save browser context state (cookies, storage) to file.
        
        Args:
            context: Playwright browser context
            app_name: Name of the application
        
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            session_path = self.get_session_path(app_name)
            
            # Get storage state (includes cookies, localStorage, sessionStorage)
            storage_state = context.storage_state()
            
            # Save to file
            with open(session_path, "w") as f:
                json.dump(storage_state, f, indent=2)
            
            print(f"✅ Session saved to: {session_path}")
            return True
            
        except Exception as e:
            print(f"❌ Error saving session: {e}")
            return False
    
    def load_session(self, app_name: str) -> Optional[dict]:
        """
        Load saved session state from file.
        
        Args:
            app_name: Name of the application
        
        Returns:
            Storage state dictionary or None if not found
        """
        session_path = self.get_session_path(app_name)
        
        if not session_path.exists():
            return None
        
        try:
            with open(session_path, "r") as f:
                storage_state = json.load(f)
            
            print(f"✅ Session loaded from: {session_path}")
            return storage_state
            
        except Exception as e:
            print(f"⚠️  Error loading session: {e}")
            return None
    
    def session_exists(self, app_name: str) -> bool:
        """
        Check if a session file exists for an app.
        
        Args:
            app_name: Name of the application
        
        Returns:
            True if session exists, False otherwise
        """
        session_path = self.get_session_path(app_name)
        return session_path.exists()
    
    def delete_session(self, app_name: str) -> bool:
        """
        Delete saved session for an app.
        
        Args:
            app_name: Name of the application
        
        Returns:
            True if deleted successfully, False otherwise
        """
        session_path = self.get_session_path(app_name)
        
        if not session_path.exists():
            return False
        
        try:
            session_path.unlink()
            print(f"✅ Session deleted: {session_path}")
            return True
        except Exception as e:
            print(f"❌ Error deleting session: {e}")
            return False
    
    def get_profile_context_options(self, app_name: str, viewport: dict = None) -> dict:
        """
        Get context options for persistent browser profile.
        This creates/uses a persistent browser profile that automatically saves cookies and storage.
        
        Args:
            app_name: Name of the application
            viewport: Viewport size dict (optional)
        
        Returns:
            Dictionary of context options for browser.new_context()
        """
        profile_path = self.get_profile_path(app_name)
        profile_path.mkdir(parents=True, exist_ok=True)
        
        options = {
            "user_data_dir": str(profile_path)
        }
        
        if viewport:
            options["viewport"] = viewport
        
        return options
    
    def find_firefox_profile(self) -> Optional[Path]:
        """
        Try to find the default Firefox profile on the system.
        This allows importing cookies from existing Firefox sessions.
        
        Returns:
            Path to Firefox profile directory or None if not found
        """
        system = platform.system()
        
        if system == "Darwin":  # macOS
            profiles_dir = Path.home() / "Library/Application Support/Firefox/Profiles"
        elif system == "Linux":
            profiles_dir = Path.home() / ".mozilla/firefox"
        elif system == "Windows":
            profiles_dir = Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles"
        else:
            return None
        
        if not profiles_dir.exists():
            return None
        
        # Look for default profile (usually ends with .default-release or .default)
        for profile_dir in profiles_dir.iterdir():
            if profile_dir.is_dir() and (profile_dir.name.endswith(".default-release") or 
                                         profile_dir.name.endswith(".default")):
                return profile_dir
        
        # If no default profile found, try the first profile
        profiles = [p for p in profiles_dir.iterdir() if p.is_dir()]
        if profiles:
            return profiles[0]
        
        return None
    
    def import_cookies_from_firefox(self, app_name: str, domain: str) -> bool:
        """
        Attempt to import cookies from Firefox's default profile.
        This tries to read cookies from Firefox's cookies.sqlite database.
        
        Args:
            app_name: Name of the application
            domain: Domain to filter cookies for (e.g., "asana.com", "notion.so")
        
        Returns:
            True if cookies were imported, False otherwise
        """
        firefox_profile = self.find_firefox_profile()
        if not firefox_profile:
            print("⚠️  Could not find Firefox profile")
            return False
        
        cookies_db = firefox_profile / "cookies.sqlite"
        if not cookies_db.exists():
            print("⚠️  Could not find Firefox cookies database")
            return False
        
        try:
            # Firefox uses SQLite for cookies
            # Note: This might fail if Firefox is running (locks the database)
            conn = sqlite3.connect(str(cookies_db))
            cursor = conn.cursor()
            
            # Query cookies for the domain
            cursor.execute("""
                SELECT name, value, host, path, expiry, isSecure, isHttpOnly
                FROM moz_cookies
                WHERE host LIKE ? OR host LIKE ?
            """, (f"%{domain}%", f"%.{domain}%"))
            
            cookies = cursor.fetchall()
            conn.close()
            
            if not cookies:
                print(f"⚠️  No cookies found for {domain} in Firefox")
                return False
            
            # Convert to Playwright format
            playwright_cookies = []
            for cookie in cookies:
                name, value, host, path, expiry, is_secure, is_http_only = cookie
                playwright_cookies.append({
                    "name": name,
                    "value": value,
                    "domain": host,
                    "path": path or "/",
                    "expires": expiry if expiry > 0 else -1,
                    "httpOnly": bool(is_http_only),
                    "secure": bool(is_secure),
                    "sameSite": "Lax"
                })
            
            # Save to session file
            session_path = self.get_session_path(app_name)
            storage_state = {
                "cookies": playwright_cookies,
                "origins": []
            }
            
            with open(session_path, "w") as f:
                json.dump(storage_state, f, indent=2)
            
            print(f"✅ Imported {len(playwright_cookies)} cookies from Firefox for {domain}")
            return True
            
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                print("⚠️  Firefox database is locked. Please close Firefox and try again.")
            else:
                print(f"⚠️  Error reading Firefox cookies: {e}")
            return False
        except Exception as e:
            print(f"⚠️  Error importing cookies from Firefox: {e}")
            return False
    
    def import_cookies_from_file(self, app_name: str, cookie_file_path: str) -> bool:
        """
        Import cookies from a JSON file (e.g., exported from browser extension).
        
        Args:
            app_name: Name of the application
            cookie_file_path: Path to JSON file with cookies
        
        Returns:
            True if cookies were imported, False otherwise
        """
        cookie_path = Path(cookie_file_path)
        if not cookie_path.exists():
            print(f"⚠️  Cookie file not found: {cookie_file_path}")
            return False
        
        try:
            with open(cookie_path, "r") as f:
                cookie_data = json.load(f)
            
            # Handle different cookie export formats
            if isinstance(cookie_data, list):
                # Direct list of cookies
                cookies = cookie_data
            elif isinstance(cookie_data, dict):
                # Might be in storage_state format or nested
                cookies = cookie_data.get("cookies", cookie_data.get("data", []))
            else:
                print("⚠️  Unknown cookie file format")
                return False
            
            if not cookies:
                print("⚠️  No cookies found in file")
                return False
            
            # Save to session file
            session_path = self.get_session_path(app_name)
            storage_state = {
                "cookies": cookies,
                "origins": []
            }
            
            with open(session_path, "w") as f:
                json.dump(storage_state, f, indent=2)
            
            print(f"✅ Imported {len(cookies)} cookies from file")
            return True
            
        except Exception as e:
            print(f"⚠️  Error importing cookies from file: {e}")
            return False


