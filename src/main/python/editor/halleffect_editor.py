# SPDX-License-Identifier: GPL-2.0-or-later
import json

from PyQt5.QtWidgets import QHBoxLayout, QGridLayout, QLabel, QTextEdit, QVBoxLayout, QMessageBox, QWidget, QTabWidget, QSpinBox, QDoubleSpinBox
from PyQt5.QtCore import Qt, pyqtSignal, QObject

from any_keycode_dialog import AnyKeycodeDialog
from editor.basic_editor import BasicEditor
from widgets.keyboard_widget import KeyboardWidget, EncoderWidget
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
        self.tabs_widget = QTabWidget()  # Create tab widget

        # Populate the tabs dynamically
        self.populate_tabs()

        # Add the tab widget to the main layout
        self.addWidget(self.tabs_widget)

        self.device = None
        KeycodeDisplay.notify_keymap_override(self)

    def populate_tabs(self):
        """Populate the QTabWidget with the Keymap Editor and three option tabs."""

        # --- Keymap Editor Tab ---
        keymap_tab = QWidget()
        keymap_layout = QVBoxLayout()

        # Zoom buttons (compact, top-right)
        zoom_layout = QVBoxLayout()  # Stack vertically without extra padding
        zoom_layout.setSpacing(2)  # Reduce space between buttons

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

        # Align zoom buttons in the top-right without taking extra space
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addStretch()  # Push buttons to the right
        top_bar_layout.addLayout(zoom_layout)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)  # Remove extra margins

        # Keyboard
        self.container = KeyboardWidget(self.layout_editor)
        self.container.clicked.connect(self.on_key_clicked)
        self.container.deselected.connect(self.on_key_deselected)

        keymap_layout.addLayout(top_bar_layout)  # Add zoom buttons at the very top
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
        keymap_tab.setLayout(keymap_layout)
        self.tabs_widget.addTab(keymap_tab, tr("HallEffectEditor", "Key Config"))

        # Row/Col Display Label
        bottom_layout = QHBoxLayout()

        self.key_info_label = QLabel("Key: None")  # Default text
        self.key_info_label.setAlignment(Qt.AlignCenter)
        self.key_info_label.setStyleSheet("padding: 2px;")  # Reduce extra space

        bottom_layout.addWidget(self.key_info_label, alignment=Qt.AlignCenter)
        bottom_layout.setContentsMargins(0, 2, 0, 2)  # Reduce margins
        keymap_layout.addLayout(bottom_layout)

        # --- Define Tab Names ---
        tab_names = ["Displacement", "Joystick", "Calibration"]

        # --- Define Option Names ---
        option_labels = ["Parameter A", "Parameter B", "Parameter C", "Parameter D", "Max Input", "Max Output"]

        # --- Create Three Centered Option Tabs ---
        for i, tab_name in enumerate(tab_names):
            options_tab = QWidget()

            options_grid = QGridLayout()
            for j in range(4):
                opt = DoubleOption(option_labels[j], options_grid, j)
                opt.changed.connect(self.on_option_changed)

            for j in range(2):
                opt = IntegerOption(option_labels[j + 4], options_grid, j + 4)
                opt.changed.connect(self.on_option_changed)

            # Wrap grid inside a centered QVBoxLayout
            centered_layout = QVBoxLayout()
            centered_layout.addLayout(options_grid)
            centered_layout.setAlignment(Qt.AlignCenter)

            options_tab.setLayout(centered_layout)
            self.tabs_widget.addTab(options_tab, tr("HallEffectEditor", tab_name))

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
        if self.valid():
            self.keyboard = device.keyboard

            # get number of layers
            self.container.set_keys(self.keyboard.keys, self.keyboard.encoders)

            self.current_layer = 0
            self.on_layout_changed()

            self.refresh_key_display()
        self.container.setEnabled(self.valid())

    def valid(self):
        return isinstance(self.device, VialKeyboard)

    def save_layout(self):
        return self.keyboard.save_layout()

    def restore_layout(self, data):
        if json.loads(data.decode("utf-8")).get("uid") != self.keyboard.keyboard_id:
            ret = QMessageBox.question(self.widget(), "",
                                       tr("HallEffectEditor", "Saved keymap belongs to a different keyboard,"
                                                          " are you sure you want to continue?"),
                                       QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.keyboard.restore_layout(data)
        self.refresh_key_display()

    def on_any_keycode(self):
        if self.container.active_key is None:
            return
        current_code = self.code_for_widget(self.container.active_key)
        if self.container.active_mask:
            kc = Keycode.find_inner_keycode(current_code)
            current_code = kc.qmk_id

        self.dlg = AnyKeycodeDialog(current_code)
        self.dlg.finished.connect(self.on_dlg_finished)
        self.dlg.setModal(True)
        self.dlg.show()

    def on_dlg_finished(self, res):
        if res > 0:
            self.on_keycode_changed(self.dlg.value)

    def code_for_widget(self, widget):
        if widget.desc.row is not None:
            return self.keyboard.layout[(self.current_layer, widget.desc.row, widget.desc.col)]
        else:
            return self.keyboard.encoder_layout[(self.current_layer, widget.desc.encoder_idx,
                                                 widget.desc.encoder_dir)]

    def refresh_key_display(self):
        """ Refresh text on key widgets to display updated keymap """
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

        if isinstance(self.container.active_key, EncoderWidget):
            self.set_key_encoder(keycode)
        else:
            self.set_key_matrix(keycode)

        self.container.select_next()

    def set_key_encoder(self, keycode):
        l, i, d = self.current_layer, self.container.active_key.desc.encoder_idx,\
                            self.container.active_key.desc.encoder_dir

        # if masked, ensure that this is a byte-sized keycode
        if self.container.active_mask:
            if not Keycode.is_basic(keycode):
                return
            kc = Keycode.find_outer_keycode(self.keyboard.encoder_layout[(l, i, d)])
            if kc is None:
                return
            keycode = kc.qmk_id.replace("(kc)", "({})".format(keycode))

        self.keyboard.set_encoder(l, i, d, keycode)
        self.refresh_key_display()

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
