import json
from pathlib import Path

class ThemeManager:
    """
    Manages loading and applying themes by combining a QSS template
    with color values from JSON configuration files.
    """
    def __init__(self, template_path: Path, themes_dir: Path):
        self.template_path = template_path
        self.themes_dir = themes_dir
        
        try:
            self.template_content = self.template_path.read_text()
        except FileNotFoundError:
            raise RuntimeError(f"Theme template not found at {self.template_path}")

    def generate_stylesheet(self, theme_name: str) -> str:
        """
        Generates a complete QSS string for a given theme name (e.g., 'dark').
        """
        theme_config_path = self.themes_dir / f"{theme_name}_theme.json"
        
        try:
            theme_data = json.loads(theme_config_path.read_text())
        except FileNotFoundError:
            print(f"Warning: Theme config for '{theme_name}' not found at '{theme_config_path}'.")
            return ""
        except json.JSONDecodeError as e:
            print(f"Error: Could not parse theme file '{theme_config_path}'. Invalid JSON: {e}")
            return ""

        processed_stylesheet = self.template_content
        for key, value in theme_data.items():
            placeholder = f"{{{{{key}}}}}"
            processed_stylesheet = processed_stylesheet.replace(placeholder, value)
            
        return processed_stylesheet
