val=$1
ps -ef|grep server.py|grep $val|awk '{print $2}'|xargs kill -s 9
