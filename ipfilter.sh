#!/bin/bash
# based on script from http://www.axllent.org/docs/view/ssh-geoip
# License: WTFPL

#
### expects geoip package and a cronjob to keep the geoip db up2date
### expects hosts.deny and hosts.allow to set up correctly aka https://tecadmin.net/allow-server-access-based-on-country/
#

## Usage example: /etc/hosts.allow
# Default country list:
#  sshd: ALL : spawn /usr/local/bin/ipfilter %a %d
# Custom country list:
#  sshd: ALL : spawn /usr/local/bin/ipfilter %a %d "DE US" [<iptables chain>]

# For OS versions having "tcp_wrappers" deprecated see instructions here:
#  https://fedoraproject.org/wiki/Changes/Deprecate_TCP_wrappers
#
# At least on Fedora >= 34 and  EL >= 8 install "tcp_wrappers" from EPEL and replace "spawn" with "aclexec"
#  see also https://src.fedoraproject.org/rpms/tcp_wrappers

## iptables extension
# it's recommended to use a dedicated chain, created with
#	iptables -A INPUT -j BLOCKDYN
# 	ip6tables -A INPUT -j BLOCKDYN

## Testing
# to stdout:
#	/path/to/ipfilter.sh 1.2.3.4 ssh DE BLOCKDYN
# to syslog
#	echo "" | /path/to/ipfilter.sh 1.2.3.4 ssh DE BLOCKDYN
# resulting in following
# 	iptables -nL BLOCKDYN
# 	Chain BLOCKDYN (1 references)
# 	target     prot opt source               destination
# 	DROP       all  --  1.2.3.4              0.0.0.0/0            /* 2018-07-21T06:27:32+0000 ssh: ipfilter.sh */

## Changelog
# 20180721/pbiering: extend syslog, proper iptables selection for IPv6 and custom iptables chain
# 20210610/pbiering: add support for "ipv6calc" with precedence above "geoiplookup"
# 20210611/pbiering: fix if called without a proper IP address

## TODO
# provide script for regular cleanup of iptables chain by checking inserted timestamp
# add support for firewalld

# UPPERCASE space-separated country codes to ACCEPT
#ALLOW_COUNTRIES="NL DE FR DK SE UK BE" # <- your potential default list
ALLOW_COUNTRIES="${ALLOW_COUNTRIES:-US}" # default if empty
LOGDENY_FACILITY="authpriv.notice"
LOGDENY_FACILITY_ERR="authpriv.error"

logtag="$(basename $0)"
if [ -n "$2" ]; then
	logtag="$2: $logtag"
fi

if [ $# -lt 2 -o $# -gt 4 ]; then
  echo "Usage:  `basename $0` <ip> <daemon name> [country list] [<iptables chain>]" 1>&2
  exit 0 # return true in case of config issue
fi

if [ -n "$3" ]; then
	ALLOW_COUNTRIES="$3"
fi

if [ -n "$4" ]; then
	CHAIN="$4"
fi

IPV6CALC="$(which ipv6calc)"

if [[ $1 =~ : ]] ; then
  IPTABLES="$(which ip6tables)"
  GEOIPLOOKUP="$(which geoiplookup6 2>/dev/null)"
  if [ -n "$IPV6CALC" ]; then
    if $IPV6CALC -v 2>&1 | grep -wq "DB_IPV6_CC"; then
      GEOIPLOOKUP="$IPV6CALC -q --addr2cc"
    fi
  fi
elif [[ $1 =~ [0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3} ]] ; then
  IPTABLES="$(which iptables)"
  GEOIPLOOKUP="$(which geoiplookup 2>/dev/null)"
  if [ -n "$IPV6CALC" ]; then
    if $IPV6CALC -v 2>&1 | grep -wq "DB_IPV4_CC"; then
      GEOIPLOOKUP="$IPV6CALC -q --addr2cc"
    fi
  fi
else
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "given IP address not supported: $1"
  [ -t 0 ] && echo "given IP address not supported: $1"
  exit 0
fi

if [ -z "$GEOIPLOOKUP" ]; then
  echo "$GEOIPLOOKUP not found - please install it via your package manager!"
  exit 0
fi

if [ ! -x "$GEOIPLOOKUP" ]; then
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "not executable: $GEOIPLOOKUP"
  [ -t 0 ] && echo "missing executable: $GEOIPLOOKUP"
  exit 0
fi

if [ -n "$CHAIN" -a -z "$IPTABLES" ]; then
  echo "$IPTABLES not found - please install it via your package manager (disable appending IP to block in chain $CHAIN)!"
  CHAIN=""
fi

if [ -n "$CHAIN" -a ! -x "$IPTABLES" ]; then
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "not executable: $IPTABLES"
  [ -t 0 ] && echo "missing executable: $IPTABLES"
  exit 0
fi

case $GEOIPLOOKUP in
  geoiplookup*)
    COUNTRY=`$GEOIPLOOKUP "$1" | awk -F ": " '{ print $2 }' | awk -F "," '{ print $1 }' | head -n 1`
    ;;
  *)
    COUNTRY=`$GEOIPLOOKUP "$1"`
    ;;
esac
[[ $COUNTRY = "IP Address not found" || $ALLOW_COUNTRIES =~ $COUNTRY ]] && RESPONSE="ALLOW" || RESPONSE="DENY"

if [[ "$RESPONSE" == "ALLOW" ]] ; then
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY "$RESPONSE $2 connection from $1 ('$COUNTRY' retrieved with $GEOIPLOOKUP)"
  [ -t 0 ] && echo "$RESPONSE $2 connection from $1 ('$COUNTRY' retrieved with $GEOIPLOOKUP)"
  exit 0
else
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY "$RESPONSE $2 connection from $1 ('$COUNTRY' retrieved with $GEOIPLOOKUP)"
  [ -t 0 ] && echo "$RESPONSE $2 connection from $1 ('$COUNTRY' retrieved with $GEOIPLOOKUP)"

  if [ -n "$CHAIN" ]; then
    # create comment for iptables
    COMMENT="$(/usr/bin/date -u -Iseconds) $COUNTRY"
    # add iptables rule because it's not working without
    OUTPUT=$($IPTABLES -w 5 -I $CHAIN 1 -s $1 -j DROP -m comment --comment "$COMMENT $logtag" 2>&1)
    if [ $? -ne 0 ]; then
      [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "command is not working: $OUTPUT"
      [ -t 0 ] && echo "$IPTABLES is not working: $OUTPUT"
    fi
  fi

  exit 1
fi
