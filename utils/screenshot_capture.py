"""
Screenshot capture utility with metadata
Handles capturing screenshots and saving them with structured metadata
"""
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, Optional


class ScreenshotCapture:
    """Handles screenshot capture and metadata management"""
    
    def __init__(self, task_name: str, base_dir: str = "captures"):
        """
        Initialize screenshot capture for a task.
        
        Args:
            task_name: Name of the task (sanitized, e.g., "create_task_in_asana")
            base_dir: Base directory for storing captures
        """
        self.task_name = task_name
        self.base_dir = Path(base_dir)
        self.task_dir = self.base_dir / task_name
        self.task_dir.mkdir(parents=True, exist_ok=True)
        
        # Metadata storage
        self.metadata_file = self.task_dir / "metadata.json"
        self.states = []
        self.step_counter = 0
        
        # Track unique states to avoid duplicates
        self.captured_urls = set()
        self.last_screenshot_hash = None
    
    def capture_state(
        self,
        page,
        action_description: str,
        state_description: str,
        url: str,
        action_type: str = "navigation"
    ) -> Dict:
        """
        Capture a screenshot of the current UI state and document it.
        
        Args:
            page: Playwright page object
            action_description: Description of the action that led to this state
            state_description: Description of the current UI state
            url: Current page URL
            action_type: Type of action (navigation, click, fill, etc.)
        
        Returns:
            Dictionary containing state metadata
        """
        self.step_counter += 1
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"step_{self.step_counter:03d}_{timestamp}.png"
        screenshot_path = self.task_dir / filename
        
        # Check if this state is significantly different from the last one
        # Take a screenshot to compare (full page to capture everything)
        page.screenshot(path=str(screenshot_path), full_page=True)
        
        # Calculate hash to detect duplicate screenshots
        import hashlib
        with open(screenshot_path, "rb") as f:
            screenshot_hash = hashlib.md5(f.read()).hexdigest()
        
        # Skip if this is a duplicate (same screenshot as last time)
        if screenshot_hash == self.last_screenshot_hash:
            print(f"⚠️  Skipping duplicate screenshot (same as previous)")
            screenshot_path.unlink()  # Delete duplicate
            return None
        
        self.last_screenshot_hash = screenshot_hash
        
        # Create state metadata
        state_metadata = {
            "step": self.step_counter,
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "action_description": action_description,
            "state_description": state_description,
            "url": url,
            "screenshot": filename,
            "page_title": page.title()
        }
        
        # Add to states list
        self.states.append(state_metadata)
        
        # Save metadata immediately (in case of crash)
        self.save_metadata()
        
        return state_metadata
    
    def save_metadata(self):
        """Save all state metadata to JSON file"""
        metadata = {
            "task_name": self.task_name,
            "total_steps": self.step_counter,
            "created_at": datetime.now().isoformat(),
            "states": self.states
        }
        
        with open(self.metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
    
    def get_task_summary(self) -> Dict:
        """Get a summary of all captured states"""
        return {
            "task_name": self.task_name,
            "total_steps": self.step_counter,
            "task_directory": str(self.task_dir),
            "states": self.states
        }

