# Softlight Assignment - AI Web Automation Agent

An intelligent AI agent that automatically navigates web applications, performs tasks, and captures every UI state in the workflow. Think of it as a smart browser assistant that can see, understand, and interact with web pages just like a human would.

## What This Does

You give it a task in plain English like:
- "Create a new task in Asana"
- "Create a new project in Linear"
- "Create a new database in Notion"

The agent then:
1. **Understands** what you want to do
2. **Logs in** (or asks you to log in if needed)
3. **Navigates** the application step by step
4. **Takes screenshots** at each important moment
5. **Creates documentation** showing exactly how to do the task

It's like having a robot that watches you do something once, then can teach others how to do it by showing them every step with pictures.

## How It Works (The Big Picture)

Imagine you're teaching someone how to use a website, but instead of explaining, you're taking a photo at each step and showing them what changed.

### The Core Concept: **See → Understand → Act → Verify**

1. **Take a Photo (Screenshot)**: The agent takes a screenshot of the current page
2. **Ask AI "What do I do next?"**: It sends the screenshot to an AI (Gemini) and asks what action to take
3. **Look at the DOM**: The agent also looks at the webpage's code (DOM) to find clickable elements
4. **Perform the Action**: It clicks a button, fills a form, or navigates somewhere
5. **See What Changed**: After clicking, it compares the DOM before and after to see what new elements appeared (like a popup opening)
6. **Repeat**: It keeps doing this until the task is complete
7. **Document Everything**: At the end, it creates a beautiful HTML guide with all the screenshots

### The Magic: DOM Change Detection

When you click a button, the webpage changes. New elements appear (like a popup, form, or menu). The agent is smart enough to:
- **Before clicking**: Save a snapshot of all elements on the page
- **After clicking**: Compare and find what's NEW
- **Focus on new stuff**: When deciding what to click next, it first looks at the new elements (like a popup that just opened)

This is like noticing "Oh, a popup just appeared, I should interact with that first!"

## Project Structure & How Each File Works

### `main.py` - The Brain
**What it does**: This is the main orchestrator. It's like the conductor of an orchestra.

**How it works**:
- Takes your task description as input
- Parses it to understand what app and what action
- Opens a browser and navigates to the app
- Checks if you're logged in (by looking for login buttons vs user indicators)
- Runs a loop:
  1. Takes a screenshot
  2. Checks if the goal is complete (asks AI: "Is the task created yet?")
  3. If not complete, asks AI: "What should I do next?" (click or fill)
  4. Finds the element in the DOM and performs the action
  5. Waits for changes and repeats
- Generates HTML documentation at the end

