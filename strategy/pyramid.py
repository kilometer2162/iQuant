# -*- coding: utf-8 -*-
import math
import time
import traceback
from threading import Lock

from trader import utility
from trader.object import StrategySetting
from strategy.template import StrategyTemplate, StgVariable

'''
三网定投网格交易
1网 小价差比例的普通网格，按固定数量固定比例买卖，如超5分钟无买单成交，则撤单重新挂，同时防止密集开单
2网 当价格到达对应阶梯时，按当前价格对应的阶梯格数差买，等价格上涨后按对应的阶梯格数差卖；如当价格为100时买3个，升到200卖1个，升到300卖2个
3网 按固定价位与相应价位对应的买卖数量，只在价格中线以下买，只在价格中线以上卖
'''

'''
,
    "OKB-USDT": {
      "low_price": 5,
      "high_price": 50,
      "step": 100,
      "ratio": 0.02,
      "second": 600,
      "volume": 0.1
    }
    ,"XLM-USDT": {
        "low_price": 0.1,
        "high_price": 2,
        "step": 80,
        "ratio": 0.02,
        "second": 100,
        "volume": 1,
        "fee": 0.0006
      },
      "SHIB-USDT": {
        "low_price":  0.00000568,
        "high_price": 0.0000568,
        "step": 50,
        "ratio": 0.03,
        "second": 200,
        "volume": 1000000,
        "fee": 0.0006
      },
    
'''


class PyramidVariable(StgVariable):

	def __init__(self, stg):
		super(PyramidVariable, self).__init__(stg)

		self._inited = False
		self.inited_lock = Lock()

		self._ordering = False
		self._ordering_lock = Lock()

		self.cancel_ordering = False
		self._cancel_ordering_lock = Lock()

		self.g1_buy_switch = False
		self._g1_buy_switch_lock = Lock()
		self._g1_buy_order_timestamp = 0
		self._g1_buy_order_id = ''
		self.g1_buy_price = 0
		self.g1_sell_price = 0
		self.g1_buy_order_amount = 0
		self.g1_buy_order_lock = Lock()

		self._g2_buy_order_timestamp = 0
		self._g2_buy_order_id = ''
		self.g2_buy_order_amount = 0
		self._g2_buy_order_lock = Lock()
		self.g2_buy_price = 0
		self.g2_sell_price = 0
		self.g2_buy_amount = 0
		self._g2_buy_amount_lock = Lock()
		self.g2_buy_multiple = 0
		self._g2_buy_multiple_lock = Lock()
		self.g2_sell_multiple = 0
		self._g2_sell_multiple_lock = Lock()

		self._g3_buy_order_timestamp = 0
		self._g3_buy_order_id = ''
		self.g3_buy_amount = 0
		self.g3_buy_order_amount = 0
		self._g3_buy_order_lock = Lock()
		self._g3_buy_amount_lock = Lock()
		self.g3_price_memory = []
		self._g3_price_index = -1
		self._g3_price_memory_lock = Lock()

		self.price_remind = {'timestamp': 0, 'price': 0}
		self.price_step = []
		self.volume_step = []
		self.ratio = 0  # grid1 网格比例差
		self.middle_price = 0
		self.step_span = 0
		self.init_step_span = 0
		self.high_price = 0
		self.low_price = 0
		self.step = 0
		self.volume = 0
		self.vol_num = 0
		self._available = 0
		self.avg_price = 0
		self._second = 0
		self.continuous_buy = 0

		self.fee = 0
		self.order_volume = 0
		self.cur_asset = 0
		self._signal = False
		self._signal_lock = Lock()


