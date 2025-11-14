"""
Prompt templates for screenshot analysis, state detection, navigation, task parsing, and docs summarization.
"""


class ScreenshotAnalysisPrompts:
    """Prompts for analyzing screenshots to detect UI states"""

    @staticmethod
    def general_analysis():
        return """
Look at this screenshot and provide a brief analysis:
1) What application or site is this?
2) Main content or purpose of the page
3) Key interactive elements visible
4) Is the page ready for interaction
"""

    @staticmethod
    def state_verification(expected_state: str, context: str = ""):
        return f"""
Verify if the UI matches this expected state: "{expected_state}"
{f"Context: {context}" if context else ""}

Answer clearly whether the expected state is visible.
Use short language like:
- "State verified: {expected_state}"
- "State not reached: {expected_state}"
- "Error or blocker detected"
"""

    @staticmethod
    def action_readiness(action_description: str):
        return f"""
Determine if the page is ready to perform this action: "{action_description}"
Reply with "Ready for action: {action_description}" only if the required elements are visible and the page is stable.
Otherwise reply with one of:
- "Not ready: missing required elements"
- "Not ready: page still loading"
- "Not ready: error detected"
"""

    @staticmethod
    def login_page_detection():
        return """
Detect if this screenshot shows a login or signup page.
Return JSON exactly as:
{
  "is_login_page": true/false,
  "page_type": "login|signup|unknown",
  "reasoning": "short"
}
"""

    @staticmethod
    def login_completion_detection():
        return """
Detect if the user is authenticated on this screenshot.
Return JSON exactly as:
{
  "login_completed": true/false,
  "is_authenticated": true/false,
  "indicator": "what indicates the status",
  "reasoning": "short"
}
"""

    @staticmethod
    def goal_check(task_goal: str, current_state: str = ""):
        return f"""
Has this goal been FULLY completed: "{task_goal}"?

CRITICAL: The goal is ONLY completed when:
- The item (task/project/database/etc.) is ACTUALLY CREATED and VISIBLE in a list or dashboard
- A confirmation message appears (e.g., "Task created", "Project created successfully")
- The item appears in the main view (not just a form/modal to create it)
- The workflow is COMPLETE, not just started

The goal is NOT completed if:
- A form/modal appears to create the item (this is just the START, not completion)
- You see input fields to fill (this means creation hasn't happened yet)
- You're in the middle of a workflow (e.g., clicked "Create" but haven't filled the form)
- The word appears in the UI but it's just a label or button text

{f"Current state: {current_state}" if current_state else ""}

Look for CONCRETE EVIDENCE of completion:
- Item visible in a list/board/dashboard
- Success/confirmation message
- Item details page showing the created item
- No more forms or modals asking for input

Return JSON exactly as:
{{
  "goal_completed": true/false,
  "completion_indicators": ["list of specific evidence"],
  "next_steps_needed": ["what still needs to be done"],
  "reasoning": "detailed explanation of why completed or not"
}}
"""

    @staticmethod
    def analyze_viewport_for_next_steps(task_goal: str, current_state: str = "", dom_data: str = ""):
        return f"""
Analyze the screenshot to find the next step toward completing "{task_goal}".
Use the DOM context if helpful:
{dom_data}

Return JSON:
{{
  "visible_elements": {{
    "buttons": [],
    "input_fields": [
      {{
        "label": "field label or placeholder",
        "type": "text|number|email|etc",
        "status": "empty|filled",
        "required": true|false
      }}
    ],
    "other_elements": []
  }},
  "suggested_actions": [
    {{
      "action": "click|fill|scroll|wait",
      "target": "exact visible text or label",
      "value": "if fill",
      "field_purpose": "short",
      "priority": "high|medium|low",
      "reasoning": "short"
    }}
  ],
  "should_scroll": true/false,
  "scroll_direction": "down|up",
  "reasoning": "overall analysis"
}}
"""

    @staticmethod
    def classify_state():
        return """
Classify the high-level UI state of this screenshot.
Return JSON exactly as:
{"state": "login|dashboard|form|modal|success|unknown"}
"""

    @staticmethod
    def ocr_text_detection():
        return """
Extract every visible text element in this screenshot.
For each distinct element, capture the text exactly as shown (trim extra whitespace) and its approximate bounding box.

Return ONLY a JSON array with objects shaped like:
[
  {
    "text": "Button label",
    "bounding_box": {"x": 123, "y": 456, "width": 200, "height": 60}
  }
]

If nothing is readable, return an empty JSON array [].
"""


