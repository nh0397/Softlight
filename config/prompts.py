"""
Prompt templates for screenshot analysis and state detection
Centralized prompt configuration for easy iteration and improvement
"""


class ScreenshotAnalysisPrompts:
    """Prompts for analyzing screenshots to detect UI states"""
    
    @staticmethod
    def page_load_verification():
        """Check if a page is fully loaded"""
        return """
        Look at this screenshot and determine if the page is fully loaded.
        
        Check for:
        1. Is the main content visible and rendered?
        2. Are there any loading indicators or spinners visible?
        3. Is the page in a stable, ready state?
        
        Answer with ONLY one of these options:
        - "Page is fully loaded"
        - "Page is still loading"
        - "Page load error detected"
        """
    
    @staticmethod
    def element_detection(element_description: str):
        """Detect if a specific UI element is visible"""
        return f"""
        Look at this screenshot and determine if the following element is visible:
        "{element_description}"
        
        Examples of element descriptions:
        - "search box" or "search input field"
        - "submit button" or "create button"
        - "modal dialog" or "popup window"
        - "form field for email"
        - "navigation menu"
        
        Answer with ONLY one of these options:
        - "Yes, {element_description} is visible"
        - "No, {element_description} not found"
        - "Partially visible, {element_description} is obscured"
        """
    
    @staticmethod
    def form_fill_verification(field_description: str = "input field"):
        """Verify if a form field has been filled"""
        return f"""
        Look at this screenshot.
        Is there text entered in a {field_description}?
        
        Answer with ONLY one of these options:
        - "Yes, {field_description} has text"
        - "No, {field_description} is empty"
        - "Cannot determine, {field_description} not visible"
        """
    
    @staticmethod
    def state_verification(expected_state: str, context: str = ""):
        """Verify if the UI is in a specific expected state"""
        return f"""
        Look at this screenshot and verify if the UI is in this expected state:
        "{expected_state}"
        
        {f"Context: {context}" if context else ""}
        
        Consider:
        1. Is the expected UI element/state visible?
        2. Is the page ready for the next action?
        3. Are there any error messages or blockers?
        
        Answer with ONLY one of these options:
        - "State verified: {expected_state}"
        - "State not reached: {expected_state}"
        - "Error or blocker detected"
        """
    
    @staticmethod
    def general_analysis():
        """General screenshot analysis for understanding page content"""
        return """
        Look at this screenshot and provide a brief analysis:
        1. What website/application is this?
        2. What is the main content or purpose of this page?
        3. What interactive elements are visible (buttons, forms, links)?
        4. Is the page in a ready state for user interaction?
        
        Provide a concise, structured answer.
        """
    
    @staticmethod
    def action_readiness(action_description: str):
        """Check if the page is ready for a specific action"""
        return f"""
        Look at this screenshot and determine if the page is ready to perform this action:
        "{action_description}"
        
        Check:
        1. Are the required UI elements visible and accessible?
        2. Is the page fully loaded (no spinners, loading states)?
        3. Are there any error messages or blockers?
        
        Answer with ONLY one of these options:
        - "Ready for action: {action_description}"
        - "Not ready: missing required elements"
        - "Not ready: page still loading"
        - "Not ready: error detected"
        """
    
    @staticmethod
    def login_page_detection():
        """Detect if the current page is a login/signup page"""
        return """
        Look at this screenshot and determine if this is a login or signup page.
        
        Look for:
        1. Login/signin forms (email/password fields)
        2. "Sign in", "Log in", "Sign up", "Create account" buttons or text
        3. Authentication-related UI elements
        4. Login page layouts
        
        Answer in this EXACT JSON format:
        {
            "is_login_page": true/false,
            "page_type": "login|signup|authenticated|unknown",
            "reasoning": "brief explanation"
        }
        
        Be strict: only mark is_login_page as true if you clearly see login/signup UI elements.
        """
    
    @staticmethod
    def login_completion_detection():
        """Detect if login has been completed"""
        return """
        Look at this screenshot and determine if the user has successfully logged in.
        
        Look for:
        1. Absence of login/signin forms
        2. Presence of authenticated user interface (dashboard, workspace, user menu, etc.)
        3. Navigation menus or app-specific content that indicates being logged in
        4. User profile indicators or account information
        
        Answer in this EXACT JSON format:
        {
            "login_completed": true/false,
            "is_authenticated": true/false,
            "indicator": "what indicates login status",
            "reasoning": "brief explanation"
        }
        
        Be strict: only mark login_completed as true if you clearly see authenticated content.
        """
    
    @staticmethod
    def goal_check(task_goal: str, current_state: str = ""):
        """Check if the task goal has been completed"""
        return f"""
        Look at this screenshot and determine if the task goal has been completed.
        
        Task Goal: "{task_goal}"
        
        {f"Current State: {current_state}" if current_state else ""}
        
        Analyze the screenshot and determine:
        1. Has the goal been successfully completed?
        2. What visible elements indicate completion or progress?
        3. What still needs to be done?
        
        Answer in this EXACT JSON format:
        {{
            "goal_completed": true/false,
            "completion_indicators": ["list", "of", "visible", "elements", "that", "show", "completion"],
            "next_steps_needed": ["list", "of", "actions", "still", "needed"],
            "reasoning": "brief explanation of why goal is or isn't completed"
        }}
        
        Be strict: only mark goal_completed as true if the goal is FULLY achieved.
        """
    
    @staticmethod
    def analyze_viewport_for_next_steps(task_goal: str, current_state: str = "", dom_data: str = ""):
        """Analyze viewport screenshot to determine what's visible and what to do next"""
        return f"""
        Look at this screenshot (full page - showing all content on the page).
        
        Task Goal: "{task_goal}"
        {f"Current State: {current_state}" if current_state else ""}
        
        {f"DOM ANALYSIS - Interactive elements extracted from page code:\n{dom_data}\n" if dom_data else ""}
        
        ANALYZE EVERYTHING visible in the screenshot carefully:
        
        1. LIST ALL interactive elements you can see:
           - Buttons (what do they say?)
           - Input fields (what are they for? are they empty or filled?)
           - Dropdowns/selects
           - Checkboxes/radio buttons
           - Links
           - Any other clickable/fillable elements
        
        2. For each input field, identify:
           - What information it's asking for (name, title, description, etc.)
           - Whether it's required (often marked with * or "required")
           - Whether it's already filled or empty
        
        3. Determine the LOGICAL next step to achieve the goal:
           - If there are empty required fields → fill them
           - If all fields are filled → click submit/save/create button
           - If we need more options → scroll or click to expand
        
        Answer in this EXACT JSON format:
        {{
            "visible_elements": {{
                "buttons": ["List all buttons with their exact text"],
                "input_fields": [
                    {{
                        "label": "field label or placeholder",
                        "type": "text|number|email|etc",
                        "status": "empty|filled",
                        "required": true|false
                    }}
                ],
                "other_elements": ["any other interactive elements"]
            }},
            "suggested_actions": [
                {{
                    "action": "click|fill|scroll|wait",
                    "target": "EXACT description of element (use visible text)",
                    "value": "value to enter if action is fill",
                    "field_purpose": "what is this field for?",
                    "priority": "high|medium|low",
                    "reasoning": "why this specific action"
                }}
            ],
            "should_scroll": true|false,
            "scroll_direction": "down|up" (only if should_scroll is true),
            "reasoning": "overall analysis: what state is the page in and what needs to happen next"
        }}
        
        Be THOROUGH. List EVERY field and button you see. Don't skip anything.
        Focus on what's ACTUALLY VISIBLE. If fields exist but aren't visible, suggest scrolling.
        """


