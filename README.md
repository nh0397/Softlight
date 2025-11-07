# Softlight UI State Capture System

An AI agent that navigates web applications and captures UI states for task workflows.

## What This Does

This system takes natural language task descriptions (like "How do I create a task in Asana?" or "How do I filter a database in Notion?") and automatically navigates the web application to perform the task, capturing screenshots of each UI state in the workflow.

## Setup

1. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
playwright install firefox
```

3. Set up environment variables:
```bash
cp env.example .env
# Edit .env and add your GEMINI_API_KEY
```

4. Run the agent:
```bash
python main.py "How do I create a task in Asana?"
```

## Requirements

- Python 3.12 or higher
- Node.js 20 or higher
- Gemini API key (get one from Google AI Studio)
- Firefox browser (installed automatically via Playwright)

## Project Structure

```
Softlight/
├── agent/          # Core agent components
│   ├── task_parser.py    # Parses natural language tasks
│   └── ...
├── captures/       # Screenshot outputs (created at runtime)
├── utils/          # Helper utilities
├── config/         # Configuration files
└── main.py         # Entry point
```

## How It Works

The system consists of several components working together:

- **Task Parser** - Understands natural language task descriptions and extracts structured information (app name, action, context)
- **Navigation Planner** - Generates step-by-step navigation plan using LLM
- **Browser Controller** - Executes actions using Playwright (Firefox)
- **State Detector** - Monitors and detects UI state changes
- **Screenshot Capture** - Saves UI states at key moments

## Getting Your Gemini API Key

1. Go to https://aistudio.google.com/
2. Sign in with your Google account
3. Click "Get API Key" or go to API Keys section
4. Create a new API key
5. Copy the key and add it to your `.env` file as `GEMINI_API_KEY=your_key_here`

## License

Apache-2.0