class pyramid(StrategyTemplate):
	def __init__(self, setting: StrategySetting, parameter: dict):
		super(pyramid, self).__init__(setting, parameter)
		self.this = self
		self.second = 1200
		self.usdt_available = 0

		for c in self.g_parameter["instrument"]:
			pv = PyramidVariable(self.this)
			e = self.g_parameter["instrument"][c]

			pv.high_price = e['high_price']
			pv.low_price = e['low_price']
			pv.step = e['step']
			pv.ratio = e['ratio']
			pv.volume = e['volume']
			pv.fee = e['fee']
			if 'second' in e:
				if e['second'] > 0:
					pv.second = e['second']
				else:
					pv.second = self.second
			pv.step_span = (pv.high_price - pv.low_price) / pv.step
			pv.init_step_span = pv.step_span
			pv.middle_price = (pv.high_price + pv.low_price) / 2
			pv.vol_num = math.ceil(pv.step / 2)

			for i in range(pv.vol_num):
				price = pv.high_price - i * pv.step_span
				pv.price_step.append(price)
				pv.g3_price_memory.append({'price': price, 'g3b': False, 'g3s': False})
				pv.volume_step.append(pv.vol_num - i)

			_price_step = []
			_volume_step = []
			for i in range(pv.vol_num):
				price = pv.low_price + i * pv.step_span
				_price_step.append(price)
				pv.g3_price_memory.append({'price': price, 'g3b': False, 'g3s': False})
				_volume_step.append(pv.vol_num - i)

			_price_step.reverse()
			_volume_step.reverse()

			pv.price_step.extend(_price_step)
			pv.volume_step.extend(_volume_step)

			pv.coin = c
			pv.enable_cache_switch(True)
			self.STV[c] = pv
			self.g_notify_active = True
			self.do_notify(c)

	def on_bar(self, data):
		coin, _, price,__ = super().on_bar(data)

		if coin in self.STV:
			_self = self.STV[coin]
			this = self.g_indicator_factory[coin][self.g_cycle]
			is_new_bar = this.is_new_bar
			# self.logger.info("on_bar -> is_new_bar: %s" % is_new_bar)

			if is_new_bar:
				now = int(time.time())
				if price > _self.high_price or price < _self.low_price:

					if _self.price_remind['timestamp'] == 0:
						_self.price_remind['timestamp'] = now
					else:
						if now - _self.price_remind['timestamp'] > _self.second:
							self.logger.error("%s 当前价格 %f 已跑出最高价与最低价区间超过10分钟，请重新设置网格参数！" % (coin, price))
							_self.price_remind['timestamp'] = 0

				if not _self.cancel_ordering:
					# 如超5分钟无买单成交，则撤单重新挂，为了防止无限挂单，过期时间随着拉长，一有卖单成交再恢复
					if _self._g1_buy_order_timestamp > 0 and len(_self._g1_buy_order_id) > 0:
						ts_diff = now - _self._g1_buy_order_timestamp
						# self.logger.info("g1 ts_diff: %f"%ts_diff)
						if ts_diff > _self.second:
							self.logger.info("cancel g1 order %s" % _self._g1_buy_order_id)
							self.cancel_order({"instId": coin, "ordId": _self._g1_buy_order_id, "patch": f"{coin}_g1"})
					if _self._g2_buy_order_timestamp > 0 and len(_self._g2_buy_order_id) > 0:
						ts_diff = now - _self._g2_buy_order_timestamp
						# self.logger.info("g2 ts_diff: %f" % ts_diff)
						if ts_diff > _self.second * 5:
							self.logger.info("cancel g2 order %s" % _self._g2_buy_order_id)
							self.cancel_order({"instId": coin, "ordId": _self._g2_buy_order_id, "patch": f"{coin}_g2"})
					if _self._g3_buy_order_timestamp > 0 and len(_self._g3_buy_order_id) > 0:
						ts_diff = now - _self._g3_buy_order_timestamp
						# self.logger.info("g3 ts_diff: %f" % ts_diff)
						if ts_diff > _self.second * 10:
							self.logger.info("cancel g3 order %s" % _self._g3_buy_order_id)
							self.cancel_order({"instId": coin, "ordId": _self._g3_buy_order_id, "patch": f"{coin}_g3"})
				with _self._signal_lock:
					_self._signal = True

	def on_depth(self, data):
		try:
			coin = data.symbol
			if coin in self.STV:
				_self = self.STV[coin]
				if _self._signal:
					if not _self._ordering:
						direction = 'buy'
						client_oid = self.gen_client_orderid(coin, 'g1b')
						if not _self._inited:
							amount = _self.volume
							# 如果当前没有足够的最小交易币量可卖，以最优价多买一手
							if _self._available < _self.volume:
								amount *= 2

							self.send_order({"instId": coin, "clOrdId": client_oid, "side": direction, "px": data.bid_price_5, "sz": _self.volume,
									 "patch": {"coin": coin, "side": direction, "amount": _self.volume, "init": 1, "grid_type": 1}})
							with _self.inited_lock:
								_self._inited = True
						if _self.g1_buy_switch:
							if _self.g1_buy_price == 0:
								price = data.bid_price_5
							elif data.bid_price_1 > _self.g1_buy_price:
								if _self.g1_sell_price > 0:
									if data.bid_price_1> _self.g1_sell_price:
										price = _self.g1_sell_price - _self.step_span
									else:
										price = data.bid_price_5
								else:
									price = data.bid_price_1 - _self.step_span
							else:
								price = _self.g1_buy_price * (1 - _self.ratio * (1 if _self.continuous_buy == 0 else _self.continuous_buy) / 2)
							self.send_order({"instId": coin, "clOrdId": client_oid, "side": direction, "px": price, "sz": _self.volume,
									 "patch": {"coin": coin, "side": direction, "amount": _self.volume, "grid_type": 1}})
							with _self._g1_buy_switch_lock:
								_self.g1_buy_switch = False

						direction, amount = self.get_grid2_direction_volume(coin, data.bid_price_1)
						self.logger.info('%s g2 direction: %s amount: %d' % (coin, direction, amount))
						if direction == 'buy':
							if _self.g2_buy_price == 0:
								price = data.bid_price_1 - _self.step_span
							# 行情向上涨，挂单跟随
							elif data.bid_price_1 > _self.g2_buy_price:
								if _self.g2_sell_price > 0:
									if data.bid_price_1 > _self.g2_sell_price:
										price = _self.g2_sell_price - _self.step_span
									else:
										price = data.bid_price_5 - _self.step_span
								else:
									price = data.bid_price_1 - _self.step_span
							else:
								price = _self.g2_buy_price - _self.step_span #_self.g2_buy_price * (1 - _self.ratio * (1 if _self.continuous_buy == 0 else _self.continuous_buy))
						else:
							price = data.ask_price_5
						if amount > 0:
							client_oid = self.gen_client_orderid(coin, 'g2' + direction[0:1])
							self.send_order({"instId": coin, "clOrdId": client_oid, "side": direction, "px": price, "sz": amount,
									 "patch": {"coin": coin, "side": direction, "amount": amount, "grid_type": 2}})

						direction, amount = self.get_grid3_direction_volume(coin, data.bid_price_1)
						self.logger.info('%s g3 direction: %s amount: %d' % (coin, direction, amount))
						if direction == 'buy':
							price = data.bid_price_5 * (1 - _self.ratio * 2)
						else:
							price = data.ask_price_5
						if amount > 0:
							client_oid = self.gen_client_orderid(coin, 'g3' + direction[0:1])
							self.send_order({"instId": coin, "clOrdId": client_oid, "side": direction, "px": price, "sz": amount,
									 "patch": {"coin": coin, "side": direction, "amount": amount, "grid_type": 3}})
					with _self._signal_lock:
						_self._signal = False
		except:
			self.logger.error("on_depth_data error,traceback=\n%s" % traceback.format_exc())

	def on_order(self, data):
		now = int(time.time())
		for row in data:
			coin = row["symbol"]
			if coin in self.STV:
				self.logger.info("on_order===>" + str(data))
				_self = self.STV[coin]
				side = row["side"]
				size = row['size']
				ord_id = row["orderid"]
				tag = row["clientid"][0:3]

				if row["status"] == 'filled':
					if tag[0] == 'g':
						price = row["price"]

						self.logger.info('tag is :%s' % tag)
						if tag == 'g1b':
							client_oid = self.gen_client_orderid(coin, 'g1s')
							self.send_order({"instId": coin, "clOrdId": client_oid, "side": 'sell', "px": price * (1 + _self.ratio), "sz": size,
									 "patch": {"coin": coin, "side": 'sell', "amount": size, "grid_type": 1}})
							self.logger.info("%s g1b set g1_buy_price: %f" % (coin, price))
							_self.g1_buy_price = price
						elif tag == 'g1s':
							with _self._g1_buy_switch_lock:
								_self.g1_buy_switch = True
							with _self.g1_buy_order_lock:
								_self._g1_buy_order_id = ''
								self.logger.info(f"### set {coin} g1 order id = ''")
								_self._g1_buy_order_timestamp = 0
							_self.g1_sell_price = price
						elif tag == 'g2b':
							self.logger.info("%s g2b set g2_buy_price: %f" % (coin, price))
							_self.g2_buy_price = price
						elif tag == 'g2s':
							with _self._g2_buy_order_lock:
								_self._g2_buy_order_id = ''
								self.logger.info(f"### set {coin} g2 order id = ''")
								_self._g2_buy_order_timestamp = 0
							_self.step_span = _self.init_step_span
							_self.g2_sell_price = price
						elif tag == 'g3b' or tag == 'g3s':
							with _self._g3_price_memory_lock:
								if tag == 'g3b':
									_self.g3_price_memory[_self._g3_price_index]['g3s'] = False
									self.logger.info(f" set {coin} g3s g3_price_memory[{_self._g3_price_index}] tag: False")
								elif tag == 'g3s':
									_self.g3_price_memory[_self._g3_price_index]['g3b'] = False
									self.logger.info(f"set {coin} g3b g3_price_memory[{_self._g3_price_index}] tag: False")
									with _self._g3_buy_order_lock:
										_self._g3_buy_order_id = ''
										self.logger.info("### set g3 order id = ''")
										_self._g3_buy_order_timestamp = 0

						if side == 'buy':
							_self.continuous_buy += 1
							_self.order_volume += size
							_self.cur_asset += price * size
							_self.avg_price = _self.cur_asset / _self.order_volume
							fee = size * _self.fee

							self.logger.info("buy avg_price ===> " + str(_self.avg_price))
							self.save_order({"coin": coin,
									 "time": utility.get_now_datetime(),
									 "type": "buy",
									 "price": price,
									 "size": size,
									 "fee": fee,
									 "pnl": 0})

							# self.send_ding_msg({"coin": coin, "type": "buy", "price": price, "vol": size})
						else:
							_self.continuous_buy = 0
							_self.order_volume -= size
							has_sell_asset = price * size
							_self.cur_asset -= has_sell_asset
							fee = has_sell_asset * _self.fee

							_self.avg_price = _self.cur_asset / _self.order_volume
							self.logger.info("sell avg_price ===> " + str(_self.avg_price))
							pnl = (price - _self.avg_price) * size - fee

							self.save_order({"coin": coin,
									 "time": utility.get_now_datetime(),
									 "type": "sell",
									 "price": price,
									 "size": size,
									 "fee": fee,
									 "pnl": pnl})

							# self.send_ding_msg({"coin": coin, "type": "sell", "price": price, "vol": size, "pnl": pnl})
				elif row["status"] == 'live':
					self.logger.info(f"##################### _self._inited : {_self._inited}, order : {ord_id}")
					if not _self._inited and side == 'buy':
						self.cancel_order({"instId": row["symbol"], "ordId": ord_id})
						return
					else:
						with _self._ordering_lock:
							self.logger.info(f"{coin} _ordering => false")
							_self._ordering = False

						# 防止频繁在窄范围内挂单，将挂单间距拉大
						if (_self._g1_buy_order_timestamp > 0 and _self._g1_buy_order_timestamp - now < 20) or (
								_self._g2_buy_order_timestamp > 0 and _self._g2_buy_order_timestamp - now < 20):
							_self.step_span *= 2

						# 如果已经连续买入5次，可能币价急速下跌，挂单间距拉大
						if _self.continuous_buy >= 5:
							_self.step_span *= 3
						else:
							_self.step_span = _self.init_step_span

					gtype = 0 if len(row["clientid"]) == 0 else int(row["clientid"][1:2])

					if side == 'buy':
						ord_id = row['orderid']
						if gtype == 1:
							_self._g1_buy_order_id = ord_id
							self.logger.info(f"^^^^ {coin} set g1 order id {_self._g1_buy_order_id}")
							_self._g1_buy_order_timestamp = now
						elif gtype == 2:
							_self._g2_buy_order_id = ord_id
							self.logger.info(f"^^^^ {coin} set g2 order id {_self._g2_buy_order_id}")
							_self._g2_buy_order_timestamp = now

							with _self._g2_buy_multiple_lock:
								_self.g2_buy_multiple = row['size'] / _self.volume
								self.logger.info(f"{coin} set g2_buy_multiple : {_self.g2_buy_multiple}")
							with _self._g2_buy_amount_lock:
								_self.g2_buy_amount += row["size"]
								_self.g2_buy_order_amount = row["size"]
						elif gtype == 3:
							_self._g3_buy_order_id = ord_id
							self.logger.info(f"^^^^ {coin} set g3 order id {_self._g3_buy_order_id}")
							_self._g3_buy_order_timestamp = now
							with _self._g3_buy_amount_lock:
								_self.g3_buy_amount += row["size"]

					elif side == 'sell':
						if gtype == 2:
							with _self._g2_sell_multiple_lock:
								_self.g2_sell_multiple = row["size"] / _self.volume
								self.logger.info(f"{coin} set g2_sell_multiple : {_self.g2_sell_multiple}")
							with _self._g2_buy_amount_lock:
								_self.g2_buy_amount -= row["size"]
								if _self.g2_buy_amount == 0:
									_self.g2_buy_multiple = 0
						elif gtype == 3:
							with _self._g3_buy_amount_lock:
								_self.g3_buy_amount -= row["size"]
				elif row["status"] == 'canceled':
					if tag[0:2] == 'g1':
						with _self.g1_buy_order_lock:
							_self._g1_buy_order_timestamp = 0
							_self._g1_buy_order_id = ''
							self.logger.info("%s __set g1 order id = ''"%coin)

					elif tag[0:2] == 'g2':
						with _self._g2_buy_order_lock:
							_self._g2_buy_order_timestamp = 0
							_self._g2_buy_order_id = ''
							self.logger.info("%s __set g2 order id = ''"%coin)
					elif tag[0:2] == 'g3':
						with _self._g3_buy_order_lock:
							_self._g3_buy_order_timestamp = 0
							_self._g3_buy_order_id = ''
							self.logger.info("%s __set g3 order id = ''"%coin)

	def on_cancel_order(self, data, patch=None):
		if patch is not None and len(patch) > 0:
			has_canceled = '514' == data["data"]['data'][0]["sCode"][0:3]
			coin = patch.split('_')[0]
			if coin in self.STV:
				_self = self.STV[coin]
				if patch.split('_')[1] == 'g1':
					if order_success(data) or has_canceled:
						with _self.g1_buy_order_lock:
							self.logger.info("%s set _g1_buy_order_id = ''"%coin)
							_self._g1_buy_order_timestamp = 0
							_self._g1_buy_order_id = ''
						with _self._g1_buy_switch_lock:
							_self.g1_buy_switch = True
				elif patch.split('_')[1] == 'g2':
					if order_success(data) or has_canceled:
						with _self._g2_buy_order_lock:
							self.logger.info("%s set _g2_buy_order_id = ''"%coin)
							_self._g2_buy_order_timestamp = 0
							_self._g2_buy_order_id = ''
						with _self._g2_buy_amount_lock:
							_self.g2_buy_amount -= _self.g2_buy_order_amount
				else:
					if order_success(data) or has_canceled:
						with _self._g3_buy_order_lock:
							self.logger.info("%s set _g3_buy_order_id = ''"%coin)
							_self._g3_buy_order_timestamp = 0
							_self._g3_buy_order_id = ''
						with _self._g3_buy_amount_lock:
							_self.g3_buy_amount -= _self.g3_buy_order_amount

				with _self._cancel_ordering_lock:
					_self.cancel_ordering = False

	def cancel_order(self, args: dict):
		self.logger.info("cancel_order => %s" % str(args))
		if 'patch' in args:
			coin = args['patch'].split('_')[0]
			_self = self.STV[coin]
			with _self._cancel_ordering_lock:
				self.logger.info(f"{coin} cancel_ordering => true")
				_self.cancel_ordering = True
		super().cancel_order(args)

	def send_order(self, args: dict):
		coin = args['patch']['coin']
		_self = self.STV[coin]
		if args['side'] == 'buy':
			self.logger.info("###### usdt_available ######: %f" % self.usdt_available)
			if args['px'] * args['sz'] > self.usdt_available:
				self.logger.info(f"no enough USDT [{self.usdt_available}] left for buy {coin}!")
				return
			_inited = '' if _self._inited else 'init'
			self.logger.info("%s g%d %s %s price: %f amount: %f" % (_inited, args['patch']['grid_type'], args['side'], coin, args['px'], args['sz']))
		with _self._ordering_lock:
			_self._ordering = True
			self.logger.info(f" {coin} _ordering ==> true")
		super().send_order(args)

	def on_send_order(self, data, patch=None):
		self.logger.info("pyramid on_send_order data=> %s" % (str(data)))
		if 'patch' in data:
			coin = data['patch']['coin']
			if coin in self.STV:
				_self = self.STV[coin]

				if data['response']['code'] == 51119:
					self.logger.info("no enough USDT left !")

				with _self._ordering_lock:
					_self._ordering = False
					self.logger.info(f"{coin} _ordering => false")

	# 获取grid2挂单方向、阶梯挂单量
	def get_grid2_direction_volume(self, coin, price):
		_self = self.STV[coin]
		direction = 'buy'
		if _self.g2_buy_amount == 0:
			return direction, _self.volume
		else:
			if 0 < _self.g2_buy_price < price:
				direction = 'sell'

			multiple = int(math.floor(abs(price - _self.g2_buy_price) / _self.step_span))
			if multiple > 0:
				self.logger.info('%s g2 multiple: %d g2_buy_multiple: %d' % (coin,multiple, _self.g2_buy_multiple))
				amt = multiple * _self.volume
				if direction == 'buy' and multiple != _self.g2_buy_multiple:
					return direction, amt
				elif direction == 'sell' and multiple != _self.g2_sell_multiple:
					# 价格越向上才越卖，向下不再卖
					if amt <= _self.g2_buy_amount and multiple > _self.g2_sell_multiple:
						self.logger.info('%s g2 sell multiple: %d g2_buy_multiple: %d' % (coin,multiple, _self.g2_buy_multiple))
						return direction, amt
		return direction, 0

	# 获取grid3挂单方向、阶梯挂单量。 等级3的卖完了，把对应倒阶3的吃单记数清0；反之，相应阶梯买完了，对应的阶梯卖数清0
	def get_grid3_direction_volume(self, coin, price):
		_self = self.STV[coin]
		amount = 0
		direction = 'buy'

		# 仅当价格超过设置的最低最高的均价之上才考虑卖
		if price >= _self.middle_price + _self.init_step_span:
			direction = 'sell'

		for i in range(len(_self.price_step) - 1, 0, -1):
			if i > 0 and _self.price_step[i - 1] > price >= _self.price_step[i]:
				with _self._g3_price_memory_lock:
					if not _self.g3_price_memory[i]['g3' + direction[0:1]]:
						self.logger.info("g3_price_memory i is  : %d " % i)
						_self.g3_price_memory[i]['g3' + direction[0:1]] = True

						amount = _self.volume_step[i] * _self.volume
						self.logger.info("g3_amount is  : %f " % amount)
						if direction == 'sell':
							if amount > _self.g3_buy_amount:
								self.logger.info("g3_buy_amount : %d ,but sell amount : %d " % (_self.g3_buy_amount, amount))
								return direction, 0
						else:
							_self._g3_price_index = i
							return direction, amount
		return direction, amount

	def on_position(self, data):
		# self.logger.info("on_position===>" + str(data))
		pass

	def on_account(self, data):
		# self.logger.info("on_account===>" + str(data))
		for d in data:
			if d["coin"] == 'USDT':
				self.usdt_available = d["available"]
			else:
				if d["coin"] + "-USDT" in self.STV:
					_self = self.STV[d["coin"] + "-USDT"]
					_self._available = d["available"]

	def gen_client_orderid(self, coin, tag):
		return "%s%s%d%d" % (tag, coin.replace('-', ''), int(time.time()), utility.get_random())


def order_success(data):
	return data['data']['data'][0]['sCode'] == "0"
