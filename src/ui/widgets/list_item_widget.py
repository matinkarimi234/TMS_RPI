from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel

class ListItemWidget(QWidget):
    """
    A custom widget for a list item with a more complex layout.
    It displays a title, a dynamic value, and a bounds/range hint.
    - Title (Top-Left)
    - Value (Top-Right)
    - Bounds (Bottom-Left)
    """
    def __init__(self, title: str, value, bounds: str, parent=None):
        super().__init__(parent)

        # --- Create the three labels ---
        self.title_label = QLabel(title)
        self.value_label = QLabel(str(value))
        self.bounds_label = QLabel(bounds)

        # --- Set object names for QSS styling ---
        self.title_label.setObjectName("ListItemTitleLabel")
        self.value_label.setObjectName("ListItemValueLabel")
        self.bounds_label.setObjectName("ListItemBoundsLabel")
        
        # The value should be right-aligned and vertically centered
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # --- Use a GridLayout for precise positioning ---
        layout = QGridLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(5)

        # Add widgets to the grid: widget, row, column
        layout.addWidget(self.title_label, 0, 0)
        layout.addWidget(self.value_label, 0, 1)
        layout.addWidget(self.bounds_label, 1, 0)
        
        # Make the first column expand, pushing the value to the right
        layout.setColumnStretch(0, 1) 
        layout.setColumnStretch(1, 0)

        self.setLayout(layout)

    def set_value(self, new_value):
        """
        Crucial method to allow external code (like the main window)
        to update the value displayed by this widget.
        """
        self.value_label.setText(str(new_value))

    def get_value(self) -> str:
        """Helper to retrieve the current value text."""
        return self.value_label.text()
    
    def get_title(self) -> str:
        return self.title_label.text()
        
    def get_bounds(self) -> str:
        return self.bounds_label.text()

    def sizeHint(self) -> QSize:
        # A slightly taller hint might be better for the new layout
        return QSize(200, 75)
