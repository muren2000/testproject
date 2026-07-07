"""`python -m pdfcompress` — CLI; `python -m pdfcompress --gui` — графический интерфейс."""

import sys

if "--gui" in sys.argv:
    from .gui import main as gui_main

    gui_main()
else:
    from .cli import main

    sys.exit(main())
