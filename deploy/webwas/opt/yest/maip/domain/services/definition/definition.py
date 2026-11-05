
from domain.services.date import DateUtil
from domain.services.sql import DbUtil
from domain.services.logging import LogWriter
from django.db import IntegrityError


class DefinitionService():
    def __init__(self):
        pass

class ProtectedError(IntegrityError):
    def __init__(self, msg, protected_objects):
        self.protected_objects = protected_objects
        super().__init__(msg, protected_objects)