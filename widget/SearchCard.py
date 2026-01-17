import re
from typing import Callable
from typing import Tuple

from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import CaptionLabel
from qfluentwidgets import CardWidget
from qfluentwidgets import CheckBox
from qfluentwidgets import FluentIcon
from qfluentwidgets import LineEdit
from qfluentwidgets import TransparentPushButton

from module.Localizer.Localizer import Localizer

class SearchCard(CardWidget):

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        # 设置容器
        self.setBorderRadius(4)
        self.root = QHBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16) # 左、上、右、下

        # 添加控件
        self.line_edit = LineEdit()
        self.line_edit.setFixedWidth(256)
        self.line_edit.setPlaceholderText(Localizer.get().placeholder)
        self.line_edit.setClearButtonEnabled(True)
        self.root.addWidget(self.line_edit)

        self.regex_checkbox = CheckBox(Localizer.get().search_regex_btn)
        self.regex_checkbox.setToolTip(Localizer.get().search_regex_off)
        self.regex_checkbox.stateChanged.connect(self._update_regex_tooltip)
        self.root.addWidget(self.regex_checkbox)

        self.prev = TransparentPushButton(self)
        self.prev.setIcon(FluentIcon.UP)
        self.prev.setText(Localizer.get().search_prev)
        self.root.addWidget(self.prev)

        self.next = TransparentPushButton(self)
        self.next.setIcon(FluentIcon.SCROLL)
        self.next.setText(Localizer.get().next)
        self.root.addWidget(self.next)

        self.match_info_label = CaptionLabel(Localizer.get().search_no_result, self)
        self.root.addWidget(self.match_info_label)

        # 填充
        self.root.addStretch(1)

        # 返回
        self.back = TransparentPushButton(self)
        self.back.setIcon(FluentIcon.EMBED)
        self.back.setText(Localizer.get().back)
        self.root.addWidget(self.back)

    def on_next_clicked(self, clicked: Callable) -> None:
        self.next.clicked.connect(lambda: clicked(self))

    def on_prev_clicked(self, clicked: Callable) -> None:
        self.prev.clicked.connect(lambda: clicked(self))

    def on_back_clicked(self, clicked: Callable) -> None:
        self.back.clicked.connect(lambda: clicked(self))

    def on_search_triggered(self, triggered: Callable) -> None:
        self.line_edit.returnPressed.connect(lambda: triggered(self))

    def get_line_edit(self) -> LineEdit:
        return self.line_edit

    def _update_regex_tooltip(self) -> None:
        if self.regex_checkbox.isChecked():
            self.regex_checkbox.setToolTip(Localizer.get().search_regex_on)
        else:
            self.regex_checkbox.setToolTip(Localizer.get().search_regex_off)

    def get_keyword(self) -> str:
        return self.line_edit.text().strip()

    def is_regex_mode(self) -> bool:
        return self.regex_checkbox.isChecked()

    def validate_regex(self) -> Tuple[bool, str]:
        try:
            re.compile(self.get_keyword(), flags=re.IGNORECASE)
            return True, ""
        except re.error as e:
            return False, str(e)

    def set_match_info(self, current: int, total: int) -> None:
        if total <= 0:
            self.match_info_label.setText(Localizer.get().search_no_result)
            return None
        self.match_info_label.setText(Localizer.get().search_match_info.format(current=current, total=total))

    def clear_match_info(self) -> None:
        self.set_match_info(0, 0)
