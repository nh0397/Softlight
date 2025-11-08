"""
Navigation Planner - Generates next action based on current state
Uses LLM to determine what action to take next
"""
import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from config.prompts import NavigationPrompts

load_dotenv()


class NavigationPlanner:
    """Plans the next action based on current state and goal"""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
    
    def get_next_action(
        self,
        task_description: str,
        app_name: str,
        action: str,
        current_url: str,
        current_page_title: str,
        screenshot_description: str = "",
        previous_actions: list = None
    ) -> dict:
        """
        Get the next action to perform based on current state.
        
        Args:
            task_description: Original task description
            app_name: Name of the application
            action: Action to perform
            current_url: Current page URL
            current_page_title: Current page title
            screenshot_description: Description of current UI state (from screenshot analysis)
            previous_actions: List of previous actions taken
        
        Returns:
            Dictionary with action details:
            {
                "action": "navigate|click|fill|wait|done",
                "element_description": "description of element to interact with",
                "value": "value to fill (if action is fill)",
                "expected_state": "what should happen after this action",
                "reasoning": "why this action was chosen"
            }
        """
        prompt = f"""
You are an AI agent controlling a web browser to complete this task:
"{task_description}"

Current situation:
- Application: {app_name}
- Goal: {action}
- Current URL: {current_url}
- Current page: {current_page_title}
- Current UI state: {screenshot_description if screenshot_description else "Page loaded"}

{f"Previous actions taken: {', '.join([str(a) for a in previous_actions])}" if previous_actions else "This is the first step."}

Based on the current state, determine the NEXT SINGLE ACTION to take.

Available actions:
1. NAVIGATE: {{"action": "navigate", "url": "https://example.com/path"}}
   - Use when you need to go to a specific URL
   
2. CLICK: {{"action": "click", "element_description": "text or label of button/link", "expected_state": "what should appear after clicking"}}
   - Use to click buttons, links, or other clickable elements
   - element_description should be visible text, button label, or link text
   
3. FILL: {{"action": "fill", "element_description": "label or placeholder of input field", "value": "text to type", "expected_state": "field filled or form ready"}}
   - Use to type text into input fields
   - element_description should be field label, placeholder, or nearby text
   
4. WAIT: {{"action": "wait", "expected_state": "what to wait for", "timeout": 5}}
   - Use to wait for page to load, modal to appear, etc.
   
5. DONE: {{"action": "done", "final_state": "description of completed state"}}
   - Use when the task is successfully completed

IMPORTANT:
- Return ONLY valid JSON, no markdown code blocks
- Return ONE action at a time
- Be specific with element descriptions (use visible text/labels)
- Consider what should be visible after the action

Example for "create task in Asana":
If on Asana homepage and "Get started" or "Sign up" button is visible:
{{"action": "click", "element_description": "Get started", "expected_state": "Login or signup page"}}

If on login page and email field is visible:
{{"action": "fill", "element_description": "Email", "value": "user@example.com", "expected_state": "Email field filled"}}

Return the next action as JSON:
"""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean up response (remove markdown code blocks if present)
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            # Parse JSON
            action = json.loads(response_text)
            return action
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            print(f"Response was: {response_text}")
            raise
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            raise

