#!/bin/bash
# License: WTFPL

#
### expects geoip package and a cronjob to keep the geoip db up2date
### expects INTERFACE set to correct interface
### expects hosts.deny and hosts.allow to set up correctly aka https://tecadmin.net/allow-server-access-based-on-country/
#

# UPPERCASE space-separated country codes to ACCEPT
ALLOW_COUNTRIES="NL DE FR DK SE UK BE"
LOGDENY_FACILITY="authpriv.notice"
GEOIP6=`which geoiplookup6`
GEOIP=`which geoiplookup`
###
if [ $GEOIP6 ]; then
  echo 'geopiplookup6 found! continue'
else
  echo 'geoiplookup6 not found - please install it via your package manager!'
  exit 1
fi
if [ $GEOIP ]; then
  echo 'geopiplookup found! continue'
else
  echo 'geoiplookup not found - please install it via your package manager!'
  exit 1
fi
if [ $# -ne 1 ]; then
  echo "Usage:  `basename $0` " 1>&2
  exit 0 # return true in case of config issue
fi

if [[ "`echo $1 | grep ':'`" != "" ]] ; then
  COUNTRY=`"$GEOIP6" "$1" | awk -F ": " '{ print $2 }' | awk -F "," '{ print $1 }' | head -n 1`
else
  COUNTRY=`"$GEOIP" "$1" | awk -F ": " '{ print $2 }' | awk -F "," '{ print $1 }' | head -n 1`
fi
[[ $COUNTRY = "IP Address not found" || $ALLOW_COUNTRIES =~ $COUNTRY ]] && RESPONSE="ALLOW" || RESPONSE="DENY"

if [[ "$RESPONSE" == "ALLOW" ]] ; then
  logger -p $LOGDENY_FACILITY "$RESPONSE sshd connection from $1 ($COUNTRY)"
  exit 0
else
  logger -p $LOGDENY_FACILITY "$RESPONSE sshd connection from $1 ($COUNTRY)"
  /sbin/iptables -I INPUT 1 -s $1 -j DROP
  exit 1
fi
