import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setThemeColor

from ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Sounder')
    app.setOrganizationName('Sounder')
    setThemeColor('#0078d4')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()