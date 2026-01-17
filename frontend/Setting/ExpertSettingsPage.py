from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QLayout
from PyQt5.QtWidgets import QVBoxLayout
from qfluentwidgets import FluentWindow
from qfluentwidgets import SingleDirectionScrollArea

from base.Base import Base
from module.Config import Config
from module.Localizer.Localizer import Localizer
from widget.ComboBoxCard import ComboBoxCard
from widget.SpinCard import SpinCard
from widget.SwitchButtonCard import SwitchButtonCard

class ExpertSettingsPage(QWidget, Base):

    def __init__(self, text: str, window: FluentWindow) -> None:
        super().__init__(window)
        self.setObjectName(text.replace(" ", "-"))

        # 载入并保存默认配置
        config = Config().load().save()

        # 设置容器
        self.root = QVBoxLayout(self)
        self.root.setSpacing(8)
        self.root.setContentsMargins(6, 24, 6, 24) # 左、上、右、下

        # 创建滚动区域的内容容器
        scroll_area_vbox_widget = QWidget()
        scroll_area_vbox = QVBoxLayout(scroll_area_vbox_widget)
        scroll_area_vbox.setContentsMargins(18, 0, 18, 0)

        # 创建滚动区域
        scroll_area = SingleDirectionScrollArea(orient = Qt.Orientation.Vertical)
        scroll_area.setWidget(scroll_area_vbox_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.enableTransparentBackground()

        # 将滚动区域添加到父布局
        self.root.addWidget(scroll_area)

        # 添加控件
        self.add_widget_preceding_lines_threshold(scroll_area_vbox, config, window)
        self.add_widget_preceding_disable_on_local(scroll_area_vbox, config, window)
        self.add_widget_clean_ruby(scroll_area_vbox, config, window)
        self.add_widget_deduplication_in_trans(scroll_area_vbox, config, window)
        self.add_widget_deduplication_in_bilingual(scroll_area_vbox, config, window)
        self.add_widget_write_translated_name_fields_to_file(scroll_area_vbox, config, window)
        self.add_widget_result_checker_retry_count_threshold(scroll_area_vbox, config, window)
        self.add_widget_request_max_retries(scroll_area_vbox, config, window)
        self.add_widget_stream_stall_timeout_seconds(scroll_area_vbox, config, window)
        self.add_widget_stream_first_chunk_timeout_seconds(scroll_area_vbox, config, window)
        self.add_widget_stream_retry_attempts(scroll_area_vbox, config, window)
        self.add_widget_stream_retry_backoff_seconds(scroll_area_vbox, config, window)
        self.add_widget_preceding_only_first_round(scroll_area_vbox, config, window)
        self.add_widget_rolling_split_retry_enable(scroll_area_vbox, config, window)
        self.add_widget_rolling_split_max_depth(scroll_area_vbox, config, window)
        self.add_widget_rolling_split_min_input_token_threshold(scroll_area_vbox, config, window)
        self.add_widget_rolling_split_halve_preceding_threshold(scroll_area_vbox, config, window)
        self.add_widget_rolling_split_right_preceding_mode(scroll_area_vbox, config, window)

        # 填充
        scroll_area_vbox.addStretch(1)

    # 参考上文行数阈值
    def add_widget_preceding_lines_threshold(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(0, 9999999)
            widget.get_spin_box().setValue(config.preceding_lines_threshold)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.preceding_lines_threshold = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_preceding_lines_threshold,
                description = Localizer.get().expert_settings_page_preceding_lines_threshold_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    # 本地接口禁用参考上文
    def add_widget_preceding_disable_on_local(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.enable_preceding_on_local
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.enable_preceding_on_local = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_preceding_disable_on_local,
                description = Localizer.get().expert_settings_page_preceding_disable_on_local_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # 清理原文中的注音文本
    def add_widget_clean_ruby(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.clean_ruby
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.clean_ruby = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_clean_ruby,
                description = Localizer.get().expert_settings_page_clean_ruby_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # T++ 项目文件中对重复文本去重
    def add_widget_deduplication_in_trans(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.deduplication_in_trans
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.deduplication_in_trans = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_deduplication_in_trans,
                description = Localizer.get().expert_settings_page_deduplication_in_trans_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # 双语输出文件中原文与译文一致的文本只输出一次
    def add_widget_deduplication_in_bilingual(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.deduplication_in_bilingual
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.deduplication_in_bilingual = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_deduplication_in_bilingual,
                description = Localizer.get().expert_settings_page_deduplication_in_bilingual_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # 将姓名字段译文写入译文文件
    def add_widget_write_translated_name_fields_to_file(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.write_translated_name_fields_to_file
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.write_translated_name_fields_to_file = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_write_translated_name_fields_to_file,
                description = Localizer.get().expert_settings_page_write_translated_name_fields_to_file_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # 自动移除前后缀代码段
    def add_widget_auto_process_prefix_suffix_preserved_text(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.auto_process_prefix_suffix_preserved_text
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.auto_process_prefix_suffix_preserved_text = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_auto_process_prefix_suffix_preserved_text,
                description = Localizer.get().expert_settings_page_auto_process_prefix_suffix_preserved_text_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    # 结果检查 - 重试次数达到阈值
    def add_widget_result_checker_retry_count_threshold(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.result_checker_retry_count_threshold
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.result_checker_retry_count_threshold = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_result_checker_retry_count_threshold,
                description = Localizer.get().expert_settings_page_result_checker_retry_count_threshold_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    def add_widget_request_max_retries(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(0, 9999999)
            widget.get_spin_box().setValue(config.request_max_retries)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.request_max_retries = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_request_max_retries_title,
                description = Localizer.get().expert_settings_page_request_max_retries_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_stream_stall_timeout_seconds(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(1, 9999999)
            widget.get_spin_box().setValue(config.stream_stall_timeout_seconds)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.stream_stall_timeout_seconds = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_stream_stall_timeout_seconds_title,
                description = Localizer.get().expert_settings_page_stream_stall_timeout_seconds_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_stream_first_chunk_timeout_seconds(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(0, 9999999)
            widget.get_spin_box().setValue(config.stream_first_chunk_timeout_seconds)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.stream_first_chunk_timeout_seconds = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_stream_first_chunk_timeout_seconds_title,
                description = Localizer.get().expert_settings_page_stream_first_chunk_timeout_seconds_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_stream_retry_attempts(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(1, 9999999)
            widget.get_spin_box().setValue(config.stream_retry_attempts)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.stream_retry_attempts = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_stream_retry_attempts_title,
                description = Localizer.get().expert_settings_page_stream_retry_attempts_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_stream_retry_backoff_seconds(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(0, 9999999)
            widget.get_spin_box().setValue(config.stream_retry_backoff_seconds)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.stream_retry_backoff_seconds = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_stream_retry_backoff_seconds_title,
                description = Localizer.get().expert_settings_page_stream_retry_backoff_seconds_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_preceding_only_first_round(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.preceding_only_first_round
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.preceding_only_first_round = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_preceding_only_first_round_title,
                description = Localizer.get().expert_settings_page_preceding_only_first_round_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    def add_widget_rolling_split_retry_enable(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.rolling_split_retry_enable
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.rolling_split_retry_enable = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_rolling_split_retry_enable_title,
                description = Localizer.get().expert_settings_page_rolling_split_retry_enable_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    def add_widget_rolling_split_max_depth(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(1, 9999999)
            widget.get_spin_box().setValue(config.rolling_split_max_depth)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.rolling_split_max_depth = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_rolling_split_max_depth_title,
                description = Localizer.get().expert_settings_page_rolling_split_max_depth_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_rolling_split_min_input_token_threshold(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SpinCard) -> None:
            widget.get_spin_box().setRange(0, 9999999)
            widget.get_spin_box().setValue(config.rolling_split_min_input_token_threshold)

        def value_changed(widget: SpinCard) -> None:
            config = Config().load()
            config.rolling_split_min_input_token_threshold = widget.get_spin_box().value()
            config.save()

        parent.addWidget(
            SpinCard(
                title = Localizer.get().expert_settings_page_rolling_split_min_input_token_threshold_title,
                description = Localizer.get().expert_settings_page_rolling_split_min_input_token_threshold_desc,
                init = init,
                value_changed = value_changed,
            )
        )

    def add_widget_rolling_split_halve_preceding_threshold(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        def init(widget: SwitchButtonCard) -> None:
            widget.get_switch_button().setChecked(
                config.rolling_split_halve_preceding_threshold
            )

        def checked_changed(widget: SwitchButtonCard) -> None:
            config = Config().load()
            config.rolling_split_halve_preceding_threshold = widget.get_switch_button().isChecked()
            config.save()

        parent.addWidget(
            SwitchButtonCard(
                title = Localizer.get().expert_settings_page_rolling_split_halve_preceding_threshold_title,
                description = Localizer.get().expert_settings_page_rolling_split_halve_preceding_threshold_desc,
                init = init,
                checked_changed = checked_changed,
            )
        )

    def add_widget_rolling_split_right_preceding_mode(self, parent: QLayout, config: Config, window: FluentWindow) -> None:

        items = [
            Localizer.get().expert_settings_page_rolling_split_right_preceding_mode_item_tail_context,
            Localizer.get().expert_settings_page_rolling_split_right_preceding_mode_item_left_head,
        ]

        def init(widget: ComboBoxCard) -> None:
            mode = str(config.rolling_split_right_preceding_mode or "").strip()
            idx = 1 if mode == "left_head" else 0
            widget.get_combo_box().setCurrentIndex(idx)

        def current_changed(widget: ComboBoxCard) -> None:
            idx = widget.get_combo_box().currentIndex()
            mode = "left_head" if idx == 1 else "tail_context"
            config = Config().load()
            config.rolling_split_right_preceding_mode = mode
            config.save()

        parent.addWidget(
            ComboBoxCard(
                title = Localizer.get().expert_settings_page_rolling_split_right_preceding_mode_title,
                description = Localizer.get().expert_settings_page_rolling_split_right_preceding_mode_desc,
                items = items,
                init = init,
                current_changed = current_changed,
            )
        )