class NavigationPrompts:
    """Prompts for navigation planning and step generation"""
    
    @staticmethod
    def generate_navigation_plan(task_description: str, app_name: str, current_url: str = ""):
        """Generate step-by-step navigation plan"""
        return f"""
        Given this task: "{task_description}"
        For the application: {app_name}
        {f"Current URL: {current_url}" if current_url else ""}
        
        Generate a step-by-step navigation plan to complete this task.
        Each step should be a specific action like:
        - Navigate to URL
        - Click on [element description]
        - Fill [field name] with [value]
        - Wait for [element/state]
        - Take screenshot
        
        Return the plan as a JSON array of steps, each with:
        {{
            "step_number": 1,
            "action": "navigate|click|fill|wait|screenshot",
            "target": "description of what to interact with",
            "value": "value to fill (if action is fill)",
            "expected_state": "what should be visible after this step"
        }}
        """
    
    @staticmethod
    def find_element_strategy(element_description: str):
        """Generate strategy for finding an element"""
        return f"""
        I need to find this element on the page: "{element_description}"
        
        Suggest the best way to locate it:
        1. By visible text
        2. By placeholder text
        3. By role/aria-label
        4. By CSS selector pattern
        5. By position/layout
        
        Return a JSON object with the strategy.
        """


class TaskParsingPrompts:
    """Prompts for parsing natural language tasks"""
    
    @staticmethod
    def parse_task(task_description: str):
        """Parse task description into structured format"""
        return f"""
        Parse this task description into structured JSON format:
        "{task_description}"
        
        Extract the following information:
        1. The web application name (e.g., "Asana", "Notion", "Linear", "Jira", "Trello")
        2. The base URL for the application:
           - Asana: "https://app.asana.com"
           - Notion: "https://www.notion.so"
           - Linear: "https://linear.app"
           - Jira: "https://www.atlassian.com/software/jira"
           - Trello: "https://trello.com"
           - For other apps: Use the main web URL (e.g., "https://appname.com")
        3. The action to perform (e.g., "create_project", "filter_issues", "create_database")
        4. A sanitized task name (lowercase, underscores, no special chars)
        5. Any additional context (empty dict if none)
        
        Return ONLY valid JSON in this exact format:
        {{
            "app": "app name",
            "app_url": "base URL",
            "action": "action description",
            "task_name": "sanitized_task_name",
            "context": {{}}
        }}
        
        Do not include any explanation, only the JSON.
        """

