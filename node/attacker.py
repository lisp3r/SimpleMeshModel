import sys
import yaml
import socket
import time
import logging
import threading
import netifaces
import re
import message
import networkx as nx
import matplotlib.pyplot as plt
from copy import copy
from random import choice, randint

class Attacker(None):

    def __init__(self):
        super().__init__()

