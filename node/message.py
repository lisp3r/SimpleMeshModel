import pickle
import json

# Узлы сети с заданным интервалом транслируют HELLO-сообщение, в которых содержится:
# * собственный адрес узла,
# * перечень всех его доступных соседей, их адреса с указанием типа соединения (симметричное или асимметричное).
# Каждый абонент сохраняет у себя информацию о соседях в одном и двух хопах от него.
# 
# Помимо всего в сети узлы периодически передают широковещательное TC-сообщение (topology control), в котором содержится:
# * информация о соединении абонента с одношаговыми соседями.

class Message:
    MESSAGE_TYPES = ['HELLO', 'TC', 'MID']

    @classmethod
    def from_type(cls, message_type, **args):
        if message_type not in cls.MESSAGE_TYPES:
            raise Exception(f'No message type "{message_type}" found')
        for subclass in cls.__subclasses__():
            if message_type.lower() in subclass.__name__.lower():
                return subclass(**args)

    def to_json(self):
        return json.dumps(self.__dict__)

    def make(self):
        return pickle.dumps()

class HelloMessage(Message):
    def __init__(self, sender, neighbor_table, addr=None):
        self.message_type = 'HELLO'
        self.sender = sender
        self.addr = addr
        self._neighbors = neighbor_table

    def make(self):
        self.neighbors = [x['addr'] for x in self._neighbors]
        return pickle.dumps(self)

# class TsMessage(Message):
#     def __init__(self, sender, neighbor_table):
#         super().__init__('TS')
#         self.sender = sender
#         self.payload = neighbor_table

class MessageHandler:
    def __pack__(self, message_type, **args):
        return pickle.dumps(Message().from_type(message_type, **args))

    def unpack(self, message):
        return pickle.loads(message)

    def hello_message(self, sender, neighbor_table, addr=None):
        # return self.__pack__('HELLO', sender=sender, neighbor_table=neighbor_table, addr=addr)
        return Message().from_type('HELLO', sender=sender, neighbor_table=neighbor_table, addr=addr)
