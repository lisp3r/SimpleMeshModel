import pickle
import json
import copy

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
        self.neighbors = neighbor_table

    def make(self):
        # (f'Neighbors to send: {self.neighbors}')
        return pickle.dumps(self)

    def __str__(self):
        return f'TYPE: {self.message_type}; SENDER: {self.sender}; ADDR: {self.addr}; NEIGHBORS: {self.neighbors}'

class TcMessage(Message):
    def __init__(self, sender, mpr_set, addr=None, ansn=0):
        self.message_type = 'TC'
        self.ansn = ansn
        self.sender = sender
        self.addr = addr
        self.mpr_set = mpr_set

    def __str__(self):
        return f'TYPE: {self.message_type}; SENDER: {self.sender}; MPR SET: {self.mpr_set}'

    def make(self):
        return pickle.dumps(self)

class MessageHandler:
    def __pack__(self, message_type, **args):
        return pickle.dumps(Message().from_type(message_type, **args))

    def unpack(self, message):
        return pickle.loads(message)

    def hello_message(self, sender, neighbor_table, addr=None):
        return Message().from_type('HELLO', sender=sender, neighbor_table=neighbor_table, addr=addr)

    def tc_message(self, sender, mpr_set, addr=None, ansn=0):
        return Message().from_type('TC', sender=sender, mpr_set=mpr_set, addr=addr, ansn=ansn)