**Key concepts**:
- **Goal checking**: Before each action, it asks AI if the task is done. The AI is trained to say "not done" if it sees a form (because forms mean you haven't submitted yet)
- **Context retention**: It remembers what it did in previous steps so it doesn't get confused
- **Smart reuse**: If the screenshot is identical to the previous one, it reuses the last instruction (but checks if the goal check suggests a different action)

### `agent/task_parser.py` - The Translator
**What it does**: Converts your natural language into structured data.

**How it works**:
- You say: "Create a new task in Asana"
- It extracts:
  - App: "Asana"
  - URL: "https://app.asana.com"
  - Action: "create_task"
  - Task name: "create_a_new_task"

**Why it matters**: The rest of the system needs to know WHERE to go and WHAT to do.

### `agent/state_detector.py` - The Observer
**What it does**: Analyzes screenshots using AI vision to understand what's on the screen.

**How it works**:
- Takes a screenshot
- Sends it to Gemini (Google's AI) with a prompt
- Gets back structured information (JSON)
- Used for:
  - **Login detection**: "Is this a login page?"
  - **Goal completion**: "Is the task created yet?"
  - **Next action**: "What should I click or fill?"

**Key features**:
- **Rate limiting**: Waits 7 seconds between AI calls to avoid hitting API limits
- **JSON extraction**: Even if AI adds extra text, it extracts just the JSON
- **Smart prompts**: Each type of question has a carefully crafted prompt

### `agent/browser_controller.py` - The Hands
**What it does**: Controls the browser using Playwright.

**How it works**:
- Opens Firefox browser
- Navigates to URLs
- Manages browser profiles (so you stay logged in)
- Handles browser sessions

**Why browser profiles**: Each app gets its own profile, so if you log into Asana once, you stay logged in for future runs.

### `agent/navigation_planner.py` - The Strategist
**What it does**: (Currently not heavily used, but available) Could generate a step-by-step plan.

**How it works**:
- Takes the task and app name
- Could research or plan the steps
- Currently, the system uses a more direct approach (just asks AI what to do next)

### `utils/dom_inspector.py` - The Code Reader
**What it does**: Looks at the webpage's HTML code (DOM) to find elements.

**How it works**:
- **Before action**: Takes a snapshot of all elements
- **After action**: Takes another snapshot
- **Compares**: Finds what's new (new elements = something appeared, like a popup)
- **Returns**: List of new elements with their properties (text, position, etc.)

**The magic**: This is how the agent knows "a popup just opened" - it sees new DOM elements that weren't there before.

### `utils/session_manager.py` - The Memory Keeper
**What it does**: Manages browser sessions and profiles.

**How it works**:
- Creates a browser profile for each app (e.g., `asana_profile/`)
- Saves cookies and login state
- Reuses profiles so you don't have to log in every time

### `utils/rate_limiter.py` - The Traffic Controller
**What it does**: Prevents hitting API rate limits.

**How it works**:
- Tracks how many API calls were made
- If too many calls in a short time, it waits
- Ensures we don't exceed Gemini's rate limits (15 calls per minute)

### `utils/web_docs.py` - The Researcher
**What it does**: (Currently not heavily used) Could fetch official documentation.

**How it works**:
- Searches for official docs
- Fetches and parses HTML
- Extracts relevant information
- Currently, the system relies more on AI vision than documentation

### `config/prompts.py` - The Instruction Manual
**What it does**: Contains all the prompts (instructions) sent to the AI.

**How it works**:
- Each function returns a prompt string
- Prompts are carefully crafted to get the right response
- Examples:
  - `goal_check()`: "Has this goal been completed? Look for concrete evidence..."
  - `login_page_detection()`: "Is this a login page? Look for password fields..."

**Why it matters**: The quality of AI responses depends heavily on how you ask. These prompts are tuned to get accurate, structured responses.

## The Complete Workflow

Let's trace through "Create a new task in Asana":

1. **You run**: `python main.py "Create a new task in Asana"`

2. **Task Parser** (`task_parser.py`):
   - Extracts: app="Asana", url="https://app.asana.com", action="create_task"

3. **Main** (`main.py`):
   - Opens browser with Asana profile
   - Navigates to `https://app.asana.com`

4. **Login Check**:
   - Takes screenshot
   - **State Detector** analyzes: "Are there login buttons? User indicators?"
   - Logic: If login buttons exist → NOT logged in
   - If not logged in → hands control to you, waits for you to log in

5. **Main Loop Starts**:
   - **Step 1**: Takes screenshot (`screenshot_step_1.png`)
   - **Goal Check**: Asks AI "Is the task created?" → "No, I see the dashboard"
   - **Action Decision**: Asks AI "What do I do next?" → `{"event": "click", "text": "Create"}`
   - **DOM Snapshot**: Saves current DOM state
   - **Click**: Finds "Create" button in DOM and clicks it
   - **DOM Diff**: Compares DOM before/after → finds new popup elements
   - **Wait**: Waits for page to settle

   - **Step 2**: Takes screenshot (`screenshot_step_2.png`)
   - **Goal Check**: "Is task created?" → "No, I see a form to create task"
   - **Action Decision**: "What next?" → `{"event": "click", "text": "Task"}` (clicking Task option in dropdown)
   - **Click**: Clicks "Task" in the popup
   - **DOM Diff**: Finds new form elements

   - **Step 3**: Takes screenshot (`screenshot_step_3.png`)
   - **Goal Check**: "Is task created?" → "No, I see input fields to fill"
   - **Action Decision**: "What next?" → `{"event": "fill", "text": "Task name"}`
   - **Fill Logic**: 
     - Finds input field by label "Task name"
     - Uses native value setter (bypasses React/Vue synthetic events)
     - Sets value to "Test"
     - Triggers all events (input, change, keydown, keyup, etc.)
     - Simulates typing (adds space, removes it) to trigger validation
   - **DOM Diff**: Checks if form is now valid

   - **Step 4**: Takes screenshot (`screenshot_step_4.png`)
   - **Goal Check**: "Is task created?" → "No, form is filled but not submitted"
   - **Action Decision**: "What next?" → `{"event": "click", "text": "Add Task"}` or `{"event": "click", "text": "Create Task"}`
   - **Click**: Clicks submit button
   - **DOM Diff**: Sees task appear in list

   - **Step 5**: Takes screenshot (`screenshot_step_5.png`)
   - **Goal Check**: "Is task created?" → "YES! I see the task in the list"
   - **Break**: Loop ends, goal reached!

6. **Final Screenshot**: Takes `screenshot_final.png` before closing browser

7. **Documentation Generation**:
   - Creates `documentation.html` with:
     - Summary of task
     - Each step with screenshot
     - Final state screenshot
     - Clean, professional styling

## Key Design Decisions

### Why Screenshots + DOM?
- **Screenshots**: AI can see what a human sees (visual understanding)
- **DOM**: Precise element finding and interaction
- **Together**: Best of both worlds - visual intelligence + precise control

### Why DOM Diffing?
- After clicking, new elements appear (popup, form, etc.)
- By comparing before/after, we know exactly what changed
- We can focus on new elements for the next action
- This prevents confusion and makes the agent smarter

### Why Native Value Setter?
- Modern web apps (React, Vue) use synthetic events
- Directly setting `input.value` doesn't trigger validation
- Using the native setter bypasses framework layers
- Simulating typing (add space, remove) triggers all validation events
- This enables buttons like "Continue" that check if fields are valid

### Why Goal Checking Every Step?
- Prevents premature stopping
- AI is trained to recognize:
  - Form = not done (need to fill and submit)
  - Item in list = done (actually created)
- Makes the agent more reliable

### Why Context Retention?
- Agent remembers what it did: "I clicked Create, then clicked Task, then filled name"
- This helps AI make better decisions
- Prevents loops (if it clicked something and nothing changed, try something else)

## Setup

1. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
playwright install firefox
```

3. **Set up environment variables**:
```bash
cp env.example .env
# Edit .env and add your GEMINI_API_KEY
```

4. **Run the agent**:
```bash
python main.py "Create a new task in Asana"
```

## Requirements

- Python 3.12 or higher
- Node.js 20 or higher (for Playwright)
- Gemini API key (get one from [Google AI Studio](https://aistudio.google.com/))
- Firefox browser (installed automatically via Playwright)

## Getting Your Gemini API Key

1. Go to https://aistudio.google.com/
2. Sign in with your Google account
3. Click "Get API Key" or go to API Keys section
4. Create a new API key
5. Copy the key and add it to your `.env` file as `GEMINI_API_KEY=your_key_here`

## Project Structure

```
Softlight/
├── agent/                    # Core agent components
│   ├── task_parser.py       # Parses natural language → structured data
│   ├── state_detector.py     # AI vision analysis of screenshots
│   ├── browser_controller.py # Browser control (Playwright)
│   └── navigation_planner.py # Step-by-step planning (optional)
├── utils/                    # Helper utilities
│   ├── dom_inspector.py     # DOM snapshot & diffing
│   ├── session_manager.py   # Browser profile management
│   ├── rate_limiter.py      # API rate limit management
│   └── web_docs.py          # Documentation fetching (optional)
├── config/                   # Configuration
│   └── prompts.py           # AI prompts (instructions)
├── captures/                 # Screenshot outputs (included in repo)
│   └── [task_name]/         # Each task gets its own folder
│       ├── screenshot_step_*.png
│       ├── screenshot_final.png
│       └── documentation.html
├── main.py                   # Main entry point & orchestrator
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## For Developers

### Adding a New App

1. The task parser will automatically detect the app from your task description
2. Make sure the app URL is correct in `agent/task_parser.py`
3. The system will create a browser profile automatically

### Customizing Prompts

Edit `config/prompts.py` to change how the AI interprets screenshots. Each prompt is carefully tuned for specific tasks.

### Debugging

- Screenshots are saved in `captures/[task_name]/`
- Check `documentation.html` to see the full workflow
- The console output shows each step and decision

## 📝 License

Apache-2.0

## 🙏 Acknowledgments

Built with:
- [Playwright](https://playwright.dev/) - Browser automation
- [Google Gemini](https://deepmind.google/technologies/gemini/) - AI vision and reasoning
- [Python](https://www.python.org/) - The language of choice

---

**Made with ❤️ for the Softlight Assignment**
