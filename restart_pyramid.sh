val=$1
ps -ef|grep client.py|grep $val|awk '{print $2}'|xargs kill -s 9
date +%F_%T
cd /home/franklin/iQuant/
#nohup python client.py $val >/dev/null 2>&1 &
nohup python client.py $val > $val_nohup.out &
ps -ef|grep $val
tail -f $val_nohup.out
