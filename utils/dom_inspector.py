"""
DOM inspection utility to extract interactive elements and page structure
"""
from typing import Dict, List
from bs4 import BeautifulSoup


class DOMInspector:
    """Extract actionable information from page DOM"""
    
    @staticmethod
    def extract_interactive_elements(page) -> Dict:
        """
        Extract all interactive elements from the current page
        
        Args:
            page: Playwright page object
        
        Returns:
            Dictionary containing lists of interactive elements
        """
        # Get the page HTML
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract buttons
        buttons = []
        for btn in soup.find_all(['button', 'a', 'input']):
            if btn.name == 'input' and btn.get('type') not in ['button', 'submit', 'reset']:
                continue
            
            element_info = {
                'tag': btn.name,
                'type': btn.get('type', ''),
                'text': btn.get_text(strip=True),
                'id': btn.get('id', ''),
                'class': ' '.join(btn.get('class', [])),
                'aria_label': btn.get('aria-label', ''),
                'title': btn.get('title', ''),
                'href': btn.get('href', '') if btn.name == 'a' else '',
                'disabled': btn.get('disabled') is not None
            }
            
            if element_info['text'] or element_info['id'] or element_info['aria_label']:
                buttons.append(element_info)
        
        # Extract input fields
        inputs = []
        for inp in soup.find_all(['input', 'textarea']):
            if inp.name == 'input' and inp.get('type') in ['button', 'submit', 'reset']:
                continue
            
            # Try to find associated label
            label_text = ''
            input_id = inp.get('id')
            if input_id:
                label = soup.find('label', {'for': input_id})
                if label:
                    label_text = label.get_text(strip=True)
            
            # Check if it's in a label
            if not label_text:
                parent_label = inp.find_parent('label')
                if parent_label:
                    label_text = parent_label.get_text(strip=True)
            
            element_info = {
                'tag': inp.name,
                'type': inp.get('type', 'text'),
                'name': inp.get('name', ''),
                'id': inp.get('id', ''),
                'placeholder': inp.get('placeholder', ''),
                'value': inp.get('value', ''),
                'label': label_text,
                'required': inp.get('required') is not None,
                'disabled': inp.get('disabled') is not None,
                'aria_label': inp.get('aria-label', '')
            }
            
            inputs.append(element_info)
        
        # Extract select/dropdown elements
        selects = []
        for sel in soup.find_all('select'):
            options = [opt.get_text(strip=True) for opt in sel.find_all('option')]
            
            element_info = {
                'tag': 'select',
                'name': sel.get('name', ''),
                'id': sel.get('id', ''),
                'options': options,
                'required': sel.get('required') is not None,
                'disabled': sel.get('disabled') is not None
            }
            
            selects.append(element_info)
        
        # Extract modals/dialogs
        modals = []
        for modal in soup.find_all(['div', 'dialog'], class_=lambda x: x and any(term in str(x).lower() for term in ['modal', 'dialog', 'popup'])):
            # Check if visible (not display:none)
            style = modal.get('style', '')
            if 'display: none' in style or 'display:none' in style:
                continue
            
            modal_info = {
                'id': modal.get('id', ''),
                'class': ' '.join(modal.get('class', [])),
                'text_content': modal.get_text(strip=True)[:200]  # First 200 chars
            }
            modals.append(modal_info)
        
        return {
            'buttons': buttons[:20],  # Limit to first 20
            'inputs': inputs[:20],
            'selects': selects[:10],
            'modals': modals[:5],
            'total_buttons': len(buttons),
            'total_inputs': len(inputs),
            'total_selects': len(selects),
            'total_modals': len(modals)
        }
    
    @staticmethod
    def format_for_prompt(elements_data: Dict) -> str:
        """
        Format extracted DOM elements into a readable string for LLM prompt
        
        Args:
            elements_data: Dictionary from extract_interactive_elements
        
        Returns:
            Formatted string describing the page elements
        """
        parts = []
        
        # Buttons
        if elements_data['buttons']:
            parts.append("BUTTONS/LINKS:")
            for idx, btn in enumerate(elements_data['buttons'], 1):
                btn_desc = f"  {idx}. "
                if btn['text']:
                    btn_desc += f'"{btn["text"]}"'
                elif btn['aria_label']:
                    btn_desc += f'"{btn["aria_label"]}"'
                elif btn['id']:
                    btn_desc += f'[id={btn["id"]}]'
                
                if btn['disabled']:
                    btn_desc += " (DISABLED)"
                if btn['href']:
                    btn_desc += f" -> {btn['href']}"
                
                parts.append(btn_desc)
            
            if elements_data['total_buttons'] > len(elements_data['buttons']):
                parts.append(f"  ... and {elements_data['total_buttons'] - len(elements_data['buttons'])} more buttons")
        
        # Input fields
        if elements_data['inputs']:
            parts.append("\nINPUT FIELDS:")
            for idx, inp in enumerate(elements_data['inputs'], 1):
                inp_desc = f"  {idx}. "
                if inp['label']:
                    inp_desc += f'Label: "{inp["label"]}"'
                elif inp['placeholder']:
                    inp_desc += f'Placeholder: "{inp["placeholder"]}"'
                elif inp['name']:
                    inp_desc += f'Name: {inp["name"]}'
                elif inp['id']:
                    inp_desc += f'ID: {inp["id"]}'
                
                inp_desc += f' | Type: {inp["type"]}'
                
                if inp['value']:
                    inp_desc += f' | Current value: "{inp["value"]}"'
                else:
                    inp_desc += " | EMPTY"
                
                if inp['required']:
                    inp_desc += " | REQUIRED"
                if inp['disabled']:
                    inp_desc += " | DISABLED"
                
                parts.append(inp_desc)
            
            if elements_data['total_inputs'] > len(elements_data['inputs']):
                parts.append(f"  ... and {elements_data['total_inputs'] - len(elements_data['inputs'])} more inputs")
        
        # Selects
        if elements_data['selects']:
            parts.append("\nDROPDOWNS/SELECTS:")
            for idx, sel in enumerate(elements_data['selects'], 1):
                sel_desc = f"  {idx}. "
                if sel['name']:
                    sel_desc += f'Name: {sel["name"]}'
                elif sel['id']:
                    sel_desc += f'ID: {sel["id"]}'
                
                if sel['options']:
                    sel_desc += f' | Options: {", ".join(sel["options"][:5])}'
                    if len(sel['options']) > 5:
                        sel_desc += f' ... and {len(sel["options"]) - 5} more'
                
                parts.append(sel_desc)
        
        # Modals
        if elements_data['modals']:
            parts.append("\nVISIBLE MODALS/DIALOGS:")
            for idx, modal in enumerate(elements_data['modals'], 1):
                modal_desc = f"  {idx}. "
                if modal['id']:
                    modal_desc += f'ID: {modal["id"]} | '
                modal_desc += f'Content preview: "{modal["text_content"][:100]}..."'
                parts.append(modal_desc)
        
        if not parts:
            return "No interactive elements found in the DOM."
        
        return "\n".join(parts)

