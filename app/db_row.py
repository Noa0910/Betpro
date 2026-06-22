"""Fila compatible con sqlite3.Row (acceso por nombre e índice)."""


class DbRow(dict):
    __slots__ = ("_values",)

    def __init__(self, columns: tuple, values: tuple):
        super().__init__(zip(columns, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)
