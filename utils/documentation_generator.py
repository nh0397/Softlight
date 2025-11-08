"""
Documentation Generator - Creates Markdown/HTML documentation from captured workflow
"""
from pathlib import Path
from typing import List, Dict
from datetime import datetime


class DocumentationGenerator:
    """Generates human-readable documentation from workflow captures"""
    
    def __init__(self, task_name: str, base_dir: str = "captures"):
        self.task_name = task_name
        self.base_dir = Path(base_dir)
        self.task_dir = self.base_dir / task_name
    
    def generate_markdown(self, workflow_data: Dict, output_path: str = None) -> str:
        """
        Generate Markdown documentation from workflow data.
        
        Args:
            workflow_data: Dictionary containing workflow steps and metadata
            output_path: Optional path to save the markdown file
        
        Returns:
            Markdown content as string
        """
        if not output_path:
            output_path = self.task_dir / "WORKFLOW.md"
        
        task_title = workflow_data.get("task_name", self.task_name).replace("_", " ").title()
        app_name = workflow_data.get("app", "Application")
        
        md_content = f"""# {task_title}

**Application:** {app_name}  
**Date:** {datetime.now().strftime("%B %d, %Y")}  
**Status:** {workflow_data.get("status", "Completed")}

## Overview

This workflow demonstrates how to {task_title.lower()} in {app_name}.

## Steps

"""
        
        # Add each step
        steps = workflow_data.get("steps", [])
        for i, step in enumerate(steps, 1):
            step_number = step.get("step_number", i)
            action = step.get("action_type", "unknown")
            description = step.get("action_description", "No description")
            state_desc = step.get("state_description", "")
            screenshot = step.get("screenshot_filename", "")
            url = step.get("url", "")
            notes = step.get("notes", "")
            
            md_content += f"""### Step {step_number}: {action.title()}

**Action:** {description}  
**URL:** `{url}`

{state_desc}

"""
            if notes:
                md_content += f"**Notes:** {notes}\n\n"
            
            if screenshot:
                md_content += f"![Step {step_number}]({screenshot})\n\n"
            
            md_content += "---\n\n"
        
        # Add summary
        md_content += f"""## Summary

Total steps completed: {len(steps)}

### Key Actions Performed

"""
        
        # Extract unique action types
        actions = list(set(step.get("action_type", "unknown") for step in steps))
        for action in actions:
            count = sum(1 for step in steps if step.get("action_type") == action)
            md_content += f"- **{action.title()}**: {count} time(s)\n"
        
        # Save to file
        output_path = Path(output_path)
        with open(output_path, "w") as f:
            f.write(md_content)
        
        print(f"✅ Markdown documentation saved to: {output_path}")
        return md_content
    
    def generate_html(self, workflow_data: Dict, output_path: str = None) -> str:
        """
        Generate HTML documentation from workflow data.
        
        Args:
            workflow_data: Dictionary containing workflow steps and metadata
            output_path: Optional path to save the HTML file
        
        Returns:
            HTML content as string
        """
        if not output_path:
            output_path = self.task_dir / "workflow.html"
        
        task_title = workflow_data.get("task_name", self.task_name).replace("_", " ").title()
        app_name = workflow_data.get("app", "Application")
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{task_title} - Workflow Documentation</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .meta {{
            color: #666;
            font-size: 14px;
        }}
        .step {{
            background: white;
            padding: 25px;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .step-header {{
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}
        .step-number {{
            background: #4CAF50;
            color: white;
            padding: 5px 15px;
            border-radius: 4px;
            display: inline-block;
            margin-bottom: 10px;
        }}
        .action-type {{
            color: #666;
            text-transform: uppercase;
            font-size: 12px;
            font-weight: bold;
        }}
        .screenshot {{
            max-width: 100%;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin: 15px 0;
        }}
        .url {{
            background: #f8f8f8;
            padding: 8px 12px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 13px;
            word-break: break-all;
        }}
        .notes {{
            background: #fff9e6;
            border-left: 4px solid #ffc107;
            padding: 12px;
            margin: 10px 0;
        }}
        .summary {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{task_title}</h1>
        <div class="meta">
            <strong>Application:</strong> {app_name} | 
            <strong>Date:</strong> {datetime.now().strftime("%B %d, %Y")} | 
            <strong>Status:</strong> {workflow_data.get("status", "Completed")}
        </div>
    </div>
"""
        
        # Add each step
        steps = workflow_data.get("steps", [])
        for i, step in enumerate(steps, 1):
            step_number = step.get("step_number", i)
            action = step.get("action_type", "unknown")
            description = step.get("action_description", "No description")
            state_desc = step.get("state_description", "")
            screenshot = step.get("screenshot_filename", "")
            url = step.get("url", "")
            notes = step.get("notes", "")
            
            html_content += f"""
    <div class="step">
        <div class="step-header">
            <div class="step-number">Step {step_number}</div>
            <div class="action-type">{action}</div>
            <h2>{description}</h2>
        </div>
        <div class="url"><strong>URL:</strong> {url}</div>
        <p>{state_desc}</p>
"""
            if notes:
                html_content += f'        <div class="notes"><strong>Notes:</strong> {notes}</div>\n'
            
            if screenshot:
                html_content += f'        <img src="{screenshot}" alt="Step {step_number}" class="screenshot">\n'
            
            html_content += "    </div>\n"
        
        # Add summary
        actions = {}
        for step in steps:
            action = step.get("action_type", "unknown")
            actions[action] = actions.get(action, 0) + 1
        
        html_content += f"""
    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Total steps completed:</strong> {len(steps)}</p>
        <h3>Key Actions Performed</h3>
        <ul>
"""
        for action, count in actions.items():
            html_content += f"            <li><strong>{action.title()}:</strong> {count} time(s)</li>\n"
        
        html_content += """        </ul>
    </div>
</body>
</html>
"""
        
        # Save to file
        output_path = Path(output_path)
        with open(output_path, "w") as f:
            f.write(html_content)
        
        print(f"✅ HTML documentation saved to: {output_path}")
        return html_content

