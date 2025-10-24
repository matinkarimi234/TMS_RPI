from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from .list_item_widget import ListItemWidget

class NavigationListWidget(QListWidget):
    """
    A QListWidget container for ListItemWidgets, allowing GPIO-style navigation.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.setObjectName("NavigationListWidget")

    # --- MODIFIED SIGNATURE HERE ---
    def add_item(self, title: str, value, bounds: str, data=None):
        # Pass all three arguments to the custom widget
        custom_widget = ListItemWidget(title, value, bounds)
        item = QListWidgetItem(self)
        item.setSizeHint(custom_widget.sizeHint())
        
        self.addItem(item)
        self.setItemWidget(item, custom_widget)
        
        if data:
            item.setData(Qt.ItemDataRole.UserRole, data)
    
    # ... (select_next and select_previous methods are unchanged) ...
    def select_next(self):
        current_row = self.currentRow()
        next_row = current_row + 1
        if next_row >= self.count():
            next_row = 0
        self.setCurrentRow(next_row)

    def select_previous(self):
        current_row = self.currentRow()
        prev_row = current_row - 1
        if prev_row < 0:
            prev_row = self.count() - 1
        self.setCurrentRow(prev_row)
