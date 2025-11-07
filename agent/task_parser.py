"""
Task Parser - Extracts structured information from natural language task descriptions
Uses Gemini API to parse tasks like "How do I create a task in Asana?" or "How do I filter a database in Notion?"
"""
import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class TaskParser:
    """
    Parses natural language task descriptions into structured format.
    Extracts: app name, action, and context.
    """
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
    
    def parse(self, task_description: str) -> dict:
        """
        Parse task description like:
        "How do I create a task in Asana?"
        
        Returns:
        {
            'app': 'Asana',
            'app_url': 'https://asana.com/...',
            'action': 'create_task',
            'task_name': 'create_task_in_asana',
            'context': {}
        }
        """
        prompt = f"""
        Parse this task description into structured JSON format:
        "{task_description}"
        
        Extract the following information:
        1. The web application name (e.g., "Asana", "Notion")
        2. The base URL if known (e.g., "https://asana.com" for Asana, "https://www.notion.so" for Notion)
        3. The action to perform (e.g., "create_project", "filter_issues", "create_database")
        4. A sanitized task name (lowercase, underscores, no special chars)
        5. Any additional context (empty dict if none)
        
        Return ONLY valid JSON in this exact format:
        {{
            "app": "app name",
            "app_url": "base URL or empty string",
            "action": "action description",
            "task_name": "sanitized_task_name",
            "context": {{}}
        }}
        
        Do not include any explanation, only the JSON.
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
            parsed = json.loads(response_text)
            return parsed
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            print(f"Response was: {response_text}")
            raise
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            raise


if __name__ == "__main__":
    # Test the task parser
    parser = TaskParser()
    
    test_tasks = [
        "How do I create a task in Asana?",
        "How do I filter a database in Notion?",
        "How do I create a database in Notion?"
    ]
    
    print("Testing Task Parser:\n")
    for task in test_tasks:
        print(f"Task: {task}")
        try:
            result = parser.parse(task)
            print(f"Parsed: {json.dumps(result, indent=2)}")
            print()
        except Exception as e:
            print(f"Error: {e}\n")

