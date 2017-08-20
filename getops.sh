#!/bin/bash
# Demo script showing how to use getops

function usage() {
    echo "Usage: $0 -h -a <arg> -b"
    echo "Demo script showing how to use getops"
    echo
    echo "    -h     Show this help"
    echo "    -a     Requires a mandatory argument"
    echo "    -b     Does not take any arguments"
    exit 0
}

while getopts ":ha:b" opt; do
    case $opt in
	a)
	    echo "-a was triggered, Parameter: $OPTARG" >&2
	    ;;
	b)  echo "-b was triggered"
	    ;;
	h)  usage
	    ;;
	?)
	    echo "Invalid option: -$OPTARG" >&2
	    exit 1
	    ;;
	:)
	    echo "Option -$OPTARG requires an argument." >&2
	    exit 1
	    ;;
    esac
done
shift $(($OPTIND - 1))
echo "Remaining arguments are: $*"
