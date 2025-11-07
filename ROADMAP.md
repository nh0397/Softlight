# Softlight Assignment - Development Roadmap

This is a straightforward plan to build the UI state capture system.

## Milestone 1 - Foundation and Basic Automation

Goal: Get browser automation working and start integrating the AI.

What we need to do:
- Set up the project structure (folders, files)
- Install dependencies (Playwright, Google Generative AI library)
- Create a basic browser automation script
- Test that we can open a browser, navigate to a website, and take screenshots
- Test that we can click buttons and fill forms
- Set up Gemini API integration
- Build a basic task parser that can extract app name and action from a task description

What we'll have at the end:
- Browser automation that works (can navigate, click, take screenshots)
- Task parser that can understand natural language and extract structured info


---

## Milestone 2 - Core Agent System

Goal: Connect all the pieces together so we have a full end-to-end flow.

What we need to do:
- Build the navigation planner (uses LLM to generate step-by-step plan)
- Build the browser controller (executes actions like click, fill, navigate)
- Build the main Agent B orchestrator (ties everything together)
- Implement element finding (how to find buttons, forms, etc. by text, placeholder, role)
- Add screenshot capture system
- Test the full flow with one simple task

What we'll have at the end:
- A system that takes a task description, parses it, plans the steps, executes them, and captures screenshots
- At least one working task end-to-end


---

## Milestone 3 - State Detection and Multiple Tasks

Goal: Make it more reliable and test it on multiple different tasks.

What we need to do:
- Improve state detection (wait for modals to fully load, forms to appear, etc.)
- Better element finding strategies (handle edge cases)
- Add basic error handling
- Test Task 1: Create project in Linear
- Test Task 2: Filter issues in Linear (or use a different app)
- Test Task 3: Create database in Notion
- Fix any issues that come up

What we'll have at the end:
- System that can handle 3 different tasks
- Screenshots captured at the right moments (not too early, not too late)
- Better error handling so it doesn't crash on edge cases


---

## Milestone 4 - Session Management and More Tasks

Goal: Handle authentication properly and test the remaining tasks.

What we need to do:
- Implement session/cookie management (save login state so we don't have to log in every time)
- Test Task 4: Pick another task
- Test Task 5: Pick another task
- Organize screenshot output better (clean folder structure)
- Add metadata to screenshots (what step it is, what action was taken)
- Create proper dataset folder structure

What we'll have at the end:
- Session persistence (login once, reuse for all tasks)
- All 5 tasks working reliably
- Well-organized dataset structure that's ready to submit


---

## Milestone 5 - Documentation and Demo Prep

Goal: Prepare everything for submission.

What we need to do:
- Write README with setup instructions
- Record Loom video showing the system working and explaining the approach
- Finalize the dataset (make sure all screenshots are good quality)
- Write task descriptions for the dataset
- Test everything one more time to make sure it works

What we'll have at the end:
- README.md with clear instructions
- Loom video link
- Dataset folder with 5 tasks, organized and documented
- GitHub repo ready to share


