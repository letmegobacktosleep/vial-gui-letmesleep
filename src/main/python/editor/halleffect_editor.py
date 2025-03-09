# SPDX-License-Identifier: GPL-2.0-or-later
import json

from PyQt5.QtWidgets import QHBoxLayout, QGridLayout, QLabel, QTextEdit, QVBoxLayout, QMessageBox, QWidget, QTabWidget, QSpinBox, QDoubleSpinBox
from PyQt5.QtCore import Qt, pyqtSignal, QObject

from any_keycode_dialog import AnyKeycodeDialog
from editor.basic_editor import BasicEditor
from widgets.keyboard_widget import KeyboardWidget
from keycodes.keycodes import Keycode
from widgets.square_button import SquareButton
from tabbed_keycodes import TabbedKeycodes, keycode_filter_masked
from util import tr, KeycodeDisplay
from vial_device import VialKeyboard

class GenericOption(QObject):
    changed = pyqtSignal()

    def __init__(self, title, container, row):
        super().__init__()

        self.row = row
        self.container = container

        self.lbl = QLabel(title)
        self.container.addWidget(self.lbl, self.row, 0)

    def delete(self):
        self.lbl.hide()
        self.lbl.deleteLater()

    def on_change(self):
        self.changed.emit()


class IntegerOption(GenericOption):
    def __init__(self, title, container, row, min_val=0, max_val=1000):
        super().__init__(title, container, row)

        self.spinbox = QSpinBox()
        self.spinbox.setMinimum(min_val)
        self.spinbox.setMaximum(max_val)
        self.spinbox.valueChanged.connect(self.on_change)
        self.container.addWidget(self.spinbox, self.row, 1)

    def value(self):
        return self.spinbox.value()

    def set_value(self, value):
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(value)
        self.spinbox.blockSignals(False)

    def delete(self):
        super().delete()
        self.spinbox.hide()
        self.spinbox.deleteLater()


class DoubleOption(GenericOption):
    def __init__(self, title, container, row, min_val=-100.0, max_val=100.0, decimals=16):
        super().__init__(title, container, row)

        self.spinbox = QDoubleSpinBox()
        self.spinbox.setDecimals(decimals)
        self.spinbox.setMinimum(min_val)
        self.spinbox.setMaximum(max_val)
        self.spinbox.setSingleStep(0.00000001)
        self.spinbox.valueChanged.connect(self.on_change)
        self.container.addWidget(self.spinbox, self.row, 1)

    def value(self):
        return self.spinbox.value()

    def set_value(self, value):
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(value)
        self.spinbox.blockSignals(False)

    def delete(self):
        super().delete()
        self.spinbox.hide()
        self.spinbox.deleteLater()

class ClickableWidget(QWidget):

    clicked = pyqtSignal()

    def mousePressEvent(self, evt):
        super().mousePressEvent(evt)
        self.clicked.emit()


