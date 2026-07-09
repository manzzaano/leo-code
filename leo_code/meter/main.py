# -*- coding: utf-8 -*-
"""Punto de entrada de leo-code Meter (panel flotante, Windows).

Uso: leo-code-meter   (o: python -m leo_code.meter.main)

Estilos barra-de-tareas/bandeja (como bar.py/tray.py de claude-code-meter)
quedan como fase futura — no implementados aqui.
"""
import platform
import sys


def main():
    if platform.system() != "Windows":
        print("leo-code-meter solo soporta Windows por ahora (usa APIs de ctypes.windll).")
        sys.exit(1)

    from leo_code.meter.panel import Panel
    Panel().mainloop()


if __name__ == "__main__":
    main()
