"""
State documentation utility
Handles documenting UI states and workflow steps
"""
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, List, Optional


class StateDocumentation:
    """Handles documenting UI states and workflow progression"""
    
    def __init__(self, task_name: str, task_description: str, parsed_task: Dict, base_dir: str = "captures"):
        """
        Initialize state documentation for a task.
        
        Args:
            task_name: Sanitized task name
            task_description: Original task description
            parsed_task: Parsed task dictionary from TaskParser
            base_dir: Base directory for storing documentation
        """
        self.task_name = task_name
        self.task_description = task_description
        self.parsed_task = parsed_task
        self.base_dir = Path(base_dir)
        self.task_dir = self.base_dir / task_name
        self.task_dir.mkdir(parents=True, exist_ok=True)
        
        # Documentation file
        self.doc_file = self.task_dir / "documentation.json"
        
        # Initialize documentation structure
        self.documentation = {
            "task": {
                "description": task_description,
                "app": parsed_task.get("app", ""),
                "action": parsed_task.get("action", ""),
                "task_name": task_name
            },
            "workflow": {
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "total_steps": 0,
                "steps": []
            },
            "states": []
        }
    
    def add_step(
        self,
        step_number: int,
        action_type: str,
        action_description: str,
        state_description: str,
        url: str,
        screenshot_filename: str,
        page_title: str = "",
        notes: Optional[str] = None
    ):
        """
        Add a workflow step and state to the documentation.
        
        Args:
            step_number: Step number in the workflow
            action_type: Type of action (navigation, click, fill, etc.)
            action_description: Description of the action
            state_description: Description of the resulting UI state
            url: URL after the action
            screenshot_filename: Name of the screenshot file
            page_title: Page title
            notes: Optional additional notes
        """
        step_data = {
            "step": step_number,
            "action_type": action_type,
            "action_description": action_description,
            "state_description": state_description,
            "url": url,
            "screenshot": screenshot_filename,
            "page_title": page_title,
            "timestamp": datetime.now().isoformat()
        }
        
        if notes:
            step_data["notes"] = notes
        
        self.documentation["workflow"]["steps"].append(step_data)
        self.documentation["states"].append({
            "step": step_number,
            "description": state_description,
            "screenshot": screenshot_filename,
            "url": url
        })
        
        self.documentation["workflow"]["total_steps"] = step_number
        
        # Save documentation immediately
        self.save()
    
    def mark_completed(self):
        """Mark the workflow as completed"""
        self.documentation["workflow"]["completed_at"] = datetime.now().isoformat()
        self.save()
    
    def save(self):
        """Save documentation to JSON file"""
        with open(self.doc_file, "w") as f:
            json.dump(self.documentation, f, indent=2)
    
    def get_summary(self) -> Dict:
        """Get a summary of the documentation"""
        return {
            "task_name": self.task_name,
            "task_description": self.task_description,
            "total_steps": self.documentation["workflow"]["total_steps"],
            "completed": self.documentation["workflow"]["completed_at"] is not None,
            "documentation_file": str(self.doc_file)
        }
    
    def get_workflow_data(self) -> Dict:
        """Get the complete workflow documentation data"""
        return self.documentation