class HallEffectEditor(BasicEditor):

    def __init__(self, layout_editor):
        super().__init__()

        self.layout_editor = layout_editor
        self.device = None  # Will be set in rebuild()
        self.keyboard = None  # Store keyboard reference

        self.tabs_widget = QTabWidget()

        self.addWidget(self.tabs_widget)

    def populate_tabs(self):
        """Populate the editor with only the tabs from vial.json."""
        self.tabs_widget.clear()  # Reset tabs before repopulating

        available_tabs = self.keyboard.hall_effect_tabs if self.keyboard else []

        tab_mapping = {
            "Key Config": self.create_key_config_tab,
            "Displacement": self.create_displacement_tab,
            "Joystick": self.create_joystick_tab,
            "Calibration": self.create_calibration_tab,
        }

        for tab_name in available_tabs:
            if tab_name in tab_mapping:
                tab_widget = tab_mapping[tab_name]()
                self.tabs_widget.addTab(tab_widget, tr("HallEffectEditor", tab_name))

    def create_key_config_tab(self):
        tab = QWidget()
        keymap_layout = QVBoxLayout()

        # Ensure container is created only if Key Config is present
        self.container = KeyboardWidget(self.layout_editor)
        self.container.clicked.connect(self.on_key_clicked)
        self.container.deselected.connect(self.on_key_deselected)

        # Zoom buttons (top-right, compact)
        zoom_layout = QVBoxLayout()
        zoom_layout.setSpacing(2)

        zoom_in_button = SquareButton("+")
        zoom_in_button.setFocusPolicy(Qt.NoFocus)
        zoom_in_button.setCheckable(False)
        zoom_in_button.clicked.connect(lambda: self.adjust_size(False))

        zoom_out_button = SquareButton("-")
        zoom_out_button.setFocusPolicy(Qt.NoFocus)
        zoom_out_button.setCheckable(False)
        zoom_out_button.clicked.connect(lambda: self.adjust_size(True))

        zoom_layout.addWidget(zoom_in_button)
        zoom_layout.addWidget(zoom_out_button)

        # Align zoom buttons in the top-right
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addStretch()
        top_bar_layout.addLayout(zoom_layout)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)

        keymap_layout.addLayout(top_bar_layout)  
        keymap_layout.addWidget(self.container, alignment=Qt.AlignCenter)

        # Integer Options
        keymap_option_labels = ["Mode", "Actuation Point", "Deadzone", "Up Sensitivity", "Down Sensitivity"]
        keymap_options_layout = QGridLayout()

        self.keymap_int_options = []
        for i, label in enumerate(keymap_option_labels):
            opt = IntegerOption(label, keymap_options_layout, i, min_val=0, max_val=255)
            opt.changed.connect(self.on_option_changed)
            self.keymap_int_options.append(opt)

        # Wrap options inside a centered vertical layout
        options_layout = QVBoxLayout()
        options_layout.addLayout(keymap_options_layout)
        options_layout.setAlignment(Qt.AlignCenter)

        # Mode Description Text Box
        mode_description = QLabel(
            "Mode\n\n"
            "0 = Normal Actuation\n\n"
            "2 = Rapid Trigger\n\n"
            "5 = Inverted Actuation\n\n"
            "8 = Inverted Rapid Trigger\n\n"
            "10 - 17 = DKS 1 - 8"
        )
        mode_description.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        mode_description.setStyleSheet("border: none; padding-left: 10px;")

        # Horizontal layout for options and text box
        options_and_text_layout = QHBoxLayout()
        options_and_text_layout.addLayout(options_layout)
        options_and_text_layout.addWidget(mode_description)
        options_and_text_layout.setAlignment(Qt.AlignCenter)

        keymap_layout.addLayout(options_and_text_layout)

        # Row/Col Display Label
        bottom_layout = QHBoxLayout()
        self.key_info_label = QLabel("Key: None")
        self.key_info_label.setAlignment(Qt.AlignCenter)
        self.key_info_label.setStyleSheet("padding: 2px;")

        bottom_layout.addWidget(self.key_info_label, alignment=Qt.AlignCenter)
        bottom_layout.setContentsMargins(0, 2, 0, 2)
        keymap_layout.addLayout(bottom_layout)

        tab.setLayout(keymap_layout)
        return tab
    
    def create_displacement_tab(self):
        return self.create_generic_options_tab("Displacement")

    def create_joystick_tab(self):
        return self.create_generic_options_tab("Joystick")

    def create_calibration_tab(self):
        return self.create_generic_options_tab("Calibration")

    def create_generic_options_tab(self, tab_name):
        tab = QWidget()
        layout = QVBoxLayout()

        option_labels = ["Parameter A", "Parameter B", "Parameter C", "Parameter D", "Max Input", "Max Output"]
        options_grid = QGridLayout()

        for i in range(4):  # Double options
            opt = DoubleOption(option_labels[i], options_grid, i)
            opt.changed.connect(self.on_option_changed)

        for i in range(2):  # Integer options
            opt = IntegerOption(option_labels[i + 4], options_grid, i + 4)
            opt.changed.connect(self.on_option_changed)

        centered_layout = QVBoxLayout()
        centered_layout.addLayout(options_grid)
        centered_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(centered_layout)
        tab.setLayout(layout)
        return tab

    def on_option_changed(self):
        print("Option changed!")

    def on_empty_space_clicked(self):
        self.container.deselect()
        self.container.update()

    def on_keycode_changed(self, code):
        self.set_key(code)

    def adjust_size(self, minus):
        if minus:
            self.container.set_scale(self.container.get_scale() - 0.1)
        else:
            self.container.set_scale(self.container.get_scale() + 0.1)

        self.refresh_key_display()

    def rebuild(self, device):
        super().rebuild(device)
        self.device = device

        if self.valid():
            self.keyboard = device.keyboard
            self.populate_tabs()  # Ensure tabs are updated when switching device

            # Ensure Key Config tab is active before using container
            if "Key Config" in self.keyboard.hall_effect_tabs:
                self.container.set_keys(self.keyboard.keys, [])
                self.current_layer = 0
                self.on_layout_changed()
                self.refresh_key_display()
            
        else:
            self.tabs_widget.clear()  # Remove all tabs if Hall Effect isn't supported

        self.tabs_widget.setEnabled(self.valid())

    def valid(self):
        """Determine if HallEffectEditor should be visible."""
        return isinstance(self.device, VialKeyboard) and self.device.keyboard.has_hall_effect

    def on_dlg_finished(self, res):
        if res > 0:
            self.on_keycode_changed(self.dlg.value)

    def code_for_widget(self, widget):
        if widget.desc.row is not None:
            return self.keyboard.layout[(self.current_layer, widget.desc.row, widget.desc.col)]

    def refresh_key_display(self):
        """ Refresh text on key widgets to display updated keymap """
        if "Key Config" in (self.keyboard.hall_effect_tabs if self.keyboard else []):
            self.container.update_layout()

            for widget in self.container.widgets:
                code = self.code_for_widget(widget)
                KeycodeDisplay.display_keycode(widget, code)

            self.container.update()
            self.container.updateGeometry()


    def switch_layer(self, idx):
        self.container.deselect()
        self.current_layer = idx
        self.refresh_key_display()

    def set_key(self, keycode):
        """ Change currently selected key to provided keycode """

        if self.container.active_key is None:
            return

        self.set_key_matrix(keycode)

        self.container.select_next()

    def set_key_matrix(self, keycode):
        l, r, c = self.current_layer, self.container.active_key.desc.row, self.container.active_key.desc.col

        if r >= 0 and c >= 0:
            # if masked, ensure that this is a byte-sized keycode
            if self.container.active_mask:
                if not Keycode.is_basic(keycode):
                    return
                kc = Keycode.find_outer_keycode(self.keyboard.layout[(l, r, c)])
                if kc is None:
                    return
                keycode = kc.qmk_id.replace("(kc)", "({})".format(keycode))

            self.keyboard.set_key(l, r, c, keycode)
            self.refresh_key_display()

    def on_key_clicked(self):
        """Called when a key on the keyboard is clicked."""
        self.refresh_key_display()
        if self.container.active_key:
            row = self.container.active_key.desc.row
            col = self.container.active_key.desc.col
            if row is not None and col is not None:
                self.key_info_label.setText(f"Key: Row {row}, Col {col}")
            else:
                self.key_info_label.setText("Key: None")


    def on_key_deselected(self):
        pass  # No longer need to reset TabbedKeycodes

    def on_layout_changed(self):
        if self.keyboard is None:
            return

        self.refresh_key_display()
        self.keyboard.set_layout_options(self.layout_editor.pack())

    def on_keymap_override(self):
        self.refresh_key_display()
