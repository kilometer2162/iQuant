# -*- coding: utf-8 -*-

"""
线程池，用于高效执行某些任务。
"""

from queue import Empty, Queue
import threading


class Task(threading.Thread):
	""" 任务  """

	def __init__(self, num, input_queue, output_queue, error_queue):
		super(Task, self).__init__()
		self.thread_name = "thread-%s" % num
		self.input_queue = input_queue
		self.output_queue = output_queue
		self.error_queue = error_queue
		self.deamon = True

	def run(self):
		"""run
		"""
		while 1:
			try:
				func, args = self.input_queue.get(block=False)
			except Empty:
				print("%s finished!" % self.thread_name)
				break
			try:
				result = func(*args)
			except Exception as exc:
				self.error_queue.put((func.func_name, args, str(exc)))
			else:
				self.output_queue.put(result)


class Pool(object):
	""" 线程池 """

	def __init__(self, size):
		self.input_queue = Queue()
		self.output_queue = Queue()
		self.error_queue = Queue()
		self.tasks = [Task(i, self.input_queue, self.output_queue, self.error_queue) for i in range(size)]

	def add_task(self, func, args):
		"""添加单个任务
		"""
		if not isinstance(args, tuple):
			raise TypeError("args must be tuple type!")
		self.input_queue.put((func, args))

	def add_tasks(self, tasks):
		"""批量添加任务
		"""
		if not isinstance(tasks, list):
			raise TypeError("tasks must be list type!")
		for func, args in tasks:
			self.add_task(func, args)

	def get_results(self):
		"""获取执行结果集
		"""
		while not self.output_queue.empty():
			print("Result: ", self.output_queue.get())

	def get_errors(self):
		"""获取执行失败的结果集
		"""
		while not self.error_queue.empty():
			func, args, error_info = self.error_queue.get()
			print("Error: func: %s, args : %s, error_info : %s" % (func.func_name, args, error_info))

	def run(self):
		"""执行
		"""
		for task in self.tasks:
			task.start()
		for task in self.tasks:
			task.join()


def test(i):
	"""test """
	result = i * 10
	return result


def main():
	""" main """
	pool = Pool(size=5)
	pool.add_tasks([(test, (i,)) for i in range(100)])
	pool.run()


if __name__ == "__main__":
	main()
