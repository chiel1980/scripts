#!/bin/bash
#
#
###############################################
recipient='mve@pragmasec.nl'
for service in {nginx,sshd,dovecot}; do
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
#for service in clamd; do
#function check_service {
#  echo "checking for $service at `date`"
#  pidof "$service" 1>/dev/null 2>&1
#}
#if check_service ;
#  then echo 'running'
#else
#  echo 'not running'
#  echo "restarted $sevice at `date`" | mail -s "$service not running at `date`" "$recipient"
#  systemctl restart "clamav-daemon"
#fi
#done

echo "checking for spamassassin at `date`"
if pgrep spamd 
 then echo 'works!'
else
 echo 'does not work!'
 echo "restarted spamassassin at `date`" | mail -s "spamassassin not running at `date`" "$recipient"
 systemctl restart spamassassin
fi

echo "checking for opensmtpd at `date`"
if pgrep smtpd 
 then echo 'works!'
else
 echo 'does not work!'
 echo "restarted opensmtpd at `date`" | mail -s "opensmtpd not running at `date`" "$recipient"
 systemctl restart opensmtpd 
fi

echo "checking for spampd at `date`"
if pgrep spampd 
 then echo 'works!'
else
 echo 'does not work!'
 echo "restarted spampd at `date`" | mail -s "spampd not running at `date`" "$recipient"
 systemctl restart spampd 
fi

echo "checking for fail2ban at `date`"
if pgrep fail2ban 
 then echo 'works!'
else
 echo 'does not work!'
 echo "restarted fail2ban at `date`" | mail -s "fail2ban not running at `date`" "$recipient"
 systemctl restart fail2ban 
fi
