#!/bin/bash
#
#
###############################################
recipient='emailadresshere'
for service in {polipo,postgres,havp,nginx}; do
function check_service {
  echo "checking for $service at `date`"
  pidof "$service" 1>/dev/null 2>&1 
}
if check_service ; 
  then echo 'running'
else
  echo 'not running'
  echo "restarted $sevice at `date`" | mail -s "$service not running at `date`" "$recipient"
  systemctl restart "$service"
fi 
done
