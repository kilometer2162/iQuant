# -*- coding: utf-8 -*-

from dataclasses import dataclass


@dataclass
class ZMQServer:
	port: str
	client: list

@dataclass
class ZMQClient:
	command_port: str
	recv_port: str


@dataclass
class StrategySetting:
	exchange: str
	strategy: str
	account: str
	zmq: ZMQClient


@dataclass
class ExchangeSetting:
	exchange: str
	account: str
	public_key: str
	private_key: str
	instrument: dict
	zmq: ZMQServer
	default_cycle: str = "5m"
	phrase: str = ""
	session_number = 5
	cycles : list = None


@dataclass
class OrderRequest:
	symbol: str
	price: float
	posside: str  # long short
	side: str  # buy sell
	size: float
	ordertype: str  # Limit
	clientid: str = ""


@dataclass
class CancelRequest:
	orderid: str
	symbol: str = ''


@dataclass
class HistoryRequest:
	symbol: str
	start: str = None
	end: str = None

@dataclass
class PositionData:
	symbol: str
	posside: str
	size:float
	frozen: float
	price: float
	upl: float


@dataclass
class OrderData:
	orderid: str
	symbol: str
	ordertype: str
	status: str
	side: str = 'buy'
	posside : str = 'long'
	price: float = 0
	filled: float = 0
	fee:float = 0
	feeCcy: str = ""
	size: float = 0
	time: str = ""
	clientid: str = ""


@dataclass
class AccountData:
	coin: str
	total:float=0
	available: float = 0
	frozen: float = 0

	def __post_init__(self):
		""""""
		self.value = self.available + self.frozen


@dataclass
class CancelRequest:
	orderid: str
	symbol: str
	client_orderid: str


@dataclass
class HistoryRequest:
	symbol: str
	start: str = None
	end: str = None

@dataclass
class DepthData:
	symbol: str
	ts: str
	bid_price_1: float = 0
	bid_price_2: float = 0
	bid_price_3: float = 0
	bid_price_4: float = 0
	bid_price_5: float = 0

	ask_price_1: float = 0
	ask_price_2: float = 0
	ask_price_3: float = 0
	ask_price_4: float = 0
	ask_price_5: float = 0

	bid_volume_1: float = 0
	bid_volume_2: float = 0
	bid_volume_3: float = 0
	bid_volume_4: float = 0
	bid_volume_5: float = 0

	ask_volume_1: float = 0
	ask_volume_2: float = 0
	ask_volume_3: float = 0
	ask_volume_4: float = 0
	ask_volume_5: float = 0

@dataclass
class TickData:
	symbol: str
	ts: str

	bidprice: float
	askprice: float

	bidvolume: float
	askvolume: float

	last_price: float
	last_volume: float

	open_24h: float
	high_24h: float
	low_24h: float
	volume_24h: float


@dataclass
class BarData:
	symbol: str
	cycle: str
	ts: str
	open_price: float = 0
	high_price: float = 0
	low_price: float = 0
	close_price: float = 0
	volume: float = 0