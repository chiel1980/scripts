#!/bin/bash
# based on script from http://www.axllent.org/docs/view/ssh-geoip
# License: WTFPL

#
### expects mmdblookup package and a cronjob to keep the GeoIP2 database up-to-date
# GeoIP2 database lookup directories:
#  /var/local/share/GeoIP /var/share/GeoIP /usr/share/GeoIP
# GeoIP2 database lookup files:
#  GeoIP2-City.mmdb GeoIP2-Country.mmdb GeoLite2-City.mmdb GeoLite2-Country.mmdb
#
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
#
#	IPV6CALC_SKIP=1 /path/to/ipfilter.sh 1.2.3.4 ssh
#	DENY ssh connection from 1.2.3.4 ('AU' retrieved with /usr/bin/mmdblookup and /var/local/share/GeoIP/GeoLite2-City.mmdb)
#
#	/path/to/ipfilter.sh 1.2.3.4 ssh
#	DENY ssh connection from 1.2.3.4 ('AU' retrieved with /usr/bin/ipv6calc)
#
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
# 20240113/pbiering: replace legacy "geoiplookup" with "mmdblookup" incl. database lookup loop
# 20240113/pbiering: add environment support IPV6CALC_SKIP (at least for testing)
# 20240113/pbiering: implement GeoIP2 database precedence mechanism to avoid using an outdated one, add support for DEBUG, add 3rd location for GeoIP2 database lookup

## TODO
# provide script for regular cleanup of iptables chain by checking inserted timestamp
# add support for firewalld or fail2ban

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

[ "$IPV6CALC_SKIP" = 1 ] || IPV6CALC="$(which ipv6calc 2>/dev/null)"

if [[ $1 =~ : ]] ; then
  IPTABLES="$(which ip6tables)"
  GEOIPLOOKUP="$(which mmdblookup 2>/dev/null)"
  if [ -n "$IPV6CALC" ]; then
    if $IPV6CALC -v 2>&1 | grep -wq "DB_IPV6_CC"; then
      GEOIPLOOKUP="$IPV6CALC"
    fi
  fi
elif [[ $1 =~ [0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3} ]] ; then
  IPTABLES="$(which iptables)"
  GEOIPLOOKUP="$(which mmdblookup 2>/dev/null)"
  if [ -n "$IPV6CALC" ]; then
    if $IPV6CALC -v 2>&1 | grep -wq "DB_IPV4_CC"; then
      GEOIPLOOKUP="$IPV6CALC"
    fi
  fi
else
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "given IP address not supported: $1"
  [ -t 0 ] && echo "given IP address not supported: $1"
  exit 0
fi

if [ -z "$GEOIPLOOKUP" ]; then
  echo "mmdblookup not found - please install it via your package manager!"
  exit 0
fi

if [ ! -x "$GEOIPLOOKUP" ]; then
  [ -t 0 ] || logger -t "$logtag" -p $LOGDENY_FACILITY_ERROR "not executable: $GEOIPLOOKUP"
  [ -t 0 ] && echo "not executable: $GEOIPLOOKUP"
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
  */mmdblookup)
    for dir in /var/local/share/GeoIP /var/share/GeoIP /usr/share/GeoIP; do
      for db in GeoIP2-City.mmdb GeoIP2-Country.mmdb GeoLite2-City.mmdb GeoLite2-Country.mmdb; do
        [ -n "$DEBUG" ] && echo "probe: $dir/$db"
        if [ -f $dir/$db -a -s $dir/$db ]; then
          [ -n "$DEBUG" ] && echo "found: $dir/$db"

          RESULT=`$GEOIPLOOKUP --file $dir/$db -v --ip $1 country iso_code 2>/dev/null`
          [ $? -eq 0 ] || continue

          re_countrycode='\s*\"(.*)\"\s*<utf8_string>'
          if [[ $RESULT =~ $re_countrycode ]]; then
            countrycode=${BASH_REMATCH[1]}
            [ -n "$DEBUG" ] && echo "country  $dir/$db: $countrycode"
          fi

          re_db_epoch='\s*Build epoch:\s*([0-9]+)'
          if [[ $RESULT =~ $re_db_epoch ]]; then
             db_epoch=${BASH_REMATCH[1]}
            [ -n "$DEBUG" ] && echo "db_epoch $dir/$db: $db_epoch"
          fi

          if [ -n "$countrycode" ]; then
            if [ -n "$db_epoch" -a -z "$COUNTRY_SOURCE_EPOCH" ]; then
              # empty
              COUNTRY_SOURCE="$dir/$db"
              COUNTRY="$countrycode"
              COUNTRY_SOURCE_EPOCH="$db_epoch"
              [ -n "$DEBUG" ] && echo "db_epoch $dir/$db: $db_epoch (new)"
            elif [ -n "$COUNTRY_SOURCE_EPOCH" -a -n "$db_epoch" ]; then
              if [ $db_epoch -gt $COUNTRY_SOURCE_EPOCH ]; then
                # newer
                COUNTRY_SOURCE="$dir/$db"
                COUNTRY="$countrycode"
                COUNTRY_SOURCE_EPOCH="$db_epoch"
                [ -n "$DEBUG" ] && echo "db_epoch $dir/$db: $db_epoch (overwrite)"
              else
                [ -n "$DEBUG" ] && echo "db_epoch $dir/$db: $db_epoch (keep)"
              fi
            elif [ -z "$db_epoch" ]; then
              # should not happen, fill at least source
              COUNTRY="$countrycode"
              COUNTRY_SOURCE="$dir/$db"
              COUNTRY_SOURCE_EPOCH="0"
              [ -n "$DEBUG" ] && echo "db_epoch $dir/$db: 0 (empty/strange)"
            fi
          fi
        fi
      done
    done

    if [ -n "$COUNTRY_SOURCE_EPOCH" -a "$COUNTRY_SOURCE_EPOCH" != 0 ]; then
      COUNTRY_SOURCE="$COUNTRY_SOURCE built $(date --utc '+%Y-%m-%d %H:%M:%S %Z' --date @$COUNTRY_SOURCE_EPOCH)"
    fi
    ;;
  */ipv6calc)
    if [[ $1 =~ : ]] ; then
      COUNTRY=`$GEOIPLOOKUP -q -m --mrtvo IPV6_COUNTRYCODE -i "$1"`
      COUNTRY_SOURCE=`$GEOIPLOOKUP -q -m --mrtvo IPV6_COUNTRYCODE_SOURCE -i "$1"`
    else
      COUNTRY=`$GEOIPLOOKUP -q -m --mrtvo IPV4_COUNTRYCODE -i "$1"`
      COUNTRY_SOURCE=`$GEOIPLOOKUP -q -m --mrtvo IPV4_COUNTRYCODE_SOURCE -i "$1"`
    fi
    ;;
esac
if [ -z "$COUNTRY" ]; then
  COUNTRY="IP Address not found"
else
  GEOIPLOOKUP="$GEOIPLOOKUP source $COUNTRY_SOURCE"
fi

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

# vim: tabstop=2 smartindent shiftwidth=2 expandtab
