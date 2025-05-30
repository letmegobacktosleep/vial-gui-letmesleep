# SPDX-License-Identifier: GPL-2.0-or-later
import json
import struct

from PyQt5.QtWidgets import QHBoxLayout, QGridLayout, QLabel, QTextEdit, QVBoxLayout, QMessageBox, QWidget, QTabWidget, QSpinBox, QDoubleSpinBox, QPushButton
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
            "id_custom_get_key_config":    1,
            "id_custom_set_key_config":    2,
            "id_custom_get_lut_config":    3,
            "id_custom_set_lut_config":    4,
            "id_custom_save_lut_config":   5,
            "id_custom_get_virtual_axes":  6,
            "id_custom_set_virtual_axes":  7,
            "id_custom_save_virtual_axes": 8
        }

        self.last_clicked_key = None
        self.last_click_count = 0
        self.integer_option_values = {
            "Mode": 2,
            "Actuation Point":  15,
            "Deadzone":         1,
            "Up Sensitivity":   5,
            "Down Sensitivity": 5,
        }

        self.lut_options = {}
        self.jst_options = {}

        self.tabs_widget = QTabWidget()

        self.addWidget(self.tabs_widget)

        layout_editor.changed.connect(self.on_layout_changed)

    def populate_tabs(self):
        """Populate the editor with only the tabs from vial.json."""
        self.tabs_widget.clear()  # Reset tabs before repopulating

        available_tabs = self.keyboard.hall_effect_tabs if self.keyboard else []

        tab_mapping = {
            "Key Config": self.create_key_config_tab,
            "Calibration": self.create_calibration_tab,
            "Displacement": self.create_displacement_tab,
            "Joystick": self.create_joystick_tab,
        }

        for tab_name in tab_mapping:
            if tab_name in available_tabs:
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
        for i, label in enumerate(self.integer_option_values):
            opt = IntegerOption(label, keymap_options_layout, i, min_val=0, max_val=255)
            opt.set_value(self.integer_option_values[label])
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
        usage_description.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
    
    def create_calibration_tab(self):
        return self.create_lut_options_tab(1)

    def create_displacement_tab(self):
        return self.create_lut_options_tab(2)
    
    def create_joystick_tab(self):
        return self.create_joystick_options_tab()

    def create_joystick_options_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        # Grid layout for options
        options_grid = QGridLayout()

        # Define LUT options
        va_fields = [
            ("Deadzone",    1, 0, 0, 200),
            ("Disable Key", 1, 1, 0, 1),
            ("Row L Joystick Left",  2, 0,  0, 127),
            ("Col L Joystick Left",  2, 4,  0, 127),
            ("Row L Joystick Right", 2, 1,  0, 127),
            ("Col L Joystick Right", 2, 5,  0, 127),
            ("Row L Joystick Up",    2, 2,  0, 127),
            ("Col L Joystick Up",    2, 6,  0, 127),
            ("Row L Joystick Down",  2, 3,  0, 127),
            ("Col L Joystick Down",  2, 7,  0, 127),
            ("Row R Joystick Left",  2, 8,  0, 127),
            ("Col R Joystick Left",  2, 12, 0, 127),
            ("Row R Joystick Right", 2, 9,  0, 127),
            ("Col R Joystick Right", 2, 13, 0, 127),
            ("Row R Joystick Up",    2, 10, 0, 127),
            ("Col R Joystick Up",    2, 14, 0, 127),
            ("Row R Joystick Down",  2, 11, 0, 127),
            ("Col R Joystick Down",  2, 15, 0, 127),
            ("Row Mouse Left",   2, 0,  0, 127),
            ("Col Mouse Left",   2, 4,  0, 127),
            ("Row Mouse Right",  2, 1,  0, 127),
            ("Col Mouse Right",  2, 5,  0, 127),
            ("Row Mouse Up",     2, 2,  0, 127),
            ("Col Mouse Up",     2, 6,  0, 127),
            ("Row Mouse Down",   2, 3,  0, 127),
            ("Col Mouse Down",   2, 7,  0, 127),
            ("Row Scroll Left",  2, 8,  0, 127),
            ("Col Scroll Left",  2, 12, 0, 127),
            ("Row Scroll Right", 2, 9,  0, 127),
            ("Col Scroll Right", 2, 13, 0, 127),
            ("Row Scroll Up",    2, 10, 0, 127),
            ("Col Scroll Up",    2, 14, 0, 127),
            ("Row Scroll Down",  2, 11, 0, 127),
            ("Col Scroll Down",  2, 15, 0, 127),
        ]

        for i, (label, axes_id, value_id, min_val, max_val, precision) in enumerate(va_fields):
            opt = IntegerOption(label, options_grid, i, min_val=min_val, max_val=max_val)
            
            # Store option reference for later retrieval
            self.jst_options[(axes_id, value_id)] = opt

            # Connect change signal
            opt.changed.connect(self.joystick_option_changed)

        centered_layout = QVBoxLayout()
        centered_layout.addLayout(options_grid)
        centered_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(centered_layout)

        # Buttons Layout
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        # Save Button
        self.btn_save_joystick = QPushButton(tr("JST", "Save"))
        self.btn_save_joystick.clicked.connect(lambda: self.save_joystick_config())
        buttons_layout.addWidget(self.btn_save_joystick)

        # Undo Button
        self.btn_undo_joystick = QPushButton(tr("JST", "Reload"))
        self.btn_undo_joystick.clicked.connect(lambda: self.reload_joystick_config())
        buttons_layout.addWidget(self.btn_undo_joystick)

        layout.addLayout(buttons_layout)
        tab.setLayout(layout)

        return tab
    
    def joystick_option_changed(self):
        pass

    def save_joystick_config(self):

        """ Data Format
        deadzone = 1 
        1 byte -> deadzone
        1 byte -> should ignore keycodes

        joystick = 2
        4 bytes -> left  rows
        4 bytes -> left  cols
        4 bytes -> right rows
        4 bytes -> right cols

        mouse    = 3
        4 bytes -> mouse  rows
        4 bytes -> mouse  cols
        4 bytes -> scroll rows
        4 bytes -> scroll cols
        """

        for axes_id in range(1, 4): # 1, 2, 3

            value = [0 for i in range(0, 16)]

            for (a_id, v_id), opt in self.jst_options.items():
                if a_id == axes_id:
                    value[v_id] = opt.value()

            # Send values to the device
            data = struct.pack(
                "BBBBBBBBBBBBBBBBBBBB",
                self.command_id,
                self.sub_command_ids["id_custom_set_virtual_axes"],
                self.channel_id,
                axes_id,
                value
            )
            
            data = self.usb_send(self.device.dev, data, retries=20)
            # print(f"Saved Joystick Values {value}")

        # Send the save command
        data = struct.pack(
            "BBB",
            self.command_id,
            self.sub_command_ids["id_custom_save_virtual_axes"],
            self.channel_id
        )

        data = self.usb_send(self.device.dev, data, retries=20)

        # Reload config from device
        self.reload_joystick_config()

    def reload_joystick_config(self):
        for axes_id in range(1, 4): # 1, 2, 3

            # Fetch value from the device
            data = struct.pack(
                "BBBB",
                self.command_id,
                self.sub_command_ids["id_custom_get_virtual_axes"],
                self.channel_id,
                axes_id
            )
            
            data = self.usb_send(self.device.dev, data, retries=20)

            # Unpack the response
            stored_value = struct.unpack("BBBBBBBBBBBBBBBB", data[4:20])
            
            for (a_id, v_id), opt in self.jst_options.items():
                if a_id == axes_id:
                    opt.set_value(stored_value[v_id])
                    # print(f"Reset Joystick Value ID: {v_id} to {stored_value[v_id]}")

    def create_lut_options_tab(self, lut_id):
        tab = QWidget()
        layout = QVBoxLayout()

        # Grid layout for options
        options_grid = QGridLayout()

        # Define LUT options
        lut_fields = [
            ("Parameter A", 1, -100, 100, 16),
            ("Parameter B", 2, -100, 100, 16),
            ("Parameter C", 3, -100, 100, 16),
            ("Parameter D", 4, -1000, 1000, 16),
            ("Max Input",  5, 0, 2047, 0),
            ("Max Output", 6, 0, 2047, 0),
        ]

        for i, (label, value_id, min_val, max_val, precision) in enumerate(lut_fields):
            opt = DoubleOption(label, options_grid, i, min_val=min_val, max_val=max_val, decimals=precision)
            
            # Store option reference for later retrieval
            self.lut_options[(lut_id, value_id)] = opt

            # Connect change signal
            opt.changed.connect(self.lut_option_changed)

        centered_layout = QVBoxLayout()
        centered_layout.addLayout(options_grid)
        centered_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(centered_layout)

        # Buttons Layout
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        # Save Button
        self.btn_save_lut = QPushButton(tr("LUT", "Save"))
        self.btn_save_lut.clicked.connect(lambda: self.save_lut_config(lut_id))
        buttons_layout.addWidget(self.btn_save_lut)

        # Undo Button
        self.btn_undo_lut = QPushButton(tr("LUT", "Reload"))
        self.btn_undo_lut.clicked.connect(lambda: self.reload_lut_config(lut_id=lut_id))
        buttons_layout.addWidget(self.btn_undo_lut)

        layout.addLayout(buttons_layout)
        tab.setLayout(layout)

        return tab
    
    def lut_option_changed(self):
        pass

    def save_lut_config(self, lut_id):

        for (l_id, v_id), opt in self.lut_options.items():
            if l_id == lut_id:
                value = opt.value()  # Get actual value from the widget
                
                # Send value to the device
                data = struct.pack(
                    "BBBBB",
                    self.command_id,
                    self.sub_command_ids["id_custom_set_lut_config"],
                    self.channel_id,
                    l_id,
                    v_id
                ) + struct.pack(
                    "d",
                    value
                )
                
                data = self.usb_send(self.device.dev, data, retries=20)
                # print(f"Saved LUT ID: {l_id}, Value ID: {v_id} to {value}")

        # Send the save command
        data = struct.pack(
            "BBBB",
            self.command_id,
            self.sub_command_ids["id_custom_save_lut_config"],
            self.channel_id,
            l_id
        )

        data = self.usb_send(self.device.dev, data, retries=20)

        # Reload config from device
        self.reload_lut_config(lut_id=lut_id)

    def reload_lut_config(self, lut_id=None):

        for (l_id, v_id), opt in self.lut_options.items():
            if l_id == lut_id or lut_id == None:
                # Fetch value from the device
                data = struct.pack(
                    "BBBBB",
                    self.command_id,
                    self.sub_command_ids["id_custom_get_lut_config"],
                    self.channel_id,
                    l_id,
                    v_id
                )
                data = self.usb_send(self.device.dev, data, retries=20)

                # Unpack the response (assuming it's a double value)
                stored_value = struct.unpack("d", data[5:13])[0]

                opt.set_value(stored_value)  # Update UI
                # print(f"Reset LUT ID: {l_id}, Value ID: {v_id} to {stored_value}")

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
                # self.refresh_key_display()
                # this is already called in on_layout_changed

            self.reload_lut_config()
            
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

    def refresh_key_display(self, coordinate=None):
        """ Refresh text on key widgets to display updated keymap """
        if "Key Config" in (self.keyboard.hall_effect_tabs if self.keyboard else []):
            self.container.update_layout()

            for widget in self.container.widgets:
                if coordinate is None:
                    widget.setText(
                        self.code_for_widget(widget),
                        scale = 0.8
                    )
                elif (widget.desc.row, widget.desc.col) == coordinate:
                    widget.setText(
                        self.code_for_widget(widget),
                        scale = 0.8
                    )

            self.container.update()
            self.container.updateGeometry()

    def on_key_clicked(self):
        """Called when a key on the keyboard is clicked."""

        row = 0
        col = 0

        if self.container.active_key:
            row = self.container.active_key.desc.row
            col = self.container.active_key.desc.col

            if (row, col) == self.last_clicked_key:
                self.last_click_count += 1  # Increment click count if same key
            else:
                self.last_clicked_key = (row, col)
                self.last_click_count = 1  # Reset click count for new key

            status_text = ""
            if self.last_click_count > 1:
                status_text = "SAVED"

                data = struct.pack(
                    "BBBBBBBBBB",
                    self.command_id,
                    self.sub_command_ids["id_custom_set_key_config"],
                    self.channel_id,
                    row,
                    col,
                    self.integer_option_values["Mode"],
                    5 * self.integer_option_values["Actuation Point"],
                    5 * self.integer_option_values["Deadzone"],
                    5 * self.integer_option_values["Up Sensitivity"],
                    5 * self.integer_option_values["Down Sensitivity"]
                )

                data = self.usb_send(self.device.dev, data, retries=20)
            
            self.key_info_label.setText(f"Key: Row {row}, Col {col} {status_text}")

        else:
            self.key_info_label.setText("Key: None")
            self.last_clicked_key = None
            self.last_click_count = 0  # Reset when no key is selected

        self.refresh_key_display(
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
