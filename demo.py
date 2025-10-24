import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, 
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
)

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.append(str(PROJECT_ROOT / 'src'))

from app.theme_manager import ThemeManager
from ui.widgets.navigation_list_widget import NavigationListWidget

class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TMS Control Interface")
        self.setGeometry(100, 100, 320, 480)

        template_path = PROJECT_ROOT / "assets" / "styles" / "template.qss"
        themes_dir = PROJECT_ROOT / "src" / "config"
        self.theme_manager = ThemeManager(template_path=template_path, themes_dir=themes_dir)
        self.current_theme = "dark"
        
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- Create and Populate the List Widget (with new signature) ---
        self.list_widget = NavigationListWidget()
        self.list_widget.add_item("Intensity", 80, "0 ~ 100 %", data={"key": "intensity"})
        self.list_widget.add_item("Frequency", 10, "1 ~ 20 Hz", data={"key": "frequency"})
        self.list_widget.add_item("Pulse Count", 50, "10 ~ 100", data={"key": "pulse_count"})
        self.list_widget.add_item("Repeat Times", 2, "1 ~ 3", data={"key": "repeat_times"})
        self.list_widget.setCurrentRow(0)
        
        main_layout.addWidget(self.list_widget, stretch=1)

        # --- Control Buttons ---
        # Group for Navigation
        nav_box = QVBoxLayout()
        nav_box.addWidget(QLabel("Item Navigation"))
        nav_buttons = QHBoxLayout()
        prev_button = QPushButton("Up")
        next_button = QPushButton("Down")
        nav_buttons.addWidget(prev_button)
        nav_buttons.addWidget(next_button)
        nav_box.addLayout(nav_buttons)
        main_layout.addLayout(nav_box)

        # Group for Value Editing
        edit_box = QVBoxLayout()
        edit_box.addWidget(QLabel("Value Editing (for selected item)"))
        edit_buttons = QHBoxLayout()
        decrease_button = QPushButton("- Decrease")
        increase_button = QPushButton("+ Increase")
        edit_buttons.addWidget(decrease_button)
        edit_buttons.addWidget(increase_button)
        edit_box.addLayout(edit_buttons)
        main_layout.addLayout(edit_box)
        
        # Separator Line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        theme_button = QPushButton("Toggle Theme")
        main_layout.addWidget(theme_button)
        
        self.setCentralWidget(central_widget)

        # --- Connect Signals ---
        prev_button.clicked.connect(self.list_widget.select_previous)
        next_button.clicked.connect(self.list_widget.select_next)
        theme_button.clicked.connect(self.toggle_theme)
        increase_button.clicked.connect(self.increase_selected_value)
        decrease_button.clicked.connect(self.decrease_selected_value)

        self.apply_theme(self.current_theme)

    def change_selected_value(self, amount: int):
        """Generic function to change the selected item's value."""
        current_item = self.list_widget.currentItem()
        if not current_item:
            return

        # Get the custom widget we embedded into the list item
        widget = self.list_widget.itemWidget(current_item)
        if not widget:
            return

        try:
            current_value = int(widget.get_value())
            new_value = current_value + amount
            
            # Here you would add logic to check against the bounds!
            # For this demo, we'll just change it.
            
            # Use the widget's own method to update its display
            widget.set_value(new_value)
        except (ValueError, TypeError):
            # Handle cases where the value is not a number
            print(f"Cannot change value for '{widget.get_title()}' as it's not a number.")
            
    def increase_selected_value(self):
        self.change_selected_value(1)

    def decrease_selected_value(self):
        self.change_selected_value(-1)

    def apply_theme(self, theme_name: str):
        stylesheet = self.theme_manager.generate_stylesheet(theme_name)
        if stylesheet:
            QApplication.instance().setStyleSheet(stylesheet)
            print(f"Applied '{theme_name}' theme.")

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme(self.current_theme)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())
