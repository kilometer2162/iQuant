val=$1
ps -ef|grep server.py|grep $val|awk '{print $2}'|xargs kill -9 
date +%F_%T
cd /home/franklin/iQuant/
#nohup python server.py $val>/dev/null 2>&1 &
nohup python server.py $val > $val_nohup.out &
ps -ef|grep server.py $val
tail -f $val_nohup.out