class NavigationPrompts:
    """Prompts for navigation planning and element finding"""

    @staticmethod
    def generate_navigation_plan(task_description: str, app_name: str, current_url: str = ""):
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

Return JSON array of steps:
[
  {{
    "step_number": 1,
    "action": "navigate|click|fill|wait|screenshot",
    "target": "description of what to interact with",
    "value": "if action is fill",
    "expected_state": "what should be visible after this step"
  }}
]
"""

    @staticmethod
    def find_element_strategy(element_description: str):
        return f"""
I need to find this element on the page: "{element_description}"

Suggest the best way to locate it:
1. By visible text
2. By placeholder text
3. By role or aria-label
4. By CSS selector pattern
5. By position or layout

Return a JSON object with the strategy.
"""


class TaskParsingPrompts:
    """Prompts for parsing natural language tasks"""

    @staticmethod
    def parse_task(task_description: str):
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
  "task_parameters": {{}}
}}
"""


class DocSummarizationPrompts:
    """Prompts for summarizing web docs into concrete steps"""

    @staticmethod
    def summarize_to_steps(app: str, action: str, points: list):
        joined = "\n".join(f"- {p}" for p in points[:20])
        return f"""
You are helping plan how to perform an action in a web app.

App: "{app}"
Action: "{action}"

Below are raw bullet points extracted from official documentation:
{joined}

Convert these into a concise, practical plan with 5 to 10 steps max that a browser automation can follow.
Each step must be an imperative instruction aimed at UI elements using visible labels.

Return ONLY valid JSON:
{{
  "app": "{app}",
  "action": "{action}",
  "steps": [
    {{
      "step": 1,
      "instruction": "Click 'New database'",
      "notes": "If hidden, open sidebar"
    }}
  ],
  "notes": "short caveats if any"
}}
"""


class DocumentationPrompts:
    """Prompts for generating human-readable documentation and reviews"""

    @staticmethod
    def step_narration(
        task_description: str,
        app_name: str,
        step_number: int,
        action_type: str,
        action_target: str,
        action_source: str,
        doc_step_text: str,
        pre_state_description: str,
        post_state_description: str
    ) -> str:
        return f"""
You are documenting a browser automation workflow for onboarding materials.

Task: "{task_description}"
Application: {app_name}
Step number: {step_number}
Action type: {action_type}
Action target or element: {action_target if action_target else "N/A"}
Action source: {action_source}
Documented step reference: "{doc_step_text if doc_step_text else "None"}"

Before performing the action, the UI looked like:
{pre_state_description if pre_state_description else "No description"}.

After performing the action, the UI now looks like:
{post_state_description if post_state_description else "No description"}.

Write clear guidance for a human following this documentation.

Return ONLY valid JSON in this format:
{{
  "summary": "One or two sentences telling the user what to do in imperative voice.",
  "notes": "Optional extra note for context, or empty string if none."
}}
"""

    @staticmethod
    def review_documentation(
        task_description: str,
        html_content: str
    ) -> str:
        return f"""
You are a senior QA documentation reviewer. The following HTML describes how to complete this task:
"{task_description}"

Evaluate whether the documentation is clear enough for a new user. Consider completeness, clarity, and accuracy.

Documentation HTML (between the markers):
DOC_HTML_START
{html_content}
DOC_HTML_END

Return ONLY valid JSON in this format:
{{
  "score": 1-5,
  "summary": "Short overall verdict",
  "strengths": ["bullet", "points"],
  "gaps": ["missing details", "confusing parts"],
  "is_clear_enough": true/false,
  "recommendation": "What to improve or confirm it is good"
}}
"""
