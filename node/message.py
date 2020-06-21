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
    MESSAGE_TYPES = ['HELLO', 'TC', 'CUSTOM', 'ALERT']

    @classmethod
    def from_type(cls, message_type, **args):
        if message_type not in cls.MESSAGE_TYPES:
            raise Exception(f'No message type "{message_type}" found')
        for subclass in cls.__subclasses__():
            if message_type.lower() in subclass.__name__.lower():
                return subclass(**args)

    def to_json(self):
        return json.dumps(self.__dict__)

    def pack(self):
        return pickle.dumps(self)

    @staticmethod
    def unpack(message):
        return pickle.loads(message)

class HelloMessage(Message):
    def __init__(self, sender, neighbor_table, addr=None):
        self.message_type = 'HELLO'
        self.sender = sender
        self.addr = addr
        self.neighbors = neighbor_table

    def __str__(self):
        return f'TYPE: {self.message_type}; SENDER: {self.sender}; ADDR: {self.addr}; NEIGHBORS: {self.neighbors}'

class TcMessage(Message):
    def __init__(self, sender, mpr_set, addr=None):
        self.message_type = 'TC'
        self.sender = sender
        self.addr = addr
        self.mpr_set = mpr_set

    def __str__(self):
        return f'TYPE: {self.message_type}; SENDER: {self.sender}; MPR SET: {self.mpr_set}'

class CustomMessage(Message):
    def __init__(self, sender, dest, msg, addr=None):
        self.message_type = 'CUSTOM'
        self.sender = sender
        self.addr = addr
        self.dest = dest
        self.msg = msg
        self.forwarders=[sender]
        # IPS: Clock parameter maintanied in message on sender
        # This may be detected on attacker side
        self.__clock = 0

    # IPS: Method for IPS to track message age
    def tick(self):
        self.__clock += 1
        return self.__clock

    def __str__(self):
        return self.msg

    def __eq__(self, other):
        return (self.sender == other.sender) and (self.addr == other.addr) and (self.dest == other.dest) and (self.msg == other.msg)
