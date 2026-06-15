"""DiviConto — divisione delle spese tra amici in un viaggio.

Package a strati:
- money:   utilità monetarie basate su Decimal
- models:  dataclasses dei dati
- db:      storage SQLite (unico punto che tocca la persistenza)
- balance: calcolo saldi netti e pagamenti di pareggio
- core:    logica di business riusabile (CLI e futura UI)
- cli:     interfaccia a riga di comando
"""

__version__ = "0.1.0"
