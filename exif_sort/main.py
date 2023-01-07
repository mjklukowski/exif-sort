from datetime import datetime
import locale
import math
from pathlib import Path
import sys
from threading import Thread

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QLineEdit
from exif_sort.ui.main_window import Ui_MainWindow

from exif_sort.sorter import ImageSorter, ImageMoveError

class MainWindow(QMainWindow, Ui_MainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.__sort_thread = None
        self.__log_status("Ready")

    def setupUi(self, MainWindow):
        super().setupUi(MainWindow)

        # Hide unusable widgets on init
        self.cancelButton.setVisible(False)

        # Open FileDialogs and update path fields
        self.inputDirectoryBrowseButton.clicked.connect(self.__on_input_directory_button_click)
        self.outputDirectoryBrowseButton.clicked.connect(self.__on_output_directory_button_click)

        # Update output preview on each path's part change
        self.outputDirectoryPathEdit.textChanged.connect(self.__on_output_directory_path_change)
        self.outputFormatComboBox.currentTextChanged.connect(self.__on_output_format_change)
        self.renameFormatComboBox.currentTextChanged.connect(self.__on_rename_format_change)
        self.renameCheckBox.clicked.connect(self.__on_rename_click)

        # Start/cancel sorting
        self.sortButton.clicked.connect(self.__on_sort_button_click)
        self.cancelButton.clicked.connect(self.__on_cancel_button_click)

        # Quit application
        self.actionQuit.triggered.connect(self.__quit)

    def __log_status(self, msg: str):
        """Displays message in status listbox"""
        self.statusList.addItem(msg)
        self.statusList.scrollToBottom()

    def __lock_ui(self, lock=True):

        widgets = [
            self.inputDirectoryPathEdit,
            self.inputDirectoryBrowseButton,
            self.outputDirectoryPathEdit,
            self.outputDirectoryBrowseButton,
            self.recursiveCheckBox,
            self.skipUnknownCheckBox,
            self.outputFormatComboBox,
            self.renameCheckBox
        ]

        for w in widgets:
            w.setDisabled(lock)

        if lock:
            self.renameFormatComboBox.setDisabled(True)
        else:
            if self.renameCheckBox.isChecked():
                self.renameFormatComboBox.setDisabled(False)

    def __unlock_ui(self):
        self.__lock_ui(False)

    def __on_input_directory_button_click(self):
        """Called when input's "Browse" button has been clicked."""
        self.__browse_in_out_directory(self.inputDirectoryPathEdit)

    def __on_output_directory_button_click(self):
        """Called when output's "Browse" button has been clicked."""
        self.__browse_in_out_directory(self.outputDirectoryPathEdit)

    def __browse_in_out_directory(self, path_edit: QLineEdit):
        """Updates path field."""
        path = QFileDialog.getExistingDirectory(self, directory=path_edit.text())

        if len(path) == 0:
            return

        path_edit.setText(path)

    def __on_output_directory_path_change(self, text: str):
        """Called when output path has been changed."""
        self.__update_output_preview()

    def __on_output_format_change(self, text: str):
        """Called when output format has been changed."""
        self.__update_output_preview()

    def __on_rename_format_change(self, text: str):
        """Called when rename format has been changed."""
        self.__update_output_preview()

    def __on_rename_click(self, checked: bool):
        """Called when renaming files has been toggled."""
        self.__update_output_preview()

    def __update_output_preview(self):
        """Updates output preview."""
        date = datetime.now()

        # Get output path
        path = self.outputDirectoryPathEdit.text().strip()
        if len(path) > 0:
            output_path = Path(path)
        else:
            output_path = Path.home()

        # Add options format
        sort_format = self.outputFormatComboBox.currentText().strip()
        output_path = output_path.joinpath(date.strftime(sort_format))

        # Add rename format
        if self.renameCheckBox.isChecked():
            rename_format = self.renameFormatComboBox.currentText().strip()
            output_path = output_path.joinpath(date.strftime(rename_format))
        else:
            output_path = output_path.joinpath("image")

        self.outputPreviewValueLabel.setText(str(output_path) + ".jpg")

    def __update_progress_bar(self, value: float):
        """
        Sets progress bar to specified value.

        Value must be in range of [0;1].
        """
        self.statusProgress.setValue(math.floor(value * 100))

    def __on_sort_button_click(self):
        """Called when "Sort" button has been clicked."""
        # Get input path
        input_path = self.inputDirectoryPathEdit.text().strip()
        if len(input_path) == 0:
            self.__log_status("Invalid input directory")
            return

        input_path = Path(input_path)

        # Get output path
        output_path = self.outputDirectoryPathEdit.text().strip()

        if len(output_path) > 0:
            output_path = Path(output_path)
        else:
            output_path = Path.home()

        # Initialize sorter
        sorter = ImageSorter(input_path)
        sorter.output_dir = output_path
        sorter.recursive = self.recursiveCheckBox.isChecked()
        sorter.group_format = self.outputFormatComboBox.currentText().strip()
        sorter.sort_unknown = not self.skipUnknownCheckBox.isChecked()

        if self.renameCheckBox.isChecked():
            sorter.rename_format = self.renameFormatComboBox.currentText().strip()

        # Toggle Cancel button
        self.sortButton.setVisible(False)
        self.cancelButton.setVisible(True)

        # Lock UI
        self.__lock_ui()

        # Start sorting
        self.__sort_thread = SorterThread(sorter)

        self.__sort_thread.on_finish.connect(self.__on_sort_finish)
        self.__sort_thread.on_move.connect(self.__on_sort_move)
        self.__sort_thread.on_skip.connect(self.__on_sort_skip)
        self.__sort_thread.on_error.connect(self.__on_sort_error)

        self.__sort_thread.start()

    def __on_sort_finish(self):
        """Called once sorting finishes."""
        # Toggle Sort button
        self.sortButton.setVisible(True)
        self.cancelButton.setVisible(False)
        self.cancelButton.setDisabled(False)

        # Unlock UI
        self.__unlock_ui()

        # Log sorting cancellation
        if self.__sort_thread.stopped:
            self.__log_status("Sorting cancelled")

        # Ready
        self.__log_status("Ready")

    def __on_sort_move(self, old_path: str, new_path: str, progress: float):
        """Called when file has been moved."""
        self.__log_status(f"Moved \"{old_path}\" to \"{new_path}\"")
        self.__update_progress_bar(progress)

    def __on_sort_skip(self, path: str, progress: float):
        """Called when file has been skipped."""
        self.__log_status(f"Skipped \"{path}\"")
        self.__update_progress_bar(progress)

    def __on_sort_error(self, exception: Exception, progress: float):
        msg = "Error: "

        if isinstance(exception, ImageMoveError):
            path = exception.path
            exception = exception.reason
        elif isinstance(exception, OSError):
            path = exception.filename

        if isinstance(exception, PermissionError):
            msg += f"Permission denied to {path}"
        elif isinstance(exception, FileNotFoundError):
            msg += f"{path} not found"
        else:
            msg += str(exception)

        self.__log_status(msg)
        self.__update_progress_bar(progress)

    def __on_cancel_button_click(self):
        """Called when "Cancel" button has been clicked."""
        self.cancelButton.setDisabled(True)
        self.__sort_thread.stop()

    def __quit(self): # pragma: no cover
        """Closes window and exits application."""
        self.close()

class SorterThread(QThread):
    """Separate thread for sorting task."""

    on_move = pyqtSignal(Path, Path, float)
    on_error = pyqtSignal(Exception, float)
    on_skip = pyqtSignal(Path, float)
    on_finish = pyqtSignal()

    def __init__(self, sorter: ImageSorter):
        super().__init__()
        self.__sorter = sorter

        self.stopped = False

        # Map sorter's callbacks to Qt signals
        self.__sorter.on_move = lambda p1, p2, pr: self.on_move.emit(p1, p2, pr)
        self.__sorter.on_error = lambda e, pr: self.on_error.emit(e, pr)
        self.__sorter.on_skip = lambda p, pr: self.on_skip.emit(p, pr)
        self.__sorter.on_finish = lambda: self.on_finish.emit()

    def run(self):
        self.__sorter.sort()

    def stop(self):
        self.stopped = True
        self.__sorter.cancel()

def main(): # pragma: no cover
    locale.setlocale(locale.LC_ALL, "")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    return app.exec()
