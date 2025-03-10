# SPDX-License-Identifier: GPL-2.0-or-later
import json
import struct

from PyQt5.QtWidgets import QHBoxLayout, QGridLayout, QLabel, QTextEdit, QVBoxLayout, QMessageBox, QWidget, QTabWidget, QSpinBox, QDoubleSpinBox
from PyQt5.QtCore import Qt, pyqtSignal, QObject

from editor.basic_editor import BasicEditor
from widgets.keyboard_widget import KeyboardWidget
from widgets.square_button import SquareButton
from util import tr, KeycodeDisplay
from vial_device import VialKeyboard
from util import MSG_LEN, hid_send

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
    def __init__(self, title, container, row, min_val=-1000.0, max_val=1000.0, decimals=16):
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

    def __init__(self, layout_editor, usb_send=hid_send):
        super().__init__()

        self.layout_editor = layout_editor
        self.device = None  # Will be set in rebuild()
        self.keyboard = None  # Store keyboard reference
        self.usb_send = usb_send

        self.command_id = 0xFF # id_unhandled
        self.channel_id = 0x00 # id_custom_channel
        self.sub_command_ids = {
            "id_custom_get_key_config": 1,
            "id_custom_set_key_config": 2,
            "id_custom_get_lut_config": 3,
            "id_custom_set_lut_config": 4
        }

        self.last_clicked_key = None
        self.last_click_count = 0
        self.integer_option_values = {
            "Mode": 0,
            "Actuation Point":  0,
            "Deadzone":         0,
            "Up Sensitivity":   0,
            "Down Sensitivity": 0,
        }

        self.tabs_widget = QTabWidget()

        self.addWidget(self.tabs_widget)

        layout_editor.changed.connect(self.on_layout_changed)

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
        keymap_options_layout = QGridLayout()
        self.keymap_int_options = {}
        for i, label in enumerate([
            "Mode",
            "Actuation Point",
            "Deadzone",
            "Up Sensitivity",
            "Down Sensitivity",
        ]):
            opt = IntegerOption(label, keymap_options_layout, i, min_val=0, max_val=255)
            opt.changed.connect(lambda name=label: self.store_integer_value(name))
            self.keymap_int_options[label] = opt

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

        # Usage Description Text Box
        usage_description = QLabel(
            "Set the key config\n"
            "in the boxes\n"
            "on the right\n\n"
            "Click on a key,\n"
            "twice in a row,\n"
            "but not too quickly,\n"
            "to write the config\n"
            "to the key clicked"
        )
        usage_description.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        usage_description.setStyleSheet("border: none; padding-right: 10px;")

        # Horizontal layout for options and text box
        options_and_text_layout = QHBoxLayout()
        options_and_text_layout.addWidget(usage_description)
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
        return self.create_lut_options_tab(2)

    def create_joystick_tab(self):
        return self.create_lut_options_tab(3)

    def create_calibration_tab(self):
        return self.create_lut_options_tab(1)

    def create_lut_options_tab(self, lut_id):
        tab = QWidget()
        layout = QVBoxLayout()

        options_grid = QGridLayout()

        for i, (label, value_id) in enumerate([
            ("Parameter A", 1),
            ("Parameter B", 2),
            ("Parameter C", 3),
            ("Parameter D", 4),
        ]):
            opt = DoubleOption(label, options_grid, i, min_val=-1000, max_val=1000)
            opt.changed.connect(self.on_option_changed)


        for i, (label, value_id) in enumerate([
            ("Max Input", 5),
            ("Max Output", 6),
        ]):
            opt = DoubleOption(label, options_grid, i + 4, min_val=0, max_val=2047, decimals=0)
            opt.changed.connect(self.on_option_changed)

        centered_layout = QVBoxLayout()
        centered_layout.addLayout(options_grid)
        centered_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(centered_layout)
        tab.setLayout(layout)
        return tab

    def on_option_changed(self):
        print("Option changed!")

        command_id     = 0xFF  # Always unhandled
        sub_command_id = None
        channel_id     = 0x00  # Always 0x00

        #data = struct.pack("BBB", command_id, sub_command_id, channel_id)
        #self.usb_send(self.device.dev, data, retries=20)

    def store_integer_value(self, name):
        value = self.keymap_int_options[name].value()  # Assuming integer_options stores the widgets
        self.integer_option_values[name] = value

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

        self.refresh_key_display(
            refresh_all=False
        )

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
                # self.refresh_key_display()
                # do not need to refresh, this is already done in on_layout_changed
            
        else:
            self.tabs_widget.clear()  # Remove all tabs if Hall Effect isn't supported

        self.tabs_widget.setEnabled(self.valid())

    def valid(self):
        """Determine if HallEffectEditor should be visible."""
        return isinstance(self.device, VialKeyboard) and self.device.keyboard.has_hall_effect

    def code_for_widget(self, widget):
        if (
            widget.desc.row is not None 
        ):
            # Try and load the values from the keyboard here
            data = struct.pack(
                "BBBBB",
                self.command_id,
                self.sub_command_ids["id_custom_get_key_config"],
                self.channel_id,
                widget.desc.row,
                widget.desc.col
            )

            data = self.usb_send(self.device.dev, data, retries=20)

            (
                mode,
                actuation_point,
                deadzone,
                up_sensitivity,
                down_sensitivity
            ) = struct.unpack(
                "BBBBB",
                data[5:10]
            )

            config_text = (f"Mode: {mode}\n"
                           f"{actuation_point}, "
                           f"{deadzone}\n"
                           f"{up_sensitivity}, "
                           f"{down_sensitivity}"
            )

            return config_text

    def refresh_key_display(self, refresh_all=True, coordinate=(0,0)):
        """ Refresh text on key widgets to display updated keymap """
        if "Key Config" in (self.keyboard.hall_effect_tabs if self.keyboard else []):
            self.container.update_layout()

            for widget in self.container.widgets:
                if (refresh_all):
                    widget.setText(self.code_for_widget(widget))
                elif (widget.desc.row, widget.desc.col) == coordinate:
                    widget.setText(self.code_for_widget(widget))

            self.container.update()
            self.container.updateGeometry()

    def on_key_clicked(self):
        """Called when a key on the keyboard is clicked."""

        row = 0
        col = 0
        refresh_all = True

        if self.container.active_key:
            row = self.container.active_key.desc.row
            col = self.container.active_key.desc.col
            refresh_all = False

            if (row, col) == self.last_clicked_key:
                self.last_click_count += 1  # Increment click count if same key
            else:
                self.last_clicked_key = (row, col)
                self.last_click_count = 1  # Reset click count for new key

            exclamation_marks = ""
            if self.last_click_count > 1:
                exclamation_marks = "!!!"

                data = struct.pack(
                    "BBBBBBBBBB",
                    self.command_id,
                    self.sub_command_ids["id_custom_set_key_config"],
                    self.channel_id,
                    row,
                    col,
                    self.integer_option_values["Mode"],
                    self.integer_option_values["Actuation Point"],
                    self.integer_option_values["Deadzone"],
                    self.integer_option_values["Up Sensitivity"],
                    self.integer_option_values["Down Sensitivity"]
                )

                data = self.usb_send(self.device.dev, data, retries=20)
            
            self.key_info_label.setText(f"Key: Row {row}, Col {col} {exclamation_marks}")
            print("Integer Option Values:", self.integer_option_values)

        else:
            self.key_info_label.setText("Key: None")
            self.last_clicked_key = None
            self.last_click_count = 0  # Reset when no key is selected

        self.refresh_key_display(
            refresh_all=False,
            coordinate=(row, col)
        )


    def on_key_deselected(self):
        pass

    def on_layout_changed(self):
        if self.keyboard is None:
            return

        self.refresh_key_display()
        self.keyboard.set_layout_options(self.layout_editor.pack())

    def on_keymap_override(self):
        pass
