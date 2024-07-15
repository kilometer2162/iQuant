import logging
import re
from logging.handlers import TimedRotatingFileHandler


class logger(object):
	def __init__(self, name, path):
		# define logger
		self.logger = logging.getLogger(name)
		self.logger.setLevel(level=logging.INFO)
		# handler = logging.FileHandler(path)
		# handler.setLevel(logging.INFO)
		# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
		# handler.setFormatter(formatter)

		file_handler = TimedRotatingFileHandler(
			filename=path, when="MIDNIGHT", interval=1, backupCount=30
		)
		# filename="mylog" suffix设置，会生成文件名为mylog.2020-02-25.log
		file_handler.suffix = "%Y-%m-%d.log"
		# extMatch是编译好正则表达式，用于匹配日志文件名后缀
		# 需要注意的是suffix和extMatch一定要匹配的上，如果不匹配，过期日志不会被删除。
		file_handler.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}.log$")
		# 定义日志输出格式
		file_handler.setFormatter(
			logging.Formatter(
				"[%(asctime)s] [%(process)d] [%(levelname)s] - %(message)s"
			)
		)
		self.logger.addHandler(file_handler)

		console = logging.StreamHandler()
		console.setLevel(logging.INFO)
		self.logger.addHandler(console)

# self.logger.info('############################################################################################')
# self.logger.debug('Do something')
# self.logger.warning('Something maybe fail')
# self.logger.info('Finish!')
